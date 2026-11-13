"""Background orchestrator, Windows System Tray icon, and global hotkeys."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

import cv2
import pystray
from PIL import Image, ImageDraw
from pynput import keyboard

from .config import DEFAULT_CONFIG_PATH, load_config, save_config
from .gestures import GestureEngine
from .hud import JarvisHUD
from .smoothing import CursorMapper
from .tracker import HandTracker, render_jarvis_hud
from .win_input import WindowsMouseController


def _make_tray_icon(color_hex: str, inner_hex: str) -> Image.Image:
    """Generate a crisp Jarvis arc-reactor style icon for the Windows System Tray."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(10, 16, 28, 255), outline=color_hex, width=4)
    draw.ellipse((15, 15, 49, 49), outline=inner_hex, width=2)
    draw.ellipse((24, 24, 40, 40), fill=color_hex)
    return img


class JarvisVisionApp:
    """Runs invisible camera hand-tracking in background with Tray + Hotkey + HUD."""

    def __init__(self) -> None:
        self.cfg: dict[str, Any] = load_config()
        self.mouse = WindowsMouseController()
        self.mapper = CursorMapper(
            screen_w=self.mouse.screen_w,
            screen_h=self.mouse.screen_h,
            roi_x_min=self.cfg["tracking"]["roi_x_min"],
            roi_x_max=self.cfg["tracking"]["roi_x_max"],
            roi_y_min=self.cfg["tracking"]["roi_y_min"],
            roi_y_max=self.cfg["tracking"]["roi_y_max"],
            min_cutoff=self.cfg["tracking"]["min_cutoff"],
            beta=self.cfg["tracking"]["beta"],
            d_cutoff=self.cfg["tracking"]["d_cutoff"],
            deadzone_px=self.cfg["tracking"]["deadzone_px"],
        )
        self.gestures = GestureEngine(
            cursor_anchor=self.cfg["tracking"]["cursor_anchor"],
            pinch_down_ratio=self.cfg["gestures"]["pinch_down_ratio"],
            pinch_up_ratio=self.cfg["gestures"]["pinch_up_ratio"],
            pinch_freeze_ratio=self.cfg["gestures"]["pinch_freeze_ratio"],
            drag_hold_ms=self.cfg["gestures"]["drag_hold_ms"],
            right_click_cooldown_ms=self.cfg["gestures"]["right_click_cooldown_ms"],
            scroll_speed=self.cfg["gestures"]["scroll_speed"],
            sleep_hold_ms=self.cfg["gestures"]["sleep_hold_ms"],
        )

        self._stop_event = threading.Event()
        self._paused = False  # True -> camera released (privacy / zero CPU)
        self._standby = False  # True -> hand-triggered sleep (watching at low FPS)
        self._mirror = bool(self.cfg["camera"]["mirror"])
        self._state_lock = threading.Lock()

        self.hud = JarvisHUD(
            width=int(self.cfg["ui"]["hud_width"]),
            height=int(self.cfg["ui"]["hud_height"]),
            opacity=float(self.cfg["ui"]["hud_opacity"]),
            on_toggle_pause=self.toggle_pause,
            on_toggle_mirror=self.set_mirror,
            on_smoothing_change=self.set_smoothing,
            on_exit=self.stop,
            initial_mirror=self._mirror,
            initial_min_cutoff=float(self.cfg["tracking"]["min_cutoff"]),
        )

        self._icon_active = _make_tray_icon("#38BDF8", "#0284C7")
        self._icon_standby = _make_tray_icon("#F59E0B", "#B45309")
        self._icon_paused = _make_tray_icon("#64748B", "#334155")
        self.tray: pystray.Icon | None = None
        self._hotkeys: keyboard.GlobalHotKeys | None = None
        self._worker_thread: threading.Thread | None = None

    def set_mirror(self, enabled: bool) -> None:
        self._mirror = bool(enabled)
        self.cfg["camera"]["mirror"] = self._mirror
        save_config(self.cfg)

    def set_smoothing(self, min_cutoff: float) -> None:
        self.mapper.update_params(min_cutoff=min_cutoff)
        self.cfg["tracking"]["min_cutoff"] = round(min_cutoff, 2)
        save_config(self.cfg)

    def toggle_pause(self) -> None:
        with self._state_lock:
            self._paused = not self._paused
            if self._paused:
                self._standby = False
            paused = self._paused
        self.mouse.release_all()
        self.gestures.reset()
        self.mapper.reset()
        self._refresh_tray_visual()
        if paused:
            self.hud.push_frame(None, "JARVIS // PAUSADO (Cámara apagada)")

    def toggle_hud(self) -> None:
        self.hud.toggle()

    def _open_config_file(self) -> None:
        if os.name == "nt":
            os.startfile(str(DEFAULT_CONFIG_PATH))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(DEFAULT_CONFIG_PATH)])

    def _refresh_tray_visual(self) -> None:
        if self.tray is None:
            return
        if self._paused:
            self.tray.icon = self._icon_paused
            self.tray.title = "Jarvis Vision — Pausado (Ctrl+Alt+J)"
        elif self._standby:
            self.tray.icon = self._icon_standby
            self.tray.title = "Jarvis Vision — Standby (Meñique+Pulgar para despertar)"
        else:
            self.tray.icon = self._icon_active
            self.tray.title = "Jarvis Vision — Activo en segundo plano"

    def _build_tray(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda _item: "Reanudar Cámara (Ctrl+Alt+J)" if self._paused else "Pausar Cámara (Ctrl+Alt+J)",
                lambda _icon, _item: self.toggle_pause(),
                default=True,
            ),
            pystray.MenuItem(
                lambda _item: "Ocultar HUD (Ctrl+Alt+H)" if self.hud.is_visible else "Mostrar HUD Jarvis (Ctrl+Alt+H)",
                lambda _icon, _item: self.toggle_hud(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir config.json", lambda _icon, _item: self._open_config_file()),
            pystray.MenuItem("Salir", lambda _icon, _item: self.stop()),
        )
        return pystray.Icon("jarvis_vision", self._icon_active, "Jarvis Vision — Activo", menu)

    def _start_hotkeys(self) -> None:
        hk_pause = self.cfg["ui"]["hotkey_toggle_tracking"]
        hk_hud = self.cfg["ui"]["hotkey_toggle_hud"]
        self._hotkeys = keyboard.GlobalHotKeys(
            {
                hk_pause: self.toggle_pause,
                hk_hud: self.toggle_hud,
            }
        )
        self._hotkeys.daemon = True
        self._hotkeys.start()

    def _tracking_loop(self) -> None:
        tracker = HandTracker()
        cap: cv2.VideoCapture | None = None
        fps_t = time.perf_counter()
        frames = 0
        fps = 0.0

        roi = (
            float(self.cfg["tracking"]["roi_x_min"]),
            float(self.cfg["tracking"]["roi_x_max"]),
            float(self.cfg["tracking"]["roi_y_min"]),
            float(self.cfg["tracking"]["roi_y_max"]),
        )

        try:
            while not self._stop_event.is_set():
                if self._paused:
                    if cap is not None:
                        cap.release()
                        cap = None
                    time.sleep(0.15)
                    continue

                if cap is None:
                    cam_idx = int(self.cfg["camera"]["index"])
                    cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        cap = cv2.VideoCapture(cam_idx)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.cfg["camera"]["width"]))
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.cfg["camera"]["height"]))
                    cap.set(cv2.CAP_PROP_FPS, int(self.cfg["camera"]["fps"]))
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not cap.isOpened():
                        self.hud.push_frame(None, "ERROR // No se pudo abrir la cámara")
                        time.sleep(1.0)
                        continue

                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.02)
                    continue

                if self._mirror:
                    frame = cv2.flip(frame, 1)

                now = time.perf_counter()
                landmarks = tracker.detect(frame, now)
                action = self.gestures.evaluate(landmarks, now)

                if action.toggle_sleep_event:
                    self._standby = not self._standby
                    self.mouse.release_all()
                    self.mapper.reset()
                    self._refresh_tray_visual()

                display_mode = "STANDBY" if self._standby else action.mode

                if not self._standby:
                    if action.left_down_event:
                        self.mouse.left_down()
                    if action.left_up_event:
                        self.mouse.left_up()
                    if action.right_click_event:
                        self.mouse.right_click()
                    if abs(action.scroll_delta) > 0.01:
                        self.mouse.scroll(action.scroll_delta)

                    if (
                        action.anchor_x is not None
                        and action.anchor_y is not None
                        and not action.freeze_cursor
                        and action.mode in ("ACTIVE", "DRAGGING")
                    ):
                        px, py = self.mapper.map_to_screen(action.anchor_x, action.anchor_y, now)
                        self.mouse.move_to(px, py)
                    elif action.mode == "NO_HAND":
                        self.mapper.reset()
                else:
                    time.sleep(0.06)

                frames += 1
                if now - fps_t >= 0.5:
                    fps = frames / (now - fps_t)
                    frames = 0
                    fps_t = now

                if self.hud.is_visible:
                    anchor_pt = (
                        (action.anchor_x, action.anchor_y)
                        if action.anchor_x is not None and action.anchor_y is not None
                        else None
                    )
                    hud_frame = render_jarvis_hud(frame, landmarks, display_mode, roi, fps, anchor_pt)
                    self.hud.push_frame(hud_frame, f"JARVIS // {display_mode} ({fps:.0f} FPS)")
        finally:
            self.mouse.release_all()
            if cap is not None:
                cap.release()
            tracker.close()

    def run(self) -> None:
        """Start background worker, hotkeys, tray icon, and HUD event loop."""
        self._start_hotkeys()

        self._worker_thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._worker_thread.start()

        self.tray = self._build_tray()
        tray_thread = threading.Thread(target=self.tray.run, daemon=True)
        tray_thread.start()

        start_visible = not bool(self.cfg["ui"]["start_minimized"])
        self.hud.run_mainloop(start_visible=start_visible)

    def stop(self) -> None:
        """Gracefully stop tracking, hotkeys, tray, and HUD."""
        self._stop_event.set()
        self.mouse.release_all()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        if self.tray is not None:
            self.tray.stop()
        self.hud.close()

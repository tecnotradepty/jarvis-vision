"""Gemini Desktop Voice Assistant orchestrator, System Tray icon, and global hotkeys."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

import pystray
from PIL import Image, ImageDraw
from pynput import keyboard

from .ai_brain import GeminiBrain
from .commands import LocalCommandRouter, extract_wake_command
from .config import DEFAULT_CONFIG_PATH, load_config, save_config
from .hud import GeminiHUD
from .speech_out import SpeechOut
from .voice_listener import VoiceListener


def _make_gemini_tray_icon(color_hex: str, core_hex: str) -> Image.Image:
    """Generate a glowing Gemini diamond-sparkle icon for the Windows System Tray."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(10, 16, 28, 255), outline=color_hex, width=3)
    spark = [(32, 12), (38, 26), (52, 32), (38, 38), (32, 52), (26, 38), (12, 32), (26, 26)]
    draw.polygon(spark, fill=core_hex)
    return img


class GeminiAssistantApp:
    """Runs Gemini voice assistant in background with Tray, Push-to-Talk, local commands & optional AI."""

    def __init__(self) -> None:
        self.cfg: dict[str, Any] = load_config()
        self.speech = SpeechOut(
            tts_enabled=bool(self.cfg["assistant"]["tts_enabled"]),
            chime_enabled=bool(self.cfg["assistant"]["chime_enabled"]),
        )
        self.brain = GeminiBrain(
            api_key=str(self.cfg["ai"]["gemini_api_key"]),
            model=str(self.cfg["ai"]["model"]),
        )

        self.hud = GeminiHUD(
            width=int(self.cfg["ui"]["hud_width"]),
            height=int(self.cfg["ui"]["hud_height"]),
            opacity=float(self.cfg["ui"]["hud_opacity"]),
            on_push_to_talk=self.push_to_talk,
            on_toggle_mute=self.toggle_mute,
            on_toggle_tts=self.set_tts_enabled,
            on_submit_text=self.handle_direct_text,
            on_save_api_key=self.save_api_key,
            on_exit=self.stop,
            initial_tts=bool(self.cfg["assistant"]["tts_enabled"]),
            initial_api_key=str(self.cfg["ai"]["gemini_api_key"]),
            initial_ai_ready=self.brain.is_configured,
        )

        self.router = LocalCommandRouter(
            on_hide_hud=self.hud.hide,
            on_show_hud=self.hud.show,
            on_mute_mic=self.toggle_mute,
        )

        self.listener = VoiceListener(
            stt_mode=str(self.cfg["assistant"].get("stt_mode", "auto")),
            language=str(self.cfg["assistant"]["language"]),
            device_index=self.cfg["assistant"]["mic_device_index"],
            vad_min_rms=float(self.cfg["assistant"]["vad_min_rms"]),
            vad_multiplier=float(self.cfg["assistant"]["vad_multiplier"]),
            silence_timeout_s=float(self.cfg["assistant"]["silence_timeout_s"]),
            should_ignore_audio=lambda: self.speech.recently_spoke,
            on_level=self.hud.set_level,
            on_state=self._on_voice_state,
            on_utterance=self._on_utterance,
        )

        self._icon_active = _make_gemini_tray_icon("#38BDF8", "#818CF8")
        self._icon_muted = _make_gemini_tray_icon("#64748B", "#94A3B8")
        self.tray: pystray.Icon | None = None
        self._hotkeys: keyboard.GlobalHotKeys | None = None

    def _on_voice_state(self, state: str) -> None:
        self.hud.set_state(state, muted=self.listener.is_muted)

    def _on_utterance(self, text: str, was_ptt: bool) -> None:
        wake_words = self.cfg["assistant"]["wake_words"]
        triggered, command_body = extract_wake_command(text, wake_words)

        if not triggered and not was_ptt:
            return

        final_cmd = command_body if triggered else text
        self.speech.play_chime("wake")
        self.hud.append_log("Tú", text)
        self._execute_command_async(final_cmd)

    def handle_direct_text(self, text: str) -> None:
        """Handle text typed directly into the HUD input box (no wake word needed)."""
        wake_words = self.cfg["assistant"]["wake_words"]
        triggered, body = extract_wake_command(text, wake_words)
        cmd = body if triggered and body else text
        self.hud.append_log("Tú", text)
        self._execute_command_async(cmd)

    def _execute_command_async(self, command_text: str) -> None:
        threading.Thread(target=self._execute_command, args=(command_text,), daemon=True).start()

    def _execute_command(self, command_text: str) -> None:
        res = self.router.execute(command_text)
        if res.handled:
            self.speech.play_chime("ok")
            if res.reply:
                self.hud.append_log("Gemini", res.reply)
                self.speech.speak(res.reply)
            return

        # Fallback to Gemini AI API if configured
        self.hud.set_state("PENSANDO...")
        reply = self.brain.ask(command_text)
        self.speech.play_chime("ok" if self.brain.is_configured else "error")
        self.hud.append_log("Gemini", reply)
        self.speech.speak(reply)
        self.hud.set_state("SILENCIADO" if self.listener.is_muted else "ESCUCHANDO")

    def push_to_talk(self) -> None:
        if self.listener.is_muted:
            self.listener.set_muted(False)
            self._refresh_tray_visual()
        self.speech.play_chime("wake")
        self.listener.trigger_push_to_talk()

    def toggle_mute(self) -> None:
        self.listener.set_muted(not self.listener.is_muted)
        self._refresh_tray_visual()

    def toggle_hud(self) -> None:
        self.hud.toggle()

    def set_tts_enabled(self, enabled: bool) -> None:
        self.speech.tts_enabled = bool(enabled)
        self.cfg["assistant"]["tts_enabled"] = bool(enabled)
        save_config(self.cfg)

    def save_api_key(self, api_key: str) -> None:
        self.brain.set_api_key(api_key)
        self.cfg["ai"]["gemini_api_key"] = api_key.strip()
        save_config(self.cfg)
        self.hud.set_ai_ready(self.brain.is_configured)
        msg = "API Key de Gemini guardada. IA conversacional activa." if self.brain.is_configured else "API Key eliminada. Modo 100% offline."
        self.hud.append_log("Sistema", msg)

    def _open_config_file(self) -> None:
        if os.name == "nt":
            os.startfile(str(DEFAULT_CONFIG_PATH))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(DEFAULT_CONFIG_PATH)])

    def _refresh_tray_visual(self) -> None:
        if self.tray is None:
            return
        if self.listener.is_muted:
            self.tray.icon = self._icon_muted
            self.tray.title = "Gemini — Micrófono silenciado (Ctrl+Alt+M)"
        else:
            self.tray.icon = self._icon_active
            self.tray.title = "Gemini — Escuchando 'Gemini...' (Ctrl+Alt+H para abrir)"

    def _build_tray(self) -> pystray.Icon:
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda _item: "Ocultar Panel (Ctrl+Alt+H)" if self.hud.is_visible else "Abrir Panel Gemini (Ctrl+Alt+H)",
                lambda _icon, _item: self.toggle_hud(),
                default=True,
            ),
            pystray.MenuItem("Hablar ahora (Ctrl+Alt+G)", lambda _icon, _item: self.push_to_talk()),
            pystray.MenuItem(
                lambda _item: "Activar Micrófono (Ctrl+Alt+M)" if self.listener.is_muted else "Silenciar Micrófono (Ctrl+Alt+M)",
                lambda _icon, _item: self.toggle_mute(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir config.json", lambda _icon, _item: self._open_config_file()),
            pystray.MenuItem("Cerrar Gemini", lambda _icon, _item: self.stop()),
        )
        return pystray.Icon("gemini_assistant", self._icon_active, "Gemini — Escuchando", menu)

    def _start_hotkeys(self) -> None:
        hk_ptt = self.cfg["ui"]["hotkey_push_to_talk"]
        hk_mute = self.cfg["ui"]["hotkey_toggle_mic"]
        hk_hud = self.cfg["ui"]["hotkey_toggle_hud"]
        self._hotkeys = keyboard.GlobalHotKeys(
            {
                hk_ptt: self.push_to_talk,
                hk_mute: self.toggle_mute,
                hk_hud: self.toggle_hud,
            }
        )
        self._hotkeys.daemon = True
        self._hotkeys.start()

    def run(self) -> None:
        self._start_hotkeys()
        self.listener.start()

        self.tray = self._build_tray()
        threading.Thread(target=self.tray.run, daemon=True).start()

        self.hud.append_log(
            "Sistema",
            "Di 'Gemini, <comando>' o presiona Ctrl+Alt+G. La cámara permanece apagada.",
        )
        start_visible = not bool(self.cfg["ui"]["start_minimized"])
        self.hud.run_mainloop(start_visible=start_visible)

    def stop(self) -> None:
        self.listener.stop()
        self.speech.close()
        if self._hotkeys is not None:
            try:
                self._hotkeys.stop()
            except Exception:
                pass
        if self.tray is not None:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.hud.close()

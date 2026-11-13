"""Optional toggleable dark Jarvis HUD window (hidden by default)."""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageTk


class JarvisHUD:
    """Lightweight Tkinter overlay window for calibration, skeleton preview, and quick controls."""

    def __init__(
        self,
        width: int = 460,
        height: int = 360,
        opacity: float = 0.92,
        on_toggle_pause: Callable[[], None] | None = None,
        on_toggle_mirror: Callable[[bool], None] | None = None,
        on_smoothing_change: Callable[[float], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        initial_mirror: bool = True,
        initial_min_cutoff: float = 1.4,
    ) -> None:
        self.width = width
        self.height = height
        self.opacity = opacity
        self._on_toggle_pause = on_toggle_pause
        self._on_toggle_mirror = on_toggle_mirror
        self._on_smoothing_change = on_smoothing_change
        self._on_exit = on_exit
        self._initial_mirror = initial_mirror
        self._initial_min_cutoff = initial_min_cutoff

        self._lock = threading.Lock()
        self._latest_rgb: np.ndarray | None = None
        self._status_text = "INICIANDO..."
        self._visible = False
        self._root: tk.Tk | None = None
        self._video_label: tk.Label | None = None
        self._status_label: tk.Label | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._ready = threading.Event()

    @property
    def is_visible(self) -> bool:
        return self._visible

    def push_frame(self, bgr_frame: np.ndarray | None, status_text: str) -> None:
        """Called from the camera thread; only converts frames when HUD is visible."""
        with self._lock:
            self._status_text = status_text
            if self._visible and bgr_frame is not None:
                self._latest_rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

    def show(self) -> None:
        self._visible = True
        if self._root is not None:
            self._root.after(0, self._show_sync)

    def hide(self) -> None:
        self._visible = False
        if self._root is not None:
            self._root.after(0, self._hide_sync)

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def close(self) -> None:
        if self._root is not None:
            self._root.after(0, self._root.quit)

    def _show_sync(self) -> None:
        if self._root is not None:
            self._root.deiconify()
            self._root.lift()

    def _hide_sync(self) -> None:
        if self._root is not None:
            self._root.withdraw()

    def run_mainloop(self, start_visible: bool = False) -> None:
        """Run the Tkinter mainloop (call on main thread)."""
        root = tk.Tk()
        root.title("J.A.R.V.I.S. Vision HUD")
        root.configure(bg="#070B12")
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.opacity)
        root.geometry(f"{self.width}x{self.height + 90}+32+32")
        root.resizable(False, False)

        # Closing window hides to tray instead of killing the background daemon
        root.protocol("WM_DELETE_WINDOW", self.hide)

        header = tk.Frame(root, bg="#0C1422", height=32)
        header.pack(fill=tk.X)

        self._status_label = tk.Label(
            header,
            text="JARVIS // BACKGROUND",
            fg="#38BDF8",
            bg="#0C1422",
            font=("Consolas", 10, "bold"),
            padx=10,
            pady=6,
        )
        self._status_label.pack(side=tk.LEFT)

        tk.Button(
            header,
            text="Ocultar (Tray)",
            command=self.hide,
            bg="#162235",
            fg="#CBD5E1",
            activebackground="#1E293B",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
        ).pack(side=tk.RIGHT, padx=6, pady=4)

        self._video_label = tk.Label(root, bg="#070B12")
        self._video_label.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        controls = tk.Frame(root, bg="#0C1422", pady=6)
        controls.pack(fill=tk.X)

        mirror_var = tk.BooleanVar(value=self._initial_mirror)
        tk.Checkbutton(
            controls,
            text="Espejo",
            variable=mirror_var,
            command=lambda: self._on_toggle_mirror and self._on_toggle_mirror(mirror_var.get()),
            bg="#0C1422",
            fg="#E2E8F0",
            selectcolor="#0F172A",
            activebackground="#0C1422",
            activeforeground="#38BDF8",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=8)

        tk.Label(
            controls,
            text="Respuesta:",
            bg="#0C1422",
            fg="#94A3B8",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(6, 2))

        smooth_var = tk.DoubleVar(value=self._initial_min_cutoff)
        tk.Scale(
            controls,
            from_=0.5,
            to=3.5,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=smooth_var,
            command=lambda val: self._on_smoothing_change and self._on_smoothing_change(float(val)),
            bg="#0C1422",
            fg="#38BDF8",
            troughcolor="#1E293B",
            highlightthickness=0,
            length=110,
            showvalue=True,
            font=("Consolas", 8),
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            controls,
            text="Pausar/Reanudar",
            command=lambda: self._on_toggle_pause and self._on_toggle_pause(),
            bg="#0EA5E9",
            fg="#04101B",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=3,
        ).pack(side=tk.RIGHT, padx=8)

        self._root = root
        self._visible = start_visible
        if not start_visible:
            root.withdraw()

        self._ready.set()
        root.after(30, self._refresh_tick)
        root.mainloop()

    def _refresh_tick(self) -> None:
        if self._root is None:
            return

        if self._visible:
            with self._lock:
                rgb = self._latest_rgb
                status = self._status_text
                self._latest_rgb = None

            if self._status_label is not None:
                self._status_label.config(text=status)

            if rgb is not None and self._video_label is not None:
                img = Image.fromarray(rgb).resize(
                    (self.width - 12, self.height - 12),
                    Image.Resampling.BILINEAR,
                )
                self._photo = ImageTk.PhotoImage(image=img)
                self._video_label.config(image=self._photo)

        self._root.after(33, self._refresh_tick)

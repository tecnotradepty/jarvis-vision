"""Visual Gemini Desktop Voice Assistant HUD (with minimize-to-tray and clean exit)."""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable


QUICK_EXAMPLES: tuple[str, ...] = (
    "\"Gemini, pausa\"",
    "\"Gemini, sube el volumen\"",
    "\"Gemini, abre Chrome\"",
    "\"Gemini, busca en YouTube...\"",
    "\"Gemini, minimiza todo\"",
    "\"Gemini, qué hora es\"",
)


class GeminiHUD:
    """Floating dark Gemini control panel with live mic level, log, text input & API key field."""

    def __init__(
        self,
        width: int = 520,
        height: int = 540,
        opacity: float = 0.96,
        on_push_to_talk: Callable[[], None] | None = None,
        on_toggle_mute: Callable[[], None] | None = None,
        on_toggle_tts: Callable[[bool], None] | None = None,
        on_submit_text: Callable[[str], None] | None = None,
        on_save_api_key: Callable[[str], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        initial_tts: bool = True,
        initial_api_key: str = "",
        initial_ai_ready: bool = False,
    ) -> None:
        self.width = width
        self.height = height
        self.opacity = opacity
        self._on_push_to_talk = on_push_to_talk
        self._on_toggle_mute = on_toggle_mute
        self._on_toggle_tts = on_toggle_tts
        self._on_submit_text = on_submit_text
        self._on_save_api_key = on_save_api_key
        self._on_exit = on_exit
        self._initial_tts = initial_tts
        self._initial_api_key = initial_api_key
        self._ai_ready = initial_ai_ready

        self._lock = threading.Lock()
        self._state_text = "INICIANDO..."
        self._muted = False
        self._mic_level = 0.0
        self._pending_logs: list[tuple[str, str]] = []
        self._visible = True

        self._root: tk.Tk | None = None
        self._status_label: tk.Label | None = None
        self._ai_badge: tk.Label | None = None
        self._mute_btn: tk.Button | None = None
        self._level_canvas: tk.Canvas | None = None
        self._log_box: tk.Text | None = None
        self._cmd_entry: tk.Entry | None = None
        self._key_entry: tk.Entry | None = None

    @property
    def is_visible(self) -> bool:
        return self._visible

    def set_state(self, state_text: str, muted: bool | None = None) -> None:
        with self._lock:
            self._state_text = state_text
            if muted is not None:
                self._muted = muted

    def set_level(self, level: float) -> None:
        with self._lock:
            self._mic_level = max(0.0, min(1.0, level))

    def set_ai_ready(self, ready: bool) -> None:
        self._ai_ready = ready

    def append_log(self, speaker: str, message: str) -> None:
        with self._lock:
            self._pending_logs.append((speaker, message))

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
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def _show_sync(self) -> None:
        if self._root is not None:
            self._root.deiconify()
            self._root.lift()

    def _hide_sync(self) -> None:
        if self._root is not None:
            self._root.withdraw()

    def _handle_exit(self) -> None:
        if self._on_exit:
            self._on_exit()
        else:
            self.close()

    def _submit_entry(self, _event: object = None) -> None:
        if self._cmd_entry is None:
            return
        text = self._cmd_entry.get().strip()
        if not text:
            return
        self._cmd_entry.delete(0, tk.END)
        if self._on_submit_text:
            self._on_submit_text(text)

    def _save_key(self) -> None:
        if self._key_entry is None:
            return
        val = self._key_entry.get().strip()
        if self._on_save_api_key:
            self._on_save_api_key(val)

    def run_mainloop(self, start_visible: bool = True) -> None:
        root = tk.Tk()
        root.title("Gemini // Asistente")
        root.configure(bg="#070B12")
        root.attributes("-topmost", True)
        root.attributes("-alpha", self.opacity)
        root.geometry(f"{self.width}x{self.height}+32+32")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._handle_exit)

        # Header
        header = tk.Frame(root, bg="#0C1422", pady=6)
        header.pack(fill=tk.X)

        self._status_label = tk.Label(
            header,
            text="GEMINI // INICIANDO",
            fg="#38BDF8",
            bg="#0C1422",
            font=("Consolas", 10, "bold"),
            padx=10,
        )
        self._status_label.pack(side=tk.LEFT)

        tk.Button(
            header,
            text="✕ Salir",
            command=self._handle_exit,
            bg="#991B1B",
            fg="#FEE2E2",
            activebackground="#DC2626",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(4, 8))

        tk.Button(
            header,
            text="2do Plano (Tray)",
            command=self.hide,
            bg="#1E293B",
            fg="#E2E8F0",
            activebackground="#334155",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=4)

        # Voice Meter & Primary Actions
        voice_bar = tk.Frame(root, bg="#0A111E", pady=8)
        voice_bar.pack(fill=tk.X, padx=10, pady=(8, 4))

        self._level_canvas = tk.Canvas(
            voice_bar, width=180, height=14, bg="#111C2E", highlightthickness=0
        )
        self._level_canvas.pack(side=tk.LEFT, padx=(10, 8))

        tk.Button(
            voice_bar,
            text="🎙 Hablar (Ctrl+Alt+G)",
            command=lambda: self._on_push_to_talk and self._on_push_to_talk(),
            bg="#0EA5E9",
            fg="#04101B",
            activebackground="#38BDF8",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=4)

        self._mute_btn = tk.Button(
            voice_bar,
            text="Silenciar Mic",
            command=lambda: self._on_toggle_mute and self._on_toggle_mute(),
            bg="#1E293B",
            fg="#E2E8F0",
            activebackground="#334155",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            pady=4,
            cursor="hand2",
        )
        self._mute_btn.pack(side=tk.RIGHT, padx=(4, 10))

        # Conversation / Action Log
        log_frame = tk.Frame(root, bg="#070B12")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        self._log_box = tk.Text(
            log_frame,
            bg="#0B1220",
            fg="#E2E8F0",
            insertbackground="#38BDF8",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            wrap=tk.WORD,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )
        self._log_box.pack(fill=tk.BOTH, expand=True)
        self._log_box.tag_config("user", foreground="#7DD3FC", font=("Segoe UI", 9, "bold"))
        self._log_box.tag_config("gemini", foreground="#A5B4FC", font=("Segoe UI", 9))
        self._log_box.tag_config("sys", foreground="#64748B", font=("Consolas", 8))

        # Text input row
        input_row = tk.Frame(root, bg="#070B12", pady=4)
        input_row.pack(fill=tk.X, padx=10)

        self._cmd_entry = tk.Entry(
            input_row,
            bg="#111C2E",
            fg="#F1F5F9",
            insertbackground="#38BDF8",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        )
        self._cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 6))
        self._cmd_entry.bind("<Return>", self._submit_entry)

        tk.Button(
            input_row,
            text="Enviar",
            command=self._submit_entry,
            bg="#6366F1",
            fg="#FFFFFF",
            activebackground="#818CF8",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            padx=12,
            pady=5,
            cursor="hand2",
        ).pack(side=tk.RIGHT)

        # Quick command hints
        hints = tk.Frame(root, bg="#09101B", pady=4)
        hints.pack(fill=tk.X, padx=10, pady=(2, 4))
        for idx, example in enumerate(QUICK_EXAMPLES):
            hints.grid_columnconfigure(idx % 3, weight=1)
            tk.Label(
                hints,
                text=example,
                bg="#101A2B",
                fg="#94A3B8",
                font=("Segoe UI", 7),
                padx=4,
                pady=2,
            ).grid(row=idx // 3, column=idx % 3, sticky="ew", padx=2, pady=2)

        # Settings footer: TTS toggle + optional Gemini API Key
        footer = tk.Frame(root, bg="#0C1422", pady=6)
        footer.pack(fill=tk.X, padx=10, pady=(0, 8))

        tts_var = tk.BooleanVar(value=self._initial_tts)
        tk.Checkbutton(
            footer,
            text="Voz",
            variable=tts_var,
            command=lambda: self._on_toggle_tts and self._on_toggle_tts(tts_var.get()),
            bg="#0C1422",
            fg="#E2E8F0",
            selectcolor="#0F172A",
            activebackground="#0C1422",
            activeforeground="#38BDF8",
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(6, 4))

        self._ai_badge = tk.Label(
            footer,
            text="IA Activa" if self._ai_ready else "Solo Offline",
            fg="#22C55E" if self._ai_ready else "#94A3B8",
            bg="#0C1422",
            font=("Consolas", 8, "bold"),
            padx=4,
        )
        self._ai_badge.pack(side=tk.LEFT, padx=4)

        tk.Button(
            footer,
            text="Guardar Key",
            command=self._save_key,
            bg="#1E293B",
            fg="#E2E8F0",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            padx=8,
            pady=2,
            cursor="hand2",
        ).pack(side=tk.RIGHT, padx=(4, 6))

        self._key_entry = tk.Entry(
            footer,
            show="*",
            bg="#111C2E",
            fg="#E2E8F0",
            insertbackground="#38BDF8",
            relief=tk.FLAT,
            font=("Consolas", 8),
            width=22,
        )
        if self._initial_api_key:
            self._key_entry.insert(0, self._initial_api_key)
        self._key_entry.pack(side=tk.RIGHT, ipady=3, padx=2)

        tk.Label(
            footer, text="API Key:", bg="#0C1422", fg="#94A3B8", font=("Segoe UI", 8)
        ).pack(side=tk.RIGHT, padx=2)

        self._root = root
        self._visible = start_visible
        if not start_visible:
            root.withdraw()

        root.after(40, self._refresh_tick)
        root.mainloop()

    def _refresh_tick(self) -> None:
        if self._root is None:
            return

        with self._lock:
            state = self._state_text
            muted = self._muted
            level = self._mic_level
            logs = list(self._pending_logs)
            self._pending_logs.clear()

        if self._visible:
            if self._status_label is not None:
                col = "#F59E0B" if muted else ("#22C55E" if "OYENDO" in state or "HABLA" in state else "#38BDF8")
                self._status_label.config(text=f"GEMINI // {state}", fg=col)

            if self._mute_btn is not None:
                if muted:
                    self._mute_btn.config(text="Activar Mic", bg="#F59E0B", fg="#04101B")
                else:
                    self._mute_btn.config(text="Silenciar Mic", bg="#1E293B", fg="#E2E8F0")

            if self._ai_badge is not None:
                self._ai_badge.config(
                    text="IA Activa" if self._ai_ready else "Solo Offline",
                    fg="#22C55E" if self._ai_ready else "#94A3B8",
                )

            if self._level_canvas is not None:
                self._level_canvas.delete("all")
                bar_w = int(level * 180)
                bar_col = "#64748B" if muted else ("#22C55E" if level > 0.25 else "#38BDF8")
                self._level_canvas.create_rectangle(0, 0, max(bar_w, 3), 14, fill=bar_col, outline="")

        if logs and self._log_box is not None:
            self._log_box.config(state=tk.NORMAL)
            for speaker, msg in logs:
                tag = "user" if speaker == "Tú" else ("gemini" if speaker == "Gemini" else "sys")
                self._log_box.insert(tk.END, f"{speaker}: ", tag)
                self._log_box.insert(tk.END, f"{msg}\n")
            self._log_box.see(tk.END)
            self._log_box.config(state=tk.DISABLED)

        self._root.after(40, self._refresh_tick)

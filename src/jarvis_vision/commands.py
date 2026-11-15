"""Local Spanish voice command router for instant Windows control."""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import unicodedata
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Callable

from .win_input import (
    VK_CONTROL,
    VK_D,
    VK_LEFT,
    VK_LWIN,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    VK_MENU,
    VK_RIGHT,
    VK_S,
    VK_SHIFT,
    VK_TAB,
    VK_VOLUME_DOWN,
    VK_VOLUME_MUTE,
    VK_VOLUME_UP,
    lock_workstation,
    send_hotkey,
    send_key,
)


@dataclass
class CommandResult:
    handled: bool
    reply: str = ""
    action: str = ""


def normalize_text(text: str) -> str:
    """Lowercase, remove diacritics, and collapse punctuation/spaces."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", no_accents)
    return " ".join(cleaned.split())


def extract_wake_command(
    raw_text: str,
    wake_words: list[str] | tuple[str, ...],
) -> tuple[bool, str]:
    """Check if text starts with or contains a wake word; return (triggered, command_body)."""
    norm_raw = normalize_text(raw_text)
    if not norm_raw:
        return False, ""

    norm_wakes = [normalize_text(w) for w in wake_words if normalize_text(w)]
    words = norm_raw.split()

    for idx, word in enumerate(words[:3]):  # wake word expected near start of utterance
        if word in norm_wakes:
            # Slice raw_text proportionally or strip up to the wake word in normalized form
            remaining = " ".join(words[idx + 1 :]).strip()
            return True, remaining

    return False, ""


def _launch_app(exe_candidates: list[str], fallback_url: str | None = None) -> bool:
    for candidate in exe_candidates:
        expanded = os.path.expandvars(candidate)
        if os.path.exists(expanded):
            subprocess.Popen([expanded], shell=False)
            return True
        found = shutil.which(expanded)
        if found:
            subprocess.Popen([found], shell=False)
            return True
    if fallback_url:
        webbrowser.open(fallback_url)
        return True
    return False


def _extract_number(norm: str, default: int = 5) -> int:
    m = re.search(r"\b(\d{1,2})\b", norm)
    if m:
        return max(1, min(int(m.group(1)), 25))
    return default


class LocalCommandRouter:
    """Executes offline Windows media, app, window, and assistant commands."""

    def __init__(
        self,
        on_hide_hud: Callable[[], None] | None = None,
        on_show_hud: Callable[[], None] | None = None,
        on_mute_mic: Callable[[], None] | None = None,
    ) -> None:
        self._on_hide_hud = on_hide_hud
        self._on_show_hud = on_show_hud
        self._on_mute_mic = on_mute_mic

    def execute(self, raw_command: str) -> CommandResult:
        cmd = normalize_text(raw_command)
        if not cmd:
            return CommandResult(handled=True, reply="Te escucho.", action="WAKE_ONLY")

        # 1. Media playback
        if any(p in cmd for p in ("pausa", "reproduce", "play", "pon musica", "continua", "deten la musica")):
            send_key(VK_MEDIA_PLAY_PAUSE)
            return CommandResult(True, "Listo, reproducción alternada.", "MEDIA_PLAY_PAUSE")

        if any(p in cmd for p in ("siguiente cancion", "proxima cancion", "siguiente pista", "cambia de cancion", "pasa cancion")):
            send_key(VK_MEDIA_NEXT_TRACK)
            return CommandResult(True, "Siguiente pista.", "MEDIA_NEXT")

        if any(p in cmd for p in ("cancion anterior", "anterior pista", "regresa cancion")):
            send_key(VK_MEDIA_PREV_TRACK)
            return CommandResult(True, "Pista anterior.", "MEDIA_PREV")

        # 2. Volume
        if any(p in cmd for p in ("sube el volumen", "sube volumen", "mas volumen", "subir volumen")):
            steps = _extract_number(cmd, default=5)
            send_key(VK_VOLUME_UP, repeat=steps)
            return CommandResult(True, "Volumen subido.", "VOLUME_UP")

        if any(p in cmd for p in ("baja el volumen", "baja volumen", "menos volumen", "bajar volumen")):
            steps = _extract_number(cmd, default=5)
            send_key(VK_VOLUME_DOWN, repeat=steps)
            return CommandResult(True, "Volumen bajado.", "VOLUME_DOWN")

        if any(p in cmd for p in ("silencia el sonido", "quita el sonido", "silenciar audio", "pon silencio", "mute")):
            send_key(VK_VOLUME_MUTE)
            return CommandResult(True, "Audio silenciado.", "VOLUME_MUTE")

        # 3. Web search & YouTube
        yt_match = re.match(r"^(?:busca|buscar|pon)\s+(?:en\s+)?youtube\s+(.+)$", cmd)
        if yt_match:
            query = yt_match.group(1).strip()
            webbrowser.open(f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}")
            return CommandResult(True, f"Buscando {query} en YouTube.", "SEARCH_YOUTUBE")

        google_match = re.match(r"^(?:busca|buscar|investiga)\s+(?:en\s+google\s+)?(.+)$", cmd)
        if google_match:
            query = google_match.group(1).strip()
            webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}")
            return CommandResult(True, f"Buscando {query} en Google.", "SEARCH_GOOGLE")

        # 4. Open common apps & sites
        if any(p in cmd for p in ("abre chrome", "abrir chrome", "abre el navegador")):
            ok = _launch_app(
                [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    "chrome.exe",
                ],
                fallback_url="https://www.google.com",
            )
            return CommandResult(ok, "Abriendo Chrome.", "OPEN_CHROME")

        if any(p in cmd for p in ("abre youtube", "abrir youtube")):
            webbrowser.open("https://www.youtube.com")
            return CommandResult(True, "Abriendo YouTube.", "OPEN_YOUTUBE")

        if any(p in cmd for p in ("abre spotify", "abrir spotify")):
            ok = _launch_app(
                [r"%APPDATA%\Spotify\Spotify.exe", "spotify.exe"],
                fallback_url="https://open.spotify.com",
            )
            return CommandResult(ok, "Abriendo Spotify.", "OPEN_SPOTIFY")

        if any(p in cmd for p in ("abre obsidian", "abrir obsidian")):
            ok = _launch_app(
                [r"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe", "obsidian.exe"]
            )
            return CommandResult(
                True,
                "Abriendo Obsidian." if ok else "No encontré Obsidian instalado.",
                "OPEN_OBSIDIAN",
            )

        if any(p in cmd for p in ("abre vs code", "abre vscode", "abre code", "visual studio code")):
            ok = _launch_app(
                [r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe", "code.cmd", "code"]
            )
            return CommandResult(
                True,
                "Abriendo VS Code." if ok else "No encontré VS Code.",
                "OPEN_VSCODE",
            )

        if any(p in cmd for p in ("abre whatsapp", "abrir whatsapp")):
            webbrowser.open("https://web.whatsapp.com")
            return CommandResult(True, "Abriendo WhatsApp Web.", "OPEN_WHATSAPP")

        if any(p in cmd for p in ("abre terminal", "abre consola", "abre powershell")):
            _launch_app(["wt.exe", "powershell.exe"])
            return CommandResult(True, "Abriendo terminal.", "OPEN_TERMINAL")

        if any(p in cmd for p in ("abre calculadora", "abrir calculadora")):
            _launch_app(["calc.exe"])
            return CommandResult(True, "Abriendo calculadora.", "OPEN_CALC")

        if any(p in cmd for p in ("abre archivos", "abre explorador", "explorador de archivos")):
            _launch_app(["explorer.exe"])
            return CommandResult(True, "Abriendo explorador.", "OPEN_EXPLORER")

        # 5. Window & Desktop control
        if any(p in cmd for p in ("minimiza todo", "muestra el escritorio", "ir al escritorio")):
            send_hotkey(VK_LWIN, VK_D)
            return CommandResult(True, "Escritorio visible.", "SHOW_DESKTOP")

        if any(p in cmd for p in ("cambia de ventana", "cambia ventana", "siguiente ventana")):
            send_hotkey(VK_MENU, VK_TAB)
            return CommandResult(True, "Cambiando de ventana.", "ALT_TAB")

        if any(p in cmd for p in ("escritorio siguiente", "siguiente escritorio")):
            send_hotkey(VK_LWIN, VK_CONTROL, VK_RIGHT)
            return CommandResult(True, "Escritorio siguiente.", "DESKTOP_NEXT")

        if any(p in cmd for p in ("escritorio anterior", "anterior escritorio")):
            send_hotkey(VK_LWIN, VK_CONTROL, VK_LEFT)
            return CommandResult(True, "Escritorio anterior.", "DESKTOP_PREV")

        if any(p in cmd for p in ("captura de pantalla", "toma captura", "screenshot")):
            send_hotkey(VK_LWIN, VK_SHIFT, VK_S)
            return CommandResult(True, "Herramienta de captura lista.", "SCREENSHOT")

        if any(p in cmd for p in ("bloquea la pantalla", "bloquea el pc", "bloquear pantalla")):
            lock_workstation()
            return CommandResult(True, "Pantalla bloqueada.", "LOCK_PC")

        # 6. Time & Date
        if any(p in cmd for p in ("que hora es", "dime la hora", "hora actual")):
            now = dt.datetime.now()
            return CommandResult(True, f"Son las {now.strftime('%I:%M %p').lstrip('0')}.", "TIME")

        if any(p in cmd for p in ("que dia es", "que fecha es", "fecha de hoy")):
            now = dt.datetime.now()
            return CommandResult(True, f"Hoy es {now.strftime('%d/%m/%Y')}.", "DATE")

        # 7. Assistant self-control
        if any(p in cmd for p in ("ocultate", "segundo plano", "minimiza panel", "oculta panel")):
            if self._on_hide_hud:
                self._on_hide_hud()
            return CommandResult(True, "Paso a segundo plano.", "HIDE_HUD")

        if any(p in cmd for p in ("muestrate", "abre panel", "muestra panel")):
            if self._on_show_hud:
                self._on_show_hud()
            return CommandResult(True, "Aquí estoy.", "SHOW_HUD")

        if any(p in cmd for p in ("silencia microfono", "deja de escuchar", "pausa microfono")):
            if self._on_mute_mic:
                self._on_mute_mic()
            return CommandResult(True, "Micrófono pausado.", "MUTE_MIC")

        return CommandResult(handled=False)

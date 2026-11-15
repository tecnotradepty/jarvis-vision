"""Non-blocking audio chimes and Spanish TTS output via Windows System.Speech."""

from __future__ import annotations

import queue
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd


def _make_tone(freqs: list[float], dur_s: float = 0.09, gain: float = 0.10) -> np.ndarray:
    sr = 22050
    parts: list[np.ndarray] = []
    for f in freqs:
        t = np.linspace(0.0, dur_s, int(sr * dur_s), endpoint=False, dtype=np.float32)
        env = np.sin(np.pi * t / dur_s).astype(np.float32)
        parts.append(np.sin(2.0 * np.pi * f * t) * env * gain)
    return np.concatenate(parts)


_CHIMES: dict[str, np.ndarray] = {
    "wake": _make_tone([587.33, 880.0], dur_s=0.07, gain=0.09),
    "ok": _make_tone([659.25, 987.77], dur_s=0.06, gain=0.07),
    "error": _make_tone([349.23, 277.18], dur_s=0.09, gain=0.08),
}


class SpeechOut:
    """Plays subtle synth chimes and speaks Spanish responses without blocking callers."""

    def __init__(self, tts_enabled: bool = True, chime_enabled: bool = True) -> None:
        self.tts_enabled = tts_enabled
        self.chime_enabled = chime_enabled
        self.is_speaking = threading.Event()
        self._last_spoke_end_t = 0.0
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._proc: subprocess.Popen[str] | None = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    @property
    def recently_spoke(self) -> bool:
        return self.is_speaking.is_set() or (time.monotonic() - self._last_spoke_end_t) < 0.45

    def play_chime(self, kind: str = "ok") -> None:
        if not self.chime_enabled:
            return
        tone = _CHIMES.get(kind)
        if tone is None:
            return
        try:
            sd.play(tone, samplerate=22050, blocking=False)
        except Exception:
            pass

    def speak(self, text: str) -> None:
        clean = " ".join(text.strip().split())
        if not clean or not self.tts_enabled:
            return
        self._queue.put(clean)

    def _ensure_ps_worker(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc

        ps_script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "try { $s.SelectVoice('Microsoft Helena Desktop') } catch {}; "
            "$s.Rate = 1; "
            "while ($true) { "
            "  $line = [Console]::In.ReadLine(); "
            "  if ($null -eq $line -or $line -eq '__EXIT__') { break }; "
            "  if ($line.Length -gt 0) { $s.Speak($line); [Console]::Out.WriteLine('DONE'); [Console]::Out.Flush() } "
            "}"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=creationflags,
        )
        return self._proc

    def _worker(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                break
            # Drain to speak only the latest queued message if multiple arrived
            while not self._queue.empty():
                nxt = self._queue.get_nowait()
                if nxt is None:
                    return
                text = nxt

            try:
                self.is_speaking.set()
                proc = self._ensure_ps_worker()
                if proc.stdin and proc.stdout:
                    proc.stdin.write(text.replace("\n", " ") + "\n")
                    proc.stdin.flush()
                    proc.stdout.readline()
            except Exception:
                self._proc = None
            finally:
                self._last_spoke_end_t = time.monotonic()
                self.is_speaking.clear()

    def close(self) -> None:
        self._queue.put(None)
        if self._proc is not None and self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.write("__EXIT__\n")
                    self._proc.stdin.flush()
                self._proc.terminate()
            except Exception:
                pass

"""Background microphone listener with adaptive VAD, SpeechRecognition + offline Vosk fallback."""

from __future__ import annotations

import collections
import io
import json
import queue
import threading
import time
import urllib.request
import wave
import zipfile
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import speech_recognition as sr
from vosk import KaldiRecognizer, Model as VoskModel, SetLogLevel

from .config import BASE_DIR

SetLogLevel(-1)

SAMPLE_RATE = 16000
BLOCK_SAMPLES = 480  # 30 ms per block
PRE_ROLL_BLOCKS = 12  # ~360 ms pre-roll so wake word start isn't clipped

VOSK_ES_URL = "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"
VOSK_ES_DIR = BASE_DIR / "models" / "vosk-model-small-es-0.42"


def ensure_vosk_model(model_dir: Path = VOSK_ES_DIR) -> Path:
    """Download and extract the compact Spanish Vosk model (~39 MB) once for offline fallback."""
    if (model_dir / "am" / "final.mdl").exists():
        return model_dir
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_path = model_dir.parent / "vosk-model-small-es-0.42.zip"
    if not zip_path.exists():
        urllib.request.urlretrieve(VOSK_ES_URL, zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(model_dir.parent)
    if zip_path.exists():
        zip_path.unlink()
    return model_dir


def _float32_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def _pcm16_to_wav_bytes(pcm16: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)
    return buf.getvalue()


class VoiceListener:
    """Listens quietly in background and transcribes utterances via SpeechRecognition + offline Vosk."""

    def __init__(
        self,
        stt_mode: str = "auto",
        language: str = "es-ES",
        device_index: int | None = None,
        vad_min_rms: float = 0.014,
        vad_multiplier: float = 2.6,
        silence_timeout_s: float = 0.65,
        should_ignore_audio: Callable[[], bool] | None = None,
        on_level: Callable[[float], None] | None = None,
        on_state: Callable[[str], None] | None = None,
        on_utterance: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.stt_mode = stt_mode  # "auto" (Google online + Vosk offline fallback) | "offline"
        self.language = language
        self.device_index = device_index
        self.vad_min_rms = vad_min_rms
        self.vad_multiplier = vad_multiplier
        self.silence_timeout_s = silence_timeout_s
        self._should_ignore_audio = should_ignore_audio
        self._on_level = on_level
        self._on_state = on_state
        self._on_utterance = on_utterance

        self._stop_event = threading.Event()
        self._muted = False
        self._ptt_active = False
        self._ptt_lock = threading.Lock()
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=256)
        self._recognizer = sr.Recognizer()
        self._vosk_model: VoskModel | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_muted(self) -> bool:
        return self._muted

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._on_state:
            self._on_state("SILENCIADO" if self._muted else "ESCUCHANDO")

    def trigger_push_to_talk(self) -> None:
        with self._ptt_lock:
            self._ptt_active = True
        if self._on_state:
            self._on_state("HABLA AHORA")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _get_vosk_model(self) -> VoskModel:
        if self._vosk_model is None:
            path = ensure_vosk_model()
            self._vosk_model = VoskModel(str(path))
        return self._vosk_model

    def _audio_callback(self, indata: np.ndarray, frames: int, _time_info: object, status: object) -> None:
        if self._stop_event.is_set():
            return
        mono = indata[:, 0].copy()
        try:
            self._audio_queue.put_nowait(mono)
        except queue.Full:
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.put_nowait(mono)
            except queue.Empty:
                pass

    def _transcribe_vosk(self, pcm16: bytes) -> str:
        model = self._get_vosk_model()
        rec = KaldiRecognizer(model, SAMPLE_RATE)
        rec.AcceptWaveform(pcm16)
        res = json.loads(rec.FinalResult())
        return str(res.get("text", "")).strip()

    def _transcribe(self, audio: np.ndarray) -> str:
        pcm16 = _float32_to_pcm16_bytes(audio)

        if self.stt_mode != "offline":
            try:
                sr_audio = sr.AudioData(pcm16, SAMPLE_RATE, 2)
                text = self._recognizer.recognize_google(sr_audio, language=self.language)
                if text:
                    return str(text).strip()
            except sr.UnknownValueError:
                return ""
            except Exception:
                # Fall back to offline Vosk if network is down
                pass

        try:
            return self._transcribe_vosk(pcm16)
        except Exception:
            return ""

    def _run_loop(self) -> None:
        if self._on_state:
            self._on_state("CARGANDO VOZ...")

        # Preload offline Vosk model in background so fallback is instant
        threading.Thread(target=self._get_vosk_model, daemon=True).start()

        if self._on_state:
            self._on_state("SILENCIADO" if self._muted else "ESCUCHANDO")

        pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=PRE_ROLL_BLOCKS)
        speech_chunks: list[np.ndarray] = []
        recording = False
        last_voice_t = 0.0
        rec_start_t = 0.0
        noise_floor = 0.005

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK_SAMPLES,
                device=self.device_index,
                callback=self._audio_callback,
            ):
                while not self._stop_event.is_set():
                    try:
                        chunk = self._audio_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    rms = float(np.sqrt(np.mean(np.square(chunk))))
                    if self._on_level:
                        self._on_level(min(1.0, rms * 14.0))

                    if self._muted or (self._should_ignore_audio and self._should_ignore_audio()):
                        recording = False
                        speech_chunks.clear()
                        pre_roll.clear()
                        continue

                    now = time.monotonic()
                    threshold = max(self.vad_min_rms, noise_floor * self.vad_multiplier)

                    if not recording:
                        pre_roll.append(chunk)
                        if rms >= threshold:
                            recording = True
                            rec_start_t = now
                            last_voice_t = now
                            speech_chunks = list(pre_roll)
                            speech_chunks.append(chunk)
                            if self._on_state:
                                self._on_state("OYENDO...")
                        else:
                            noise_floor = noise_floor * 0.96 + min(rms, 0.03) * 0.04
                    else:
                        speech_chunks.append(chunk)
                        if rms >= threshold * 0.75:
                            last_voice_t = now

                        timed_out = (now - last_voice_t) >= self.silence_timeout_s
                        too_long = (now - rec_start_t) >= 7.5
                        if timed_out or too_long:
                            recording = False
                            audio_arr = np.concatenate(speech_chunks)
                            speech_chunks.clear()

                            if len(audio_arr) >= int(SAMPLE_RATE * 0.35):
                                if self._on_state:
                                    self._on_state("PROCESANDO...")
                                text = self._transcribe(audio_arr)
                                with self._ptt_lock:
                                    was_ptt = self._ptt_active
                                    self._ptt_active = False

                                if text and self._on_utterance:
                                    self._on_utterance(text, was_ptt)

                            if self._on_state and not self._muted:
                                self._on_state("ESCUCHANDO")
        except Exception as exc:
            if self._on_state:
                self._on_state(f"ERROR MIC: {exc}")

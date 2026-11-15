"""Configuration management for Gemini Desktop Assistant."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "assistant": {
        "name": "Gemini",
        "wake_words": ["gemini", "geminis", "gémini", "géminis", "jemini", "yemini", "hemini"],
        "stt_mode": "auto",
        "language": "es-ES",
        "tts_enabled": True,
        "chime_enabled": True,
        "mic_device_index": None,
        "vad_min_rms": 0.014,
        "vad_multiplier": 2.6,
        "silence_timeout_s": 0.65,
    },
    "ai": {
        "gemini_api_key": "",
        "model": "gemini-2.5-flash",
    },
    "ui": {
        "start_minimized": False,
        "hud_width": 520,
        "hud_height": 540,
        "hud_opacity": 0.96,
        "hotkey_push_to_talk": "<ctrl>+<alt>+g",
        "hotkey_toggle_mic": "<ctrl>+<alt>+m",
        "hotkey_toggle_hud": "<ctrl>+<alt>+h",
    },
    "camera": {
        "index": 0,
        "width": 640,
        "height": 480,
        "fps": 30,
        "mirror": True,
    },
    "tracking": {
        "sensitivity": 2.2,
        "roi_center_x": 0.50,
        "roi_center_y": 0.45,
        "cursor_anchor": "palm",
        "min_cutoff": 2.0,
        "beta": 0.08,
        "d_cutoff": 1.0,
        "deadzone_px": 1.0,
    },
    "gestures": {
        "pinch_down_ratio": 0.32,
        "pinch_up_ratio": 0.42,
        "drag_hold_ms": 260,
        "double_click_window_ms": 480,
        "right_click_cooldown_ms": 450,
        "scroll_speed": 55.0,
    },
}


def compute_roi(
    sensitivity: float,
    center_x: float = 0.50,
    center_y: float = 0.45,
) -> tuple[float, float, float, float]:
    """Compute clamped (x_min, x_max, y_min, y_max) ROI from sensitivity multiplier."""
    sens = max(1.0, min(float(sensitivity), 4.0))
    half_w = min(0.46, 0.36 / sens)
    half_h = min(0.44, 0.32 / sens)
    x_min = max(0.04, center_x - half_w)
    x_max = min(0.96, center_x + half_w)
    y_min = max(0.04, center_y - half_h)
    y_max = min(0.96, center_y + half_h)
    return (x_min, x_max, y_min, y_max)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config from disk merged with defaults."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        save_config(DEFAULT_CONFIG, cfg_path)
        return copy.deepcopy(DEFAULT_CONFIG)

    with cfg_path.open("r", encoding="utf-8") as fh:
        user_cfg = json.load(fh)
    return _deep_merge(DEFAULT_CONFIG, user_cfg)


def save_config(cfg: dict[str, Any], path: Path | None = None) -> None:
    """Persist configuration to JSON."""
    cfg_path = path or DEFAULT_CONFIG_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)

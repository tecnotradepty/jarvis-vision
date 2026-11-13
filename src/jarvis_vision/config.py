"""Configuration management for Jarvis Vision."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "camera": {
        "index": 0,
        "width": 640,
        "height": 480,
        "fps": 30,
        "mirror": True,
    },
    "tracking": {
        "roi_x_min": 0.20,
        "roi_x_max": 0.80,
        "roi_y_min": 0.18,
        "roi_y_max": 0.78,
        "cursor_anchor": "knuckle",
        "min_cutoff": 1.4,
        "beta": 0.04,
        "d_cutoff": 1.0,
        "deadzone_px": 1.5,
    },
    "gestures": {
        "pinch_down_ratio": 0.30,
        "pinch_up_ratio": 0.40,
        "pinch_freeze_ratio": 0.48,
        "drag_hold_ms": 220,
        "right_click_cooldown_ms": 450,
        "scroll_speed": 42.0,
        "sleep_hold_ms": 800,
    },
    "ui": {
        "start_minimized": True,
        "hud_width": 460,
        "hud_height": 360,
        "hud_opacity": 0.92,
        "hotkey_toggle_tracking": "<ctrl>+<alt>+j",
        "hotkey_toggle_hud": "<ctrl>+<alt>+h",
    },
}


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

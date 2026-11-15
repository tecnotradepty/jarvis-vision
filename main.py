"""Entry point for Gemini Desktop Voice Assistant."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jarvis_vision.tray import GeminiAssistantApp
from jarvis_vision.win_input import acquire_single_instance, focus_existing_window


def main() -> None:
    if not acquire_single_instance():
        focus_existing_window()
        return

    app = GeminiAssistantApp()
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()
    finally:
        app.stop()
        os._exit(0)


if __name__ == "__main__":
    main()

"""Unit tests for Gemini wake word extraction and local command routing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jarvis_vision.commands import LocalCommandRouter, extract_wake_command, normalize_text


class VoiceCommandTests(unittest.TestCase):
    def test_wake_word_fuzzy_variants(self) -> None:
        wakes = ["gemini", "geminis", "gémini", "jemini", "yemini"]

        ok, body = extract_wake_command("Gemini, sube el volumen", wakes)
        self.assertTrue(ok)
        self.assertEqual(body, "sube el volumen")

        ok2, body2 = extract_wake_command("Oye Gémini abre Chrome", wakes)
        self.assertTrue(ok2)
        self.assertEqual(body2, "abre chrome")

        ok3, _ = extract_wake_command("sube el volumen por favor", wakes)
        self.assertFalse(ok3)

    def test_time_and_date_local_commands(self) -> None:
        router = LocalCommandRouter()
        res_time = router.execute("qué hora es")
        self.assertTrue(res_time.handled)
        self.assertEqual(res_time.action, "TIME")
        self.assertIn("Son las", res_time.reply)

        res_date = router.execute("dime la fecha de hoy")
        self.assertTrue(res_date.handled)
        self.assertEqual(res_date.action, "DATE")

    def test_unrecognized_command_falls_through_to_ai(self) -> None:
        router = LocalCommandRouter()
        res = router.execute("explícame qué es un agujero negro")
        self.assertFalse(res.handled)

    def test_normalize_strips_accents(self) -> None:
        self.assertEqual(normalize_text("¡Qué HORA es, Gémini!"), "que hora es gemini")


if __name__ == "__main__":
    unittest.main()

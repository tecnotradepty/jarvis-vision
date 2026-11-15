"""Unit tests for re-engineered gestures (click, double-click, drag, scroll, clutch) and ROI sensitivity."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jarvis_vision.gestures import GestureEngine
from jarvis_vision.smoothing import CursorMapper


def _make_open_hand(
    thumb_tip: tuple[float, float] = (0.35, 0.55),
    index_tip: tuple[float, float] = (0.45, 0.25),
    middle_tip: tuple[float, float] = (0.52, 0.24),
    ring_tip: tuple[float, float] = (0.59, 0.26),
    pinky_tip: tuple[float, float] = (0.65, 0.30),
    curled_middle: bool = False,
    curled_ring: bool = False,
    curled_pinky: bool = False,
    curled_index: bool = False,
) -> list[tuple[float, float, float]]:
    lms = [(0.5, 0.7, 0.0)] * 21
    lms[0] = (0.50, 0.80, 0.0)   # WRIST
    lms[1] = (0.43, 0.72, 0.0)
    lms[2] = (0.39, 0.65, 0.0)
    lms[3] = (0.37, 0.60, 0.0)
    lms[4] = (*thumb_tip, 0.0)

    lms[5] = (0.45, 0.52, 0.0)   # INDEX_MCP
    lms[6] = (0.45, 0.40, 0.0)   # INDEX_PIP
    lms[7] = (0.45, 0.32, 0.0)
    lms[8] = (0.48, 0.54, 0.0) if curled_index else (*index_tip, 0.0)

    lms[9] = (0.51, 0.51, 0.0)   # MIDDLE_MCP
    lms[10] = (0.51, 0.39, 0.0)  # MIDDLE_PIP
    lms[11] = (0.51, 0.31, 0.0)
    lms[12] = (0.51, 0.55, 0.0) if curled_middle else (*middle_tip, 0.0)

    lms[13] = (0.57, 0.52, 0.0)  # RING_MCP
    lms[14] = (0.57, 0.41, 0.0)  # RING_PIP
    lms[15] = (0.57, 0.33, 0.0)
    lms[16] = (0.54, 0.56, 0.0) if curled_ring else (*ring_tip, 0.0)

    lms[17] = (0.62, 0.55, 0.0)  # PINKY_MCP
    lms[18] = (0.62, 0.45, 0.0)  # PINKY_PIP
    lms[19] = (0.62, 0.37, 0.0)
    lms[20] = (0.56, 0.58, 0.0) if curled_pinky else (*pinky_tip, 0.0)
    return lms


class GestureAndSmoothingTests(unittest.TestCase):
    def test_open_hand_moves_and_fist_clutches(self) -> None:
        engine = GestureEngine()
        act = engine.evaluate(_make_open_hand(), 1.0)
        self.assertEqual(act.mode, "ACTIVE")
        self.assertFalse(act.freeze_cursor)

        fist = _make_open_hand(
            curled_index=True, curled_middle=True, curled_ring=True, curled_pinky=True
        )
        act_fist = engine.evaluate(fist, 1.05)
        self.assertEqual(act_fist.mode, "CLUTCH")
        self.assertTrue(act_fist.freeze_cursor)

    def test_quick_tap_and_double_click_never_stick(self) -> None:
        engine = GestureEngine(drag_hold_ms=260, double_click_window_ms=480)
        pinch = _make_open_hand(thumb_tip=(0.45, 0.30), index_tip=(0.46, 0.31))
        open_hand = _make_open_hand()

        # First tap down -> does NOT emit left_down_event yet
        a1 = engine.evaluate(pinch, 1.00)
        self.assertFalse(a1.left_down_event)
        self.assertFalse(a1.left_click_event)
        self.assertEqual(a1.mode, "LEFT_TAP_HOLD")

        # Release quickly (< 260ms) -> atomic left_click_event
        a2 = engine.evaluate(open_hand, 1.12)
        self.assertTrue(a2.left_click_event)
        self.assertFalse(a2.left_down_event)
        self.assertEqual(a2.mode, "LEFT_CLICK")

        # Second tap quickly within 480ms -> DOUBLE_CLICK
        engine.evaluate(pinch, 1.24)
        a4 = engine.evaluate(open_hand, 1.32)
        self.assertTrue(a4.left_click_event)
        self.assertEqual(a4.mode, "DOUBLE_CLICK")

    def test_hold_triggers_drag_and_release_ends_it(self) -> None:
        engine = GestureEngine(drag_hold_ms=260)
        pinch = _make_open_hand(thumb_tip=(0.45, 0.30), index_tip=(0.46, 0.31))

        engine.evaluate(pinch, 1.00)
        a_hold = engine.evaluate(pinch, 1.30)
        self.assertTrue(a_hold.left_down_event)
        self.assertEqual(a_hold.mode, "DRAGGING")

        a_rel = engine.evaluate(_make_open_hand(), 1.45)
        self.assertTrue(a_rel.left_up_event)
        self.assertFalse(a_rel.left_click_event)

    def test_scroll_two_fingers(self) -> None:
        engine = GestureEngine(scroll_speed=55.0)
        pose1 = _make_open_hand(
            index_tip=(0.45, 0.28),
            middle_tip=(0.51, 0.28),
            curled_ring=True,
            curled_pinky=True,
        )
        pose2 = _make_open_hand(
            index_tip=(0.45, 0.22),
            middle_tip=(0.51, 0.22),
            curled_ring=True,
            curled_pinky=True,
        )
        s1 = engine.evaluate(pose1, 1.0)
        self.assertEqual(s1.mode, "SCROLL")
        self.assertEqual(s1.scroll_delta, 0.0)

        s2 = engine.evaluate(pose2, 1.05)
        self.assertEqual(s2.mode, "SCROLL")
        self.assertGreater(s2.scroll_delta, 0.0)

    def test_sensitivity_shrinks_roi_ergonomically(self) -> None:
        low = CursorMapper(1920, 1080, sensitivity=1.0)
        high = CursorMapper(1920, 1080, sensitivity=2.5)
        low_span = low.roi_x_max - low.roi_x_min
        high_span = high.roi_x_max - high.roi_x_min
        self.assertGreater(low_span, high_span)
        self.assertEqual(high.map_to_screen(0.1, 0.1, 1.0), (0, 0))


if __name__ == "__main__":
    unittest.main()

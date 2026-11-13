"""Hand landmark geometry & gesture state machine for air-mouse control."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


# MediaPipe 21-landmark indices
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20


@dataclass
class GestureAction:
    """Output of gesture evaluation for a single video frame."""

    mode: str  # ACTIVE | LEFT_PINCH | DRAGGING | RIGHT_CLICK | SCROLL | CLUTCH | SLEEP_TOGGLE | NO_HAND
    anchor_x: float | None = None
    anchor_y: float | None = None
    freeze_cursor: bool = False
    left_down_event: bool = False
    left_up_event: bool = False
    right_click_event: bool = False
    scroll_delta: float = 0.0
    toggle_sleep_event: bool = False
    pinch_ratio: float = 1.0


def _dist2d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _lm_xy(landmarks: Sequence[tuple[float, float, float]], idx: int) -> tuple[float, float]:
    return landmarks[idx][0], landmarks[idx][1]


def _is_finger_extended(
    landmarks: Sequence[tuple[float, float, float]],
    tip_idx: int,
    pip_idx: int,
    mcp_idx: int,
) -> bool:
    """Determine if a non-thumb finger is extended via wrist-distance & joint geometry."""
    wrist = _lm_xy(landmarks, WRIST)
    tip = _lm_xy(landmarks, tip_idx)
    pip = _lm_xy(landmarks, pip_idx)
    mcp = _lm_xy(landmarks, mcp_idx)
    return _dist2d(wrist, tip) > _dist2d(wrist, pip) * 1.08 and _dist2d(wrist, tip) > _dist2d(wrist, mcp)


class GestureEngine:
    """Stateful gesture recognizer with hysteresis, pinch-freeze, and cooldowns."""

    def __init__(
        self,
        cursor_anchor: str = "knuckle",
        pinch_down_ratio: float = 0.30,
        pinch_up_ratio: float = 0.40,
        pinch_freeze_ratio: float = 0.48,
        drag_hold_ms: int = 220,
        right_click_cooldown_ms: int = 450,
        scroll_speed: float = 42.0,
        sleep_hold_ms: int = 800,
    ) -> None:
        self.cursor_anchor = cursor_anchor
        self.pinch_down_ratio = pinch_down_ratio
        self.pinch_up_ratio = pinch_up_ratio
        self.pinch_freeze_ratio = pinch_freeze_ratio
        self.drag_hold_ms = drag_hold_ms
        self.right_click_cooldown_ms = right_click_cooldown_ms
        self.scroll_speed = scroll_speed
        self.sleep_hold_ms = sleep_hold_ms

        self._left_pinched = False
        self._left_pinch_start_t: float | None = None
        self._dragging = False
        self._right_pinched = False
        self._last_right_click_t: float = -10.0
        self._prev_scroll_y: float | None = None
        self._pinky_pinch_start_t: float | None = None
        self._pinky_toggled_in_hold = False

    def reset(self) -> None:
        self._left_pinched = False
        self._left_pinch_start_t = None
        self._dragging = False
        self._right_pinched = False
        self._prev_scroll_y = None
        self._pinky_pinch_start_t = None
        self._pinky_toggled_in_hold = False

    def _get_anchor(self, landmarks: Sequence[tuple[float, float, float]]) -> tuple[float, float]:
        if self.cursor_anchor == "index_tip":
            return _lm_xy(landmarks, INDEX_TIP)
        # Default "knuckle": blend Index MCP (5) & Middle MCP (9) for rock-solid aim during pinches
        ix, iy = _lm_xy(landmarks, INDEX_MCP)
        mx, my = _lm_xy(landmarks, MIDDLE_MCP)
        return (ix * 0.65 + mx * 0.35), (iy * 0.65 + my * 0.35)

    def evaluate(
        self,
        landmarks: Sequence[tuple[float, float, float]] | None,
        t: float,
    ) -> GestureAction:
        """Evaluate normalized 21-point landmarks at timestamp t (seconds)."""
        if not landmarks or len(landmarks) < 21:
            was_pressed = self._left_pinched or self._dragging
            self.reset()
            return GestureAction(mode="NO_HAND", left_up_event=was_pressed)

        wrist = _lm_xy(landmarks, WRIST)
        middle_mcp = _lm_xy(landmarks, MIDDLE_MCP)
        palm_scale = max(_dist2d(wrist, middle_mcp), 1e-4)

        thumb_tip = _lm_xy(landmarks, THUMB_TIP)
        index_tip = _lm_xy(landmarks, INDEX_TIP)
        middle_tip = _lm_xy(landmarks, MIDDLE_TIP)
        pinky_tip = _lm_xy(landmarks, PINKY_TIP)

        left_ratio = _dist2d(thumb_tip, index_tip) / palm_scale
        right_ratio = _dist2d(thumb_tip, middle_tip) / palm_scale
        pinky_ratio = _dist2d(thumb_tip, pinky_tip) / palm_scale

        idx_ext = _is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP, INDEX_MCP)
        mid_ext = _is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP)
        rng_ext = _is_finger_extended(landmarks, RING_TIP, RING_PIP, RING_MCP)
        pnk_ext = _is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP, PINKY_MCP)

        anchor_x, anchor_y = self._get_anchor(landmarks)

        # 1. Sleep toggle gesture: Thumb + Pinky pinch held for sleep_hold_ms
        if pinky_ratio < self.pinch_down_ratio and idx_ext and mid_ext:
            if self._pinky_pinch_start_t is None:
                self._pinky_pinch_start_t = t
            elif (
                not self._pinky_toggled_in_hold
                and (t - self._pinky_pinch_start_t) * 1000.0 >= self.sleep_hold_ms
            ):
                self._pinky_toggled_in_hold = True
                was_pressed = self._left_pinched or self._dragging
                self._left_pinched = False
                self._dragging = False
                return GestureAction(
                    mode="SLEEP_TOGGLE",
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    freeze_cursor=True,
                    left_up_event=was_pressed,
                    toggle_sleep_event=True,
                    pinch_ratio=pinky_ratio,
                )
        else:
            self._pinky_pinch_start_t = None
            self._pinky_toggled_in_hold = False

        # 2. Closed Fist -> Clutch (freeze cursor without clicking)
        if not idx_ext and not mid_ext and not rng_ext and not pnk_ext and not self._dragging:
            was_pressed = self._left_pinched
            self._left_pinched = False
            self._left_pinch_start_t = None
            self._prev_scroll_y = None
            return GestureAction(
                mode="CLUTCH",
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                freeze_cursor=True,
                left_up_event=was_pressed,
                pinch_ratio=left_ratio,
            )

        # 3. Scroll mode: Index + Middle extended, Ring + Pinky curled (and not pinching)
        if (
            idx_ext
            and mid_ext
            and not rng_ext
            and not pnk_ext
            and not self._left_pinched
            and right_ratio > self.pinch_up_ratio
        ):
            scroll_y = (index_tip[1] + middle_tip[1]) * 0.5
            delta = 0.0
            if self._prev_scroll_y is not None:
                dy = self._prev_scroll_y - scroll_y  # hand up -> positive -> scroll up
                if abs(dy) > 0.004:
                    delta = dy * self.scroll_speed
            self._prev_scroll_y = scroll_y
            return GestureAction(
                mode="SCROLL",
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                freeze_cursor=True,
                scroll_delta=delta,
                pinch_ratio=left_ratio,
            )

        self._prev_scroll_y = None

        # 4. Left Click / Drag (Thumb + Index pinch with hysteresis)
        left_down_event = False
        left_up_event = False
        if not self._left_pinched:
            if left_ratio < self.pinch_down_ratio:
                self._left_pinched = True
                self._left_pinch_start_t = t
                self._dragging = False
                left_down_event = True
        else:
            if left_ratio > self.pinch_up_ratio:
                self._left_pinched = False
                self._left_pinch_start_t = None
                self._dragging = False
                left_up_event = True
            elif (
                not self._dragging
                and self._left_pinch_start_t is not None
                and (t - self._left_pinch_start_t) * 1000.0 >= self.drag_hold_ms
            ):
                self._dragging = True

        # 5. Right Click (Thumb + Middle pinch with cooldown, only when not left-pinching)
        right_click_event = False
        if not self._left_pinched and not self._dragging:
            if not self._right_pinched:
                if (
                    right_ratio < self.pinch_down_ratio
                    and (t - self._last_right_click_t) * 1000.0 >= self.right_click_cooldown_ms
                ):
                    self._right_pinched = True
                    self._last_right_click_t = t
                    right_click_event = True
            elif right_ratio > self.pinch_up_ratio:
                self._right_pinched = False

        # Freeze cursor right as user approaches a click (unless actively dragging)
        approaching_left = (not self._dragging) and (left_ratio < self.pinch_freeze_ratio)
        approaching_right = right_ratio < self.pinch_freeze_ratio
        freeze = (approaching_left or approaching_right) and not self._dragging

        mode = "ACTIVE"
        if self._dragging:
            mode = "DRAGGING"
        elif self._left_pinched:
            mode = "LEFT_PINCH"
        elif right_click_event:
            mode = "RIGHT_CLICK"

        return GestureAction(
            mode=mode,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            freeze_cursor=freeze,
            left_down_event=left_down_event,
            left_up_event=left_up_event,
            right_click_event=right_click_event,
            pinch_ratio=left_ratio,
        )

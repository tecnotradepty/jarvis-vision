"""Re-engineered hand gesture state machine with reliable click, double-click, drag, scroll & clutch."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_TIP = 20


@dataclass
class GestureAction:
    """Output of gesture evaluation for a single frame."""

    mode: str  # ACTIVE | LEFT_TAP_HOLD | LEFT_CLICK | DOUBLE_CLICK | DRAGGING | RIGHT_CLICK | SCROLL | CLUTCH | NO_HAND
    anchor_x: float | None = None
    anchor_y: float | None = None
    freeze_cursor: bool = False
    left_click_event: bool = False
    left_down_event: bool = False
    left_up_event: bool = False
    right_click_event: bool = False
    scroll_delta: float = 0.0
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
    wrist = _lm_xy(landmarks, WRIST)
    tip = _lm_xy(landmarks, tip_idx)
    pip = _lm_xy(landmarks, pip_idx)
    mcp = _lm_xy(landmarks, mcp_idx)
    return _dist2d(wrist, tip) > _dist2d(wrist, pip) * 1.05 and _dist2d(wrist, tip) > _dist2d(wrist, mcp)


def _is_finger_curled_tight(
    landmarks: Sequence[tuple[float, float, float]],
    tip_idx: int,
    pip_idx: int,
    palm_center: tuple[float, float],
    palm_scale: float,
) -> bool:
    wrist = _lm_xy(landmarks, WRIST)
    tip = _lm_xy(landmarks, tip_idx)
    pip = _lm_xy(landmarks, pip_idx)
    return _dist2d(tip, palm_center) < palm_scale * 0.78 and _dist2d(wrist, tip) < _dist2d(wrist, pip) * 1.06


class GestureEngine:
    """Stateful gesture recognizer: atomic click/double-click, deliberate hold-to-drag, scroll, clutch."""

    def __init__(
        self,
        cursor_anchor: str = "palm",
        pinch_down_ratio: float = 0.32,
        pinch_up_ratio: float = 0.42,
        drag_hold_ms: int = 260,
        double_click_window_ms: int = 480,
        right_click_cooldown_ms: int = 450,
        scroll_speed: float = 55.0,
    ) -> None:
        self.cursor_anchor = cursor_anchor
        self.pinch_down_ratio = pinch_down_ratio
        self.pinch_up_ratio = pinch_up_ratio
        self.drag_hold_ms = drag_hold_ms
        self.double_click_window_ms = double_click_window_ms
        self.right_click_cooldown_ms = right_click_cooldown_ms
        self.scroll_speed = scroll_speed

        self._left_pinched = False
        self._left_pinch_start_t: float | None = None
        self._dragging = False
        self._last_click_t: float = -10.0
        self._badge_until_t: float = -10.0
        self._badge_mode: str = "ACTIVE"

        self._right_pinched = False
        self._last_right_click_t: float = -10.0
        self._prev_scroll_y: float | None = None

    def reset(self) -> None:
        self._left_pinched = False
        self._left_pinch_start_t = None
        self._dragging = False
        self._right_pinched = False
        self._prev_scroll_y = None
        self._badge_until_t = -10.0

    def _get_anchor(self, landmarks: Sequence[tuple[float, float, float]]) -> tuple[float, float]:
        if self.cursor_anchor == "index_tip":
            return _lm_xy(landmarks, INDEX_TIP)
        if self.cursor_anchor == "knuckle":
            ix, iy = _lm_xy(landmarks, INDEX_MCP)
            mx, my = _lm_xy(landmarks, MIDDLE_MCP)
            return (ix * 0.65 + mx * 0.35), (iy * 0.65 + my * 0.35)
        # Default "palm": MIDDLE_MCP (landmark 9) stays completely stable during pinches & curls
        return _lm_xy(landmarks, MIDDLE_MCP)

    def evaluate(
        self,
        landmarks: Sequence[tuple[float, float, float]] | None,
        t: float,
    ) -> GestureAction:
        if not landmarks or len(landmarks) < 21:
            was_dragging = self._dragging
            self.reset()
            return GestureAction(mode="NO_HAND", left_up_event=was_dragging)

        wrist = _lm_xy(landmarks, WRIST)
        middle_mcp = _lm_xy(landmarks, MIDDLE_MCP)
        palm_scale = max(_dist2d(wrist, middle_mcp), 1e-4)

        thumb_tip = _lm_xy(landmarks, THUMB_TIP)
        index_tip = _lm_xy(landmarks, INDEX_TIP)
        middle_tip = _lm_xy(landmarks, MIDDLE_TIP)

        left_ratio = _dist2d(thumb_tip, index_tip) / palm_scale
        right_ratio = _dist2d(thumb_tip, middle_tip) / palm_scale

        anchor_x, anchor_y = self._get_anchor(landmarks)

        # 1. Strict Closed Fist -> Clutch (only when NOT actively pinching/dragging)
        if not self._left_pinched and not self._dragging:
            all_curled = (
                _is_finger_curled_tight(landmarks, INDEX_TIP, INDEX_PIP, middle_mcp, palm_scale)
                and _is_finger_curled_tight(landmarks, MIDDLE_TIP, MIDDLE_PIP, middle_mcp, palm_scale)
                and _is_finger_curled_tight(landmarks, RING_TIP, RING_PIP, middle_mcp, palm_scale)
                and _is_finger_curled_tight(landmarks, PINKY_TIP, PINKY_PIP, middle_mcp, palm_scale)
            )
            if all_curled:
                self._prev_scroll_y = None
                return GestureAction(
                    mode="CLUTCH",
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    freeze_cursor=True,
                    pinch_ratio=left_ratio,
                )

        # 2. Two-finger Peace sign (Index + Middle up, Ring + Pinky down) -> Scroll
        idx_ext = _is_finger_extended(landmarks, INDEX_TIP, INDEX_PIP, INDEX_MCP)
        mid_ext = _is_finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP, MIDDLE_MCP)
        rng_ext = _is_finger_extended(landmarks, RING_TIP, RING_PIP, RING_MCP)
        pnk_ext = _is_finger_extended(landmarks, PINKY_TIP, PINKY_PIP, PINKY_MCP)

        if (
            idx_ext
            and mid_ext
            and not rng_ext
            and not pnk_ext
            and not self._left_pinched
            and not self._dragging
            and left_ratio > self.pinch_up_ratio
            and right_ratio > self.pinch_up_ratio
        ):
            scroll_y = (index_tip[1] + middle_tip[1]) * 0.5
            delta = 0.0
            if self._prev_scroll_y is not None:
                dy = self._prev_scroll_y - scroll_y
                if abs(dy) > 0.003:
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

        # 3. Left Click, Double-Click & Drag (deferred click on release if quick tap!)
        left_click_event = False
        left_down_event = False
        left_up_event = False

        if not self._left_pinched:
            if left_ratio < self.pinch_down_ratio:
                self._left_pinched = True
                self._left_pinch_start_t = t
                self._dragging = False
        else:
            if left_ratio > self.pinch_up_ratio:
                # Released!
                if self._dragging:
                    left_up_event = True
                else:
                    # Quick tap -> atomic click (double-click friendly!)
                    left_click_event = True
                    is_double = (t - self._last_click_t) * 1000.0 <= self.double_click_window_ms
                    self._last_click_t = t
                    self._badge_mode = "DOUBLE_CLICK" if is_double else "LEFT_CLICK"
                    self._badge_until_t = t + 0.35
                self._left_pinched = False
                self._left_pinch_start_t = None
                self._dragging = False
            elif (
                not self._dragging
                and self._left_pinch_start_t is not None
                and (t - self._left_pinch_start_t) * 1000.0 >= self.drag_hold_ms
            ):
                # Held past drag threshold -> begin drag
                self._dragging = True
                left_down_event = True

        # 4. Right Click (Thumb + Middle pinch)
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
                    self._badge_mode = "RIGHT_CLICK"
                    self._badge_until_t = t + 0.35
            elif right_ratio > self.pinch_up_ratio:
                self._right_pinched = False

        # Determine display mode without needlessly freezing cursor
        if self._dragging:
            mode = "DRAGGING"
        elif self._left_pinched:
            mode = "LEFT_TAP_HOLD"
        elif t < self._badge_until_t:
            mode = self._badge_mode
        else:
            mode = "ACTIVE"

        return GestureAction(
            mode=mode,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            freeze_cursor=False,
            left_click_event=left_click_event,
            left_down_event=left_down_event,
            left_up_event=left_up_event,
            right_click_event=right_click_event,
            pinch_ratio=left_ratio,
        )

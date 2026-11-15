"""One-Euro Filter and ergonomic ROI coordinate mapping for cursor control."""

from __future__ import annotations

import math

from .config import compute_roi


def _smoothing_factor(t_e: float, cutoff: float) -> float:
    r = 2.0 * math.pi * cutoff * t_e
    return r / (r + 1.0)


def _exponential_smoothing(a: float, x: float, x_prev: float) -> float:
    return a * x + (1.0 - a) * x_prev


class OneEuroFilter:
    """Adaptive low-pass filter that eliminates jitter at rest with low lag in motion."""

    def __init__(
        self,
        min_cutoff: float = 2.0,
        beta: float = 0.08,
        d_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float | None = None

    def reset(self) -> None:
        """Reset internal state when hand tracking resumes."""
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None

    def filter(self, x: float, t: float) -> float:
        """Return filtered value for signal x at timestamp t (seconds)."""
        if self._t_prev is None or self._x_prev is None:
            self._x_prev = x
            self._dx_prev = 0.0
            self._t_prev = t
            return x

        t_e = max(t - self._t_prev, 1e-4)
        a_d = _smoothing_factor(t_e, self.d_cutoff)
        dx = (x - self._x_prev) / t_e
        dx_hat = _exponential_smoothing(a_d, dx, self._dx_prev)

        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = _smoothing_factor(t_e, cutoff)
        x_hat = _exponential_smoothing(a, x, self._x_prev)

        self._x_prev = x_hat
        self._dx_prev = dx_hat
        self._t_prev = t
        return x_hat


class CursorMapper:
    """Maps normalized webcam ROI coordinates to smoothed screen pixels."""

    def __init__(
        self,
        screen_w: int,
        screen_h: int,
        sensitivity: float = 2.2,
        roi_center_x: float = 0.50,
        roi_center_y: float = 0.45,
        min_cutoff: float = 2.0,
        beta: float = 0.08,
        d_cutoff: float = 1.0,
        deadzone_px: float = 1.0,
    ) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.sensitivity = sensitivity
        self.roi_center_x = roi_center_x
        self.roi_center_y = roi_center_y
        self.roi_x_min, self.roi_x_max, self.roi_y_min, self.roi_y_max = compute_roi(
            sensitivity, roi_center_x, roi_center_y
        )
        self.deadzone_px = deadzone_px
        self.filter_x = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self.filter_y = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self._last_px: tuple[float, float] | None = None

    def reset(self) -> None:
        self.filter_x.reset()
        self.filter_y.reset()
        self._last_px = None

    def get_roi(self) -> tuple[float, float, float, float]:
        return (self.roi_x_min, self.roi_x_max, self.roi_y_min, self.roi_y_max)

    def update_params(
        self,
        sensitivity: float | None = None,
        min_cutoff: float | None = None,
        beta: float | None = None,
        screen_w: int | None = None,
        screen_h: int | None = None,
    ) -> None:
        if sensitivity is not None:
            self.sensitivity = sensitivity
            self.roi_x_min, self.roi_x_max, self.roi_y_min, self.roi_y_max = compute_roi(
                sensitivity, self.roi_center_x, self.roi_center_y
            )
        if min_cutoff is not None:
            self.filter_x.min_cutoff = min_cutoff
            self.filter_y.min_cutoff = min_cutoff
        if beta is not None:
            self.filter_x.beta = beta
            self.filter_y.beta = beta
        if screen_w is not None:
            self.screen_w = screen_w
        if screen_h is not None:
            self.screen_h = screen_h

    def map_to_screen(self, norm_x: float, norm_y: float, t: float) -> tuple[int, int]:
        """Map [0..1] camera coords inside ROI to clamped, smoothed pixel coords."""
        span_x = max(self.roi_x_max - self.roi_x_min, 0.05)
        span_y = max(self.roi_y_max - self.roi_y_min, 0.05)

        rx = min(max((norm_x - self.roi_x_min) / span_x, 0.0), 1.0)
        ry = min(max((norm_y - self.roi_y_min) / span_y, 0.0), 1.0)

        target_x = rx * (self.screen_w - 1)
        target_y = ry * (self.screen_h - 1)

        sx = self.filter_x.filter(target_x, t)
        sy = self.filter_y.filter(target_y, t)

        if self._last_px is not None:
            dist = math.hypot(sx - self._last_px[0], sy - self._last_px[1])
            if dist < self.deadzone_px:
                sx, sy = self._last_px

        self._last_px = (sx, sy)
        return int(round(sx)), int(round(sy))

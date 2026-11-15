"""MediaPipe HandLandmarker tracker and Jarvis HUD frame renderer."""

from __future__ import annotations

import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from .config import BASE_DIR

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
DEFAULT_MODEL_PATH = BASE_DIR / "models" / "hand_landmarker.task"

HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)


def ensure_model_downloaded(model_path: Path = DEFAULT_MODEL_PATH) -> Path:
    if model_path.exists() and model_path.stat().st_size > 100_000:
        return model_path
    model_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = model_path.with_suffix(".tmp")
    urllib.request.urlretrieve(MODEL_URL, tmp_path)
    tmp_path.replace(model_path)
    return model_path


class HandTracker:
    """Fast MediaPipe HandLandmarker in VIDEO mode using downscaled RGB inference."""

    def __init__(self, model_path: Path = DEFAULT_MODEL_PATH) -> None:
        resolved_model = ensure_model_downloaded(model_path)
        base_options = mp.tasks.BaseOptions(model_asset_path=str(resolved_model))
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=0.55,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55,
        )
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._last_ts_ms = 0

    def detect(
        self, bgr_frame: np.ndarray, timestamp_s: float
    ) -> list[tuple[float, float, float]] | None:
        """Downscale to 384x288 for fast CPU inference; landmarks remain normalized [0..1]."""
        small = cv2.resize(bgr_frame, (384, 288), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts_ms = int(timestamp_s * 1000.0)
        if ts_ms <= self._last_ts_ms:
            ts_ms = self._last_ts_ms + 1
        self._last_ts_ms = ts_ms

        result = self._landmarker.detect_for_video(mp_image, ts_ms)
        if not result.hand_landmarks:
            return None

        hand = result.hand_landmarks[0]
        return [(float(lm.x), float(lm.y), float(lm.z)) for lm in hand]

    def close(self) -> None:
        self._landmarker.close()


def render_jarvis_hud(
    bgr_frame: np.ndarray,
    landmarks: list[tuple[float, float, float]] | None,
    mode: str,
    roi: tuple[float, float, float, float],
    fps: float,
    anchor: tuple[float, float] | None = None,
    pinch_ratio: float = 1.0,
) -> np.ndarray:
    """Draw Jarvis cyber HUD overlay with live ROI box, skeleton, and pinch feedback."""
    frame = cv2.convertScaleAbs(bgr_frame, alpha=0.62, beta=0)
    h, w = frame.shape[:2]

    x1 = int(roi[0] * w)
    y1 = int(roi[2] * h)
    x2 = int(roi[1] * w)
    y2 = int(roi[3] * h)

    roi_color = (240, 210, 40) if mode != "CLUTCH" else (80, 170, 255)
    cv2.rectangle(frame, (x1, y1), (x2, y2), roi_color, 1, cv2.LINE_AA)

    b = 14
    for cx, cy, dx, dy in (
        (x1, y1, 1, 1),
        (x2, y1, -1, 1),
        (x1, y2, 1, -1),
        (x2, y2, -1, -1),
    ):
        cv2.line(frame, (cx, cy), (cx + dx * b, cy), (255, 225, 70), 2, cv2.LINE_AA)
        cv2.line(frame, (cx, cy), (cx, cy + dy * b), (255, 225, 70), 2, cv2.LINE_AA)

    if landmarks:
        pts = [(int(lm[0] * w), int(lm[1] * h)) for lm in landmarks]
        for a, b_idx in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b_idx], (255, 195, 35), 2, cv2.LINE_AA)
        for idx, pt in enumerate(pts):
            radius = 5 if idx in (4, 8, 12) else 3
            color = (0, 255, 255) if idx in (4, 8, 12) else (240, 180, 40)
            cv2.circle(frame, pt, radius, color, -1, cv2.LINE_AA)

        # Visual pinch meter line between thumb & index
        pinch_col = (100, 255, 120) if pinch_ratio < 0.36 else (180, 220, 240)
        cv2.line(frame, pts[4], pts[8], pinch_col, 2, cv2.LINE_AA)

        if anchor is not None:
            ax, ay = int(anchor[0] * w), int(anchor[1] * h)
            cv2.circle(frame, (ax, ay), 10, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(frame, (ax, ay), 5, (0, 255, 190), -1, cv2.LINE_AA)

    cv2.putText(
        frame,
        f"{fps:.0f} FPS",
        (w - 86, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (200, 235, 250),
        1,
        cv2.LINE_AA,
    )
    return frame

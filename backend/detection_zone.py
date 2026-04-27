"""
Shared zone-of-interest state for the detection pipeline and API.

Coordinates are normalized to the frame: x/y values are floats in [0, 1].
An empty polygon means "no zone filter", so detections anywhere are allowed.
"""

from __future__ import annotations

import threading
from typing import Iterable

import cv2
import numpy as np


class DetectionZone:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._polygon: list[dict[str, float]] = []

    def get(self) -> list[dict[str, float]]:
        with self._lock:
            return [p.copy() for p in self._polygon]

    def set(self, points: Iterable[dict[str, float]]) -> list[dict[str, float]]:
        cleaned: list[dict[str, float]] = []
        for point in points:
            x = float(point["x"])
            y = float(point["y"])
            cleaned.append({
                "x": min(1.0, max(0.0, x)),
                "y": min(1.0, max(0.0, y)),
            })

        if cleaned and len(cleaned) < 3:
            raise ValueError("Detection zone must have at least 3 points")

        with self._lock:
            self._polygon = cleaned
            return [p.copy() for p in self._polygon]

    def clear(self) -> None:
        with self._lock:
            self._polygon = []

    def contains_box_center(self, box: tuple[int, int, int, int], frame_shape: tuple[int, ...]) -> bool:
        polygon = self.get()
        if not polygon:
            return True

        height, width = frame_shape[:2]
        if width <= 0 or height <= 0:
            return True

        x1, y1, x2, y2 = box
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        pts = np.array(
            [(p["x"] * width, p["y"] * height) for p in polygon],
            dtype=np.float32,
        )
        return cv2.pointPolygonTest(pts, (cx, cy), False) >= 0


detection_zone = DetectionZone()

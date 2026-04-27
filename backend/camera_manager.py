"""
camera_manager.py
─────────────────
Camera lifecycle management for ThreatSense AI.

Wraps OpenCV VideoCapture with:
  - Auto-reconnect with exponential backoff
  - Thread-safe frame grabbing
  - Health metrics (FPS, resolution, connection status)
  - Configurable source (webcam index, RTSP URL, video file)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

import cv2
import numpy as np

_log = logging.getLogger(__name__)


class CameraManager:
    """Thread-safe camera wrapper with auto-reconnect."""

    def __init__(
        self,
        source: int | str = 0,
        width: int = 1280,
        height: int = 720,
        target_fps: int = 30,
        max_backoff: float = 30.0,
        flip_horizontal: bool = True,
    ) -> None:
        self.source = source
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.max_backoff = max_backoff
        self.flip_horizontal = flip_horizontal

        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._connected = False
        self._frame_count = 0
        self._fps_window: deque[float] = deque(maxlen=30)
        self._last_frame_ts: Optional[float] = None
        self._actual_width = 0
        self._actual_height = 0
        self._actual_fps = 0.0

    # ── connection lifecycle ─────────────────────────────────────────

    def connect(self) -> bool:
        """Open the camera source. Returns True on success."""
        with self._lock:
            if self._cap and self._cap.isOpened():
                self._cap.release()

            # Try default backend first
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                cap.release()
                # Try DirectShow on Windows
                cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    self._connected = False
                    return False

            # Configure camera
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.target_fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            self._actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._actual_fps = cap.get(cv2.CAP_PROP_FPS)

            self._cap = cap
            self._connected = True
            _log.info(
                "Camera connected: %dx%d @ %.0f FPS",
                self._actual_width, self._actual_height, self._actual_fps,
            )
            return True

    def disconnect(self) -> None:
        """Release the camera."""
        with self._lock:
            if self._cap:
                self._cap.release()
                self._cap = None
            self._connected = False

    def reconnect(self, backoff: float = 3.0) -> bool:
        """Disconnect and reconnect with backoff."""
        self.disconnect()
        _log.info("Reconnecting in %.1fs …", backoff)
        time.sleep(backoff)
        return self.connect()

    # ── frame grabbing ───────────────────────────────────────────────

    def read(self) -> Optional[np.ndarray]:
        """Read the next frame. Returns None on failure."""
        with self._lock:
            if not self._cap or not self._cap.isOpened():
                return None

            ret, frame = self._cap.read()
            if not ret or frame is None:
                self._connected = False
                return None

            if self.flip_horizontal:
                frame = cv2.flip(frame, 1)

            self._frame = frame
            self._frame_count += 1

            now = time.time()
            if self._last_frame_ts and (now - self._last_frame_ts) > 0:
                self._fps_window.append(1.0 / (now - self._last_frame_ts))
            self._last_frame_ts = now

            return frame

    # ── health metrics ───────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def fps(self) -> float:
        if not self._fps_window:
            return 0.0
        return sum(self._fps_window) / len(self._fps_window)

    @property
    def resolution(self) -> tuple[int, int]:
        return (self._actual_width, self._actual_height)

    def health(self) -> dict:
        """Return a dictionary of health metrics."""
        return {
            "connected": self._connected,
            "source": str(self.source),
            "resolution": f"{self._actual_width}x{self._actual_height}",
            "fps": round(self.fps, 1),
            "frames": self._frame_count,
            "last_frame_ts": self._last_frame_ts,
        }

    # ── context manager ──────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

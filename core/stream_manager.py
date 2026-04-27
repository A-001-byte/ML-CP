import threading
import time
from collections import deque
import cv2
import numpy as np


class StreamManager:
    """Thread-safe singleton holding the latest pipeline frame.

    JPEG encoding is done once inside update_frame() (pipeline thread) and
    cached.  get_frame_bytes() just returns the cached bytes — no encoding in
    the async HTTP path, which was the cause of 10 FPS on the web stream.
    """
    _instance = None
    _lock = threading.Lock()

    # Loaded from config/settings.py — override via STREAM_WIDTH / STREAM_JPEG_QUALITY env vars.
    try:
        from config.settings import settings as _s
        STREAM_WIDTH  = _s.pipeline.stream_width
        JPEG_QUALITY  = _s.pipeline.stream_jpeg_quality
    except Exception:
        STREAM_WIDTH  = 854
        JPEG_QUALITY  = 70

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.frame: np.ndarray | None = None
            self._cached_bytes: bytes | None = None   # pre-encoded JPEG
            self.lock = threading.Lock()
            self.frames = 0
            self.last_frame_ts: float | None = None
            self._fps_window: deque[float] = deque(maxlen=30)
            self.initialized = True

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def update_frame(self, frame: np.ndarray) -> None:
        """Store latest frame and pre-encode JPEG for the web stream.

        Encoding happens here (pipeline thread) so the HTTP handler never
        blocks the asyncio event loop doing expensive cv2.imencode calls.
        """
        if frame is None:
            return

        # Downscale for web — keeps transfer fast without degrading the cv2
        # window (which gets the full-res frame from the pipeline directly).
        h, w = frame.shape[:2]
        if w > self.STREAM_WIDTH:
            scale = self.STREAM_WIDTH / w
            stream_frame = cv2.resize(frame, (self.STREAM_WIDTH, int(h * scale)),
                                       interpolation=cv2.INTER_LINEAR)
        else:
            stream_frame = frame

        success, buf = cv2.imencode(
            '.jpg', stream_frame,
            [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY],
        )

        now = time.time()
        with self.lock:
            self.frame = frame
            self._cached_bytes = buf.tobytes() if success else None

            if self.last_frame_ts and (delta := now - self.last_frame_ts) > 0:
                self._fps_window.append(1.0 / delta)
            self.last_frame_ts = now
            self.frames += 1

    def get_frame_bytes(self) -> bytes | None:
        """Return the latest pre-encoded JPEG bytes (non-blocking)."""
        with self.lock:
            return self._cached_bytes

    def health(self) -> dict:
        with self.lock:
            fps = (sum(self._fps_window) / len(self._fps_window)
                   if self._fps_window else None)
            return {
                "frames":        self.frames,
                "fps":           fps,
                "last_frame_ts": self.last_frame_ts,
            }


stream_manager = StreamManager()

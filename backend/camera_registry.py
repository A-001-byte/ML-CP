"""
camera_registry.py
──────────────────
Manages multiple camera sources for the ThreatSense-AI surveillance system.

Each camera runs its own SurveillancePipeline in a daemon thread.
Frames from all cameras are multiplexed through a per-camera StreamManager.

Usage:
    registry = CameraRegistry()
    registry.add("cam1", source=0, location="Main Entrance")
    registry.add("cam2", source="rtsp://192.168.1.100/stream", location="Back Door")
    registry.start_all()

    # In your FastAPI route:
    frame_bytes = registry.get_frame("cam1")

Camera configuration can also come from environment variable CAMERAS_JSON:
    CAMERAS_JSON='[{"id":"cam1","source":0,"location":"Main Entrance"}]'
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

_log = logging.getLogger("backend.cameras")


@dataclass
class CameraConfig:
    id: str
    source: int | str          # webcam index or RTSP/file URL
    location: str = "Unknown"
    enabled: bool = True


@dataclass
class CameraState:
    config: CameraConfig
    thread: Optional[threading.Thread] = None
    running: bool = False
    latest_frame: Optional[np.ndarray] = None
    latest_bytes: Optional[bytes] = None
    fps: float = 0.0
    frame_count: int = 0
    last_frame_ts: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update_frame(self, frame: np.ndarray) -> None:
        now = time.time()
        encoded = cv2.imencode(
            ".jpg", cv2.resize(frame, (854, min(480, frame.shape[0]))),
            [cv2.IMWRITE_JPEG_QUALITY, 70],
        )
        with self.lock:
            self.latest_frame = frame
            self.latest_bytes = encoded[1].tobytes() if encoded[0] else None
            if self.last_frame_ts:
                delta = now - self.last_frame_ts
                if delta > 0:
                    self.fps = round(1.0 / delta, 1)
            self.last_frame_ts = now
            self.frame_count += 1

    def get_bytes(self) -> Optional[bytes]:
        with self.lock:
            return self.latest_bytes

    def health(self) -> dict:
        with self.lock:
            age = (time.time() - self.last_frame_ts) if self.last_frame_ts else None
            return {
                "id":           self.config.id,
                "location":     self.config.location,
                "source":       str(self.config.source),
                "running":      self.running,
                "fps":          self.fps,
                "frame_count":  self.frame_count,
                "last_frame_age_s": round(age, 1) if age else None,
                "online":       age is not None and age < 5.0,
            }


class CameraRegistry:
    """Manages the lifecycle of all camera pipelines."""

    def __init__(self) -> None:
        self._cameras: dict[str, CameraState] = {}
        self._lock = threading.Lock()
        self._load_from_env()

    # ── Public API ────────────────────────────────────────────────────

    def add(self, cam_id: str, source: int | str, location: str = "Camera") -> None:
        cfg   = CameraConfig(id=cam_id, source=source, location=location)
        state = CameraState(config=cfg)
        with self._lock:
            self._cameras[cam_id] = state
        _log.info("[cameras] Registered: %s → %s (%s)", cam_id, source, location)

    def start_all(self) -> None:
        with self._lock:
            cameras = list(self._cameras.values())
        for state in cameras:
            if state.config.enabled and not state.running:
                self._start_camera(state)

    def stop_all(self) -> None:
        with self._lock:
            for state in self._cameras.values():
                state.running = False

    def get_frame(self, cam_id: str) -> Optional[bytes]:
        state = self._cameras.get(cam_id)
        return state.get_bytes() if state else None

    def list_cameras(self) -> list[dict]:
        with self._lock:
            return [s.health() for s in self._cameras.values()]

    def get_default_id(self) -> Optional[str]:
        with self._lock:
            ids = list(self._cameras.keys())
        return ids[0] if ids else None

    # ── Internal ──────────────────────────────────────────────────────

    def _start_camera(self, state: CameraState) -> None:
        state.running = True
        t = threading.Thread(
            target=self._run_camera,
            args=(state,),
            daemon=True,
            name=f"cam-{state.config.id}",
        )
        state.thread = t
        t.start()
        _log.info("[cameras] Started: %s", state.config.id)

    def _run_camera(self, state: CameraState) -> None:
        src     = state.config.source
        backoff = 3

        while state.running:
            cap = cv2.VideoCapture(src if isinstance(src, str) else int(src))
            if not cap.isOpened():
                _log.warning("[cameras] %s: cannot open source %s. Retry in %ds",
                             state.config.id, src, backoff)
                time.sleep(backoff)
                continue

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            _log.info("[cameras] %s online", state.config.id)

            while state.running:
                ret, frame = cap.read()
                if not ret:
                    if isinstance(src, str) and not src.startswith(('http', 'rtsp')):
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    _log.warning("[cameras] %s: frame grab failed", state.config.id)
                    break
                state.update_frame(frame)

            cap.release()
            if state.running:
                _log.info("[cameras] %s: reconnecting in %ds…", state.config.id, backoff)
                time.sleep(backoff)

        _log.info("[cameras] %s stopped", state.config.id)

    def _load_from_env(self) -> None:
        """Load camera config from CAMERAS_JSON env var if set."""
        raw = os.environ.get("CAMERAS_JSON", "")
        if not raw:
            return
        try:
            cameras = json.loads(raw)
            for cam in cameras:
                self.add(
                    cam_id   = cam["id"],
                    source   = cam["source"],
                    location = cam.get("location", "Camera"),
                )
        except Exception as exc:
            _log.error("[cameras] Failed to parse CAMERAS_JSON: %s", exc)


# Module-level singleton — used by routes and pipeline
camera_registry = CameraRegistry()

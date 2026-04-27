"""
tracking_engine.py
──────────────────
ByteTrack tracking facade for ThreatSense AI.

Wraps the PersonDetector's track() method into a clean stateful
interface that maintains track ID → person state mapping across frames.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from detection.person_detector import PersonDetector

_log = logging.getLogger(__name__)


@dataclass
class TrackedPerson:
    """State of a tracked person across frames."""
    track_id: int
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    frame_count: int = 1


class TrackingEngine:
    """Stateful person tracking using ByteTrack."""

    def __init__(
        self,
        person_model: str = "yolov8m.pt",
        device: int | str | None = None,
        imgsz: int = 416,
        person_conf: float = 0.4,
    ) -> None:
        self.person_conf = person_conf

        _log.info("Loading person tracker (ByteTrack) …")
        self.detector = PersonDetector(
            model_path=person_model,
            device=device,
            imgsz=imgsz,
            half=True,
        )

        # Active track states
        self._tracks: Dict[int, TrackedPerson] = {}

    def update(
        self,
        frame: np.ndarray,
    ) -> List[TrackedPerson]:
        """
        Run person detection + ByteTrack tracking on a frame.

        Returns a list of TrackedPerson objects for all currently
        visible persons with stable track IDs.
        """
        tracked = self.detector.track(frame, conf=self.person_conf)
        now = time.time()

        active_ids: Set[int] = set()
        results: List[TrackedPerson] = []

        for x1, y1, x2, y2, conf, tid in tracked:
            active_ids.add(tid)

            if tid in self._tracks:
                # Update existing track
                tp = self._tracks[tid]
                tp.bbox = (x1, y1, x2, y2)
                tp.confidence = conf
                tp.last_seen = now
                tp.frame_count += 1
            else:
                # New track
                tp = TrackedPerson(
                    track_id=tid,
                    bbox=(x1, y1, x2, y2),
                    confidence=conf,
                    first_seen=now,
                    last_seen=now,
                )
                self._tracks[tid] = tp

            results.append(tp)

        # Clean up stale tracks (not seen for > 5 seconds)
        stale_ids = [
            tid for tid, tp in self._tracks.items()
            if tid not in active_ids and (now - tp.last_seen) > 5.0
        ]
        for tid in stale_ids:
            del self._tracks[tid]

        return results

    @property
    def active_count(self) -> int:
        """Number of currently active tracks."""
        return len(self._tracks)

    @property
    def active_ids(self) -> Set[int]:
        """Set of currently active track IDs."""
        return set(self._tracks.keys())

    def get_track(self, track_id: int) -> Optional[TrackedPerson]:
        """Get a specific track by ID."""
        return self._tracks.get(track_id)

    def reset(self) -> None:
        """Clear all tracking state."""
        self._tracks.clear()

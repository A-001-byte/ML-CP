"""
detection_engine.py
───────────────────
Detection orchestrator facade for ThreatSense AI.

Wraps the existing PersonDetector and WeaponDetector into a single
clean interface with structured output.  All strict filtering
(confidence >= 0.75, area >= 5000, IoU >= 0.5, lower-half spatial
constraint) is already applied inside the detector modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from detection.person_detector import PersonDetector
from detection.weapon_detector import WeaponDetector

_log = logging.getLogger(__name__)


@dataclass
class PersonResult:
    """A single detected person with optional tracking and weapon info."""
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    track_id: Optional[int] = None
    armed: bool = False
    weapons: List[Tuple[int, int, int, int, float, str]] = field(default_factory=list)


@dataclass
class FrameDetections:
    """All detections for a single frame."""
    persons: List[PersonResult]
    raw_weapon_count: int = 0  # total before association


class DetectionEngine:
    """Unified detection interface wrapping person + weapon detectors."""

    def __init__(
        self,
        person_model: str = "yolov8m.pt",
        weapon_model: Optional[str] = "models/weapon_detector.pt",
        device: int | str | None = None,
        imgsz: int = 416,
        person_conf: float = 0.4,
        weapon_conf: float = 0.3,
        armed_threshold: float = 0.50,
    ) -> None:
        self.person_conf = person_conf
        self.weapon_conf = weapon_conf
        self.armed_threshold = armed_threshold

        _log.info("Loading person detector (%s) …", person_model)
        self.person_det = PersonDetector(
            model_path=person_model,
            device=device,
            imgsz=imgsz,
            half=True,
        )

        self.weapon_det: Optional[WeaponDetector] = None
        if weapon_model:
            _log.info("Loading weapon detector (%s) …", weapon_model)
            self.weapon_det = WeaponDetector(
                model_path=weapon_model,
                device=device,
                imgsz=imgsz,
                half=True,
            )

    def detect_persons(
        self, frame: np.ndarray
    ) -> List[PersonResult]:
        """Run person detection (no tracking)."""
        detections = self.person_det.detect(frame, conf=self.person_conf)
        return [
            PersonResult(bbox=(x1, y1, x2, y2), confidence=conf)
            for x1, y1, x2, y2, conf in detections
        ]

    def detect_weapons_for_person(
        self,
        frame: np.ndarray,
        person_bbox: Tuple[int, int, int, int],
    ) -> List[Tuple[int, int, int, int, float, str]]:
        """Run weapon detection within a person's bounding box region."""
        if self.weapon_det is None:
            return []
        return self.weapon_det.detect_in_region(
            frame, person_bbox, conf=self.weapon_conf
        )

    def process_frame(
        self,
        frame: np.ndarray,
        tracked_persons: Optional[List[Tuple]] = None,
    ) -> FrameDetections:
        """
        Full detection pass on a frame.

        Parameters
        ----------
        frame : np.ndarray
            The video frame (BGR).
        tracked_persons : optional list of (x1, y1, x2, y2, conf, track_id)
            If provided, uses these instead of running person detection.

        Returns
        -------
        FrameDetections with all persons and their weapon associations.
        """
        results: List[PersonResult] = []
        total_weapons = 0

        # Use tracked persons if provided, otherwise detect
        if tracked_persons is not None:
            persons = [
                (x1, y1, x2, y2, conf, tid)
                for x1, y1, x2, y2, conf, tid in tracked_persons
            ]
        else:
            raw = self.person_det.detect(frame, conf=self.person_conf)
            persons = [
                (x1, y1, x2, y2, conf, None)
                for x1, y1, x2, y2, conf in raw
            ]

        for x1, y1, x2, y2, conf, tid in persons:
            # Detect weapons within this person's region
            weapons = self.detect_weapons_for_person(frame, (x1, y1, x2, y2))
            total_weapons += len(weapons)

            # A person is armed if any weapon detection passes all filters
            # AND has confidence >= armed_threshold
            high_conf_weapons = [
                w for w in weapons if w[4] >= self.armed_threshold
            ]
            is_armed = len(high_conf_weapons) > 0

            results.append(PersonResult(
                bbox=(x1, y1, x2, y2),
                confidence=conf,
                track_id=tid,
                armed=is_armed,
                weapons=high_conf_weapons if is_armed else weapons,
            ))

        return FrameDetections(persons=results, raw_weapon_count=total_weapons)

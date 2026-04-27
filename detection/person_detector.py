"""
person_detector.py
──────────────────
YOLOv8x-based person detector with ByteTrack tracking support.
Filters for COCO class 0 (person) only.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np
from ultralytics import YOLO

# (x1, y1, x2, y2, confidence)
Detection = Tuple[int, int, int, int, float]

# (x1, y1, x2, y2, confidence, track_id)
TrackedDetection = Tuple[int, int, int, int, float, int]


class PersonDetector:
    """Detect and track persons using YOLOv8x + ByteTrack."""

    def __init__(
        self,
        model_path: str = "yolov8x.pt",
        device: int | str | None = None,
        imgsz: int = 640,
        half: bool = True,
    ) -> None:
        self.model = YOLO(model_path)
        self.device = device
        self.imgsz = imgsz
        self.half = half

    # ── detection only (no tracking) ─────────────────────────────────

    def detect(
        self,
        frame: np.ndarray,
        conf: float = 0.4,
    ) -> List[Detection]:
        """
        Run person detection on *frame* (no tracking).

        Returns
        -------
        list of (x1, y1, x2, y2, confidence)
        """
        results = self.model.predict(
            source=frame,
            conf=conf,
            classes=[0],
            device=self.device,
            imgsz=self.imgsz,
            half=self.half,
            verbose=False,
        )

        detections: List[Detection] = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                confidence = round(float(box.conf[0]), 4)
                detections.append((x1, y1, x2, y2, confidence))

        return detections

    # ── detection + ByteTrack tracking ───────────────────────────────

    def track(
        self,
        frame: np.ndarray,
        conf: float = 0.4,
        tracker: str = "bytetrack.yaml",
    ) -> List[TrackedDetection]:
        """
        Run person detection + ByteTrack tracking on *frame*.

        Parameters
        ----------
        frame : np.ndarray
            BGR frame from the video source.
        conf : float
            Confidence threshold for person detection.
        tracker : str
            Tracker config file (shipped with Ultralytics).

        Returns
        -------
        list of (x1, y1, x2, y2, confidence, track_id)
            Bounding boxes with persistent track IDs.
        """
        results = self.model.track(
            source=frame,
            conf=conf,
            classes=[0],
            device=self.device,
            imgsz=self.imgsz,
            half=self.half,
            verbose=False,
            tracker=tracker,
            persist=True,       # keep tracker state across calls
        )

        detections: List[TrackedDetection] = []
        for r in results:
            if r.boxes.id is None:
                continue
            for box in r.boxes:
                if box.id is None:
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                confidence = round(float(box.conf[0]), 4)
                track_id = int(box.id[0])
                detections.append((x1, y1, x2, y2, confidence, track_id))

        return detections

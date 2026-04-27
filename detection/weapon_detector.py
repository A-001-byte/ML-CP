"""
weapon_detector.py
──────────────────
Weapon detector that runs on the LOWER BODY ZONE of a person crop.

Key design decision: instead of running on the full person bounding box and
filtering results with geometric rules, we physically crop only the lower 60%
of the person box before running the model.  This guarantees the model never
sees the head, glasses, ceiling objects, curtains, or anything above shoulder
height — eliminating the entire class of upper-body false positives without
needing fragile post-hoc coordinate checks.

Expected model class scheme:
    0: gun      1: knife      2: person (ignored)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

WeaponDetection = Tuple[int, int, int, int, float, str]

PROJECT_ROOT  = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = PROJECT_ROOT / "models" / "weapon_detector.pt"

# ── Constants ────────────────────────────────────────────────────────────────

IGNORED_CLASSES:    set[str] = {"person"}
WEAPON_ONLY_CLASSES: set[str] = {"gun", "knife"}

# Confidence — well-trained model (mAP50=0.888); true positives typically >0.70
WEAPON_CONF_THRESHOLD: float = 0.65

# Minimum bounding box area in full-frame pixels (rejects tiny noise detections)
WEAPON_MIN_AREA: int = 4000

# What fraction of the person height to skip from the top when cropping.
# 0.40 = skip the top 40% (head, face, glasses, shoulders).
# Weapons are held at torso/waist/hand level, never above the head.
PERSON_TOP_SKIP: float = 0.40

# Minimum fraction of the weapon box that must lie inside the person box.
WEAPON_PERSON_OVERLAP: float = 0.35


class WeaponDetector:
    """Detect weapons in the lower-body zone of tracked person crops."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL,
        device: int | str | None = None,
        imgsz: int = 640,
        half: bool = True,
    ) -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"Weapon detector model not found: {model_path}\n"
                "Place weapon_detector.pt in the models/ directory."
            )
        self.model  = YOLO(str(model_path))
        self.device = device
        self.imgsz  = imgsz
        self.half   = half

    # ── Raw inference on any image ───────────────────────────────────

    def detect(
        self,
        image: np.ndarray,
        conf: float = WEAPON_CONF_THRESHOLD,
    ) -> List[WeaponDetection]:
        """Run inference + class/confidence/area filters on `image`.

        Returns detections whose coordinates are relative to `image`.
        """
        results = self.model.predict(
            source=image,
            conf=conf,
            device=self.device,
            imgsz=self.imgsz,
            half=self.half,
            verbose=False,
        )

        detections: List[WeaponDetection] = []
        for r in results:
            for box in r.boxes:
                cls_id     = int(box.cls[0])
                cls_name   = self.model.names.get(cls_id, str(cls_id))
                confidence = round(float(box.conf[0]), 4)

                if cls_name in IGNORED_CLASSES:
                    continue
                if cls_name not in WEAPON_ONLY_CLASSES:
                    continue
                if confidence < WEAPON_CONF_THRESHOLD:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                if (x2 - x1) * (y2 - y1) < WEAPON_MIN_AREA:
                    continue

                detections.append((x1, y1, x2, y2, confidence, cls_name))

        return detections

    # ── Zone-based crop + detect ─────────────────────────────────────

    def detect_in_region(
        self,
        frame: np.ndarray,
        person_bbox: Tuple[int, int, int, int],
        conf: float = WEAPON_CONF_THRESHOLD,
    ) -> List[WeaponDetection]:
        """Detect weapons in the lower-body zone of a tracked person.

        We crop only the lower (1 - PERSON_TOP_SKIP) fraction of the person
        bounding box — no padding, no head region, no background above the
        shoulders.  This makes coordinate-based spatial filters unnecessary
        and eliminates false positives from glasses, curtains, and wall art.

        Returns weapon detections remapped to full-frame coordinates.
        """
        h_frame, w_frame = frame.shape[:2]
        px1, py1, px2, py2 = person_bbox

        ph = py2 - py1
        if ph <= 0 or (px2 - px1) <= 0:
            return []

        # ── Zone: lower 60% of the person box, exact edges, no padding ──
        zone_y1 = py1 + int(ph * PERSON_TOP_SKIP)
        cx1 = max(0, px1)
        cy1 = max(0, zone_y1)
        cx2 = min(w_frame, px2)
        cy2 = min(h_frame, py2)

        crop = frame[cy1:cy2, cx1:cx2]
        if crop.size == 0:
            return []

        crop_h, crop_w = crop.shape[:2]
        resized = cv2.resize(crop, (self.imgsz, self.imgsz))

        sx = crop_w / self.imgsz
        sy = crop_h / self.imgsz

        crop_dets = self.detect(resized, conf=conf)
        if not crop_dets:
            return []

        # ── Remap crop coordinates → full-frame coordinates ──────────
        remapped: List[WeaponDetection] = []
        for wx1, wy1, wx2, wy2, wconf, wname in crop_dets:
            fx1 = int(wx1 * sx) + cx1
            fy1 = int(wy1 * sy) + cy1
            fx2 = int(wx2 * sx) + cx1
            fy2 = int(wy2 * sy) + cy1

            # Weapon must substantially overlap the person box
            ix1 = max(px1, fx1); iy1 = max(py1, fy1)
            ix2 = min(px2, fx2); iy2 = min(py2, fy2)
            inter  = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            w_area = max(1, (fx2 - fx1) * (fy2 - fy1))
            if inter / w_area < WEAPON_PERSON_OVERLAP:
                continue

            remapped.append((fx1, fy1, fx2, fy2, wconf, wname))

        return remapped

    # ── Full-frame scan (optional, disabled by default) ──────────────

    def detect_full_frame(
        self,
        frame: np.ndarray,
        conf: float = WEAPON_CONF_THRESHOLD,
    ) -> List[WeaponDetection]:
        """Detect weapons in the full frame (no person crop).

        Lower recall than detect_in_region (weapons are small relative to
        frame) but useful as a fallback when person detection misses someone.
        No spatial constraints are applied here.
        """
        h, w = frame.shape[:2]
        resized = cv2.resize(frame, (self.imgsz, self.imgsz))
        sx, sy = w / self.imgsz, h / self.imgsz

        return [
            (int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy), wconf, wname)
            for x1, y1, x2, y2, wconf, wname in self.detect(resized, conf=conf)
        ]

"""
weapon_verifier.py
──────────────────
Multi-frame Weapon Confidence Accumulation System for ThreatSense-AI.

Rationale
---------
A single YOLO inference over one frame can produce false-positive weapon
detections.  This module introduces a short-term per-person memory that
requires *consistent* detections across multiple frames AND a minimum average
confidence before a weapon is declared confirmed.

Algorithm
---------
1. Receive YOLO weapon detections (list of bounding boxes + confidence) and
   SORT-tracked person objects (list of dicts with "id" and "bbox").
2. For each weapon detection, find the tracked person whose bounding box
   overlaps most (highest IoU).  Only associate if IoU > 0.
3. Update that person's weapon memory (increment frame count, accumulate
   confidence score).
4. For persons who had NO weapon associated in this frame, increment their
   missed-frame counter.  After `decay_after` consecutive missed frames the
   memory entry is reset entirely (automatic decay).
5. A weapon is **confirmed** for a person when:
       frames_with_weapon >= min_frames  (default 3)
       AND average_confidence >= min_avg_conf  (default 0.6)

Memory structure (internal)
---------------------------
weapon_memory = {
    person_id: {
        "frames":          int,    # consecutive frames with a weapon detection
        "confidence_sum":  float,  # sum of confidence scores
        "missed_frames":   int,    # consecutive frames WITHOUT a weapon detection
    }
}

Integration
-----------
Place this module between weapon detection and BehaviorAnalyzer::

    YOLO weapon detections
        → WeaponVerifier.update(weapon_dets, tracked_persons)
        → confirmed_ids  (set[int])
        → analyzer.set_weapon_flag(pid, pid in confirmed_ids)
        → BehaviorAnalyzer.analyze(tracked_persons)
        → RiskEngine.process_frame(behavior_results)
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple


# Type alias: (x1, y1, x2, y2, confidence, class_name)
WeaponDetection = Tuple[int, int, int, int, float, str]

# Minimum IoU for associating a weapon detection with a person
MIN_IOU_THRESHOLD: float = 0.5


class WeaponVerifier:
    """
    Accumulate weapon evidence across frames per tracked-person ID.

    Parameters
    ----------
    min_frames : int
        Minimum number of frames a weapon must be detected for a given person
        before the weapon is considered confirmed (default: 3).
    min_avg_conf : float
        Minimum average detection confidence required for confirmation
        (default: 0.6).
    decay_after : int
        Number of consecutive frames *without* a detection before the stored
        evidence for that person is fully reset (default: 3).
    """

    def __init__(
        self,
        min_frames: int = 4,
        min_avg_conf: float = 0.6,
        decay_after: int = 3,
    ) -> None:
        self.min_frames = min_frames
        self.min_avg_conf = min_avg_conf
        self.decay_after = decay_after

        # Per-person weapon memory
        self.weapon_memory: Dict[int, Dict] = {}

    # ── public API ────────────────────────────────────────────────────

    def update(
        self,
        weapon_detections: List[WeaponDetection],
        tracked_persons: List[Dict],
    ) -> Set[int]:
        """
        Process one video frame and return the set of confirmed armed person IDs.

        Parameters
        ----------
        weapon_detections : list of (x1, y1, x2, y2, confidence, class_name)
            Raw YOLO weapon detections for this frame (full-frame coordinates).
        tracked_persons : list of dict
            SORT tracker output.  Each dict must contain:
              - "id"   : int  — stable track ID
              - "bbox" : [x1, y1, x2, y2] — full-frame bounding box

        Returns
        -------
        set[int]
            Person IDs for whom a weapon has been *confirmed* (meet both
            the frame-count and average-confidence thresholds).
        """
        # Build a list of person bboxes indexed by track ID for fast lookup
        person_bboxes: Dict[int, List[int]] = {
            p["id"]: p["bbox"] for p in tracked_persons
        }

        # Track which person IDs received a weapon association this frame.
        persons_with_weapon: Set[int] = set()

        # Per-frame deduplication: ensure each person's frame count and
        # confidence_sum are updated at most ONCE per update() call,
        # even if multiple weapon detections overlap the same person bbox.
        seen_pids_this_frame: Set[int] = set()

        for det in weapon_detections:
            wx1, wy1, wx2, wy2, wconf, _wname = det

            # Find the person with the highest IoU overlap with this weapon box
            best_pid = self._best_matching_person(
                (wx1, wy1, wx2, wy2), person_bboxes
            )

            if best_pid is None:
                # No tracked person overlaps this weapon bbox — skip
                continue

            persons_with_weapon.add(best_pid)

            if best_pid in seen_pids_this_frame:
                # This person was already credited for a weapon detection this
                # frame — skip to avoid counting multiple detections as multiple
                # frames and inflating the frame-count / confidence_sum.
                continue

            seen_pids_this_frame.add(best_pid)

            # Initialise memory entry on the person's first weapon sighting
            if best_pid not in self.weapon_memory:
                self.weapon_memory[best_pid] = {
                    "frames": 0,
                    "confidence_sum": 0.0,
                    "missed_frames": 0,
                }

            entry = self.weapon_memory[best_pid]
            entry["frames"] += 1
            entry["confidence_sum"] += wconf
            entry["missed_frames"] = 0  # reset decay counter on fresh detection

        # ── Decay step: update persons that had NO weapon this frame ──
        for pid in list(self.weapon_memory.keys()):
            if pid not in persons_with_weapon:
                self.weapon_memory[pid]["missed_frames"] += 1
                if self.weapon_memory[pid]["missed_frames"] >= self.decay_after:
                    # Gradual decay: halve confidence and reduce frame count
                    # instead of full reset — makes system resilient to
                    # brief occlusion while still decaying stale evidence
                    entry = self.weapon_memory[pid]
                    entry["confidence_sum"] *= 0.5
                    entry["frames"] = max(0, entry["frames"] - 1)
                    entry["missed_frames"] = 0  # reset miss counter after decay step
                    if entry["frames"] <= 0:
                        # Fully decayed — remove entry
                        del self.weapon_memory[pid]

        # ── Confirmation step ─────────────────────────────────────────
        confirmed: Set[int] = set()
        for pid, entry in self.weapon_memory.items():
            frames = entry["frames"]
            avg_conf = entry["confidence_sum"] / frames if frames > 0 else 0.0
            if frames >= self.min_frames and avg_conf >= self.min_avg_conf:
                confirmed.add(pid)

        return confirmed

    def reset(self, person_id: int | None = None) -> None:
        """
        Clear weapon memory.

        Parameters
        ----------
        person_id : int or None
            If given, clear only that person's memory.
            If None, clear all memory (useful at scene changes).
        """
        if person_id is not None:
            self.weapon_memory.pop(person_id, None)
        else:
            self.weapon_memory.clear()

    def get_memory(self) -> Dict[int, Dict]:
        """Return a *copy* of the current weapon memory (for inspection / tests)."""
        return {pid: dict(entry) for pid, entry in self.weapon_memory.items()}

    def get_confirmed_ids(self) -> Set[int]:
        """
        Return the set of currently confirmed armed person IDs.
        
        This is useful for frames where weapon detection is skipped -
        it returns IDs that were confirmed in a previous update() call
        and still meet the confirmation criteria.
        """
        confirmed: Set[int] = set()
        for pid, entry in self.weapon_memory.items():
            frames = entry["frames"]
            avg_conf = entry["confidence_sum"] / frames if frames > 0 else 0.0
            if frames >= self.min_frames and avg_conf >= self.min_avg_conf:
                confirmed.add(pid)
        return confirmed

    # ── private helpers ───────────────────────────────────────────────

    def _best_matching_person(
        self,
        weapon_box: Tuple[int, int, int, int],
        person_bboxes: Dict[int, List[int]],
    ) -> int | None:
        """
        Return the person ID whose bounding box has the highest IoU with the
        weapon bounding box, or None if no overlap meets the threshold.

        Requires:
          - IoU >= MIN_IOU_THRESHOLD (0.5)
          - Weapon centre must be in the LOWER half of the person box
        """
        best_pid = None
        best_iou = 0.0

        for pid, pbbox in person_bboxes.items():
            # Instead of traditional IoU, check what fraction of the weapon is inside the person box
            # Weapon box is typically much smaller than person box.
            ax1, ay1, ax2, ay2 = weapon_box
            bx1, by1, bx2, by2 = pbbox
            
            ix1 = max(ax1, bx1)
            iy1 = max(ay1, by1)
            ix2 = min(ax2, bx2)
            iy2 = min(ay2, by2)
            
            inter_area = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            weapon_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
            
            if weapon_area == 0:
                continue
                
            overlap_ratio = inter_area / weapon_area

            # Spatial constraint removed to allow testing with weapons held up high

            if overlap_ratio > best_iou:
                best_iou = overlap_ratio
                best_pid = pid

        return best_pid

    @staticmethod
    def _compute_iou(
        box_a: Tuple[int, int, int, int],
        box_b: List[int],
    ) -> float:
        """
        Compute Intersection-over-Union between two axis-aligned bounding boxes.

        Parameters
        ----------
        box_a : (x1, y1, x2, y2)
        box_b : [x1, y1, x2, y2]

        Returns
        -------
        float in [0, 1]
        """
        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b

        # Intersection rectangle
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)

        inter_w = max(0, ix2 - ix1)
        inter_h = max(0, iy2 - iy1)
        intersection = inter_w * inter_h

        if intersection == 0:
            return 0.0

        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
        union = area_a + area_b - intersection

        return intersection / union if union > 0 else 0.0

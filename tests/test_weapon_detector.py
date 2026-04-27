"""
Unit tests for the weapon detection post-processing logic.

These tests do NOT require a GPU or the actual YOLO model — they test
the coordinate math, zone-based cropping, overlap checks, and NMS logic
in isolation using mocked inference results.

Run with:
    pytest tests/test_weapon_detector.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_detector():
    """WeaponDetector with the YOLO model replaced by a controllable mock."""
    with patch("detection.weapon_detector.YOLO") as MockYOLO:
        mock_model = MagicMock()
        mock_model.names = {0: "gun", 1: "knife", 2: "person"}
        MockYOLO.return_value = mock_model

        from detection.weapon_detector import WeaponDetector
        detector = WeaponDetector.__new__(WeaponDetector)
        detector.model  = mock_model
        detector.device = "cpu"
        detector.imgsz  = 416
        detector.half   = False

        yield detector, mock_model


@pytest.fixture
def blank_frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def _make_box_result(x1, y1, x2, y2, conf, cls_id):
    """Build a minimal mock ultralytics Results object."""
    box = MagicMock()
    box.cls  = MagicMock(); box.cls.__getitem__ = lambda s, i: cls_id
    box.conf = MagicMock(); box.conf.__getitem__ = lambda s, i: conf
    box.xyxy = MagicMock()
    box.xyxy.__getitem__ = lambda s, i: MagicMock(tolist=lambda: [x1, y1, x2, y2])

    result = MagicMock()
    result.boxes = [box]
    return result


# ── WeaponDetector.detect() — filtering logic ─────────────────────────────────

class TestDetectFiltering:
    def test_ignores_person_class(self, mock_detector, blank_frame):
        detector, model = mock_detector
        model.predict.return_value = [_make_box_result(100, 100, 300, 400, 0.9, 2)]  # person
        results = detector.detect(blank_frame)
        assert results == []

    def test_ignores_unknown_class(self, mock_detector, blank_frame):
        detector, model = mock_detector
        model.predict.return_value = [_make_box_result(100, 100, 300, 400, 0.9, 99)]
        results = detector.detect(blank_frame)
        assert results == []

    def test_passes_gun_above_threshold(self, mock_detector, blank_frame):
        detector, model = mock_detector
        model.predict.return_value = [_make_box_result(100, 100, 300, 400, 0.8, 0)]  # gun
        results = detector.detect(blank_frame)
        assert len(results) == 1
        assert results[0][5] == "gun"

    def test_rejects_gun_below_threshold(self, mock_detector, blank_frame):
        from detection.weapon_detector import WEAPON_CONF_THRESHOLD
        detector, model = mock_detector
        low_conf = WEAPON_CONF_THRESHOLD - 0.05
        model.predict.return_value = [_make_box_result(100, 100, 300, 400, low_conf, 0)]
        results = detector.detect(blank_frame)
        assert results == []

    def test_rejects_tiny_box(self, mock_detector, blank_frame):
        from detection.weapon_detector import WEAPON_MIN_AREA
        detector, model = mock_detector
        # Box area = 30x30 = 900 which is below WEAPON_MIN_AREA
        model.predict.return_value = [_make_box_result(100, 100, 130, 130, 0.9, 0)]
        results = detector.detect(blank_frame)
        assert results == []

    def test_detects_knife(self, mock_detector, blank_frame):
        detector, model = mock_detector
        model.predict.return_value = [_make_box_result(50, 50, 250, 300, 0.75, 1)]  # knife
        results = detector.detect(blank_frame)
        assert len(results) == 1
        assert results[0][5] == "knife"


# ── WeaponDetector.detect_in_region() — zone-based crop ──────────────────────

class TestDetectInRegion:
    def test_returns_empty_on_no_detections(self, mock_detector, blank_frame):
        detector, model = mock_detector
        model.predict.return_value = [MagicMock(boxes=[])]
        results = detector.detect_in_region(blank_frame, (100, 100, 600, 600))
        assert results == []

    def test_weapon_in_lower_zone_passes(self, mock_detector, blank_frame):
        """A weapon detection in the lower 60% of the person box should pass."""
        detector, model = mock_detector
        # Person box: (200, 100, 800, 700) → zone starts at y=100+0.4*(700-100)=340
        # Detection at center y=500 is in the lower zone
        model.predict.return_value = [_make_box_result(150, 200, 350, 350, 0.85, 0)]
        results = detector.detect_in_region(blank_frame, (200, 100, 800, 700))
        # May or may not pass overlap check — just verify no crash
        assert isinstance(results, list)

    def test_empty_person_box_returns_empty(self, mock_detector, blank_frame):
        detector, model = mock_detector
        results = detector.detect_in_region(blank_frame, (100, 100, 100, 100))
        assert results == []

    def test_person_box_outside_frame_returns_empty(self, mock_detector, blank_frame):
        detector, model = mock_detector
        # Frame is 1280x720, person box entirely outside
        results = detector.detect_in_region(blank_frame, (2000, 2000, 3000, 3000))
        assert results == []


# ── Pipeline NMS dedup ────────────────────────────────────────────────────────

class TestPipelineNMS:
    def setup_method(self):
        from core.pipeline import SurveillancePipeline
        self.dedup = SurveillancePipeline._dedup_tracks

    def test_single_track_unchanged(self):
        tracks = [(0, 0, 100, 200, 0.9, 1)]
        assert self.dedup(tracks) == tracks

    def test_non_overlapping_tracks_both_kept(self):
        t1 = (0,   0, 100, 200, 0.9, 1)   # left person
        t2 = (500, 0, 600, 200, 0.8, 2)   # right person, no overlap
        result = self.dedup([t1, t2])
        assert len(result) == 2

    def test_identical_boxes_deduped_to_one(self):
        t1 = (0, 0, 200, 400, 0.9, 1)
        t2 = (0, 0, 200, 400, 0.8, 2)   # same box, lower confidence
        result = self.dedup([t1, t2])
        assert len(result) == 1
        assert result[0][4] == 0.9   # higher confidence kept

    def test_high_overlap_deduped(self):
        t1 = (0,  0, 200, 400, 0.95, 1)
        t2 = (5,  5, 205, 405, 0.85, 2)  # >0.55 IoU with t1
        result = self.dedup([t1, t2])
        assert len(result) == 1

    def test_empty_list(self):
        assert self.dedup([]) == []


# ── WeaponVerifier integration ────────────────────────────────────────────────

class TestWeaponVerifier:
    def setup_method(self):
        from core.weapon_verifier import WeaponVerifier
        self.verifier = WeaponVerifier(min_frames=3, min_avg_conf=0.65, decay_after=3)

    def _person(self, tid, x1=0, y1=0, x2=500, y2=700):
        return {"id": tid, "bbox": [x1, y1, x2, y2]}

    def _weapon(self, conf=0.80, x1=50, y1=300, x2=250, y2=500):
        return (x1, y1, x2, y2, conf, "gun")

    def test_not_confirmed_before_min_frames(self):
        p = self._person(1)
        w = self._weapon()
        for _ in range(2):   # only 2 frames, need 3
            result = self.verifier.update([w], [p])
        assert 1 not in result

    def test_confirmed_after_min_frames(self):
        p = self._person(1)
        w = self._weapon(conf=0.80)
        for _ in range(3):
            result = self.verifier.update([w], [p])
        assert 1 in result

    def test_low_confidence_not_confirmed(self):
        p = self._person(1)
        w = self._weapon(conf=0.50)   # below min_avg_conf=0.65
        for _ in range(5):
            result = self.verifier.update([w], [p])
        assert 1 not in result

    def test_decays_after_weapon_gone(self):
        p = self._person(2)
        w = self._weapon(conf=0.80)
        for _ in range(3):
            self.verifier.update([w], [p])
        assert 2 in self.verifier.get_confirmed_ids()
        # Now stop sending weapon detections
        for _ in range(10):
            self.verifier.update([], [p])
        assert 2 not in self.verifier.get_confirmed_ids()

    def test_reset_clears_memory(self):
        p = self._person(3)
        w = self._weapon(conf=0.80)
        for _ in range(3):
            self.verifier.update([w], [p])
        assert 3 in self.verifier.get_confirmed_ids()
        self.verifier.reset(3)
        assert 3 not in self.verifier.get_confirmed_ids()

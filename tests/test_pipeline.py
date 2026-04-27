"""
test_pipeline.py
────────────────
Behavioral tests for BehaviorAnalyzer and core pipeline logic.

Feeds synthetic tracked-person dicts directly to BehaviorAnalyzer —
no SortTracker dependency (tracker module was consolidated into the
active pipeline; these tests validate the analysis layer, not the
tracker itself).

Run:  pytest tests/test_pipeline.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from behavior.behavior_analyzer import BehaviorAnalyzer
from core.weapon_verifier import WeaponVerifier


# ── Helpers ──────────────────────────────────────────────────────────────────

def _person(tid: int, x1=100, y1=100, x2=200, y2=300) -> dict:
    """Minimal tracked-person dict matching BehaviorAnalyzer's expected schema."""
    return {"id": tid, "bbox": [x1, y1, x2, y2]}


def _weapon(conf=0.80, x1=120, y1=200, x2=180, y2=280) -> tuple:
    return (x1, y1, x2, y2, conf, "gun")


# ── BehaviorAnalyzer ─────────────────────────────────────────────────────────

class TestBehaviorAnalyzer:

    def test_analyze_returns_result_per_person(self):
        analyzer = BehaviorAnalyzer()
        persons = [_person(1), _person(2)]
        results = analyzer.analyze(persons)
        assert len(results) == len(persons)

    def test_analyze_empty_input(self):
        analyzer = BehaviorAnalyzer()
        results = analyzer.analyze([])
        assert results == []

    def test_person_id_preserved_in_result(self):
        analyzer = BehaviorAnalyzer()
        results = analyzer.analyze([_person(42)])
        assert results[0]["id"] == 42

    def test_weapon_flag_propagates(self):
        """set_weapon_flag(True) should appear in the next analyze() result."""
        analyzer = BehaviorAnalyzer()
        p = _person(1)
        analyzer.set_weapon_flag(1, True)
        results = analyzer.analyze([p])
        assert results[0].get("weapon_detected") is True

    def test_weapon_flag_cleared(self):
        analyzer = BehaviorAnalyzer()
        p = _person(1)
        analyzer.set_weapon_flag(1, True)
        analyzer.analyze([p])
        analyzer.set_weapon_flag(1, False)
        results = analyzer.analyze([p])
        assert results[0].get("weapon_detected") is not True

    def test_stationary_person_does_not_immediately_loiter(self):
        """Loitering requires sustained presence — should not trigger in 1 frame."""
        analyzer = BehaviorAnalyzer()
        p = _person(1)
        results = analyzer.analyze([p])
        assert results[0].get("loitering") is not True

    def test_multiple_persons_independent_state(self):
        """weapon_detected on person 1 must not affect person 2."""
        analyzer = BehaviorAnalyzer()
        analyzer.set_weapon_flag(1, True)
        analyzer.set_weapon_flag(2, False)
        results = analyzer.analyze([_person(1), _person(2)])
        r1 = next(r for r in results if r["id"] == 1)
        r2 = next(r for r in results if r["id"] == 2)
        assert r1.get("weapon_detected") is True
        assert r2.get("weapon_detected") is not True


# ── WeaponVerifier (integration) ─────────────────────────────────────────────

class TestWeaponVerifierIntegration:
    """Integration tests — verifier + analyzer working together."""

    def setup_method(self):
        self.verifier = WeaponVerifier(min_frames=3, min_avg_conf=0.65, decay_after=5)
        self.analyzer = BehaviorAnalyzer()

    def test_weapon_confirmed_sets_behavior_flag(self):
        p = _person(1)
        w = _weapon(conf=0.80)

        for _ in range(3):
            confirmed = self.verifier.update([w], [p])

        self.analyzer.set_weapon_flag(1, 1 in confirmed)
        results = self.analyzer.analyze([p])
        assert results[0].get("weapon_detected") is True

    def test_weapon_cleared_clears_behavior_flag(self):
        p = _person(2)
        w = _weapon(conf=0.80)

        for _ in range(3):
            self.verifier.update([w], [p])

        # Now stop detecting the weapon — verifier should eventually decay
        for _ in range(20):
            confirmed = self.verifier.update([], [p])

        self.analyzer.set_weapon_flag(2, 2 in confirmed)
        results = self.analyzer.analyze([p])
        assert results[0].get("weapon_detected") is not True

    def test_low_confidence_weapon_not_flagged(self):
        p = _person(3)
        w = _weapon(conf=0.40)   # below min_avg_conf=0.65

        for _ in range(5):
            confirmed = self.verifier.update([w], [p])

        self.analyzer.set_weapon_flag(3, 3 in confirmed)
        results = self.analyzer.analyze([p])
        assert results[0].get("weapon_detected") is not True

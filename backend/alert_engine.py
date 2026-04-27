"""
alert_engine.py
───────────────
Alert orchestrator facade for ThreatSense AI.

Wraps the existing WeaponVerifier, BehaviorAnalyzer, RiskEngine,
and AlertManager into a single clean interface.  Takes tracked persons
plus weapon detections → produces confirmed alerts with risk scores.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set, Tuple

_log = logging.getLogger(__name__)


class AlertEngine:
    """Unified alert evaluation pipeline.

    Flow:
        weapon detections + tracked persons
            → WeaponVerifier (multi-frame confirmation)
            → BehaviorAnalyzer (per-person behavior signals)
            → RiskEngine (threat scoring + alert dispatch)
            → confirmed alerts
    """

    def __init__(self) -> None:
        from core.weapon_verifier import WeaponVerifier
        from behavior.behavior_analyzer import BehaviorAnalyzer
        from engine.risk_engine import RiskEngine

        _log.info("Initializing alert engine components …")

        self.weapon_verifier = WeaponVerifier(
            min_frames=3,
            min_avg_conf=0.6,
            decay_after=3,
        )
        self.behavior_analyzer = BehaviorAnalyzer()
        self.risk_engine = RiskEngine()

    def evaluate(
        self,
        weapon_detections: List[Tuple],
        tracked_persons: List[Dict],
    ) -> Dict:
        """
        Run the full alert evaluation pipeline.

        Parameters
        ----------
        weapon_detections : list of (x1, y1, x2, y2, confidence, class_name)
            Filtered weapon detections for this frame.
        tracked_persons : list of dict
            Each dict must have "id" (track_id) and "bbox" [x1, y1, x2, y2].

        Returns
        -------
        dict with:
          - confirmed_armed_ids: set of person IDs confirmed as armed
          - behavior_results: list of behavior analysis results
          - risk_decisions: list of risk engine decisions
        """
        # 1. Weapon verification (multi-frame confirmation)
        confirmed_armed_ids = self.weapon_verifier.update(
            weapon_detections, tracked_persons
        )

        # 2. Propagate weapon flags to behavior analyzer
        for p in tracked_persons:
            pid = p["id"]
            self.behavior_analyzer.set_weapon_flag(
                pid, pid in confirmed_armed_ids
            )

        # 3. Behavior analysis
        behavior_results = self.behavior_analyzer.analyze(tracked_persons)

        # 4. Risk engine — threat scoring + alert dispatch
        risk_decisions = []
        if behavior_results:
            risk_decisions = self.risk_engine.process_frame(behavior_results)

        return {
            "confirmed_armed_ids": confirmed_armed_ids,
            "behavior_results": behavior_results,
            "risk_decisions": risk_decisions,
        }

    def get_confirmed_ids(self) -> Set[int]:
        """Get currently confirmed armed person IDs (for skipped frames)."""
        return self.weapon_verifier.get_confirmed_ids()

    def reset(self, person_id: int | None = None) -> None:
        """Reset alert state for a person or all persons."""
        self.weapon_verifier.reset(person_id)

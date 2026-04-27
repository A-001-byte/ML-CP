from typing import List, Dict, Any
from engine.risk_calculator import RiskCalculator
from engine.threat_classifier import ThreatClassifier
from engine.behavior_fusion import BehaviorFusion
from memory.memory_store import MemoryStore
from analytics.pattern_detector import PatternDetector
from analytics.group_behavior_detector import GroupBehaviorDetector
from alerts.alert_manager import AlertManager
from risk_logging.event_logger import EventLogger
from risk_logging.audit_logger import AuditLogger
from utils.time_utils import get_current_timestamp_str, get_current_time_seconds
from utils.config_loader import load_json_config
import os
import time

try:
    from backend.notifications import notifier as _notifier
except Exception:
    _notifier = None

class RiskEngine:
    """
    The central orchestrator for the ThreatSense-AI Decision Layer.
    
    Pipeline order:
      1. Receive tracked persons
      2. Update memory
      3. Compute base risk
      4. Apply behavior fusion
      5. Apply pattern detection
      6. Apply group detection
      7. Classify threat level
      8. Apply decay
      9. Log event
     10. Trigger alerts
    """
    
    def __init__(self):
        self.calculator = RiskCalculator()
        self.classifier = ThreatClassifier()
        self.fusion = BehaviorFusion()
        self.memory_store = MemoryStore()
        self.pattern_detector = PatternDetector()
        self.group_detector = GroupBehaviorDetector()
        self.alert_manager = AlertManager()
        self.event_logger = EventLogger()
        self.audit_logger = AuditLogger()
        self._last_alert_ts: dict[int | str, float] = {}
        self._alert_cooldown_s: float = 30.0
        
        # Load decay config
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "decay_config.json")
        decay_config = load_json_config(config_path)
        self.decay_points_per_minute = decay_config.get("decay_rate_per_minute", 5)

    def _apply_decay(self, memory, base_score: int, behavior_flags: Dict[str, bool]) -> tuple:
        """Applies risk decay if no suspicious behavior is currently detected."""
        reasons = []
        score = base_score
        
        if not any(behavior_flags.values()) and memory.risk_history:
            last_risk = memory.risk_history[-1]
            if memory.last_seen:
                minutes_passed = (get_current_time_seconds() - memory.last_seen) / 60
                decay_total = int(minutes_passed * self.decay_points_per_minute)
                if decay_total > 0:
                    score = max(0, last_risk - decay_total)
                    reasons.append(f"Risk Decay: Decreased by {decay_total} points due to inactivity")
        return score, reasons

    def process_person(self, person_data: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the full decision pipeline for a single tracked person."""
        person_id = person_data["id"]
        
        # 1. Fetch/create memory
        memory = self.memory_store.get_person(person_id)
        
        # 2. Extract behavior flags
        behavior_flags = {
            "loitering": person_data.get("loitering", False),
            "zone_intrusion": person_data.get("zone_intrusion", False),
            "weapon_detected": person_data.get("weapon_detected", False)
        }
        
        # 3. Compute base risk
        base_score, base_reasons, active_behaviors = self.calculator.compute_score(behavior_flags, memory)
        
        # 4. Apply behavior fusion
        fusion_bonus, fusion_reasons = self.fusion.apply_fusion(active_behaviors, base_score)
        total_score = base_score + fusion_bonus
        all_reasons = base_reasons + fusion_reasons
        
        # 5. Apply pattern detection
        pattern_alerts = self.pattern_detector.detect_patterns(person_id, memory)
        if pattern_alerts:
            total_score += 10  # Penalty for matching a suspicious pattern
            all_reasons.extend(pattern_alerts)
        
        # 6. Apply decay (only if no current behavior)
        decayed_score, decay_reasons = self._apply_decay(memory, total_score, behavior_flags)
        if decay_reasons:
            total_score = decayed_score
            all_reasons.extend(decay_reasons)
        
        # 7. Classify threat level
        threat_level = self.classifier.classify(total_score)
        
        # 8. Update memory with the final computed score
        self.memory_store.update_person(person_id, active_behaviors, total_score)
        
        # 9. Log the event - ONLY if there's something significant to log
        # Skip logging for NORMAL threat level with no behaviors (reduces log spam)
        if active_behaviors or threat_level != "NORMAL":
            self.audit_logger.log_decision(
                person_id=person_id,
                behaviors=active_behaviors,
                risk_score=total_score,
                threat_level=threat_level,
                reasons=all_reasons
            )
        
        # 10. Formulate result
        result = {
            "person_id": person_id,
            "risk_score": total_score,
            "threat_level": threat_level,
            "behaviors": active_behaviors,
            "reasons": all_reasons,
            "timestamp": get_current_timestamp_str()
        }
        
        # 11. Trigger alerts with per-person cooldown to avoid DB spam.
        if self._should_dispatch_alert(person_id, result):
            self.alert_manager.evaluate_and_alert(result)

        # 12. Fire email notification on weapon detection
        if behavior_flags.get("weapon_detected") and _notifier:
            _notifier.send_weapon_alert(
                person_id=str(person_id),
                weapon_class="weapon",
                confidence=total_score / 100.0,
                location="Main Entrance",
            )

        return result

    def _should_dispatch_alert(self, person_id: int | str, decision: Dict[str, Any]) -> bool:
        if not self.alert_manager.rules.should_alert(decision):
            return False

        now = time.time()
        last = self._last_alert_ts.get(person_id, 0.0)
        if now - last < self._alert_cooldown_s:
            return False

        self._last_alert_ts[person_id] = now
        return True

    def process_frame(self, persons_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Processes a list of persons detected in a single video frame.
        Also runs group-level detection after individual processing.
        """
        results = []
        for p in persons_list:
            decision = self.process_person(p)
            results.append(decision)
        
        # Group behavior detection across all persons in this frame
        group_alerts = self.group_detector.detect_group_threats(results)
        if group_alerts:
            self.alert_manager.evaluate_group_alerts(group_alerts)
            
        return results

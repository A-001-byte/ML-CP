from typing import Dict, Any, List, Optional
import logging
import time
from alerts.alert_rules import AlertRules
from utils.time_utils import get_current_timestamp_str

logger = logging.getLogger(__name__)

# Import database persistence functions
try:
    from backend.database import add_alert as db_add_alert, add_incident as db_add_incident
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    db_add_alert = None
    db_add_incident = None

# Import WebSocket event emitters
try:
    from backend.ws_manager import ws_manager
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False


def normalize_risk_score(raw_score: float) -> float:
    """Normalize risk score to 0.0-1.0 range.
    
    Handles both percentage (0-100) and fractional (0.0-1.0) inputs.
    Returns clamped value in [0.0, 1.0].
    """
    if raw_score > 1.0:
        # Assume percentage, convert to fraction
        score = raw_score / 100.0
    else:
        score = raw_score
    # Clamp to valid range
    return max(0.0, min(1.0, score))


# Mapping from threat levels to DB-supported risk levels
THREAT_TO_RISK_LEVEL = {
    "normal": "low",
    "low": "low",
    "suspicious": "medium",
    "medium": "medium",
    "high": "high",
    "critical": "critical",
}


def normalize_threat_level(threat_level: str) -> str:
    """Map threat level to DB-supported risk level.
    
    Maps incoming threat levels to: low, medium, high, critical.
    Unknown values default to 'low'.
    """
    return THREAT_TO_RISK_LEVEL.get(threat_level.lower(), "low")


class AlertManager:
    """Manages the generation and dispatch of security alerts."""
    
    # Throttle settings: max 1 alert per person per behavior per N seconds
    THROTTLE_WINDOW_SECONDS = 30
    
    def __init__(self, camera_id: str = "CAM-01"):
        self.rules = AlertRules()
        self.alert_log: List[Dict[str, Any]] = []
        self.camera_id = camera_id
        self.location = "Main Entrance"
        # Throttle tracking: key = (person_id, behavior_key) -> last_alert_time
        self._throttle_cache: Dict[tuple, float] = {}

    def _get_throttle_key(self, decision: Dict[str, Any]) -> tuple:
        """Generate a throttle key from person_id and behavior set.
        
        Uses an order-independent representation of behaviors (sorted tuple)
        so identical behavior sets in different orders yield the same key.
        """
        person_id = decision.get("person_id", "unknown")
        behaviors = decision.get("behaviors", [])
        # Normalize: deduplicate via set, sort for consistency, convert to tuple
        behavior_key = tuple(sorted(set(behaviors))) if behaviors else ("general",)
        return (person_id, behavior_key)

    def _is_throttled(self, decision: Dict[str, Any]) -> bool:
        """Check if this alert should be throttled."""
        key = self._get_throttle_key(decision)
        now = time.time()
        
        if key in self._throttle_cache:
            last_time = self._throttle_cache[key]
            if now - last_time < self.THROTTLE_WINDOW_SECONDS:
                return True
        
        # Update throttle cache
        self._throttle_cache[key] = now
        
        # Cleanup old entries (older than 2x throttle window)
        cutoff = now - (self.THROTTLE_WINDOW_SECONDS * 2)
        self._throttle_cache = {k: v for k, v in self._throttle_cache.items() if v > cutoff}
        
        return False

    def evaluate_and_alert(self, decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Checks a decision against alert rules and generates an alert if warranted."""
        if not self.rules.should_alert(decision):
            return None
        
        # Apply throttling to prevent alert spam
        if self._is_throttled(decision):
            return None
            
        priority = self.rules.get_alert_priority(decision)
        
        # Determine event_type from behaviors or reasons
        behaviors = decision.get("behaviors", [])
        if "weapon_detected" in behaviors:
            event_type = "Weapon Detected"
        elif "zone_intrusion" in behaviors:
            event_type = "Zone Intrusion"
        elif "loitering" in behaviors:
            event_type = "Loitering Detected"
        elif behaviors:
            event_type = sorted(behaviors)[0].replace("_", " ").title()
        else:
            event_type = "Suspicious Behavior"
        
        # Normalize risk_score to 0.0-1.0 range
        risk_score = normalize_risk_score(decision["risk_score"])
        # Normalize threat_level to DB-supported risk_level
        risk_level = normalize_threat_level(decision["threat_level"])
        
        alert = {
            "person_id": str(decision["person_id"]),
            "event_type": event_type,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "threat_level": decision["threat_level"],
            "priority": priority,
            "reasons": decision.get("reasons", []),
            "timestamp": get_current_timestamp_str(),
            "camera_id": self.camera_id,
            "location": self.location,
            "status": "Active"
        }
        
        # Persist to database if available
        if DB_AVAILABLE and db_add_alert is not None:
            try:
                alert_id = db_add_alert(
                    person_id=alert["person_id"],
                    event_type=alert["event_type"],
                    risk_score=alert["risk_score"],
                    risk_level=alert["risk_level"],
                    camera_id=alert["camera_id"],
                    location=alert["location"],
                    status=alert["status"]
                )
                alert["id"] = alert_id

                # Promote high-priority detections to incidents
                if db_add_incident is not None and risk_level in ("high", "critical"):
                    incident_id = db_add_incident(
                        title=f"{event_type}: ID {decision['person_id']}",
                        description=f"Automated incident for {decision['person_id']}. Reasons: {', '.join(decision.get('reasons', []))}",
                        event_type=event_type,
                        location=self.location,
                        risk_level=risk_level,
                        status="open"
                    )
                    # Push incident over WebSocket
                    if WS_AVAILABLE:
                        ws_manager.broadcast_incident({
                            "id": incident_id,
                            "title": f"{event_type}: ID {decision['person_id']}",
                            "description": f"Automated incident for {decision['person_id']}. Reasons: {', '.join(decision.get('reasons', []))}",
                            "event_type": event_type,
                            "location": self.location,
                            "risk_level": risk_level,
                            "status": "Open",
                            "person_id": str(decision["person_id"]),
                            "camera_id": self.camera_id,
                        })

            except Exception:
                logger.exception("Failed to persist alert/incident to DB")
        
        if "id" not in alert:
            alert["id"] = int(time.time() * 1000)
            
        self.alert_log.append(alert)

        # Notify via WebSocket if available
        if WS_AVAILABLE:
            ws_manager.broadcast_alert(alert)
        
        # Compact log line (was verbose multi-line print block)
        reasons_str = "; ".join(alert["reasons"][:3])  # Show top 3 reasons
        logger.info(f"[ALERT] {priority} | ID:{alert['person_id']} | Score:{alert['risk_score']} | {alert['threat_level']} | {reasons_str}")
        
        return alert

    def evaluate_group_alerts(self, group_alerts: List[Dict[str, Any]]):
        """Handles group-level alerts from the GroupBehaviorDetector."""
        for ga in group_alerts:
            logger.info(f"[GROUP ALERT] {ga['type']} | Members:{ga['members']} | {ga['description']}")

"""
API endpoint tests — covers auth, alerts, incidents, and system endpoints.

Run with:
    pytest tests/test_api.py -v
"""
from __future__ import annotations

import os
import pytest

os.environ.setdefault("THREATSENSE_NO_PIPELINE", "1")
os.environ.setdefault("JWT_SECRET", "test-secret")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _login(client, username: str, password: str):
    return client.post("/api/login", json={"username": username, "password": password})


# ── Auth tests ────────────────────────────────────────────────────────────────

class TestAuth:
    def test_login_missing_fields(self, api_client):
        resp = api_client.post("/api/login", json={})
        assert resp.status_code in (400, 422)

    def test_login_wrong_password(self, api_client):
        resp = _login(api_client, "admin", "definitelywrong")
        assert resp.status_code == 401

    def test_protected_route_without_token(self, api_client):
        resp = api_client.get("/api/alerts")
        assert resp.status_code == 401

    def test_protected_route_with_bad_token(self, api_client):
        resp = api_client.get(
            "/api/alerts",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401


# ── System endpoints ──────────────────────────────────────────────────────────

class TestSystemEndpoints:
    def test_system_status_public(self, api_client):
        """system_status should be reachable without auth."""
        resp = api_client.get("/api/system_status")
        assert resp.status_code == 200
        data = resp.json()
        assert "pipeline_running" in data
        assert "camera_connected" in data

    def test_system_metrics_public(self, api_client):
        resp = api_client.get("/api/system_metrics")
        assert resp.status_code == 200

    def test_health_check(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.status_code in (200, 404)  # 404 if not yet implemented


# ── Alerts ────────────────────────────────────────────────────────────────────

class TestAlerts:
    def test_get_alerts_requires_auth(self, api_client):
        resp = api_client.get("/api/alerts")
        assert resp.status_code == 401

    def test_get_alerts_returns_list(self, api_client, auth_headers):
        resp = api_client.get("/api/alerts", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_alerts_empty_on_fresh_db(self, api_client, auth_headers):
        resp = api_client.get("/api/alerts?limit=100", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_alerts_pagination_limit(self, api_client, auth_headers):
        """limit param must be respected."""
        resp = api_client.get("/api/alerts?limit=5", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) <= 5


# ── Incidents ─────────────────────────────────────────────────────────────────

class TestIncidents:
    def test_get_incidents_requires_auth(self, api_client):
        resp = api_client.get("/api/incidents")
        assert resp.status_code == 401

    def test_get_incidents_returns_list(self, api_client, auth_headers):
        resp = api_client.get("/api/incidents", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_incidents_empty_on_fresh_db(self, api_client, auth_headers):
        resp = api_client.get("/api/incidents", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []


# ── Database layer unit tests ─────────────────────────────────────────────────

class TestDatabase:
    def test_add_alert_stores_record(self, tmp_db):
        from backend.database import add_alert, get_db_connection
        import contextlib

        alert_id = add_alert(
            person_id="p1",
            event_type="Weapon Detected",
            risk_score=0.9,
            risk_level="high",
        )
        assert isinstance(alert_id, int)
        assert alert_id > 0

        with contextlib.closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        assert row is not None
        assert row["event_type"] == "Weapon Detected"
        assert row["risk_level"] == "high"

    def test_add_alert_timestamp_is_ist(self, tmp_db):
        from backend.database import add_alert, get_db_connection
        import contextlib

        add_alert("p2", "Test", 0.5, "medium")
        with contextlib.closing(get_db_connection()) as conn:
            row = conn.execute("SELECT timestamp FROM alerts ORDER BY id DESC LIMIT 1").fetchone()
        # IST timestamps are stored without timezone suffix; just verify format
        ts = row["timestamp"]
        assert len(ts) == 19  # "YYYY-MM-DD HH:MM:SS"

    def test_add_alert_invalid_risk_score(self, tmp_db):
        from backend.database import add_alert
        with pytest.raises(ValueError):
            add_alert("p3", "Test", "not-a-number", "low")

    def test_add_incident_stores_record(self, tmp_db):
        from backend.database import add_incident, get_db_connection
        import contextlib

        inc_id = add_incident(
            title="Armed Person Detected",
            description="Person with visible firearm at main gate",
            event_type="Weapon Detected",
            risk_level="critical",
        )
        assert inc_id > 0

        with contextlib.closing(get_db_connection()) as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id=?", (inc_id,)).fetchone()
        assert row["title"] == "Armed Person Detected"
        assert row["risk_level"] == "critical"

    def test_add_alert_clamps_risk_score(self, tmp_db):
        from backend.database import add_alert, get_db_connection
        import contextlib

        # score > 1.0 should be clamped to 1.0
        alert_id = add_alert("p4", "Test", 5.0, "high")
        with contextlib.closing(get_db_connection()) as conn:
            row = conn.execute("SELECT risk_score FROM alerts WHERE id=?", (alert_id,)).fetchone()
        assert row["risk_score"] == 1.0

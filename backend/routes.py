"""
routes.py
─────────
FastAPI API router — all REST endpoints for the ThreatSense AI backend.

Replaces the old Flask Blueprint.  Every endpoint preserves the same
URL path and response shape so the frontend remains compatible.
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from werkzeug.security import check_password_hash, generate_password_hash

from backend.auth import (
    COOKIE_NAME,
    create_token,
    get_current_user,
    get_optional_user,
    require_roles,
    verify_token,
    _extract_token,
)
from backend.database import add_alert, add_incident, get_db_connection
from backend.detection_zone import detection_zone
from core.stream_manager import stream_manager

router = APIRouter(prefix="/api")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INCIDENTS_DIR = PROJECT_ROOT / "logs" / "incidents"
EVAL_DIR = PROJECT_ROOT / "docs" / "evaluation" / "eval"
EVAL_PLOTS = {
    "confusion_matrix.png": "Confusion Matrix",
    "confusion_matrix_normalized.png": "Normalized Confusion Matrix",
    "BoxPR_curve.png": "Precision-Recall Curve",
    "BoxP_curve.png": "Precision Curve",
    "BoxR_curve.png": "Recall Curve",
    "BoxF1_curve.png": "F1 Curve",
}

# ── Rate-limit state (simple in-memory, per-IP) ─────────────────────────────
# For production, swap with Redis-backed slowapi.
_rate_limits: dict[str, list[float]] = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 10  # requests per window


def _check_rate_limit(request: Request, max_requests: int = RATE_LIMIT_MAX) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    hits = _rate_limits.setdefault(ip, [])
    hits[:] = [t for t in hits if now - t < RATE_LIMIT_WINDOW]
    if len(hits) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many requests")
    hits.append(now)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    _check_rate_limit(request, max_requests=5)

    conn = get_db_connection()
    user = conn.execute(
        "SELECT * FROM users WHERE username = ?", (body.username,)
    ).fetchone()
    conn.close()

    if user and check_password_hash(user["password_hash"], body.password):
        token = create_token(user["username"], user["role"])
        response = JSONResponse({
            "message": "Login successful",
            "token": token,
            "role": user["role"],
            "username": user["username"],
        })
        # HttpOnly cookie — JS cannot read this, eliminates XSS token theft
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            samesite="strict",
            max_age=86400,    # 24 h — matches TOKEN_EXPIRE_HOURS
            secure=False,     # flip to True in production (HTTPS)
            path="/",
        )
        return response

    raise HTTPException(status_code=401, detail="Invalid username or password")


@router.post("/logout")
async def logout():
    """Clear the HttpOnly auth cookie."""
    response = JSONResponse({"message": "Logged out"})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.post("/register")
async def register(body: RegisterRequest, request: Request):
    _check_rate_limit(request, max_requests=5)

    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="Missing username or password")

    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists")

        conn.execute(
            "INSERT INTO users (username, password_hash, role, status, last_active) VALUES (?, ?, ?, ?, ?)",
            (username, generate_password_hash(body.password), "operator", "Active", "Just now"),
        )
        conn.commit()
    finally:
        conn.close()

    return {"message": "Registration successful", "username": username}


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    return {"username": user.get("username"), "role": user.get("role")}


# ══════════════════════════════════════════════════════════════════════════════
# ALERTS
# ══════════════════════════════════════════════════════════════════════════════

MAX_LIMIT = 100


@router.get("/alerts")
async def get_alerts(limit: int = 50, _user: dict = Depends(get_current_user)):
    limit = max(1, min(limit, MAX_LIMIT))
    conn = get_db_connection()
    alerts = conn.execute(
        "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in alerts]


class CreateAlertRequest(BaseModel):
    event_type: str
    risk_score: float
    person_id: str = "UNKNOWN"
    risk_level: str = "low"
    camera_id: str = "CAM-01"
    location: str = "Main Entrance"
    status: str = "Active"


@router.post("/alerts", status_code=201)
async def create_alert(
    body: CreateAlertRequest,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    try:
        alert_id = add_alert(
            person_id=body.person_id,
            event_type=body.event_type,
            risk_score=body.risk_score,
            risk_level=body.risk_level,
            camera_id=body.camera_id,
            location=body.location,
            status=body.status,
        )
        return {"message": "Alert created", "id": alert_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(
    alert_id: int,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute("UPDATE alerts SET status = ? WHERE id = ?", ("Dismissed", alert_id))
    conn.commit()
    rows = result.rowcount
    conn.close()
    if rows == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert dismissed", "id": alert_id}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute("UPDATE alerts SET status = ? WHERE id = ?", ("Under Review", alert_id))
    conn.commit()
    rows = result.rowcount
    conn.close()
    if rows == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert acknowledged", "id": alert_id}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute("UPDATE alerts SET status = ? WHERE id = ?", ("Resolved", alert_id))
    conn.commit()
    rows = result.rowcount
    conn.close()
    if rows == 0:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"message": "Alert resolved", "id": alert_id}


@router.post("/alerts/bulk-dismiss")
async def bulk_dismiss_alerts(
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute(
        "UPDATE alerts SET status = 'Dismissed' WHERE status IN ('Resolved', 'Active')"
    )
    conn.commit()
    rows = result.rowcount
    conn.close()
    return {"message": f"{rows} alerts dismissed", "count": rows}


# ══════════════════════════════════════════════════════════════════════════════
# INCIDENTS
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/incidents")
async def get_incidents(
    status: Optional[str] = None,
    limit: int = 100,
    _user: dict = Depends(get_current_user),
):
    limit = max(1, min(limit, 1000))
    conn = get_db_connection()
    if status:
        incidents = conn.execute(
            "SELECT * FROM incidents WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        incidents = conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(row) for row in incidents]


class CreateIncidentRequest(BaseModel):
    title: str
    description: str = ""
    event_type: str = "Manual Entry"
    location: str = "Main Entrance"
    risk_level: str = "low"
    status: str = "open"


@router.post("/incidents", status_code=201)
async def create_incident(
    body: CreateIncidentRequest,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    try:
        incident_id = add_incident(
            title=body.title,
            description=body.description,
            event_type=body.event_type,
            location=body.location,
            risk_level=body.risk_level,
            status=body.status,
        )
        return {"message": "Incident created", "id": incident_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: int,
    _user: dict = Depends(get_current_user),
):
    conn = get_db_connection()
    incident = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    conn.close()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return dict(incident)


def _safe_file_under(path: Path, parent: Path) -> Path | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(parent.resolve())
        return resolved if resolved.is_file() else None
    except Exception:
        return None


def _extract_person_id(incident: dict) -> str | None:
    if incident.get("person_id"):
        return str(incident["person_id"])
    text = f"{incident.get('title') or ''} {incident.get('description') or ''}"
    match = re.search(r"\bID\s+([A-Za-z0-9_-]+)", text)
    return match.group(1) if match else None


def _resolve_incident_clip(incident: dict) -> Path | None:
    clip_path = incident.get("clip_path")
    if clip_path:
        candidate = Path(clip_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        safe = _safe_file_under(candidate, INCIDENTS_DIR)
        if safe:
            return safe

    if not INCIDENTS_DIR.exists():
        return None

    person_id = _extract_person_id(incident)
    if not person_id:
        return None
    clips = sorted(INCIDENTS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    clips = [p for p in clips if f"person{person_id}_" in p.name]
    return clips[0] if clips else None


@router.get("/incidents/{incident_id}/clip")
async def get_incident_clip(incident_id: int, request: Request):
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    verify_token(token)

    conn = get_db_connection()
    incident = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    conn.close()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    clip = _resolve_incident_clip(dict(incident))
    if not clip:
        raise HTTPException(status_code=404, detail="Incident clip not found")

    return FileResponse(
        path=str(clip),
        media_type="video/mp4",
        filename=clip.name,
        headers={"Accept-Ranges": "bytes"},
    )


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: int,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute(
        "UPDATE incidents SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        ("Resolved", incident_id),
    )
    conn.commit()
    rows = result.rowcount
    conn.close()
    if rows == 0:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"message": "Incident resolved", "id": incident_id}


@router.post("/incidents/{incident_id}/escalate")
async def escalate_incident(
    incident_id: int,
    user: dict = Depends(require_roles("admin", "security", "operator")),
):
    conn = get_db_connection()
    result = conn.execute(
        "UPDATE incidents SET status = ?, risk_level = CASE "
        "WHEN risk_level = 'low' THEN 'medium' "
        "WHEN risk_level = 'medium' THEN 'high' "
        "ELSE risk_level END WHERE id = ?",
        ("Escalated", incident_id),
    )
    conn.commit()
    rows = result.rowcount
    conn.close()
    if rows == 0:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"message": "Incident escalated", "id": incident_id}


# ══════════════════════════════════════════════════════════════════════════════
# STATS & SYSTEM
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/stats")
async def get_stats(_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    total_alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    total_incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    active_incidents = conn.execute(
        "SELECT COUNT(*) FROM incidents WHERE status NOT IN ('Resolved', 'False Alarm')"
    ).fetchone()[0]
    high_risk_alerts = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE risk_score >= 0.8"
    ).fetchone()[0]
    active_tracks = conn.execute(
        "SELECT COUNT(DISTINCT person_id) FROM alerts WHERE status NOT IN ('Resolved', 'Dismissed')"
    ).fetchone()[0]
    conn.close()

    health = stream_manager.health()
    fps = health.get("fps")
    last_frame_age = None
    if health.get("last_frame_ts"):
        last_frame_age = round(time.time() - health["last_frame_ts"], 1)

    return {
        "total_alerts": total_alerts,
        "total_incidents": total_incidents,
        "active_incidents": active_incidents,
        "high_risk_alerts": high_risk_alerts,
        "active_tracks": active_tracks,
        "pipeline_fps": round(fps, 1) if fps else None,
        "pipeline_running": health.get("last_frame_ts") is not None,
        "pipeline_frames": health.get("frames", 0),
        "last_frame_age_s": last_frame_age,
    }


@router.get("/health")
async def health_check():
    """Unauthenticated liveness probe for load balancers and Docker healthcheck."""
    return {"status": "ok"}


@router.get("/system_status")
async def system_status():
    health = stream_manager.health()
    now = time.time()
    last_ts = health.get("last_frame_ts") or 0
    pipeline_running = (now - last_ts) < 5

    return {
        "pipeline_running": bool(pipeline_running),
        "camera_connected": bool(pipeline_running),
        "fps": round(health.get("fps") or 0, 1),
        "last_frame_ts": last_ts,
    }


@router.get("/system_metrics")
async def system_metrics(_user: Optional[dict] = Depends(get_optional_user)):
    """Extended system metrics including GPU info."""
    health = stream_manager.health()
    fps = health.get("fps")
    last_frame_age = None
    if health.get("last_frame_ts"):
        last_frame_age = round(time.time() - health["last_frame_ts"], 1)

    # GPU metrics
    import torch
    gpu_info = None
    if torch.cuda.is_available():
        try:
            gpu_info = {
                "name": torch.cuda.get_device_name(0),
                "memory_allocated_mb": round(torch.cuda.memory_allocated(0) / 1024 / 1024, 1),
                "memory_reserved_mb": round(torch.cuda.memory_reserved(0) / 1024 / 1024, 1),
                "memory_total_mb": round(torch.cuda.get_device_properties(0).total_mem / 1024 / 1024, 1),
                "utilization_percent": None,  # requires pynvml for real utilization
            }
        except Exception:
            pass

    return {
        "pipeline_fps": round(fps, 1) if fps else None,
        "pipeline_running": health.get("last_frame_ts") is not None,
        "pipeline_frames": health.get("frames", 0),
        "last_frame_age_s": last_frame_age,
        "gpu_available": torch.cuda.is_available(),
        "gpu_info": gpu_info,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
    }


def _parse_alert_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_IST)
    except Exception:
        return None


def _weapon_type_from_event(event_type: str | None) -> str | None:
    event = (event_type or "").lower()
    if "knife" in event:
        return "knife"
    if "gun" in event or "firearm" in event or "weapon" in event:
        return "gun"
    return None


@router.get("/analytics")
async def get_analytics(_user: dict = Depends(get_current_user)):
    now = datetime.now(_IST)
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    hour_buckets = [hour_start - timedelta(hours=23 - i) for i in range(24)]
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_buckets = [day_start - timedelta(days=6 - i) for i in range(7)]

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT event_type, risk_score, risk_level, timestamp, location FROM alerts"
    ).fetchall()
    total_incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    conn.close()

    alerts_by_hour = {bucket.strftime("%Y-%m-%d %H:00"): 0 for bucket in hour_buckets}
    alerts_by_day = {bucket.strftime("%Y-%m-%d"): 0 for bucket in day_buckets}
    risk_distribution = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    weapon_types = {"gun": 0, "knife": 0}
    locations: dict[str, int] = {}
    risk_total = 0.0

    for row in rows:
        ts = _parse_alert_ts(row["timestamp"])
        if ts is not None:
            hour_key = ts.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:00")
            if hour_key in alerts_by_hour:
                alerts_by_hour[hour_key] += 1
            day_key = ts.strftime("%Y-%m-%d")
            if day_key in alerts_by_day:
                alerts_by_day[day_key] += 1

        risk_level = (row["risk_level"] or "low").lower()
        if risk_level in risk_distribution:
            risk_distribution[risk_level] += 1

        weapon_type = _weapon_type_from_event(row["event_type"])
        if weapon_type:
            weapon_types[weapon_type] = weapon_types.get(weapon_type, 0) + 1

        location = row["location"] or "Unknown"
        locations[location] = locations.get(location, 0) + 1
        risk_total += float(row["risk_score"] or 0)

    total_alerts = len(rows)
    top_locations = sorted(
        [{"location": location, "count": count} for location, count in locations.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:5]

    return {
        "alerts_by_hour": [
            {"hour": bucket[-5:], "count": count}
            for bucket, count in alerts_by_hour.items()
        ],
        "alerts_by_day": [
            {"date": date, "count": count}
            for date, count in alerts_by_day.items()
        ],
        "risk_distribution": risk_distribution,
        "weapon_types": weapon_types,
        "top_locations": top_locations,
        "total_alerts": total_alerts,
        "total_incidents": total_incidents,
        "avg_risk_score": round(risk_total / total_alerts, 2) if total_alerts else 0.0,
        "detection_rate_per_hour": round(sum(alerts_by_hour.values()) / 24.0, 2),
    }


class ZonePoint(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)


class ZoneRequest(BaseModel):
    points: list[ZonePoint] = Field(default_factory=list)


@router.get("/detection_zone")
async def get_detection_zone(_user: dict = Depends(get_current_user)):
    return {"points": detection_zone.get()}


@router.put("/detection_zone")
async def update_detection_zone(
    body: ZoneRequest,
    _user: dict = Depends(require_roles("admin", "security", "operator")),
):
    try:
        points = detection_zone.set([{"x": p.x, "y": p.y} for p in body.points])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"points": points}


@router.delete("/detection_zone")
async def clear_detection_zone(_user: dict = Depends(require_roles("admin", "security", "operator"))):
    detection_zone.clear()
    return {"points": []}


@router.get("/model_performance")
async def model_performance(_user: dict = Depends(get_current_user)):
    plots = [
        {
            "filename": filename,
            "title": title,
            "url": f"/api/model_performance/{filename}",
        }
        for filename, title in EVAL_PLOTS.items()
        if (EVAL_DIR / filename).is_file()
    ]
    return {"plots": plots}


@router.get("/model_performance/{filename}")
async def model_performance_plot(filename: str, request: Request):
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    verify_token(token)

    if filename not in EVAL_PLOTS:
        raise HTTPException(status_code=404, detail="Plot not found")
    path = _safe_file_under(EVAL_DIR / filename, EVAL_DIR)
    if not path:
        raise HTTPException(status_code=404, detail="Plot not found")
    return FileResponse(str(path), media_type="image/png")


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════════════════

_IST = timezone(timedelta(hours=5, minutes=30))


@router.get("/alerts/export/csv")
async def export_alerts_csv(
    limit: int = 1000,
    _user: dict = Depends(get_current_user),
):
    """Download all alerts as a CSV file."""
    import contextlib
    with contextlib.closing(get_db_connection()) as conn:
        rows = conn.execute(
            "SELECT id, person_id, event_type, risk_score, risk_level, "
            "timestamp, camera_id, location, status FROM alerts "
            "ORDER BY timestamp DESC LIMIT ?",
            (min(limit, 10000),),
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "person_id", "event_type", "risk_score",
                     "risk_level", "timestamp", "camera_id", "location", "status"])
    for row in rows:
        writer.writerow(list(row))

    ts = datetime.now(_IST).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="alerts_{ts}.csv"'},
    )


@router.get("/incidents/export/csv")
async def export_incidents_csv(
    limit: int = 1000,
    _user: dict = Depends(get_current_user),
):
    """Download all incidents as a CSV file."""
    import contextlib
    with contextlib.closing(get_db_connection()) as conn:
        rows = conn.execute(
            "SELECT id, title, description, event_type, location, "
            "risk_level, status, created_at, resolved_at FROM incidents "
            "ORDER BY created_at DESC LIMIT ?",
            (min(limit, 10000),),
        ).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "title", "description", "event_type",
                     "location", "risk_level", "status", "created_at", "resolved_at"])
    for row in rows:
        writer.writerow(list(row))

    ts = datetime.now(_IST).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="incidents_{ts}.csv"'},
    )


# ══════════════════════════════════════════════════════════════════════════════
# MULTI-CAMERA
# ══════════════════════════════════════════════════════════════════════════════

try:
    from backend.camera_registry import camera_registry
    _MULTI_CAM = True
except Exception:
    camera_registry = None
    _MULTI_CAM = False


@router.get("/cameras")
async def list_cameras(_user: dict = Depends(get_current_user)):
    """List all registered cameras and their live health status."""
    if not _MULTI_CAM or camera_registry is None:
        return []
    return camera_registry.list_cameras()


@router.get("/cameras/{cam_id}/feed")
async def camera_feed(cam_id: str, request: Request):
    """MJPEG stream for a specific camera by ID."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    verify_token(token)

    if not _MULTI_CAM or camera_registry is None:
        raise HTTPException(status_code=503, detail="Multi-camera not configured")

    async def generate():
        while True:
            if await request.is_disconnected():
                break
            frame_bytes = await asyncio.get_event_loop().run_in_executor(
                None, camera_registry.get_frame, cam_id
            )
            if frame_bytes is None:
                await asyncio.sleep(0.1)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            await asyncio.sleep(0.025)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


# ══════════════════════════════════════════════════════════════════════════════
# VIDEO FEED
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/video_feed")
async def video_feed(request: Request):
    """MJPEG video stream. Requires a valid JWT token."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required for video feed")
    verify_token(token)  # raises 401 if invalid or expired

    async def generate():
        while True:
            if await request.is_disconnected():
                break
            # get_frame_bytes() returns pre-encoded bytes (no blocking encode here)
            frame_bytes = await asyncio.get_event_loop().run_in_executor(
                None, stream_manager.get_frame_bytes
            )
            if frame_bytes is None:
                await asyncio.sleep(0.05)
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            await asyncio.sleep(0.025)  # ~40 FPS cap

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/frame")
async def single_frame(request: Request):
    """Return the latest frame as a single JPEG."""
    token = _extract_token(request)
    if token:
        verify_token(token)

    frame_bytes = stream_manager.get_frame_bytes()
    if frame_bytes is None:
        raise HTTPException(status_code=503, detail="No frame available")
    return Response(content=frame_bytes, media_type="image/jpeg")


# ══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════


@router.get("/users")
async def get_users(user: dict = Depends(require_roles("admin"))):
    conn = get_db_connection()
    users = conn.execute(
        "SELECT id, username, role, status, last_active FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(row) for row in users]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    user: dict = Depends(require_roles("admin")),
):
    if body.role not in ("admin", "operator", "viewer", "security"):
        raise HTTPException(status_code=400, detail="Invalid role")

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (body.username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Username already exists")

    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, status, last_active) VALUES (?, ?, ?, ?, ?)",
            (body.username, generate_password_hash(body.password), body.role, "Active", "Just now"),
        )
        conn.commit()
        user_id = cursor.lastrowid
    finally:
        conn.close()

    return {"message": "User created", "id": user_id}


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    user: dict = Depends(require_roles("admin")),
):
    conn = get_db_connection()
    existing = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    updates = []
    values = []

    if body.username is not None:
        other = conn.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?", (body.username, user_id)
        ).fetchone()
        if other:
            conn.close()
            raise HTTPException(status_code=409, detail="Username already taken")
        updates.append("username = ?")
        values.append(body.username)

    if body.password:
        updates.append("password_hash = ?")
        values.append(generate_password_hash(body.password))

    if body.role is not None:
        if body.role not in ("admin", "operator", "viewer", "security"):
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid role")
        updates.append("role = ?")
        values.append(body.role)

    if body.status is not None:
        allowed = {"active", "inactive", "suspended"}
        if body.status.strip().lower() not in allowed:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(allowed)}")
        updates.append("status = ?")
        values.append(body.status.strip().title())

    if not updates:
        conn.close()
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    conn.execute(query, values)
    conn.commit()
    conn.close()

    return {"message": "User updated", "id": user_id}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    user: dict = Depends(require_roles("admin")),
):
    conn = get_db_connection()
    existing = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")

    conn.execute("UPDATE users SET status = ? WHERE id = ?", ("Inactive", user_id))
    conn.commit()
    conn.close()

    return {"message": "User deactivated", "id": user_id}


# ══════════════════════════════════════════════════════════════════════════════
# FOOTAGE & PIPELINE CONTROL
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/footage")
async def get_footage(_user: dict = Depends(get_current_user)):
    footage_dir = PROJECT_ROOT / "footage"
    files = []
    if footage_dir.exists():
        files = [f.name for f in footage_dir.glob("*.mp4")]
    
    sources = [
        {"label": "Webcam", "value": "0"},
        {"label": "RTSP Stream", "value": "rtsp://localhost:8554/stream"}
    ]
    for f in files:
        sources.append({"label": f"Footage: {f}", "value": f"footage/{f}"})
        
    return {"files": files, "sources": sources}


class SwitchSourceRequest(BaseModel):
    source: str

@router.post("/pipeline/switch_source")
async def switch_pipeline_source(
    body: SwitchSourceRequest,
    _user: dict = Depends(require_roles("admin", "security", "operator"))
):
    source = body.source.strip()
    if not source:
        raise HTTPException(status_code=400, detail="Source cannot be empty")
        
    # In a real system, this would signal the pipeline thread to restart with the new source.
    return {"message": "Pipeline source switch requested", "source": source}


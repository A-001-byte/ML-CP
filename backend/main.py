"""
main.py
───────
FastAPI entry point for the ThreatSense AI backend.

Replaces the old Flask app.py.  Starts the AI surveillance pipeline
in a background thread and serves:
  - REST API at /api/*
  - WebSocket at /ws (real-time stats + alerts)
  - MJPEG video feed at /api/video_feed

Usage:
    python -m backend.main
    # or
    uvicorn backend.main:app --host 0.0.0.0 --port 5000 --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
import threading
import time

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db, get_db_connection
from backend.routes import router as api_router
from backend.ws_manager import ws_manager
from core.stream_manager import stream_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
_log = logging.getLogger("backend")


# ── Model validation ────────────────────────────────────────────────────────

def _resolve_models() -> tuple[str, str | None]:
    """Locate AI model files.  Returns (person_model_path, weapon_model_path)."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    person_model = os.path.join(root, "yolov8m.pt")
    weapon_model = os.path.join(root, "models", "weapon_detector.pt")
    fallback = os.path.join(root, "yolo26n.pt")

    if not os.path.isfile(person_model):
        _log.warning("Primary person model not found at %s", person_model)
        if not os.path.isfile(fallback):
            raise RuntimeError(
                f"No person detection model found.\n"
                f"  Tried: {person_model}\n"
                f"  Tried: {fallback}\n"
                "Place at least yolo26n.pt in the project root."
            )
        person_model = fallback
        _log.info("Using fallback model: %s", fallback)

    if not os.path.isfile(weapon_model):
        _log.warning("Weapon model not found at %s — weapon detection disabled", weapon_model)
        weapon_model = None

    return person_model, weapon_model


# ── Pipeline thread ─────────────────────────────────────────────────────────

def _parse_pipeline_source(raw_source: str | None) -> int | str:
    source = (raw_source or "0").strip()
    if source.isdigit():
        return int(source)
    if not ("://" in source) and not os.path.isabs(source):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        candidate = os.path.join(root, source)
        if os.path.exists(candidate):
            return candidate
    return source


# ── Pipeline management globals ──────────────────────────────────────────────
_pipeline_instance = None          # live SurveillancePipeline object
_pipeline_thread: threading.Thread | None = None
_pipeline_lock = threading.Lock()  # serialise restart requests
_person_model_path: str = ""
_weapon_model_path: str | None = None


def _run_pipeline(person_model: str, weapon_model: str | None) -> None:
    """Start the AI surveillance pipeline (blocking — runs in a daemon thread)."""
    global _pipeline_instance
    _log.info("Starting AI pipeline …")
    _log.info("  Person model: %s", person_model)
    _log.info("  Weapon model: %s", weapon_model)
    source = _parse_pipeline_source(os.environ.get("PIPELINE_SOURCE"))
    _log.info("  Source: %s", source)

    # Auto-detect device — graceful fallback to CPU
    import torch
    requested_device = os.environ.get("PIPELINE_DEVICE", "cuda:0")
    if requested_device.startswith("cuda") and not torch.cuda.is_available():
        _log.warning("CUDA requested but not available — falling back to CPU")
        requested_device = "cpu"
    else:
        _log.info("  Device: %s", requested_device)

    try:
        from core.pipeline import SurveillancePipeline

        # Auto-tune for CPU if no GPU available
        import torch
        is_cpu = (requested_device == "cpu") or not torch.cuda.is_available()
        
        default_imgsz = "256" if is_cpu else "320"
        default_weapon_skip = "10" if is_cpu else "6"
        default_risk_skip = "5" if is_cpu else "4"
        
        pipeline = SurveillancePipeline(
            source=source,
            person_model=person_model,
            weapon_model=weapon_model,
            device=requested_device,
            headless=True,
            imgsz=int(os.environ.get("PIPELINE_IMGSZ", default_imgsz)),
            weapon_skip=int(os.environ.get("PIPELINE_WEAPON_SKIP", default_weapon_skip)),
            risk_skip=int(os.environ.get("PIPELINE_RISK_SKIP", default_risk_skip)),
        )
        _pipeline_instance = pipeline
        pipeline.run()
    except Exception as e:
        _log.exception("AI pipeline crashed: %s", e)
    finally:
        _pipeline_instance = None


def restart_pipeline() -> None:
    """Stop the current AI pipeline and start a fresh one with the current env config.

    Thread-safe — only one restart runs at a time.
    Called by POST /api/pipeline/switch_source.
    """
    global _pipeline_thread, _pipeline_instance
    with _pipeline_lock:
        # 1. Signal the current pipeline to stop
        if _pipeline_instance is not None:
            _log.info("Requesting pipeline stop …")
            _pipeline_instance._stop_requested = True

        # 2. Wait for the old thread to finish (max 8s)
        if _pipeline_thread is not None and _pipeline_thread.is_alive():
            _pipeline_thread.join(timeout=8)
            if _pipeline_thread.is_alive():
                _log.warning("Pipeline thread did not stop within 8s — starting new one anyway")

        # 3. Launch a new pipeline thread
        _log.info("Restarting pipeline with source=%s", os.environ.get("PIPELINE_SOURCE", "0"))
        _pipeline_thread = threading.Thread(
            target=_run_pipeline,
            args=(_person_model_path, _weapon_model_path),
            daemon=True,
            name="ai-pipeline",
        )
        _pipeline_thread.start()


# ── Stats emitter ────────────────────────────────────────────────────────────

def _stats_emitter() -> None:
    """Periodically push system stats via WebSocket (runs in daemon thread)."""
    while True:
        try:
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

            stats = {
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
            ws_manager.broadcast_stats(stats)
        except Exception as e:
            _log.error("Stats emitter error: %s", e)

        time.sleep(5)


# ── FastAPI app ──────────────────────────────────────────────────────────────

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Initialise the SQLite database
    init_db()

    # Register the asyncio loop so the pipeline thread can broadcast
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)

    # Resolve model paths and store for restart use
    global _person_model_path, _weapon_model_path, _pipeline_thread
    _person_model_path, _weapon_model_path = _resolve_models()

    # Skip AI pipeline when running under pytest / CI
    if os.environ.get("THREATSENSE_NO_PIPELINE") != "1":
        _pipeline_thread = threading.Thread(
            target=_run_pipeline,
            args=(_person_model_path, _weapon_model_path),
            daemon=True,
            name="ai-pipeline",
        )
        _pipeline_thread.start()
    else:
        _log.info("THREATSENSE_NO_PIPELINE=1 — AI pipeline disabled (test mode)")

    # Start multi-camera registry (adds any cameras from CAMERAS_JSON env var)
    if os.environ.get("THREATSENSE_NO_PIPELINE") != "1":
      try:
        from backend.camera_registry import camera_registry
        camera_registry.start_all()
        _log.info("Camera registry started (%d cameras)", len(camera_registry.list_cameras()))
      except Exception as exc:
        _log.warning("Camera registry failed to start: %s", exc)

    # Start stats emitter
    stats_thread = threading.Thread(
        target=_stats_emitter,
        daemon=True,
        name="stats-emitter",
    )
    stats_thread.start()

    _log.info("╔══════════════════════════════════════╗")
    _log.info("║   ThreatSense-AI  •  Backend Ready   ║")
    _log.info("╚══════════════════════════════════════╝")

    yield  # app is running

    _log.info("Shutting down …")


app = FastAPI(
    title="ThreatSense-AI",
    description=(
        "Real-time AI-powered weapon detection and surveillance API.\n\n"
        "**Authentication:** All data endpoints require a JWT token.\n"
        "Login via `POST /api/login` — the response sets an HttpOnly cookie "
        "(`ts_token`) and also returns the token in the body for API clients.\n\n"
        "Pass the token as:\n"
        "- `Authorization: Bearer <token>` header\n"
        "- `ts_token` HttpOnly cookie (set automatically on login)\n"
        "- `?token=<token>` query param (for video feed `<img>` tags)\n\n"
        "**Model:** YOLOv8m fine-tuned on 19k weapon images — mAP50=0.892\n\n"
        "See `GET /api/health` for liveness probe and `GET /api/system_status` for pipeline health."
    ),
    version="2.1.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth",      "description": "Login, logout, register, user info"},
        {"name": "alerts",    "description": "Weapon detection alerts — list, filter, export"},
        {"name": "incidents", "description": "Incident reports — list, resolve, escalate, export"},
        {"name": "cameras",   "description": "Camera registry and live MJPEG streams"},
        {"name": "system",    "description": "Pipeline health, metrics, liveness probe"},
    ],
)

# ── CORS ─────────────────────────────────────────────────────────────────────
allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "TRUSTED_DASHBOARD_HOSTS",
        "http://localhost:3000,http://localhost:3001",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routes ──────────────────────────────────────────────────────────────
app.include_router(api_router)


# ── WebSocket endpoint ───────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive — read pings / client messages
            data = await websocket.receive_text()
            # Clients may send pings or commands; for now, just acknowledge
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# ── Health probe ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "service": "ThreatSense AI Backend", "version": "2.1.0"}


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="ThreatSense-AI FastAPI backend")
    parser.add_argument("--source", default=None, help="Video source: webcam index, .mp4 path, or RTSP URL")
    args, _unknown = parser.parse_known_args()
    if args.source:
        os.environ["PIPELINE_SOURCE"] = args.source

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    reload_flag = os.environ.get("RELOAD", "0") == "1"

    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=reload_flag,
        log_level="info",
    )

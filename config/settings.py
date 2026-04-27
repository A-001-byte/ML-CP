"""
settings.py
───────────
Single source of truth for all runtime configuration.
Values are loaded from environment variables with sane defaults.

Usage:
    from config.settings import settings
    print(settings.weapon_conf_threshold)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PipelineSettings:
    # ── Detection thresholds ────────────────────────────────────────
    person_conf: float          = float(os.environ.get("PERSON_CONF",          "0.40"))
    weapon_conf: float          = float(os.environ.get("WEAPON_CONF",          "0.30"))
    weapon_conf_threshold: float = float(os.environ.get("WEAPON_CONF_THRESHOLD", "0.65"))
    armed_threshold: float      = float(os.environ.get("ARMED_THRESHOLD",      "0.62"))
    weapon_min_area: int        = int(os.environ.get("WEAPON_MIN_AREA",        "4000"))
    person_top_skip: float      = float(os.environ.get("PERSON_TOP_SKIP",      "0.40"))

    # ── Frame skipping ──────────────────────────────────────────────
    weapon_skip: int    = int(os.environ.get("WEAPON_SKIP",   "5"))
    risk_skip: int      = int(os.environ.get("RISK_SKIP",     "3"))
    person_skip: int    = int(os.environ.get("PIPELINE_PERSON_SKIP", "1"))

    # ── Verification ────────────────────────────────────────────────
    verifier_min_frames: int    = int(os.environ.get("VERIFIER_MIN_FRAMES",   "3"))
    verifier_min_conf: float    = float(os.environ.get("VERIFIER_MIN_CONF",   "0.62"))
    verifier_decay_after: int   = int(os.environ.get("VERIFIER_DECAY_AFTER",  "5"))
    weapon_box_persist: int     = int(os.environ.get("WEAPON_BOX_PERSIST",    "20"))

    # ── Models ──────────────────────────────────────────────────────
    person_model: str = os.environ.get("PERSON_MODEL",  str(PROJECT_ROOT / "yolov8m.pt"))
    weapon_model: str = os.environ.get("WEAPON_MODEL",  str(PROJECT_ROOT / "models" / "weapon_detector.pt"))
    device: str       = os.environ.get("PIPELINE_DEVICE", "cuda:0")
    imgsz: int        = int(os.environ.get("PIPELINE_IMGSZ", "416"))

    # ── Stream ──────────────────────────────────────────────────────
    stream_width: int      = int(os.environ.get("STREAM_WIDTH",   "854"))
    stream_jpeg_quality: int = int(os.environ.get("STREAM_JPEG_QUALITY", "70"))
    stream_fps_cap: float  = float(os.environ.get("STREAM_FPS_CAP",   "40"))


@dataclass(frozen=True)
class SecuritySettings:
    jwt_expire_hours: int = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))
    cookie_secure: bool   = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    cors_origins: list    = field(default_factory=lambda: [
        o.strip() for o in
        os.environ.get("TRUSTED_DASHBOARD_HOSTS", "http://localhost:3000,http://localhost:3001").split(",")
        if o.strip()
    ])


@dataclass(frozen=True)
class NotificationSettings:
    email_enabled: bool = os.environ.get("ALERT_EMAIL_ENABLED", "false").lower() == "true"
    smtp_host: str      = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
    smtp_port: int      = int(os.environ.get("ALERT_SMTP_PORT", "587"))
    smtp_user: str      = os.environ.get("ALERT_SMTP_USER", "")
    smtp_pass: str      = os.environ.get("ALERT_SMTP_PASS", "")
    email_to: list      = field(default_factory=lambda: [
        r.strip() for r in os.environ.get("ALERT_EMAIL_TO", "").split(",") if r.strip()
    ])


@dataclass(frozen=True)
class AppSettings:
    pipeline: PipelineSettings     = field(default_factory=PipelineSettings)
    security: SecuritySettings     = field(default_factory=SecuritySettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    debug: bool = os.environ.get("FLASK_DEBUG", "0") == "1"


settings = AppSettings()

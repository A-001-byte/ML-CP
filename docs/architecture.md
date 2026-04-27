# ThreatSense-AI — System Architecture

## Overview

ThreatSense-AI is a real-time AI-powered surveillance system that detects weapons in live camera feeds and dispatches alerts to security operators via a web dashboard.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CAMERA SOURCES                               │
│   Webcam 0 │ Webcam 1 │ RTSP Stream │ Video File                   │
└──────┬──────┴────┬──────┴──────┬──────┴────────────┘
       │           │             │
       └───────────┴─────────────┘
                   │
       ┌───────────▼───────────────────────────────────────┐
       │             AI PIPELINE  (background thread)       │
       │                                                     │
       │  ┌──────────────┐   ┌────────────────────────┐    │
       │  │ PersonDetector│   │ WeaponDetector         │    │
       │  │ YOLOv8m       │──▶│ YOLOv8m (fine-tuned)  │    │
       │  │ + ByteTrack   │   │ Zone-based crop        │    │
       │  └──────────────┘   └──────────┬─────────────┘    │
       │                                │                    │
       │                    ┌───────────▼─────────────┐     │
       │                    │ WeaponVerifier           │     │
       │                    │ Multi-frame confirmation │     │
       │                    │ (min 3 frames, conf≥0.62)│     │
       │                    └───────────┬─────────────┘     │
       │                                │                    │
       │            ┌───────────────────▼────────────────┐  │
       │            │  BehaviorAnalyzer + RiskEngine      │  │
       │            │  Loitering / zone intrusion / armed │  │
       │            └───────────────────┬────────────────┘  │
       │                                │                    │
       │  ┌─────────────┐   ┌───────────▼────────────────┐  │
       │  │StreamManager│   │  IncidentRecorder          │  │
       │  │JPEG pre-enc │   │  Rolling buffer → MP4 clip │  │
       │  └──────┬──────┘   └────────────────────────────┘  │
       └─────────┼─────────────────────────────────────────-┘
                 │
       ┌─────────▼──────────────────────────────────────────┐
       │               FASTAPI BACKEND  (:5000)              │
       │                                                      │
       │  REST API /api/*          WebSocket /ws             │
       │  ┌────────────────┐      ┌─────────────────────┐   │
       │  │ /alerts        │      │ Live stats push      │   │
       │  │ /incidents     │      │ Weapon alerts        │   │
       │  │ /cameras       │      │ Pipeline health      │   │
       │  │ /video_feed    │      └─────────────────────┘   │
       │  │ /health        │                                  │
       │  └────────────────┘      ┌─────────────────────┐   │
       │                          │ EmailNotifier        │   │
       │  SQLite (surveillance.db)│ SMTP on weapon detect│   │
       │  alerts / incidents /    └─────────────────────┘   │
       │  users tables                                        │
       └─────────────────────────────────────────────────────┘
                 │                        │
       ┌─────────▼──────────┐   ┌─────────▼──────────────┐
       │  NEXT.JS DASHBOARD │   │  Security Operators     │
       │  (:3000 / :3001)   │   │  Email / Mobile Alerts  │
       │  Live Monitor       │   └────────────────────────┘
       │  Incident History   │
       │  User Management    │
       └────────────────────┘
```

---

## Data Flow

### Normal Operation (no threat)
```
Camera frame
  → PersonDetector (YOLOv8m + ByteTrack)
  → Person bounding boxes with track IDs
  → WeaponDetector (lower 60% crop only)
  → No detections above threshold
  → StreamManager (JPEG encode, push to web)
  → Dashboard shows GREEN boxes at 30+ FPS
```

### Threat Detected
```
Camera frame
  → PersonDetector → Person track ID = 7
  → WeaponDetector → "gun" at 0.81 confidence
  → WeaponVerifier → 3rd consecutive frame, avg_conf=0.79 ✓ CONFIRMED
  → confirmed_armed_ids = {7}
  → IncidentRecorder.trigger(7, "gun")  → saves MP4 clip to logs/incidents/
  → RiskEngine → risk_score=85, threat_level="critical"
  → AlertManager → INSERT into alerts table
  → EmailNotifier → SMTP email to security team
  → WebSocket → push to dashboard
  → Dashboard shows RED box + "Armed ID 7"
```

---

## Module Dependency Map

```
backend/main.py          ← entry point
  ├── backend/routes.py  ← REST API + MJPEG stream
  ├── backend/auth.py    ← JWT + HttpOnly cookie
  ├── backend/database.py← SQLite (IST timestamps)
  ├── backend/ws_manager.py ← WebSocket broadcast
  ├── backend/notifications.py ← Email alerts
  ├── backend/camera_registry.py ← Multi-camera
  └── core/pipeline.py   ← AI pipeline (background thread)
        ├── detection/person_detector.py  ← YOLOv8m + ByteTrack
        ├── detection/weapon_detector.py  ← YOLOv8m fine-tuned
        ├── core/weapon_verifier.py       ← multi-frame confirm
        ├── core/stream_manager.py        ← JPEG pre-encode
        ├── backend/incident_recorder.py  ← MP4 clip recording
        ├── behavior/behavior_analyzer.py ← motion/loiter
        ├── engine/risk_engine.py         ← scoring + alerting
        └── config/settings.py            ← all thresholds (env-driven)
```

---

## Model Architecture

### Person Detector
- **Model**: YOLOv8m (COCO pre-trained, frozen)
- **Input**: Full camera frame at 416px
- **Output**: Person bounding boxes + ByteTrack IDs
- **NMS**: Custom IoU dedup (threshold=0.55) to eliminate duplicate tracks

### Weapon Detector
- **Model**: YOLOv8m fine-tuned on ~19k weapon images
- **Classes**: `gun` (0), `knife` (1), `person` (2, ignored)
- **Input**: Lower 60% of person bounding box (no head/background)
- **Training**: 70 epochs, AdamW, imgsz=640, mAP50=0.888
- **Filters**: confidence ≥ 0.65, box area ≥ 4000px², ≥35% overlap with person box

### WeaponVerifier
- Requires ≥3 consecutive detection frames with avg confidence ≥0.62
- Gradual decay: 5 missed cycles → evidence halved → eventually cleared
- Prevents single-frame false positives from triggering alerts

---

## Security Model

| Mechanism | Implementation |
|---|---|
| Authentication | JWT, 24h expiry, signed with `JWT_SECRET` |
| Cookie security | HttpOnly + SameSite=Strict (eliminates XSS token theft) |
| Authorization | Role-based (admin / security / viewer) on all data endpoints |
| Rate limiting | 5 req/min on login; 10 req/min per IP on API |
| Video feed | Auth required (Bearer or HttpOnly cookie) |
| CORS | Whitelist via `TRUSTED_DASHBOARD_HOSTS` env var |

---

## Deployment

### Development
```bash
python -m backend.main        # FastAPI backend on :5000
cd dashboard && npm run dev   # Next.js frontend on :3000
```

### Docker (recommended)
```bash
cp .env.example .env          # fill in JWT_SECRET, ADMIN_PASSWORD
docker compose up --build
```

### Environment variables → `config/settings.py`
All thresholds and secrets are environment-driven. See `.env.example` for the full list.

---

## Known Limitations

1. **Model trained on stock photos** — performance degrades on night footage, heavy motion blur, and partial occlusion. Retraining with negative examples (textured backgrounds, glasses) would improve precision.
2. **SQLite** — not suitable for concurrent write-heavy production loads; migrate to PostgreSQL.
3. **Single-process** — AI pipeline and API server share the same OS process. Under heavy inference load, API latency increases. A message queue (Redis) between pipeline and API is the production path.
4. **No face anonymization** — real deployment requires GDPR/DPDP-compliant face blurring for non-suspects.
5. **blunt_weapon class omitted** — only 5 training samples available; class will be added in a future training run with an augmented dataset.

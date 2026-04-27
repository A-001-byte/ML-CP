# ThreatSense-AI

Real-time AI weapon detection and surveillance system built with YOLOv8, FastAPI, and Next.js.  
Detects guns and knives in live camera feeds, confirms detections across multiple frames, records incident clips, and dispatches alerts to security operators via a web dashboard.

---

## Model Results

| Metric | Value |
|---|---|
| **mAP50 (overall)** | **0.892** |
| mAP50-95 | 0.658 |
| Precision | 0.837 |
| Recall | 0.867 |
| Gun — mAP50 | 0.918 |
| Knife — mAP50 | 0.948 |
| Live FPS | ~32 FPS (RTX 3050) |
| Training dataset | 19,295 images (4 merged sources) |
| Training epochs | 70 (early stop at patience=20) |

Full results → [`docs/evaluation_results.json`](docs/evaluation_results.json)  
Confusion matrix + PR curves → [`docs/evaluation/eval/`](docs/evaluation/eval/)

---

## Architecture

```
Camera ──▶ YOLOv8m Person Detector ──▶ YOLOv8m Weapon Detector (zone crop)
                                              │
                                        WeaponVerifier (multi-frame confirm)
                                              │
                            ┌─────────────────┴──────────────────┐
                     IncidentRecorder                      RiskEngine
                     (MP4 clip saved)              (BehaviorAnalyzer + alerts)
                            │                              │
                     FastAPI Backend ◀──────────────────────┘
                            │
                     Next.js Dashboard ◀── WebSocket (live stats)
                            │
                     Email Notifications (SMTP on weapon confirm)
```

See [`docs/architecture.md`](docs/architecture.md) for the full diagram with module dependencies.

---

## Quick Start

### Prerequisites
- Python 3.11+  |  Node.js 20+  |  GPU recommended (CPU fallback supported)
- `models/weapon_detector.pt` in `models/` — download from releases or train (see below)

```bash
git clone https://github.com/your-org/threatsense-ai
cd threatsense-ai

python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # set JWT_SECRET + ADMIN_PASSWORD

# Terminal 1 — backend
python -m backend.main        # http://localhost:5000  |  Swagger: /docs

# Terminal 2 — dashboard
cd dashboard && npm install && npm run dev    # http://localhost:3000
```

### Docker
```bash
docker compose up --build     # backend + dashboard, no manual setup
```

---

## Running Tests

```bash
pytest tests/ -v
# 61 passed, 5 skipped
```

CI runs on every push — `.github/workflows/ci.yml`.

---

## Training

### Dataset preparation
```bash
# After downloading datasets into datasets/<name>/ (see scripts/merge_weapon_classes.py)
python scripts/merge_weapon_classes.py
python scripts/zip_for_colab.py          # → weapon_merged.zip for Google Colab
```

### Train (Colab recommended — T4 GPU, ~9 hrs)
Upload `weapon_merged.zip` to Google Drive → open `training/threatsense_train.ipynb` in Colab.

### Train locally
```bash
python training/train_weapon_detector.py --batch 8
copy runs\detect\weapon_training\weights\best.pt models\weapon_detector.pt
```

### Evaluate
```bash
python scripts/evaluate_model.py
# → docs/evaluation_results.json + docs/evaluation/eval/*.png
```

---

## Multi-Camera

```bash
CAMERAS_JSON='[{"id":"cam1","source":0,"location":"Main Entrance"},{"id":"cam2","source":"rtsp://...","location":"Back Door"}]'
python -m backend.main
```

API: `GET /api/cameras` — list health  |  `GET /api/cameras/{id}/feed` — MJPEG stream

---

## API Reference

Swagger UI: **http://localhost:5000/docs**

| Endpoint | Auth | Method |
|---|---|---|
| `/api/login` | — | POST |
| `/api/logout` | — | POST |
| `/api/alerts` | ✓ | GET |
| `/api/alerts/export/csv` | ✓ | GET |
| `/api/incidents` | ✓ | GET |
| `/api/stats` | ✓ | GET |
| `/api/cameras` | ✓ | GET |
| `/api/video_feed` | ✓ | GET (MJPEG) |
| `/api/system_status` | — | GET |
| `/api/health` | — | GET |

---

## Project Structure

```
threatsense-ai/
├── backend/              FastAPI backend
│   ├── main.py           Entry point + lifespan
│   ├── routes.py         All REST endpoints
│   ├── auth.py           JWT + HttpOnly cookie
│   ├── database.py       SQLite (IST timestamps)
│   ├── notifications.py  Email on weapon detect
│   ├── incident_recorder.py  MP4 clip on detect
│   └── camera_registry.py   Multi-camera manager
├── core/
│   ├── pipeline.py       AI loop (detect → verify → alert)
│   ├── stream_manager.py JPEG pre-encoding (~40 FPS web)
│   └── weapon_verifier.py Multi-frame confirmation
├── detection/
│   ├── person_detector.py  YOLOv8m + ByteTrack + NMS
│   └── weapon_detector.py  Fine-tuned, zone-based crop
├── config/settings.py    Centralized env-driven config
├── dashboard/            Next.js 16 frontend
├── docs/                 Architecture + evaluation results
├── models/               Weights (gitignored)
├── scripts/              Dataset + evaluation utilities
├── tests/                61 pytest tests
└── training/             Colab notebook + train script
```

---

## Security Model

| | |
|---|---|
| Token storage | HttpOnly cookie (not localStorage — XSS-safe) |
| Authorization | Role-based: `admin` / `security` / `viewer` |
| Rate limiting | 5 req/min on login, 10 req/min API |
| CORS | Whitelist via `TRUSTED_DASHBOARD_HOSTS` |
| Video feed | Auth required (cookie or Bearer) |

---

## Known Limitations & Technical Debt

- Model trained on stock photos — false positive rate increases with textured backgrounds (curtains, patterned wallpaper). Retraining with in-situ negative examples recommended.
- SQLite is not production-safe under concurrent writes — migrate to PostgreSQL.
- No automated database migrations configured. Schema evolution currently relies on ad-hoc `CREATE TABLE IF NOT EXISTS` checks.
- Single-process state memory — rate limiters, JWT secrets, active WebSocket sets, and per-camera states are held in-memory. Horizontal scaling requires an external store (e.g., Redis).
- No face anonymization — required for GDPR/India DPDP compliance.
- Blunt weapon class omitted (5 training samples — insufficient).

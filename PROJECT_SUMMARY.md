# ThreatSense AI — Project Analysis Summary

*Senior Software Analyst Review — April 28, 2026*

---

## 1. Executive Summary

**ThreatSense AI** is a real-time, AI-powered surveillance and weapon-detection platform. It combines a Python computer-vision pipeline (YOLOv8 + ByteTrack + a fine-tuned weapon model) with a FastAPI backend and a Next.js 16 / React 19 dashboard. The system ingests camera feeds, detects persons, tracks them, looks for weapons in their lower-body region, confirms detections across multiple frames, evaluates behavioral risk (loitering, zone intrusion, group threats), records evidence clips, and pushes everything to a security operator dashboard in real time.

The product is in a working, demo-ready state. A trained weapon-detection model is shipped (`models/weapon_detector.pt`, mAP50 = 0.892), the database has been seeded with admin / operator / viewer accounts, and incident clips from late April 2026 are present in `logs/incidents/`. Most of the headline features are functionally wired end-to-end. A handful of modules are legacy or unwired (see §6).

---

## 2. What the Project Is Trying to Build

A self-hosted security command-center that an operator can leave running 24/7:

- Watches one or more camera feeds (USB webcam, video file, RTSP).
- Detects people, tracks them with stable IDs, looks for guns / knives.
- Filters false positives via multi-frame confirmation and a polygonal "detection zone".
- Scores each person on a risk scale combining current behavior, behavior history, behavior-fusion bonuses, pattern matches and group dynamics.
- Surfaces threats in a web dashboard with a live MJPEG feed, a real-time WebSocket alert toast, an incident log with playable evidence clips, an analytics view, and admin CRUD over operator accounts.
- Sends email notifications and persists everything to SQLite for audit.

It is positioned as a research-grade / hackathon-grade product — single-machine, single SQLite DB, in-memory rate limiter, in-memory JWT secret in dev mode — but with surprisingly mature plumbing (HttpOnly cookies, role-based access control, CSV exports, IST-aware timestamps, exponential-backoff WebSocket reconnect, etc.).

---

## 3. Repository Layout

```
Pick-me-Programmers/
├── backend/             FastAPI app — REST, WebSocket, MJPEG, JWT auth, SQLite
├── core/                Pipeline orchestration + WeaponVerifier + StreamManager
├── detection/           PersonDetector (YOLOv8) + WeaponDetector (lower-body crop)
├── behavior/            BehaviorAnalyzer — loitering / zone / speed / crowd
├── engine/              RiskEngine + RiskCalculator + ThreatClassifier + BehaviorFusion
├── memory/              Per-person memory store with decay
├── analytics/           Pattern + group-behavior detectors
├── alerts/              AlertRules + AlertManager (DB persistence + throttling)
├── risk_logging/        EventLogger + AuditLogger (JSONL audit trail)
├── config/              settings.py + JSON configs (risk_weights, threat_levels, decay)
├── utils/               config_loader, time_utils, logger
├── training/            train_weapon_detector.py + Jupyter notebook
├── scripts/             merge_weapon_classes, evaluate_model, check_accuracy, zip_for_colab
├── tests/               pytest suite — API, pipeline, weapon detector, risk engine
├── models/              weapon_detector.pt (gitignored)
├── datasets/            yolo-weapon-detection (gitignored)
├── docs/                architecture.md, evaluation_results.json, eval/ plots
├── logs/                audit_*.jsonl + incidents/*.mp4 (runtime)
├── dashboard/           Next.js 16 + React 19 + Tailwind 4 frontend
│   ├── app/             App Router — (auth)/login, (dashboard)/{monitor,incidents,...}
│   ├── components/      LiveMonitor, IncidentHistory, Analytics, CameraGrid, etc.
│   └── lib/             api.ts (HTTP client), socket.ts (WebSocket hook)
├── requirements.txt     Python deps
└── .gitignore           Excludes models, datasets, db, logs, node_modules
```

---

## 4. Architecture

### 4.1 The AI Pipeline (`core/pipeline.py`)

Runs in a daemon thread started by `backend/main.py` lifespan. Per-frame flow:

1. **PersonDetector.track()** — YOLOv8m + ByteTrack → tracked persons with stable IDs. NMS de-duplication is applied because ByteTrack occasionally assigns two IDs to the same person.
2. **WeaponDetector.detect_in_region()** — for each person box, crops the lower 60% (`PERSON_TOP_SKIP=0.40`) and runs the fine-tuned weapon YOLO. This physical crop replaces fragile post-hoc spatial filters and eliminates upper-body false positives (glasses, ceiling tiles, etc.). Results are remapped to full-frame coordinates and required to overlap the person box ≥ 35%.
3. **DetectionZone filter** — if a polygon zone is configured, weapon detections whose box-center falls outside the polygon are dropped.
4. **WeaponVerifier.update()** — accumulates per-person evidence; a weapon is "confirmed" only when ≥ 3 frames hit with average confidence ≥ 0.62. Missed frames decay (halve confidence + decrement frame count) after 5 consecutive misses.
5. **BehaviorAnalyzer.analyze()** — computes loitering (low displacement over 30 frames), zone intrusion, speed, crowd density, weapon flag.
6. **RiskEngine.process_frame()** — for each person:
   - Pulls per-person `PersonMemory` (loiter_count, zone_intrusions, weapon_events, risk_history).
   - `RiskCalculator` adds base weights (`risk_weights.json`: weapon=90, zone_intrusion=35, loitering=20, running=15) plus history penalties.
   - `BehaviorFusion` adds synergy bonuses (loitering + intrusion = +15; intrusion + weapon force ≥ 100).
   - `PatternDetector` flags "multiple intrusions", "persistent high risk", "loitering→intrusion".
   - Decay: idle minutes × 5 points/min reduces stale risk.
   - `ThreatClassifier` maps score → NORMAL/LOW/SUSPICIOUS/HIGH_RISK/CRITICAL (`threat_levels.json`).
   - `AuditLogger` writes a JSONL line to `logs/audit_YYYYMMDD.jsonl`.
   - `AlertManager.evaluate_and_alert()` persists to DB (alerts + incidents for high/critical), with 30-second per-(person, behavior-set) throttling.
   - `GroupBehaviorDetector` adds GROUP_LOITERING / MASS_INCURSION across all persons in the frame.
7. **Drawing** — green box for tracked person, red for confirmed-armed, weapon class label and FPS overlay.
8. **IncidentRecorder** — keeps a 5-second pre-buffer; on any newly-confirmed armed ID, starts recording for 10 more seconds and writes an MP4 to `logs/incidents/`. The clip path is back-attached to the matching incident row in SQLite, or a new incident is created.
9. **StreamManager** — single JPEG-encoded "latest frame" exposed to the FastAPI MJPEG endpoint. Encoding happens on the pipeline thread, not the request thread, which is why the live feed can sustain 30+ FPS.
10. **WSManager.broadcast_weapon_alert()** — fires a `weapon_alert` WebSocket message on each *new* confirmed-armed ID transition.

### 4.2 The Backend (`backend/`)

- **`main.py`** — FastAPI app factory; CORS, lifespan, `/ws`, `/`, `/api/*`. Spawns the pipeline thread, the camera-registry threads, and a 5-second stats emitter.
- **`routes.py`** — full REST surface: auth (login/logout/register/me), alerts (list, dismiss, acknowledge, resolve, bulk-dismiss, CSV export, create), incidents (list, create, get, resolve, escalate, clip stream, CSV export), stats / system_status / system_metrics / health, analytics (24-hour & 7-day buckets, risk distribution, weapon types, top locations, totals), detection_zone CRUD, model_performance plot listing + image streaming, cameras list + per-camera MJPEG, video_feed + single-frame snapshot, users CRUD (admin only).
- **`auth.py`** — PyJWT-based: `Authorization: Bearer`, HttpOnly cookie `ts_token`, or `?token=` query param (for `<img>` tags). 24-hour expiry. `require_roles()` dependency factory enforces RBAC. Dev mode generates a random JWT secret if `JWT_SECRET` is unset; production refuses to start without it.
- **`database.py`** — SQLite with `users`, `alerts`, `incidents` tables. Indian Standard Time helper. Werkzeug-hashed passwords. Seeds admin / operator1 / viewer1 from env vars or random `secrets.token_urlsafe(12)`. Validates and clamps `risk_score` to [0, 1]; normalises `risk_level` and `status` to allowlists.
- **`ws_manager.py`** — thread-safe WebSocket broadcaster. Pipeline thread schedules sends on the asyncio loop via `asyncio.run_coroutine_threadsafe`. Convenience methods for `stats_update`, `new_alert`, `new_incident`, `weapon_alert`, `detection`.
- **`incident_recorder.py`** — rolling deque pre-buffer + per-person active recordings; flushes finished clips on a separate writer thread; back-attaches MP4 path to the latest matching incident.
- **`detection_zone.py`** — thread-safe polygon (≥ 3 points, normalised 0…1) with `cv2.pointPolygonTest`-based containment.
- **`camera_registry.py`** — multi-camera manager driven by the `CAMERAS_JSON` env var. Each camera runs its own grab thread, encodes JPEGs, and reports health.
- **`notifications.py`** — SMTP email notifier (Gmail-ready) for confirmed weapon alerts; runs in a daemon thread, fire-and-forget.

### 4.3 The Dashboard (`dashboard/`)

Stack: **Next.js 16.1.6, React 19.2.3, Tailwind 4, TypeScript 5, Lucide icons, axios** (in `package.json`, though the code actually uses `fetch`).

- **App Router structure:**
  - `(auth)/login` → `LoginScreen`
  - `(dashboard)/monitor` → `LiveMonitor` (MJPEG feed, threat timeline, recent events table, system metrics, active-alerts stack with acknowledge/resolve/dismiss, detection-zone polygon drawer)
  - `(dashboard)/incidents` → `IncidentHistory` (filter by risk/status, search, modal video player, CSV export, escalate/resolve)
  - `(dashboard)/analytics` → `Analytics` (24h bar chart, 7-day line chart, risk-distribution donut, weapon-type bars, top-locations heatbars)
  - `(dashboard)/cameras` → `CameraGrid` (per-camera health + MJPEG modal)
  - `(dashboard)/performance` → `ModelPerformance` (renders the YOLO eval PNGs)
  - `(dashboard)/users` → `UserManagement` (admin-only CRUD, separate cyan-themed UI)
- **`AuthProvider`** stores token *in memory only* (never in localStorage) plus role/username display cache; verifies via `/api/me` against the HttpOnly cookie on mount; redirects unauthenticated users to `/login`.
- **`lib/api.ts`** — HTTP client. Cookie-first, Bearer-fallback. Auto-401 → kick to login.
- **`lib/socket.ts`** — native `WebSocket` (the project moved off Socket.IO). Exponential-backoff reconnect, 25-second ping keepalive, returns `{status, ws}` from a custom hook.
- **Real-time UX** — `LiveMonitor` plays an oscillator alarm sound on each weapon_alert toast, animates a slide-in toast, mutates the document title to `"⚠ ALERT — ThreatSense-AI"`, and stores the mute preference in localStorage.

### 4.4 Data Model

```
users      (id, username, password_hash, role[admin|operator|viewer|security], status, last_active)
alerts     (id, person_id, event_type, risk_score 0..1, risk_level, timestamp IST, camera_id, location, status)
incidents  (id, title, description, event_type, location, risk_level, status,
            created_at IST, resolved_at, clip_path, person_id, camera_id)
```

JSONL audit log: one `logs/audit_YYYYMMDD.jsonl` per day with `{person_id, behaviors, risk_score, threat_level, reasons, timestamp}`.

### 4.5 Configuration Layers

Three coexisting layers, in order of precedence:

1. **Environment variables** (loaded in `config/settings.py`) — pipeline thresholds (PERSON_CONF, WEAPON_CONF, ARMED_THRESHOLD, frame skips), models, device, stream width/quality, JWT settings, SMTP, CORS origins.
2. **JSON configs** (`config/*.json`) — risk weights per behavior, threat-level thresholds, decay rate / memory expiry. Loaded by `RiskEngine`, `RiskCalculator`, `ThreatClassifier`.
3. **Hard-coded defaults** in module constants (`detection/weapon_detector.py` confidence thresholds, `behavior/behavior_analyzer.py` history windows, etc.).

---

## 5. Working Features (verified end-to-end)

| Feature | Status | Evidence |
|---|---|---|
| Trained weapon model | Working | `models/weapon_detector.pt`, `docs/evaluation_results.json` mAP50 0.892 |
| Person detection + ByteTrack | Working | `detection/person_detector.py` with `tracker="bytetrack.yaml"` |
| Multi-frame weapon confirmation | Working | `core/weapon_verifier.py` + integration tests in `tests/test_pipeline.py` |
| Risk scoring + threat classification | Working | `engine/risk_engine.py`, JSON-driven |
| Behavior fusion + pattern + group detection | Working | `engine/behavior_fusion.py`, `analytics/*` |
| Per-person decay | Working | `decay_config.json` + `RiskEngine._apply_decay` |
| Polygonal detection zone | Working | Backend CRUD + frontend canvas drawer + pipeline filter |
| Incident video clips | Working | `logs/incidents/` already contains 21 mp4s from 2026-04-27 |
| Audit JSONL trail | Working | `logs/audit_*.jsonl` from March/April 2026 present |
| FastAPI REST + JWT (HttpOnly + Bearer + ?token=) | Working | `routes.py`, `auth.py`, `tests/test_api.py` |
| WebSocket real-time push | Working | `ws_manager.py` ↔ `lib/socket.ts` with reconnect |
| MJPEG live feed | Working | `/api/video_feed`, pre-encoded JPEG bytes |
| Multi-camera registry (RTSP / webcam / file) | Working | `backend/camera_registry.py`, `CAMERAS_JSON` env |
| SQLite persistence (alerts/incidents/users) | Working | `backend/database.py` with validation + IST timestamps |
| Email alerts on weapon detection | Working when configured | `backend/notifications.py`, env-gated |
| User management CRUD with RBAC | Working | `routes.py /api/users/*`, `UserManagement.tsx` |
| Alert acknowledge / resolve / dismiss / bulk-dismiss | Working | Backend routes + `LiveMonitor` UI |
| Incident resolve / escalate | Working | Backend routes + `IncidentHistory` UI |
| CSV export (alerts + incidents) | Working | `/api/alerts/export/csv`, download links in UI |
| Analytics aggregation | Working | `/api/analytics` with 24h + 7d buckets, real DB-driven |
| Model performance plot viewer | Working | `/api/model_performance` reads `docs/evaluation/eval/*.png` |
| Login rate limiting | Working (in-memory) | `_check_rate_limit` in `routes.py` (5/min) |
| Pytest suite | Present | API, pipeline, weapon detector, risk engine tests |

---

## 6. Hardcoded, Legacy, or Inactive Code

These do not break anything but should not be mistaken for live behavior.

| Item | Why it's dead/legacy | Effect |
|---|---|---|
| `backend/websocket_events.py` | References Flask-SocketIO; `_socketio` is never initialised in the FastAPI version. `init_socketio()` has no caller. | `alerts/alert_manager.py` calls `emit_new_alert` / `emit_new_incident` which silently no-op. *The active broadcast path is `backend/ws_manager.py`*, used by `core/pipeline.py` for weapon_alerts and by `backend/main.py`'s stats emitter. So most alerts persist to DB but do not push over WS — only weapon confirmations and stats do. |
| `config/risk_weights.py` | Older Python config (`BEHAVIOR_WEIGHTS` dict). | The active path is `config/risk_weights.json`, loaded by `engine/risk_calculator.py`. The .py file is unused. |
| `backend/alert_engine.py`, `backend/detection_engine.py`, `backend/tracking_engine.py` | Clean façade classes that wrap the existing components. | Not imported by `core/pipeline.py`, which uses `PersonDetector`, `WeaponDetector`, `WeaponVerifier`, `BehaviorAnalyzer`, `RiskEngine` directly. Likely a planned refactor. |
| `backend/camera_manager.py` | Standalone `CameraManager` class with auto-reconnect. | Not used by `core/pipeline.py` (which calls `cv2.VideoCapture` directly) nor by `backend/camera_registry.py` (which has its own grab loop). Dead. |
| `dashboard/components/auth/LoginCard.tsx` | A `LoginCard` component exists separately. | The active login UI is `components/LoginScreen.tsx`, which is what `app/(auth)/login/page.tsx` actually imports. |
| `dashboard/components/Header.tsx` | Header bar component. | `(dashboard)/layout.tsx` only renders `Sidebar` + `AuthProvider`, never `Header`. There is no top bar in the rendered layout. |
| `risk_logging/event_logger.py` | Initialised by `RiskEngine` but never called after `__init__`. | Inert. |
| Default location strings | `"Main Entrance"`, `"Default Zone"`, `"CAM-01"` are hard-coded fallbacks across `database.py`, `alert_manager.py`, `notifications.py`, `routes.py`. | Anything inserted without explicit camera_id / location ends up labelled "Main Entrance / CAM-01". This is fine for single-camera demos but misleading once `CAMERAS_JSON` is configured for multiple sites. |
| Frontend API base URL | `process.env.NEXT_PUBLIC_API_URL` → defaults to `http://localhost:5000/api` in 6+ files. | Must be set at build time for any non-localhost deployment. |
| Dev JWT secret | `auth.py` generates a random secret if `JWT_SECRET` is unset (development only). | Tokens are invalidated on every restart in dev. Production refuses to boot without `JWT_SECRET` — good. |
| Admin password seeding | If `ADMIN_PASSWORD` is unset, a random `token_urlsafe(12)` is generated and printed to stdout. | First-time deployers must capture the printed password from logs. |
| `package.json` includes `axios` | Listed as a dependency. | Source code uses native `fetch` everywhere. axios is unused. |
| In-memory rate limiter | `_rate_limits: dict` in `routes.py`. | Per-process only — won't survive scaling to multiple workers. The code itself flags this with a "swap with Redis-backed slowapi" comment. |

---

## 7. Notable Engineering Decisions (worth respecting)

- **Lower-body crop instead of post-hoc filtering.** `WeaponDetector.detect_in_region` physically crops the bottom 60% of each person box before inference. This is faster and removes an entire class of false positives without fragile coordinate checks.
- **Multi-frame verification with graceful decay.** A single-frame YOLO hit never confirms a weapon; the verifier requires 3 frames at 0.62+ confidence. Misses halve confidence rather than fully resetting, so brief occlusion does not drop a confirmed-armed person.
- **Pipeline-thread JPEG encoding.** `StreamManager` pre-encodes JPEGs in the pipeline thread; the MJPEG HTTP handler just streams cached bytes. This is what allows the live feed to stay near native FPS even under load.
- **HttpOnly cookie + in-memory token + ?token= for `<img>`.** Three auth transports for three clients (browser, API, MJPEG `<img>` element). Tokens are deliberately never written to localStorage to prevent XSS theft.
- **CPU/GPU auto-tuning.** `backend/main.py` sniffs `torch.cuda.is_available()` and adjusts `imgsz`, `weapon_skip`, `risk_skip` to keep CPU fallback usable.
- **Per-(person, behavior-set) throttle.** `AlertManager` deduplicates the same alert (same person, same sorted behavior tuple) within 30 seconds, preventing dashboard spam during continuous detections.
- **IST timestamps everywhere.** `Asia/Kolkata` is wired into both the DB (`ist_now()`) and the frontend (`toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })`) — a small detail that prevents off-by-5h30m bugs in a system intended for Indian deployment.

---

## 8. Risks and Gaps

- **WebSocket alert path inconsistency.** Non-weapon alerts (zone intrusion, loitering, etc.) are written to the DB but not pushed to the dashboard live, because `backend/websocket_events.py` is dead (Flask-SocketIO leftover). The dashboard *does* still receive them on the next `getAlerts()` poll, but there is no real-time push for these. Either delete `websocket_events.py` and route everything through `ws_manager.broadcast_alert(...)`, or wire a thin shim.
- **No automated migrations.** `init_db` uses `CREATE TABLE IF NOT EXISTS` + `_ensure_columns` for ad-hoc ALTERs. Fine for now, but the schema cannot be evolved safely with existing data once it is more complex than `clip_path / person_id / camera_id` column adds.
- **Single-process state.** Rate limiter, JWT secret (dev), WS connection set, throttle cache, and per-camera state are all in-memory. Horizontal scaling is not currently feasible.
- **Hard import-time failure on missing weapon model.** `detection/weapon_detector.py` raises `FileNotFoundError` at module import, which means the entire backend won't start without `models/weapon_detector.pt`. `backend/main.py` tries to handle a missing model gracefully (`weapon_model = None`), but the import in `core/pipeline.py` happens earlier. Worth aligning.
- **No CI configured** that I can see — there are pytest tests but no `.github/workflows`, no `pre-commit`, no `Makefile`. Tests have to be run manually.
- **`frontend axios` listed but unused** — dead dependency, could be removed.
- **Header component not rendered** — dashboard pages have no top bar showing who you are / sign-out except via the sidebar's status block. Header.tsx contains exactly that UI but is never mounted.

---

## 9. How "Done" Is It?

Roughly:

- **AI core (detection + tracking + verification + risk)** — ~95% done. Trained model, integration tests, runtime artefacts all present. Tunable via env.
- **Backend REST + WebSocket + DB** — ~90% done. Routes, auth, RBAC, exports, multi-camera, video clips, analytics — all in place. The websocket_events legacy is the main rough edge.
- **Frontend dashboard** — ~85% done. Every page renders real data; the only "looks-stylistically-different" page is `UserManagement.tsx` (cyan terminal aesthetic vs. the rest of the panels using CSS variables) — likely a leftover from an earlier design pass. Header bar isn't mounted.
- **DevOps / deployment** — ~30% done. No Dockerfile, no docker-compose, no CI. Works as `python -m backend.main` + `npm run dev`.
- **Documentation** — Partial. `docs/architecture.md` and `docs/architecture_report.md` exist. Frontend has the default `create-next-app` README only. There is no top-level project README explaining how to set up.
- **Tests** — pytest suite covers API auth, alerts, incidents, DB validation, BehaviorAnalyzer, WeaponVerifier, and the risk engine. No frontend tests.

---

## 10. Summary in One Paragraph

ThreatSense AI is a substantively-built, mostly-finished real-time weapon-detection product: a YOLOv8 pipeline (with a custom-trained gun/knife model at mAP50 0.892) feeding a FastAPI backend that persists alerts and incidents to SQLite, captures evidence MP4s with a rolling pre/post buffer, broadcasts updates over native WebSocket, and is consumed by a Next.js 16 / React 19 dashboard with live MJPEG, polygonal detection zones, audit-grade analytics, and admin-only user management. The hard problems (multi-frame verification, behavior-based risk scoring with decay and group/pattern detection, RBAC with HttpOnly cookies, multi-camera support) are solved. The remaining work is mostly cleanup: drop the dead Flask-SocketIO shim and route non-weapon alerts through the new `ws_manager`, delete the unused façades and `axios`, mount the Header, unify the user-management styling with the rest of the dashboard, and add a Dockerfile, README, and CI pipeline. As-is, the system is operable today on a single workstation against a webcam or RTSP stream.

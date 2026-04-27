# ThreatSense-AI Technical Architecture Report

This document provides a complete technical analysis of the ThreatSense-AI surveillance system, detailing its structure, execution flow, models, data loops, and production readiness gaps.

---

## 1. Project Structure

The repository follows a modular, monolithic layout:

```text
ThreatSense-AI/
├── backend/          # Flask backend API (app.py, routes.py, database.py)
├── core/             # Central pipeline execution (pipeline.py, stream_manager.py)
├── detection/        # YOLO and ByteTrack wrappers (person_detector.py, weapon_detector.py)
├── tracking/         # (integrated logic within detection modules)
├── behavior/         # Behavior analysis (loitering, zone intrusion, crowds)
├── engine/           # Risk calculation and threat scoring rules
├── alerts/           # Alert prioritization and DB persistence mapping
├── models/           # Local storage for PyTorch `.pt` model weights
├── dashboard/        # Next.js React frontend application
└── main.py           # CLI entry point for standalone camera testing
```

**Key Modules:**
* [core/pipeline.py](file:///e:/Pick-me-Programmers/core/pipeline.py): The heart of the system. Orchestrates the camera loop, AI inference, and risk delegation.
* [backend/app.py](file:///e:/Pick-me-Programmers/backend/app.py): The REST API server. Crucially, it spins up the [pipeline.py](file:///e:/Pick-me-Programmers/test_pipeline.py) loop in a background thread on launch.
* `dashboard/`: Consumes the backend API and video feed to display a security command center.

---

## 2. Pipeline Flow

The AI pipeline executes a synchronous, linear loop per video frame. It is invoked either natively via [main.py](file:///e:/Pick-me-Programmers/main.py) or as a background Daemon thread via [backend/app.py](file:///e:/Pick-me-Programmers/backend/app.py).

**Execution Trace (`core/pipeline.py -> SurveillancePipeline.run`):**

1. **Camera Input:** Frame captured via `cv2.VideoCapture.read()`.
2. **Detection & Tracking:** Frame passed to `PersonDetector.track()`, running YOLO + ByteTrack to detect humans and assign stable `track_id`s.
3. **Targeted Detection:** Cropped bounding boxes for each person are passed to `WeaponDetector.detect_in_region()`. To save processing, this only occurs every `N` frames.
4. **Verification:** `WeaponVerifier` checks consecutive frames to confirm weapon presence (preventing 1-frame glitches).
5. **Behavior Analysis:** [BehaviorAnalyzer](file:///e:/Pick-me-Programmers/behavior/behavior_analyzer.py#11-193) maps historical `track_id` coordinates to calculate speed, loitering time, and zone intrusion.
6. **Risk Engine:** [RiskEngine](file:///e:/Pick-me-Programmers/engine/risk_engine.py#15-145) compiles behavior flags + weapon flags into a normalized threat score.
7. **Outputs:** 
   * Local Video Overlay: Bounds and scores drawn using `cv2.rectangle/putText`. 
   * Stream Output: Raw drawn frames exported to `stream_manager`.
   * Alerts: Rule thresholds trigger [AlertManager](file:///e:/Pick-me-Programmers/alerts/alert_manager.py#54-173) to store events in SQLite.

---

## 3. Model Usage

The system heavily relies on the Ultralytics YOLOv8 architecture:

* **Person Detection / Tracking:** [models/yolov8m_fixed.pt](file:///e:/Pick-me-Programmers/models/yolov8m_fixed.pt) (Medium model, ~48MB). Tracks people across frames using ByteTrack logic baked into the wrapper.
* **Weapon Detection:** [models/weapon_detector_fixed.pt](file:///e:/Pick-me-Programmers/models/weapon_detector_fixed.pt) (Custom trained Nano/Small layer, ~5.6MB). Runs strictly on cropped regions inside person bounding boxes.
* **CPU Optimization Fallback:** [yolo26n.pt](file:///e:/Pick-me-Programmers/yolo26n.pt) (Nano model, ~5MB) used when `--cpu-optimized` is enabled.

**Inference Environment:**
* Loaded natively into VRAM via PyTorch (`device="cuda:0"`).
* Falls back to `device="cpu"` if CUDA is unavailable, causing severe inference penalties (up to 15s per frame on `yolov8m`).
* Uses Half Precision (`half=True`) by default when running on GPU.

---

## 4. Camera System

**Capture Mechanism:** 
Controlled via OpenCV (`cv2.VideoCapture`). Explicitly reduces buffers (`cv2.CAP_PROP_BUFFERSIZE, 1`) to drop old frames and maintain real-time low latency.

**Streaming System:** 
Operates via **MJPEG** (Motion JPEG) through Flask.
[core/stream_manager.py](file:///e:/Pick-me-Programmers/core/stream_manager.py) holds a thread-safe singleton lock containing the latest processed `numpy.ndarray` frame. 
When the frontend fetches `/api/video_feed`, Flask yields a constant stream of JPEG bytes using `multipart/x-mixed-replace`.

**Current System Issues:**
* **Blocking Loops:** If `cv2` or `PyTorch` blocks, the entire stream halts. The MJPEG backend repeats the same frozen frame or falls back to snapshot polling, causing "0 FPS" freezes.
* **Single Thread Pipeline:** The camera capture, ML inference, and DB writing all happen sequentially in one giant `while` loop.

---

## 5. Backend API

The system uses standard **Flask REST Routes** secured by PyJWT. (WebSockets are **not** utilized).

**Endpoints ([backend/routes.py](file:///e:/Pick-me-Programmers/backend/routes.py)):**
* **Auth**: `/api/login`, `/api/register`, `/api/me`.
* **Telemetry**: `/api/stats` (Fetches FPS, total tracked entities, active incidents), `/api/system_status`.
* **Alerts/Incidents**: `/api/alerts`, `/api/alerts/:id/resolve`, `/api/incidents` (Fetch + state mutation updates SQLite DB).
* **Video Output**: `/api/video_feed` (HTTP MJPEG Stream), `/api/frame` (Base64 JPEG Snapshot).

---

## 6. Data Flow

* **Detections:** Handled completely in VRAM/RAM during the pipeline loop.
* **Alerts:** Once [RiskEngine](file:///e:/Pick-me-Programmers/engine/risk_engine.py#15-145) calculates a high threat level, [AlertManager](file:///e:/Pick-me-Programmers/alerts/alert_manager.py#54-173) inserts it synchronously into SQLite ([backend/database.py](file:///e:/Pick-me-Programmers/backend/database.py)), mapping the JSON dictionary to tables.
* **Frontend:** The React dashboard hits `/api/alerts` and `/api/stats` every 15 seconds to sync data. 

**Alert JSON Schema Example:**
```json
{
  "id": 104,
  "person_id": "12",
  "event_type": "Weapon Detected",
  "risk_score": 0.95,
  "risk_level": "critical",
  "timestamp": "2026-03-21T13:45:00",
  "camera_id": "CAM-01",
  "location": "Main Entrance",
  "status": "Active"
}
```

---

## 7. Frontend Dashboard

The `dashboard/` directory contains a Next.js 16.x application using React 19.

* **UI/UX Strategy:** Dark-mode, neon-heavy tactical layout driven by Tailwind CSS ([globals.css](file:///e:/Pick-me-Programmers/dashboard/app/globals.css)).
* **Components:** [LiveMonitor.tsx](file:///e:/Pick-me-Programmers/dashboard/components/LiveMonitor.tsx) holds the video feed and "Threat Radar". [IncidentHistory.tsx](file:///e:/Pick-me-Programmers/dashboard/components/IncidentHistory.tsx) holds investigative tables.
* **Data Hooks:** It natively polls the REST API [getAlerts()](file:///e:/Pick-me-Programmers/dashboard/lib/api.ts#66-71) and [getStats()](file:///e:/Pick-me-Programmers/dashboard/lib/api.ts#82-86) every **15000ms** via `useEffect` loops.
* **Real vs Hardcoded:** The data is completely real (pulled from SQLite). However, `camera_id` ("CAM-01") and `location` ("Main Entrance") strings are currently hardcoded placeholders injected by the Pipeline before database entry.

---

## 8. Current Issues

* **Architecture Bottleneck:** The primary `cap.read() -> infer -> write_db` loop is synchronous. Network latency writing an alert to the database directly pauses the camera feed.
* **Heavy CPU Stalls:** The default Medium YOLOv8 model will freeze non-GPU laptops. Requires strict toggling to Nano variants.
* **Rest Polling Latency:** A 15-second HTTP polling loop on the frontend means critical gun/weapon alerts might not appear on the dashboard UI for up to 14.9 seconds after detection.
* **SQLite Locking:** SQLite does not support highly concurrent writes lock-free. Extensive threat logs or concurrent users will crash the Flask process with `database is locked`.
* **Log Spam / Loitering:** A person standing still for ~60 frames continuously creates "Loitering" flag injections, muddying the threat pool.

---

## 9. Performance Analysis

* **Expected FPS:**
  * **CUDA/RTX GPUs:** 30+ FPS, strictly bottlenecked by the camera hardware framerate limit.
  * **CPUs:** 0.1 FPS (Medium Model) -> 5 FPS (Nano Model).
* **Latency Sources:** 
  1. MJPEG byte conversion (`cv2.imencode`).
  2. Python Thread switching (Flask taking priority over the Daemon thread).
  3. Synchronous SQLite writes inside [RiskEngine](file:///e:/Pick-me-Programmers/engine/risk_engine.py#15-145).
* **Network Overhead:** Multipart HTTP polling for video is heavy on bandwidth compared to modern protocols like WebRTC.

---

## 10. Production Readiness

**Verdict:** Currently essentially an advanced Prototype/MVP. Not production-ready for multi-camera deployments.

* **Stability:** Low. A single camera disconnect throws an exception looping the pipeline until manual restart.
* **Scalability:** Very Low. It cannot handle >1 camera feed efficiently because the Python GIL limits concurrent YOLO inferences, and Flask background threads do not scale.
* **Reliability:** Medium. State history is cleared if the app restarts. Alerts are persisted properly, but the lack of WebSockets means delayed human response times.

---

## 11. Improvement Roadmap

**Phase 1 — Critical Fixes (Immediate)**
* Refactor Dashboard communication from 15s REST Polling to **Socket.io WebSockets** for instant <100ms alerts.
* Decouple database writes from the main pipeline thread (implement a non-blocking `queue` system for [AlertManager](file:///e:/Pick-me-Programmers/alerts/alert_manager.py#54-173)).

**Phase 2 — System Stability (Short-term)**
* Replace SQLite with PostgreSQL.
* Fix hardcoded Location labels mapping (allow API endpoints to map IPs/Streams to Camera labels).
* Offload the video frame broadcasting to an asynchronous message broker, preventing the PyTorch pipeline from slowing down when multiple viewers open the MJPEG stream.

**Phase 3 — Enterprise Scaling (Long-term)**
* Move [SurveillancePipeline](file:///e:/Pick-me-Programmers/core/pipeline.py#57-434) into isolated Celery workers or independent Docker processes, separating the Flask web server completely from PyTorch execution.
* Upgrade the MJPEG endpoint to WebRTC for high-framerate, multi-channel video multiplexing.

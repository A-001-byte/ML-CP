"""
pipeline.py
───────────
Real-time surveillance pipeline for ThreatSense-AI.

Flow:
    webcam frame
        → PersonDetector + ByteTrack  → tracked persons (NMS-deduped)
        → WeaponDetector (per-crop)   → raw weapon detections
        → WeaponVerifier              → confirmed_armed_ids
        → BehaviorAnalyzer + RiskEngine (backend alerts only)
        → _draw: GREEN = safe, RED = weapon confirmed by verifier
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Optional
import torch

import cv2
import numpy as np

from detection.person_detector import PersonDetector
from detection.weapon_detector import WeaponDetector
from core.weapon_verifier import WeaponVerifier
from core.stream_manager import stream_manager
from behavior.behavior_analyzer import BehaviorAnalyzer
from engine.risk_engine import RiskEngine
from config.settings import settings as _cfg

try:
    from backend.incident_recorder import incident_recorder
except Exception:
    incident_recorder = None

try:
    from backend.ws_manager import ws_manager
except Exception:
    ws_manager = None

try:
    from backend.detection_zone import detection_zone
except Exception:
    detection_zone = None

# ── Drawing constants ────────────────────────────────────────────────────────
COLOR_PERSON = (0, 255, 0)      # green  — normal, no weapon
COLOR_ARMED  = (0, 0, 255)      # red    — confirmed weapon
COLOR_WEAPON = (0, 0, 255)      # red    — weapon bounding box label
COLOR_FPS    = (0, 255, 255)    # yellow
FONT         = cv2.FONT_HERSHEY_SIMPLEX
THICKNESS    = 2

# All thresholds pulled from config/settings.py — override via env vars.
WEAPON_SKIP       = _cfg.pipeline.weapon_skip
WEAPON_BOX_PERSIST = _cfg.pipeline.weapon_box_persist
PERSON_NMS_IOU    = 0.55


class SurveillancePipeline:
    """Orchestrate person tracking + weapon detection on a live video source."""

    def __init__(
        self,
        source: int | str = 0,
        person_conf: float = 0.4,
        weapon_conf: float = 0.3,
        armed_threshold: float = 0.62,
        persist_frames: int = WEAPON_BOX_PERSIST,
        person_model: str = "yolov8m.pt",
        weapon_model: Optional[str] = None,
        device: int | str | None = None,
        headless: bool = False,
        weapon_skip: int = WEAPON_SKIP,
        risk_skip: int = 3,
        imgsz: int = 416,
        fullframe_scan_skip: int = 0,
    ) -> None:
        self.source         = source
        self.person_conf    = person_conf
        self.weapon_conf    = weapon_conf
        self.armed_threshold = armed_threshold
        self.persist_frames = persist_frames
        self.headless       = headless
        self.risk_skip      = max(1, int(risk_skip))
        self.weapon_skip    = max(1, int(weapon_skip))
        self.fullframe_scan_skip = fullframe_scan_skip
        self.imgsz          = imgsz
        self._frame_count   = 0
        self._last_tracked: list = []
        self._stop_requested = False   # set True to break the run() loop cleanly
        self._prev_confirmed_ids: set[int] = set()

        # GPU / CPU setup
        self.device = device or "cuda:0"
        if isinstance(self.device, str) and self.device.startswith("cuda"):
            if not torch.cuda.is_available():
                print("[pipeline] CUDA not available — falling back to CPU")
                self.device = "cpu"
        self.is_cpu     = str(self.device) == "cpu"
        self._use_half  = not self.is_cpu

        self.person_skip = int(os.environ.get(
            "PIPELINE_PERSON_SKIP", "3" if self.is_cpu else "1"
        ))

        # ── Load models ───────────────────────────────────────────────
        print(f"[pipeline] Loading person detector at {imgsz}px …")
        self.person_det = PersonDetector(
            model_path=person_model,
            device=self.device,
            imgsz=imgsz,
            half=self._use_half,
        )

        print(f"[pipeline] Loading weapon detector at {imgsz}px …")
        weapon_kwargs: dict = {"device": self.device, "imgsz": imgsz, "half": self._use_half}
        if weapon_model is not None:
            weapon_kwargs["model_path"] = weapon_model
        self.weapon_det = WeaponDetector(**weapon_kwargs)

        # ── WeaponVerifier ────────────────────────────────────────────
        # Confirms weapon after >= 3 detection frames with avg_conf >= 0.62.
        # decay_after=5: needs 5 consecutive missed detection cycles before
        # evidence starts clearing — keeps person armed while weapon is visible.
        self.weapon_verifier = WeaponVerifier(
            min_frames=_cfg.pipeline.verifier_min_frames,
            min_avg_conf=_cfg.pipeline.verifier_min_conf,
            decay_after=_cfg.pipeline.verifier_decay_after,
        )

        # ── Behavior / Risk (backend alerts only) ─────────────────────
        print("[pipeline] Initializing BehaviorAnalyzer …")
        self.behavior_analyzer = BehaviorAnalyzer()
        print("[pipeline] Initializing RiskEngine …")
        self.risk_engine = RiskEngine()

        # ── State ─────────────────────────────────────────────────────
        self._fps_window: deque[float] = deque(maxlen=30)
        # tid → {"weapons": [...], "ttl": int}  — weapon box coordinates only
        self._weapon_box_buffer: dict[int, dict] = {}
        # Backend risk cache (does not affect display color)
        self._risk_decisions: dict[int, dict] = {}

        if self.is_cpu:
            print(f"[pipeline] CPU mode — person_skip={self.person_skip}, "
                  f"weapon_skip={self.weapon_skip}, half=False")

    # ── NMS dedup on person tracks ───────────────────────────────────

    @staticmethod
    def _dedup_tracks(tracked: list, iou_thresh: float = PERSON_NMS_IOU) -> list:
        """Remove overlapping ByteTrack duplicates (same person, two IDs).

        Sorts by confidence descending, then suppresses any track whose box
        overlaps an already-kept track above `iou_thresh`.
        """
        if len(tracked) <= 1:
            return tracked

        sorted_tracks = sorted(tracked, key=lambda t: t[4], reverse=True)
        kept: list = []

        for t in sorted_tracks:
            tx1, ty1, tx2, ty2 = t[0], t[1], t[2], t[3]
            dominated = False
            for k in kept:
                kx1, ky1, kx2, ky2 = k[0], k[1], k[2], k[3]
                ix1 = max(tx1, kx1); iy1 = max(ty1, ky1)
                ix2 = min(tx2, kx2); iy2 = min(ty2, ky2)
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                if inter == 0:
                    continue
                area_t = max(1, (tx2 - tx1) * (ty2 - ty1))
                area_k = max(1, (kx2 - kx1) * (ky2 - ky1))
                iou = inter / (area_t + area_k - inter)
                if iou > iou_thresh:
                    dominated = True
                    break
            if not dominated:
                kept.append(t)

        return kept

    # ── Main loop ────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the live surveillance loop.  Press q to quit."""
        backoff = 3
        is_file_source = isinstance(self.source, str) and os.path.isfile(self.source)

        if not self.headless:
            cv2.namedWindow("ThreatSense-AI", cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)

        def open_capture():
            cap = cv2.VideoCapture(self.source)
            if cap.isOpened():
                return cap
            cap.release()
            cap = cv2.VideoCapture(self.source, cv2.CAP_DSHOW)
            return cap if cap.isOpened() else None

        while True:
            if self._stop_requested:
                print("[pipeline] Stop requested — exiting.")
                return

            cap = open_capture()
            if cap is None:
                print(f"[pipeline] Cannot open source {self.source}. Retry in {backoff}s…")
                time.sleep(backoff)
                continue

            if self.is_cpu:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            else:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps_src = cap.get(cv2.CAP_PROP_FPS)
            source_label = "Video file" if is_file_source else "Camera"
            print(f"[pipeline] {source_label}: {w}x{h} @ {fps_src} FPS  (press q to quit)")

            try:
                while True:
                    t0 = time.perf_counter()

                    ret, frame = cap.read()
                    if not ret:
                        if is_file_source:
                            if incident_recorder is not None and hasattr(incident_recorder, "flush_all"):
                                incident_recorder.flush_all()
                            print("[pipeline] Reached end of video file.")
                            return
                        print("[pipeline] Frame grab failed — reinitialising…")
                        break

                    if not is_file_source:
                        frame = cv2.flip(frame, 1)

                    # ── 1. Person detection + tracking ─────────────────
                    if self._frame_count % self.person_skip == 0 or not self._last_tracked:
                        raw_tracked = self.person_det.track(frame, conf=self.person_conf)
                        # Remove duplicate tracks (same person, two IDs from ByteTrack)
                        self._last_tracked = self._dedup_tracks(raw_tracked)

                    tracked = self._last_tracked

                    # ── 2. Build analyzer input + weapon detection ──────
                    active_ids: set[int]        = set()
                    all_weapon_dets: list       = []
                    tracked_for_analyzer: list  = []
                    # Collect per-person weapon hits this detection cycle
                    new_weapon_hits: dict[int, list] = {}

                    run_weapon = (self._frame_count % self.weapon_skip == 0)

                    for px1, py1, px2, py2, _, tid in tracked:
                        active_ids.add(tid)
                        tracked_for_analyzer.append({"id": tid, "bbox": [px1, py1, px2, py2]})

                        if run_weapon:
                            hits = self.weapon_det.detect_in_region(
                                frame, (px1, py1, px2, py2), conf=self.weapon_conf,
                            )
                            hits = self._filter_zone_hits(frame, hits)
                            if hits:
                                new_weapon_hits[tid] = hits
                                all_weapon_dets.extend(hits)

                    # Optional full-frame scan
                    if self.fullframe_scan_skip > 0 and \
                            self._frame_count % self.fullframe_scan_skip == 0:
                        full_hits = self.weapon_det.detect_full_frame(frame, conf=self.weapon_conf)
                        all_weapon_dets.extend(self._filter_zone_hits(frame, full_hits))

                    # ── 3. WeaponVerifier — single source of truth ──────
                    if run_weapon:
                        confirmed_armed_ids = self.weapon_verifier.update(
                            all_weapon_dets, tracked_for_analyzer
                        )
                    else:
                        confirmed_armed_ids = self.weapon_verifier.get_confirmed_ids()

                    self._broadcast_new_weapon_confirmations(
                        set(confirmed_armed_ids),
                        new_weapon_hits,
                    )

                    # ── 4. Update weapon box coordinate buffer ──────────
                    # Buffer only stores coordinates for display — armed state
                    # comes exclusively from confirmed_armed_ids above.
                    if run_weapon:
                        for tid, hits in new_weapon_hits.items():
                            self._weapon_box_buffer[tid] = {
                                "weapons": hits,
                                "ttl": self.persist_frames,
                            }
                        # Decay buffer for tracks that had no hits this cycle
                        for tid in list(self._weapon_box_buffer):
                            if tid not in new_weapon_hits:
                                self._weapon_box_buffer[tid]["ttl"] -= 1
                                if self._weapon_box_buffer[tid]["ttl"] <= 0:
                                    del self._weapon_box_buffer[tid]

                    # Remove buffer entries for disappeared tracks
                    for tid in [t for t in self._weapon_box_buffer if t not in active_ids]:
                        del self._weapon_box_buffer[tid]

                    # ── 5. Build person_states for drawing ──────────────
                    person_states: list[dict] = []
                    for px1, py1, px2, py2, _, tid in tracked:
                        armed = tid in confirmed_armed_ids
                        # Show weapon boxes only while this person is confirmed armed
                        buf = self._weapon_box_buffer.get(tid)
                        shown_weapons = buf["weapons"] if (armed and buf) else []
                        person_states.append({
                            "bbox":     (px1, py1, px2, py2),
                            "track_id": tid,
                            "armed":    armed,
                            "weapons":  shown_weapons,
                        })

                    # ── 6. Behavior + Risk (backend alerts only) ────────
                    for p in tracked_for_analyzer:
                        self.behavior_analyzer.set_weapon_flag(
                            p["id"], p["id"] in confirmed_armed_ids
                        )

                    behavior_results = self.behavior_analyzer.analyze(tracked_for_analyzer)

                    if behavior_results and self._frame_count % self.risk_skip == 0:
                        for rd in self.risk_engine.process_frame(behavior_results):
                            self._risk_decisions[rd["person_id"]] = rd

                    # Prune stale risk decisions
                    for tid in [t for t in self._risk_decisions if t not in active_ids]:
                        del self._risk_decisions[tid]

                    # ── 7. Draw ─────────────────────────────────────────
                    self._draw(frame, person_states)
                    self._draw_detection_zone(frame)

                    # ── 8. FPS overlay ──────────────────────────────────
                    elapsed = time.perf_counter() - t0
                    self._fps_window.append(elapsed)
                    fps = len(self._fps_window) / sum(self._fps_window)
                    cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30),
                                FONT, 1.0, COLOR_FPS, 2)

                    # ── 9. Incident recording ───────────────────────────
                    if incident_recorder is not None:
                        incident_recorder.push_frame(frame)
                        for tid in confirmed_armed_ids:
                            wclass = "weapon"
                            buf = self._weapon_box_buffer.get(tid)
                            if buf and buf.get("weapons"):
                                wclass = buf["weapons"][0][5]  # class name from tuple
                            incident_recorder.trigger(tid, wclass)
                        incident_recorder.tick()

                    # ── 10. Stream + display ────────────────────────────
                    stream_manager.update_frame(frame)
                    self._frame_count += 1

                    if not self.headless:
                        cv2.imshow("ThreatSense-AI", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            raise KeyboardInterrupt

            except KeyboardInterrupt:
                print("[pipeline] Stopped.")
                cap.release()
                cv2.destroyAllWindows()
                return

            except Exception as e:
                print(f"[pipeline] Error: {e}. Restarting in {backoff}s…")

            finally:
                cap.release()
                cv2.destroyAllWindows()
                time.sleep(backoff)

    # ── Drawing ──────────────────────────────────────────────────────

    @staticmethod
    def _draw(frame: np.ndarray, person_states: list[dict]) -> None:
        """
        Draw person and weapon overlays.

        Rules (simple and intentional):
          GREEN box  = person detected, no confirmed weapon
          RED box    = weapon confirmed by WeaponVerifier for this person
          RED label  = weapon class + confidence on the weapon bounding box

        The RiskEngine / BehaviorAnalyzer do NOT affect box colour — motion
        alone must never trigger a red box.
        """
        for ps in person_states:
            x1, y1, x2, y2 = ps["bbox"]
            tid = ps["track_id"]

            # Color is purely weapon-driven
            color = COLOR_ARMED if ps["armed"] else COLOR_PERSON
            label = f"Armed ID {tid}" if ps["armed"] else f"ID {tid}"

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, THICKNESS)
            cv2.putText(frame, label, (x1, max(y1 - 8, 0)),
                        FONT, 0.6, color, 1)

            # Weapon bounding boxes (only shown when person is confirmed armed)
            for wx1, wy1, wx2, wy2, wconf, wname in ps["weapons"]:
                cv2.rectangle(frame, (wx1, wy1), (wx2, wy2), COLOR_WEAPON, THICKNESS)
                cv2.putText(frame, f"{wname} {wconf:.2f}",
                            (wx1, max(wy1 - 8, 0)), FONT, 0.6, COLOR_WEAPON, 1)

    @staticmethod
    def _filter_zone_hits(frame: np.ndarray, hits: list) -> list:
        if detection_zone is None or not hits:
            return hits
        return [
            hit for hit in hits
            if detection_zone.contains_box_center(
                (int(hit[0]), int(hit[1]), int(hit[2]), int(hit[3])),
                frame.shape,
            )
        ]

    @staticmethod
    def _draw_detection_zone(frame: np.ndarray) -> None:
        if detection_zone is None:
            return
        polygon = detection_zone.get()
        if len(polygon) < 3:
            return

        height, width = frame.shape[:2]
        pts = np.array(
            [(int(p["x"] * width), int(p["y"] * height)) for p in polygon],
            dtype=np.int32,
        )
        cv2.polylines(frame, [pts], isClosed=True, color=(255, 180, 0), thickness=2)
        cv2.putText(frame, "Detection Zone", tuple(pts[0]), FONT, 0.55, (255, 180, 0), 1)

    def _broadcast_new_weapon_confirmations(
        self,
        confirmed_armed_ids: set[int],
        new_weapon_hits: dict[int, list],
    ) -> None:
        if ws_manager is None:
            self._prev_confirmed_ids = confirmed_armed_ids
            return

        for tid in confirmed_armed_ids - self._prev_confirmed_ids:
            hits = new_weapon_hits.get(tid)
            if not hits:
                buf = self._weapon_box_buffer.get(tid)
                hits = buf.get("weapons", []) if buf else []

            weapon_class = "weapon"
            confidence = 0.0
            if hits:
                weapon_class = str(hits[0][5])
                confidence = sum(float(hit[4]) for hit in hits) / len(hits)

            ws_manager.broadcast_weapon_alert(tid, weapon_class, confidence)

        self._prev_confirmed_ids = confirmed_armed_ids

"""
incident_recorder.py
────────────────────
Records short video clips around weapon-detection events for evidence
preservation.  Runs entirely in a background thread — no impact on the
main pipeline throughput.

Design:
  - A rolling pre-buffer keeps the last PRE_SECONDS of frames in memory.
  - When trigger() is called, recording starts immediately using the
    buffered frames + POST_SECONDS of new frames.
  - Output: MP4 files in  logs/incidents/<YYYYMMDD_HHMMSS_<person_id>>.mp4

Usage:
    recorder = IncidentRecorder(fps=30)
    recorder.push_frame(frame)   # called every pipeline frame
    recorder.trigger(person_id, weapon_class)  # called on weapon confirm
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
import contextlib

import cv2
import numpy as np

_log = logging.getLogger("backend.recorder")

IST = timezone(timedelta(hours=5, minutes=30))
INCIDENTS_DIR = Path(__file__).resolve().parent.parent / "logs" / "incidents"

PRE_SECONDS  = 5    # seconds of footage saved BEFORE the trigger
POST_SECONDS = 10   # seconds of footage saved AFTER the trigger
MAX_FPS      = 15   # write at 15fps to keep file sizes manageable


class IncidentRecorder:
    """Thread-safe rolling-buffer video recorder."""

    def __init__(self, fps: float = 30.0) -> None:
        self._fps        = fps
        self._buf_size   = int(PRE_SECONDS * fps)
        self._buffer: deque[np.ndarray] = deque(maxlen=self._buf_size)
        self._lock       = threading.Lock()
        self._active: dict[str, dict] = {}   # person_id → recording state
        INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)

    def push_frame(self, frame: np.ndarray) -> None:
        """Call once per pipeline frame to keep the pre-buffer fresh."""
        if frame is None:
            return
        with self._lock:
            self._buffer.append(frame.copy())
            # Feed any active recordings
            for state in list(self._active.values()):
                state["frames"].append(frame.copy())

    def trigger(self, person_id: str | int, weapon_class: str = "weapon") -> None:
        """Start recording for `person_id`.  No-op if already recording."""
        pid = str(person_id)
        with self._lock:
            if pid in self._active:
                return   # already recording this person
            pre_frames = list(self._buffer)
            self._active[pid] = {
                "frames":        pre_frames,
                "weapon_class":  weapon_class,
                "started_at":    time.time(),
                "target_frames": int((PRE_SECONDS + POST_SECONDS) * self._fps),
            }
        _log.info("[recorder] Incident recording started for person %s (%s)", pid, weapon_class)

    def _flush_finished(self) -> None:
        """Write out any recordings that have collected enough frames."""
        with self._lock:
            finished = [
                pid for pid, state in self._active.items()
                if len(state["frames"]) >= state["target_frames"]
            ]
            to_write = {pid: self._active.pop(pid) for pid in finished}

        for pid, state in to_write.items():
            threading.Thread(
                target=self._write_clip,
                args=(pid, state["frames"], state["weapon_class"]),
                daemon=True,
            ).start()

    def flush_all(self) -> None:
        """Synchronously write every active recording, used when a file source ends."""
        with self._lock:
            to_write = dict(self._active)
            self._active.clear()

        for pid, state in to_write.items():
            self._write_clip(pid, state["frames"], state["weapon_class"])

    def _write_clip(
        self, person_id: str, frames: list[np.ndarray], weapon_class: str
    ) -> None:
        if not frames:
            return
        ts    = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        fname = INCIDENTS_DIR / f"{ts}_person{person_id}_{weapon_class}.mp4"

        h, w  = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out    = cv2.VideoWriter(str(fname), fourcc, MAX_FPS, (w, h))

        # Subsample to MAX_FPS if pipeline fps is higher
        step = max(1, int(self._fps / MAX_FPS))
        for frame in frames[::step]:
            out.write(frame)
        out.release()

        size_kb = fname.stat().st_size // 1024
        _log.info("[recorder] Saved incident clip: %s (%d KB)", fname.name, size_kb)
        self._attach_clip_to_incident(person_id, weapon_class, fname)

    def _attach_clip_to_incident(self, person_id: str, weapon_class: str, clip_path: Path) -> None:
        """Attach the clip to the latest matching incident, or create one."""
        try:
            from backend.database import add_incident, get_db_connection

            rel_path = str(clip_path.relative_to(INCIDENTS_DIR.parent.parent))
            with contextlib.closing(get_db_connection()) as conn:
                row = conn.execute(
                    """
                    SELECT id FROM incidents
                    WHERE clip_path IS NULL
                      AND (person_id = ? OR title LIKE ? OR description LIKE ?)
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (person_id, f"%ID {person_id}%", f"%{person_id}%"),
                ).fetchone()

                if row:
                    conn.execute(
                        "UPDATE incidents SET clip_path = ?, person_id = COALESCE(person_id, ?) WHERE id = ?",
                        (rel_path, person_id, row["id"]),
                    )
                    conn.commit()
                    return

            add_incident(
                title=f"Weapon Detected: ID {person_id}",
                description=f"Automated incident clip captured for person {person_id}.",
                event_type="Weapon Detected",
                location="Default Zone",
                risk_level="high",
                status="open",
                clip_path=rel_path,
                person_id=person_id,
            )
        except Exception:
            _log.exception("[recorder] Failed to attach clip to incident")

    def tick(self) -> None:
        """Call periodically (e.g. every pipeline frame) to flush finished clips."""
        self._flush_finished()


# Module-level singleton
incident_recorder = IncidentRecorder()

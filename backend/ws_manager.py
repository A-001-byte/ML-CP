"""
ws_manager.py
─────────────
Thread-safe WebSocket connection manager for FastAPI.

The AI pipeline runs in a background thread and calls broadcast methods
here.  This module safely queues messages and dispatches them to all
connected WebSocket clients from the asyncio event loop.

Message protocol (JSON):
    { "type": "stats_update", "data": { ... } }
    { "type": "new_alert",    "data": { ... } }
    { "type": "new_incident", "data": { ... } }
    { "type": "weapon_alert", "data": { ... } }
    { "type": "detection",    "data": { ... } }
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Set

from fastapi import WebSocket

_log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


class WSManager:
    """Manage active WebSocket connections and broadcast messages."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── connection lifecycle ─────────────────────────────────────────

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Register the running asyncio event loop (called once at startup)."""
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        _log.info("[ws] Client connected — total: %d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        _log.info("[ws] Client disconnected — total: %d", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    # ── async broadcast (called from async context) ──────────────────

    async def _broadcast_async(self, message: dict) -> None:
        """Send a JSON message to all connected clients (async)."""
        if not self._connections:
            return

        payload = json.dumps(message)
        stale: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)

        for ws in stale:
            self._connections.discard(ws)

    # ── thread-safe broadcast (called from pipeline thread) ──────────

    def broadcast(self, msg_type: str, data: dict) -> None:
        """Thread-safe broadcast — schedules send on the asyncio loop."""
        message = {"type": msg_type, "data": data}

        if self._loop is None or self._loop.is_closed():
            return
        if not self._connections:
            return

        asyncio.run_coroutine_threadsafe(
            self._broadcast_async(message),
            self._loop,
        )

    # ── convenience methods ──────────────────────────────────────────

    def broadcast_stats(self, stats: dict) -> None:
        self.broadcast("stats_update", stats)

    def broadcast_alert(self, alert: dict) -> None:
        self.broadcast("new_alert", alert)

    def broadcast_incident(self, incident: dict) -> None:
        self.broadcast("new_incident", incident)

    def broadcast_detection(self, detection: dict) -> None:
        self.broadcast("detection", detection)

    def broadcast_weapon_alert(
        self,
        person_id: int | str,
        weapon_class: str,
        confidence: float,
        location: str = "Main Entrance",
    ) -> None:
        self.broadcast("weapon_alert", {
            "person_id": person_id,
            "weapon_class": weapon_class,
            "confidence": round(float(confidence), 3),
            "location": location,
            "timestamp": datetime.now(IST).strftime("%H:%M:%S"),
        })


# Module-level singleton
ws_manager = WSManager()

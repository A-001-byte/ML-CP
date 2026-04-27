/**
 * Native WebSocket client with auto-reconnect for the ThreatSense AI dashboard.
 *
 * Replaces Socket.IO. Connects to ws://localhost:5000/ws and provides
 * a React hook (useWebSocket) for consuming real-time events.
 *
 * Message protocol (JSON from server):
 *   { "type": "stats_update", "data": { ... } }
 *   { "type": "new_alert",    "data": { ... } }
 *   { "type": "new_incident", "data": { ... } }
 *   { "type": "weapon_alert", "data": { ... } }
 *   { "type": "detection",    "data": { ... } }
 *   { "type": "pong" }
 */

import { useEffect, useRef, useCallback, useState } from "react";

// ── Constants ───────────────────────────────────────────────────────────────

const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (process.env.NEXT_PUBLIC_API_URL?.replace(/^http/, "ws").replace("/api", "/ws")) ||
  "ws://localhost:5000/ws";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const PING_INTERVAL_MS = 25000;

// ── Types ───────────────────────────────────────────────────────────────────

export type WSMessageType =
  | "stats_update"
  | "new_alert"
  | "new_incident"
  | "weapon_alert"
  | "detection"
  | "pong";

export interface WSMessage {
  type: WSMessageType;
  data?: Record<string, unknown>;
}

export type WSStatus = "connecting" | "connected" | "disconnected";

type MessageHandler = (msg: WSMessage) => void;

// ── Hook ────────────────────────────────────────────────────────────────────

export function useWebSocket(onMessage?: MessageHandler) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pingTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [status, setStatus] = useState<WSStatus>("disconnected");

  const cleanup = useCallback(() => {
    if (pingTimer.current) {
      clearInterval(pingTimer.current);
      pingTimer.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    // Don't reconnect if already connected
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[ws] Connected to", WS_URL);
      setStatus("connected");
      reconnectAttempt.current = 0;

      // Start ping interval to keep connection alive
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send("ping");
        }
      }, PING_INTERVAL_MS);
    };

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        onMessage?.(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      console.warn("[ws] Disconnected");
      setStatus("disconnected");
      cleanup();

      // Exponential backoff reconnect
      const delay = Math.min(
        RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt.current),
        RECONNECT_MAX_MS
      );
      reconnectAttempt.current += 1;
      console.log(`[ws] Reconnecting in ${delay}ms (attempt ${reconnectAttempt.current}) …`);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror — reconnect handled there
    };

    wsRef.current = ws;
  }, [onMessage, cleanup]);

  useEffect(() => {
    connect();

    return () => {
      cleanup();
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on unmount
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, cleanup]);

  return { status, ws: wsRef };
}

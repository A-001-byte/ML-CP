"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useAuth } from "@/components/AuthProvider";
import {
  Activity,
  AlertTriangle,
  BellOff,
  Check,
  Clock,
  Cpu,
  Download,
  Eye,
  Gauge,
  Monitor,
  Pencil,
  RefreshCw,
  Trash2,
  Video,
  VideoOff,
  Wifi,
  WifiOff,
  X,
  Zap,
} from "lucide-react";
import {
  acknowledgeAlert,
  dismissAlert,
  getAlerts,
  getDetectionZone,
  getStats,
  resolveAlert,
  bulkDismissAlerts,
  updateDetectionZone,
  clearDetectionZone,
  ZonePoint,
} from "@/lib/api";
import { useWebSocket, WSMessage } from "@/lib/socket";
import { getApiToken } from "@/lib/api";

// â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

interface Alert {
  id: number;
  person_id: string;
  event_type: string;
  risk_score: number;
  risk_level: string;
  timestamp: string;
  camera_id: string;
  location: string;
  status: string;
}

interface Stats {
  total_alerts: number;
  total_incidents: number;
  active_incidents: number;
  high_risk_alerts: number;
  active_tracks: number;
  pipeline_fps: number | null;
  pipeline_running: boolean;
  pipeline_frames: number;
  last_frame_age_s: number | null;
}

interface SystemMetrics {
  pipeline_fps: number | null;
  pipeline_running: boolean;
  pipeline_frames: number;
  last_frame_age_s: number | null;
  gpu_available: boolean;
  gpu_info: {
    name: string;
    memory_allocated_mb: number;
    memory_reserved_mb: number;
    memory_total_mb: number;
  } | null;
  device: string;
}

interface PixelPoint {
  x: number;
  y: number;
}

interface WeaponAlertPayload {
  person_id: number | string;
  weapon_class: string;
  confidence: number;
  location: string;
  timestamp: string;
}

interface WeaponToast extends WeaponAlertPayload {
  id: string;
}

function isWeaponAlertPayload(data: Record<string, unknown> | undefined): data is Record<string, unknown> & WeaponAlertPayload {
  return Boolean(
    data &&
    (typeof data.person_id === "number" || typeof data.person_id === "string") &&
    typeof data.weapon_class === "string" &&
    typeof data.confidence === "number" &&
    typeof data.location === "string" &&
    typeof data.timestamp === "string"
  );
}

function playAlarm() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.setValueAtTime(660, ctx.currentTime + 0.3);
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
    osc.start();
    osc.stop(ctx.currentTime + 0.8);
  } catch {
    // Browsers can block audio before user interaction; the toast still appears.
  }
}

function distance(a: PixelPoint, b: PixelPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function ZoneCanvas({
  savedZone,
  drawing,
  onComplete,
}: {
  savedZone: ZonePoint[];
  drawing: boolean;
  onComplete: (points: ZonePoint[]) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [draft, setDraft] = useState<PixelPoint[]>([]);
  const [cursor, setCursor] = useState<PixelPoint | null>(null);
  const wasDrawing = useRef(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;

    const syncSize = () => {
      const rect = parent.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      canvas.width = width;
      canvas.height = height;
      setSize({ width, height });
    };

    syncSize();
    const observer = new ResizeObserver(syncSize);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (drawing && !wasDrawing.current) {
      setDraft([]);
      setCursor(null);
    }
    wasDrawing.current = drawing;
  }, [drawing]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (savedZone.length >= 3) {
      ctx.beginPath();
      savedZone.forEach((point, index) => {
        const x = point.x * canvas.width;
        const y = point.y * canvas.height;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = "rgba(0, 255, 0, 0.15)";
      ctx.strokeStyle = "rgba(0, 255, 0, 0.95)";
      ctx.lineWidth = 2;
      ctx.fill();
      ctx.stroke();
    }

    if (drawing) {
      if (draft.length > 0) {
        ctx.beginPath();
        draft.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.lineWidth = 2;
        ctx.stroke();

        if (cursor) {
          const last = draft[draft.length - 1];
          ctx.beginPath();
          ctx.setLineDash([7, 7]);
          ctx.moveTo(last.x, last.y);
          ctx.lineTo(cursor.x, cursor.y);
          ctx.strokeStyle = "rgba(255,255,255,0.65)";
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

      draft.forEach((point, index) => {
        ctx.beginPath();
        ctx.arc(point.x, point.y, index === 0 ? 8 : 6, 0, Math.PI * 2);
        ctx.fillStyle = "white";
        ctx.fill();
        ctx.strokeStyle = index === 0 ? "#22c55e" : "rgba(0,0,0,0.4)";
        ctx.lineWidth = 2;
        ctx.stroke();
      });
    }
  }, [cursor, draft, drawing, savedZone, size]);

  const pointFromEvent = (event: React.MouseEvent<HTMLCanvasElement>): PixelPoint => {
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((event.clientX - rect.left) / rect.width) * canvas.width,
      y: ((event.clientY - rect.top) / rect.height) * canvas.height,
    };
  };

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!drawing) return;
    const point = pointFromEvent(event);
    if (draft.length >= 3 && distance(point, draft[0]) <= 15) {
      onComplete(draft.map((item) => ({
        x: Math.min(1, Math.max(0, item.x / Math.max(1, event.currentTarget.width))),
        y: Math.min(1, Math.max(0, item.y / Math.max(1, event.currentTarget.height))),
      })));
      setDraft([]);
      setCursor(null);
      return;
    }
    setDraft((prev) => [...prev, point]);
  };

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full"
      style={{ pointerEvents: drawing ? "all" : "none", cursor: drawing ? "crosshair" : "default" }}
      onClick={handleClick}
      onMouseMove={(event) => drawing && setCursor(pointFromEvent(event))}
      onMouseLeave={() => setCursor(null)}
      aria-label="Detection zone drawing canvas"
    />
  );
}

// â”€â”€ SVG Threat Timeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function ThreatTimeline({ alerts }: { alerts: Alert[] }) {
  const WIDTH = 600;
  const HEIGHT = 80;
  const PADDING = 4;

  const data = alerts
    .slice(0, 30)
    .reverse()
    .map((a) => Math.min(1, Math.max(0, a.risk_score ?? 0)));

  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center h-20 text-xs" style={{ color: 'var(--text-dim)' }}>
        Awaiting threat dataâ€¦
      </div>
    );
  }

  const stepX = (WIDTH - PADDING * 2) / (data.length - 1);
  const getY = (val: number) =>
    PADDING + (1 - val) * (HEIGHT - PADDING * 2);

  const points = data.map(
    (val, i) => `${PADDING + i * stepX},${getY(val)}`
  );
  const linePath = `M${points.join("L")}`;
  const areaPath = `${linePath}L${PADDING + (data.length - 1) * stepX},${HEIGHT}L${PADDING},${HEIGHT}Z`;

  const maxRisk = Math.max(...data);
  const lineColor =
    maxRisk > 0.7 ? "#ef4444" : maxRisk > 0.4 ? "#f59e0b" : "#22c55e";
  const fillColor =
    maxRisk > 0.7
      ? "rgba(239,68,68,0.06)"
      : maxRisk > 0.4
        ? "rgba(245,158,11,0.05)"
        : "rgba(34,197,94,0.04)";

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full h-20"
      preserveAspectRatio="none"
    >
      {[0.25, 0.5, 0.75].map((v) => (
        <line
          key={v}
          x1={PADDING}
          y1={getY(v)}
          x2={WIDTH - PADDING}
          y2={getY(v)}
          stroke="rgba(255,255,255,0.04)"
          strokeWidth="0.5"
        />
      ))}
      <path d={areaPath} fill={fillColor} />
      <path
        d={linePath}
        fill="none"
        stroke={lineColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={PADDING + (data.length - 1) * stepX}
        cy={getY(data[data.length - 1])}
        r="3"
        fill={lineColor}
      />
    </svg>
  );
}

// â”€â”€ Metric Card â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function MetricCard({
  label,
  value,
  color = "var(--accent)",
  icon: Icon,
}: {
  label: string;
  value: string;
  color?: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-md" style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
      {Icon && (
        <span className="flex-shrink-0" style={{ color }}>
          <Icon className="w-3.5 h-3.5" />
        </span>
      )}
      <div className="flex-1 min-w-0">
        <div className="data-label truncate">{label}</div>
        <div className="data-value mt-0.5" style={{ color }}>
          {value}
        </div>
      </div>
    </div>
  );
}

// â”€â”€ Main Component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function LiveMonitor() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [alarmMuted, setAlarmMuted] = useState(() => {
    if (typeof window !== "undefined")
      return localStorage.getItem("alarmMuted") === "true";
    return false;
  });
  const [bulkDismissing, setBulkDismissing] = useState(false);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [currentFeed, setCurrentFeed] = useState<string | null>(null);
  const [zonePoints, setZonePoints] = useState<ZonePoint[]>([]);
  const [drawingZone, setDrawingZone] = useState(false);
  const [zoneSaving, setZoneSaving] = useState(false);
  const [weaponToasts, setWeaponToasts] = useState<WeaponToast[]>([]);
  const [feedStatus, setFeedStatus] = useState<"loading" | "connected" | "offline">("loading");
  const fallbackInterval = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasTriedStream = useRef(false);
  const feedErrorCount = useRef(0);
  const alarmMutedRef = useRef(alarmMuted);

  useEffect(() => {
    alarmMutedRef.current = alarmMuted;
  }, [alarmMuted]);

  // Derived state
  const activeAlerts = useMemo(
    () =>
      alerts.filter(
        (a) =>
          (a.status || "").toLowerCase() !== "resolved" &&
          (a.status || "").toLowerCase() !== "dismissed"
      ),
    [alerts]
  );

  const highRiskAlert = useMemo(
    () =>
      activeAlerts.find((a) => {
        const lvl = (a.risk_level || "").toLowerCase();
        return lvl === "high" || lvl === "critical";
      }),
    [activeAlerts]
  );

  // â”€â”€ WebSocket â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const dismissWeaponToast = useCallback((id: string) => {
    setWeaponToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const handleWSMessage = useCallback((msg: WSMessage) => {
    if (msg.type === "new_alert" && msg.data) {
      setAlerts((prev) => [msg.data as unknown as Alert, ...prev]);
    }
    if (msg.type === "stats_update" && msg.data) {
      setStats(msg.data as unknown as Stats);
    }
    if (msg.type === "weapon_alert" && isWeaponAlertPayload(msg.data)) {
      const id = `${Date.now()}-${msg.data.person_id}-${msg.data.weapon_class}`;
      const toast: WeaponToast = { ...msg.data, id };
      setWeaponToasts((prev) => [...prev, toast].slice(-3));
      window.setTimeout(() => dismissWeaponToast(id), 8000);
      if (!alarmMutedRef.current) playAlarm();
    }
  }, [dismissWeaponToast]);

  const { status: wsStatus } = useWebSocket(handleWSMessage);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.title = weaponToasts.length > 0 ? "⚠ ALERT — ThreatSense-AI" : "ThreatSense-AI";
  }, [weaponToasts.length]);

  // â”€â”€ Initial data load â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [alertRes, statsRes] = await Promise.all([
        getAlerts(50),
        getStats(),
      ]);
      const incoming = Array.isArray(alertRes?.alerts)
        ? alertRes.alerts
        : Array.isArray(alertRes)
          ? alertRes
          : [];
      setAlerts(incoming as Alert[]);
      setStats(statsRes as Stats);
    } catch (err) {
      console.error("Failed to load dashboard data", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch system metrics (device info, GPU)
  const fetchMetrics = useCallback(async () => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000/api";
      const res = await fetch(`${API_BASE}/system_metrics`);
      if (res.ok) {
        setMetrics(await res.json());
      }
    } catch {
      // Silently ignore
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchMetrics();
    getDetectionZone()
      .then((zone) => {
        const points = Array.isArray(zone.points) ? zone.points : [];
        setZonePoints(points);
      })
      .catch(() => {});
    const metricsInterval = setInterval(fetchMetrics, 10000);
    return () => clearInterval(metricsInterval);
  }, [fetchData, fetchMetrics]);

  // â”€â”€ Video feed URLs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  useEffect(() => {
    // Use in-memory token (never from localStorage) for cross-port video feed auth
    const streamBase =
      process.env.NEXT_PUBLIC_VIDEO_FEED_URL ||
      "http://localhost:5000/api/video_feed";
    const snapBase =
      process.env.NEXT_PUBLIC_VIDEO_FRAME_URL ||
      "http://localhost:5000/api/frame";
    const stream = token
      ? `${streamBase}?token=${encodeURIComponent(token)}`
      : streamBase;
    const snap = token
      ? `${snapBase}?token=${encodeURIComponent(token)}`
      : snapBase;
    setStreamUrl(stream);
    setSnapshotUrl(snap);
    setCurrentFeed(stream);
  }, [token]);

  const startSnapshotFallback = useCallback(() => {
    if (!snapshotUrl || fallbackInterval.current) return;
    const tick = () =>
      setCurrentFeed(
        `${snapshotUrl}${snapshotUrl.includes("?") ? "&" : "?"}ts=${Date.now()}`
      );
    tick();
    fallbackInterval.current = setInterval(tick, 1500);
  }, [snapshotUrl]);

  const stopSnapshotFallback = useCallback(() => {
    if (fallbackInterval.current) {
      clearInterval(fallbackInterval.current);
      fallbackInterval.current = null;
    }
  }, []);

  // â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const formatTime = (timestamp: string) => {
    const dt = new Date(timestamp);
    return dt.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "Asia/Kolkata",
    });
  };

  const getBadgeClass = (risk?: string) => {
    const lvl = (risk || "").toLowerCase();
    if (lvl === "critical") return "badge badge-critical";
    if (lvl === "high") return "badge badge-high";
    if (lvl === "medium") return "badge badge-medium";
    return "badge badge-low";
  };

  // â”€â”€ Alert actions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  const updateAlertStatus = (id: number, status: string) => {
    setAlerts((prev) =>
      prev.map((a) => (a.id === id ? { ...a, status } : a))
    );
  };

  const handleAck = async (id: number) => {
    setActionLoading(id);
    try {
      await acknowledgeAlert(id);
      updateAlertStatus(id, "Under Review");
    } catch { /* ignore */ } finally {
      setActionLoading(null);
    }
  };

  const handleResolve = async (id: number) => {
    setActionLoading(id);
    try {
      await resolveAlert(id);
      updateAlertStatus(id, "Resolved");
    } catch { /* ignore */ } finally {
      setActionLoading(null);
    }
  };

  const handleDismiss = async (id: number) => {
    setActionLoading(id);
    try {
      await dismissAlert(id);
      updateAlertStatus(id, "Dismissed");
    } catch { /* ignore */ } finally {
      setActionLoading(null);
    }
  };

  const handleBulkDismiss = async () => {
    setBulkDismissing(true);
    try {
      await bulkDismissAlerts();
      await fetchData();
    } catch { /* ignore */ } finally {
      setBulkDismissing(false);
    }
  };

  const toggleMute = () => {
    setAlarmMuted((prev) => {
      const next = !prev;
      if (typeof window !== "undefined")
        localStorage.setItem("alarmMuted", String(next));
      return next;
    });
  };

  const completeZone = async (points: ZonePoint[]) => {
    setZoneSaving(true);
    try {
      const zone = await updateDetectionZone(points);
      setZonePoints(zone.points || []);
      setDrawingZone(false);
    } finally {
      setZoneSaving(false);
    }
  };

  const clearZone = async () => {
    setZoneSaving(true);
    try {
      await clearDetectionZone();
      setZonePoints([]);
      setDrawingZone(false);
    } finally {
      setZoneSaving(false);
    }
  };

  // Derive device label from real metrics
  const deviceLabel = metrics?.gpu_available
    ? metrics.gpu_info?.name || "GPU"
    : "CPU";

  // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
  // RENDER
  // â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

  return (
    <div className="space-y-4 p-1" style={{ color: 'var(--text-primary)' }}>
      {/* â”€â”€ Critical Alert Banner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      {highRiskAlert && (
        <div className="panel animate-fade-in" style={{ borderColor: 'var(--danger-border)' }}>
          <div className="flex items-center gap-3 px-4 py-3" style={{ background: 'var(--danger-dim)' }}>
            <div className="status-dot status-dot-danger animate-pulse-dot" />
            <AlertTriangle className="w-4 h-4" style={{ color: 'var(--danger)' }} />
            <span className="text-xs font-semibold uppercase" style={{ color: 'var(--danger)' }}>
              Critical Threat Detected
            </span>
            <span className="text-sm flex-1" style={{ color: 'var(--text-secondary)' }}>
              {highRiskAlert.event_type} â€” {highRiskAlert.location || "Unknown"}{" "}
              â€” {formatTime(highRiskAlert.timestamp)}
            </span>
            <button onClick={toggleMute} className="btn btn-danger">
              <BellOff className="w-3 h-3" />
              {alarmMuted ? "Unmute" : "Mute"}
            </button>
            <button
              onClick={() => handleDismiss(highRiskAlert.id)}
              disabled={actionLoading === highRiskAlert.id}
              className="btn btn-ghost"
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      <div className="weapon-toast-container fixed top-4 right-4 z-[9999] space-y-3 w-[340px] max-w-[calc(100vw-2rem)]">
        {weaponToasts.map((toast) => (
          <div
            key={toast.id}
            className="rounded-lg overflow-hidden animate-slide-in"
            style={{ background: "var(--bg-panel)", border: "1px solid var(--danger-border)", boxShadow: "0 18px 50px rgba(0,0,0,0.35)" }}
          >
            <div className="p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 flex-shrink-0" style={{ color: "var(--danger)" }} />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-semibold tracking-wide" style={{ color: "var(--danger)" }}>⚠ WEAPON DETECTED</div>
                  <div className="text-sm mt-1" style={{ color: "var(--text-primary)" }}>
                    {toast.weapon_class} - Person ID {toast.person_id}
                  </div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                    Confidence: {Math.round(toast.confidence * 100)}%
                  </div>
                  <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                    {toast.location} · {toast.timestamp}
                  </div>
                </div>
                <button type="button" onClick={() => dismissWeaponToast(toast.id)} className="btn btn-ghost" aria-label="Dismiss weapon alert">
                  <X className="w-3 h-3" />
                </button>
              </div>
            </div>
            <div className="h-1" style={{ background: "var(--danger-dim)" }}>
              <div className="h-full weapon-toast-progress" style={{ background: "var(--danger)" }} />
            </div>
          </div>
        ))}
      </div>

      {/* â”€â”€ Main Grid: Feed + Side Panels â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* â”€â”€ LEFT: Camera Feed + Timeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="lg:col-span-8 space-y-4">
          {/* Camera Feed */}
          <div className="panel">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <Video className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                <span className="panel-title">Live Feed</span>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className="badge"
                  style={{
                    color: zonePoints.length >= 3 ? "var(--success)" : "var(--text-muted)",
                    borderColor: zonePoints.length >= 3 ? "rgba(34,197,94,0.3)" : "var(--border-strong)",
                    background: zonePoints.length >= 3 ? "var(--success-dim)" : "transparent",
                  }}
                >
                  {zonePoints.length >= 3 ? "Zone Active" : "No Zone"}
                </span>
                <button
                  onClick={() => setDrawingZone((prev) => !prev)}
                  className="btn btn-ghost"
                  title="Draw detection zone"
                >
                  <Pencil className="w-3 h-3" />
                  {drawingZone ? "Cancel Zone" : "Draw Zone"}
                </button>
                {zonePoints.length > 0 && (
                  <button
                    onClick={clearZone}
                    className="btn btn-warning"
                    disabled={zoneSaving}
                    title="Clear detection zone"
                  >
                    <Trash2 className="w-3 h-3" />
                    Clear Zone
                  </button>
                )}
                <div className="flex items-center gap-1.5">
                  {wsStatus === "connected" ? (
                    <Wifi className="w-3 h-3" style={{ color: 'var(--success)' }} />
                  ) : (
                    <WifiOff className="w-3 h-3" style={{ color: 'var(--danger)' }} />
                  )}
                  <span
                    className="text-[11px] font-medium"
                    style={{
                      color: wsStatus === "connected" ? "var(--success)" : "var(--danger)",
                    }}
                  >
                    {wsStatus === "connected" ? "Connected" : "Offline"}
                  </span>
                </div>
              </div>
            </div>

            <div
              className={`relative aspect-video ${drawingZone ? "cursor-crosshair" : ""}`}
              style={{ background: '#0a0e14' }}
            >
              {/* Feed */}
              {currentFeed && (
                <img
                  id="camera-feed"
                  src={currentFeed}
                  alt="Live Camera Feed"
                  className="w-full h-full object-contain"
                  style={{ display: feedStatus === "connected" ? "block" : "none" }}
                  onError={() => {
                    feedErrorCount.current += 1;
                    if (!hasTriedStream.current && streamUrl) {
                      hasTriedStream.current = true;
                      if (currentFeed !== streamUrl) {
                        setCurrentFeed(streamUrl);
                        return;
                      }
                      // currentFeed already is streamUrl — fall through to error handling
                    }
                    if (feedErrorCount.current >= 3) {
                      setFeedStatus("offline");
                      stopSnapshotFallback();
                    } else {
                      startSnapshotFallback();
                    }
                  }}
                  onLoad={() => {
                    feedErrorCount.current = 0;
                    setFeedStatus("connected");
                    if (currentFeed === streamUrl) stopSnapshotFallback();
                  }}
                />
              )}

              {/* Loading skeleton */}
              {feedStatus === "loading" && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                  <div className="absolute inset-0 overflow-hidden">
                    <div
                      className="absolute inset-0"
                      style={{
                        background: 'linear-gradient(90deg, transparent 0%, rgba(59,130,246,0.06) 40%, rgba(59,130,246,0.10) 50%, rgba(59,130,246,0.06) 60%, transparent 100%)',
                        animation: 'shimmer 2s ease-in-out infinite',
                      }}
                    />
                  </div>
                  <Video className="w-8 h-8 animate-pulse" style={{ color: 'var(--text-dim)' }} />
                  <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                    Connecting to video feed…
                  </span>
                </div>
              )}

              {/* Offline state */}
              {feedStatus === "offline" && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                  <VideoOff className="w-10 h-10" style={{ color: 'var(--danger)' }} />
                  <span className="text-sm font-semibold" style={{ color: 'var(--danger)' }}>Feed Offline</span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    Unable to connect to video stream
                  </span>
                  <button
                    className="btn btn-ghost mt-1"
                    onClick={() => {
                      feedErrorCount.current = 0;
                      hasTriedStream.current = false;
                      setFeedStatus("loading");
                      const base = process.env.NEXT_PUBLIC_VIDEO_FEED_URL || "http://localhost:5000/api/video_feed";
                      const retryUrl = new URL(base);
                      if (token) retryUrl.searchParams.append("token", token);
                      retryUrl.searchParams.append("ts", Date.now().toString());
                      setCurrentFeed(retryUrl.toString());
                    }}
                  >
                    <RefreshCw className="w-3 h-3" />
                    Retry
                  </button>
                </div>
              )}

              <ZoneCanvas
                savedZone={zonePoints}
                drawing={drawingZone}
                onComplete={completeZone}
              />

              {drawingZone && (
                <div className="absolute left-3 top-3 max-w-xs rounded px-3 py-2 text-[11px]" style={{ background: 'rgba(15,20,25,0.9)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                  Click points on the frame. Click near the first point to close and save the polygon.
                </div>
              )}

              {/* FPS overlay */}
              <div className="absolute top-3 right-3 px-2.5 py-1 rounded" style={{ background: 'rgba(15,20,25,0.85)', border: '1px solid var(--border)' }}>
                <span className="text-[11px] font-mono font-medium" style={{ color: 'var(--success)' }}>
                  {stats?.pipeline_fps
                    ? `${stats.pipeline_fps} FPS`
                    : "â€” FPS"}
                </span>
              </div>

              {/* Bottom info bar */}
              <div className="absolute bottom-0 left-0 right-0 px-4 py-3" style={{ background: 'linear-gradient(to top, rgba(15,20,25,0.9), transparent)' }}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className={`status-dot ${stats?.pipeline_running ? "status-dot-success animate-pulse-dot" : "status-dot-danger"}`} />
                    <span className="text-[11px] font-medium" style={{ color: stats?.pipeline_running ? "var(--success)" : "var(--danger)" }}>
                      {stats?.pipeline_running ? "AI Active" : "AI Offline"}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono" style={{ color: 'var(--text-muted)' }}>
                    {stats?.pipeline_frames?.toLocaleString() ?? "0"} frames processed
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Threat Timeline */}
          <div className="panel">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                <span className="panel-title">Threat Timeline</span>
              </div>
              <span className="data-label">
                {alerts.length} event{alerts.length !== 1 ? "s" : ""}
              </span>
            </div>
            <div className="panel-body">
              <ThreatTimeline alerts={alerts} />
            </div>
          </div>

          {/* Recent Events Table */}
          <div className="panel">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                <span className="panel-title">Recent Events</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="data-label">{activeAlerts.length} active</span>
                <a
                  href={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000/api'}/alerts/export/csv${getApiToken() ? `?token=${encodeURIComponent(getApiToken()!)}` : ''}`}
                  download
                  className="flex items-center gap-1 px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--accent-dim)', color: 'var(--accent)', border: '1px solid rgba(59,130,246,0.2)' }}
                  title="Export alerts as CSV"
                >
                  <Download className="w-3 h-3" />
                  CSV
                </a>
              </div>
            </div>
            <div className="max-h-[260px] overflow-y-auto">
              {loading ? (
                <div className="p-4 space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="animate-pulse h-10 rounded" style={{ background: 'var(--bg-primary)' }} />
                  ))}
                </div>
              ) : alerts.length === 0 ? (
                <div className="p-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                  No events recorded
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--border)' }}>
                      <th className="text-left px-3 py-2 table-header">Time</th>
                      <th className="text-left px-3 py-2 table-header">Event</th>
                      <th className="text-left px-3 py-2 table-header">Entity</th>
                      <th className="text-left px-3 py-2 table-header">Severity</th>
                      <th className="text-left px-3 py-2 table-header">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.slice(0, 15).map((a) => (
                      <tr
                        key={a.id}
                        className="transition-colors"
                        style={{ borderBottom: '1px solid var(--border)' }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)'; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                      >
                        <td className="px-3 py-2 font-mono text-[11px]" style={{ color: 'var(--accent)' }}>
                          {formatTime(a.timestamp)}
                        </td>
                        <td className="px-3 py-2" style={{ color: 'var(--text-primary)' }}>
                          {a.event_type}
                        </td>
                        <td className="px-3 py-2 font-mono" style={{ color: 'var(--text-secondary)' }}>
                          {a.person_id || "â€”"}
                        </td>
                        <td className="px-3 py-2">
                          <span className={getBadgeClass(a.risk_level)}>
                            {a.risk_level?.toUpperCase() || "LOW"}
                          </span>
                        </td>
                        <td className="px-3 py-2 font-mono" style={{ color: 'var(--text-secondary)' }}>
                          {(a.risk_score ?? 0).toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

        {/* â”€â”€ RIGHT: Alert Stack + Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
        <div className="lg:col-span-4 space-y-4">
          {/* System Metrics */}
          <div className="panel">
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <Gauge className="w-4 h-4" style={{ color: 'var(--accent)' }} />
                <span className="panel-title">System Metrics</span>
              </div>
            </div>
            <div className="panel-body space-y-2">
              <MetricCard
                label="Pipeline FPS"
                value={stats?.pipeline_fps != null ? `${stats.pipeline_fps}` : "â€”"}
                color="var(--success)"
                icon={Zap}
              />
              <MetricCard
                label="Frame Latency"
                value={
                  stats?.last_frame_age_s != null
                    ? `${stats.last_frame_age_s}s`
                    : "â€”"
                }
                color="var(--warning)"
                icon={Clock}
              />
              <MetricCard
                label="Active Tracks"
                value={`${stats?.active_tracks ?? 0}`}
                color="var(--accent)"
                icon={Eye}
              />
              <MetricCard
                label="Device"
                value={deviceLabel}
                color="var(--success)"
                icon={Cpu}
              />
              <MetricCard
                label="Pipeline"
                value={stats?.pipeline_running ? "Running" : "Offline"}
                color={
                  stats?.pipeline_running
                    ? "var(--success)"
                    : "var(--danger)"
                }
                icon={Monitor}
              />
            </div>
          </div>

          {/* Active Alert Stack */}
          <div className="panel" style={{ borderColor: activeAlerts.length > 0 ? 'var(--danger-border)' : undefined }}>
            <div className="panel-header" style={{ background: activeAlerts.length > 0 ? 'var(--danger-dim)' : undefined }}>
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" style={{ color: activeAlerts.length > 0 ? 'var(--danger)' : 'var(--text-muted)' }} />
                <span className="panel-title" style={{ color: activeAlerts.length > 0 ? 'var(--danger)' : undefined }}>
                  Active Alerts
                </span>
              </div>
              <span className="data-value" style={{ color: 'var(--danger)', fontSize: 14 }}>
                {activeAlerts.length}
              </span>
            </div>

            {/* Bulk dismiss */}
            <div className="px-3 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
              <button
                onClick={handleBulkDismiss}
                disabled={bulkDismissing || activeAlerts.length === 0}
                className="btn btn-ghost w-full justify-center py-1.5"
              >
                {bulkDismissing ? "Clearingâ€¦" : "Clear All"}
              </button>
            </div>

            {/* Alert list */}
            <div className="max-h-[480px] overflow-y-auto">
              {activeAlerts.length === 0 && (
                <div className="p-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                  No active threats
                </div>
              )}
              {activeAlerts.map((alert) => {
                const isHighRisk =
                  alert.risk_level?.toLowerCase() === "high" ||
                  alert.risk_level?.toLowerCase() === "critical";
                return (
                  <div
                    key={alert.id}
                    className="p-3 transition-colors animate-fade-in"
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: isHighRisk ? 'var(--danger-dim)' : 'transparent',
                    }}
                  >
                    <div className="flex items-start justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <div className={`status-dot ${isHighRisk ? "status-dot-danger animate-pulse-dot" : alert.risk_level?.toLowerCase() === "medium" ? "status-dot-warning" : "status-dot-success"}`} />
                        <span className="data-label">
                          {alert.camera_id || "CAM-01"}
                        </span>
                      </div>
                      <span className={getBadgeClass(alert.risk_level)}>
                        {alert.risk_level?.toUpperCase() || "LOW"}
                      </span>
                    </div>

                    <div className="text-sm font-medium mb-1" style={{ color: 'var(--text-primary)' }}>
                      {alert.event_type}
                    </div>
                    <div className="data-label mb-2">
                      Score: {(alert.risk_score ?? 0).toFixed(2)} Â· {formatTime(alert.timestamp)}
                    </div>

                    {/* Action buttons */}
                    <div className="flex gap-1.5 pt-1.5" style={{ borderTop: '1px solid var(--border)' }}>
                      {alert.status?.toLowerCase() === "active" && (
                        <button
                          onClick={() => handleAck(alert.id)}
                          disabled={actionLoading === alert.id}
                          className="btn btn-warning"
                        >
                          Acknowledge
                        </button>
                      )}
                      <button
                        onClick={() => handleResolve(alert.id)}
                        disabled={actionLoading === alert.id}
                        className="btn btn-success"
                      >
                        <Check className="w-3 h-3" />
                        Resolve
                      </button>
                      <button
                        onClick={() => handleDismiss(alert.id)}
                        disabled={actionLoading === alert.id}
                        className="btn btn-ghost"
                      >
                        <X className="w-3 h-3" />
                        Dismiss
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Operations Summary */}
          <div className="panel">
            <div className="panel-header">
              <span className="panel-title">Operations Summary</span>
            </div>
            <div className="panel-body space-y-2">
              <div className="flex items-center justify-between rounded-md px-3 py-2" style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
                <span className="data-label">Total Alerts</span>
                <span className="data-value" style={{ color: 'var(--accent)' }}>
                  {stats?.total_alerts ?? "â€”"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md px-3 py-2" style={{ background: 'var(--bg-primary)', border: '1px solid rgba(245, 158, 11, 0.15)' }}>
                <span className="data-label">Active Incidents</span>
                <span className="data-value" style={{ color: 'var(--warning)' }}>
                  {stats?.active_incidents ?? "â€”"}
                </span>
              </div>
              <div className="flex items-center justify-between rounded-md px-3 py-2" style={{ background: 'var(--bg-primary)', border: '1px solid var(--danger-border)' }}>
                <span className="data-label">High Risk</span>
                <span className="data-value" style={{ color: 'var(--danger)' }}>
                  {stats?.high_risk_alerts ?? "â€”"}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

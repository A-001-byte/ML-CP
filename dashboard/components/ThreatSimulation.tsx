"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  Activity,
  AlertTriangle,
  FlaskConical,
  Radiation,
  RotateCcw,
  ShieldAlert,
  Siren,
} from "lucide-react";
import { getStats, logSimulationAlert } from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

type SimMode = "idle" | "chemical" | "bio";

interface SimPoint {
  x: number; // 0–1 normalised to canvas width
  y: number; // 0–1 normalised to canvas height
}

interface AlertEntry {
  id: string;
  time: string;
  mode: "chemical" | "bio";
  persons: number;
  radius: number;
}

function isPointInZone(
  pxNorm: number,
  pyNorm: number,
  src: SimPoint | null,
  mode: SimMode,
  radius: number
): boolean {
  if (!src || mode === "idle" || radius <= 0) return false;
  const dx = pxNorm - src.x;
  const dy = pyNorm - src.y;
  return Math.sqrt(dx * dx + dy * dy) <= radius;
}

function getPersonsInZone(count: number, src: SimPoint | null, mode: SimMode, radius: number): number {
  if (count <= 0 || !src || mode === "idle" || radius <= 0) return 0;
  let inZoneCount = 0;
  const seed = [0.18, 0.72, 0.45, 0.91, 0.33, 0.61, 0.08, 0.55, 0.79, 0.27];
  const seedY = [0.25, 0.65, 0.42, 0.80, 0.15, 0.58, 0.35, 0.72, 0.50, 0.88];
  for (let i = 0; i < count; i++) {
    const pxNorm = seed[i % seed.length];
    const pyNorm = seedY[i % seedY.length];
    if (isPointInZone(pxNorm, pyNorm, src, mode, radius)) {
      inZoneCount++;
    }
  }
  return inZoneCount;
}

// ── Drawing helpers ───────────────────────────────────────────────────────────

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const cols = 24;
  const rows = 16;
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1;
  for (let c = 0; c <= cols; c++) {
    ctx.beginPath();
    ctx.moveTo((c / cols) * w, 0);
    ctx.lineTo((c / cols) * w, h);
    ctx.stroke();
  }
  for (let r = 0; r <= rows; r++) {
    ctx.beginPath();
    ctx.moveTo(0, (r / rows) * h);
    ctx.lineTo(w, (r / rows) * h);
    ctx.stroke();
  }
}

function drawChemical(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  src: SimPoint,
  radius: number,
  tick: number
) {
  const cx = src.x * w;
  const cy = src.y * h;
  const maxR = Math.sqrt(w * w + h * h) * radius;

  // Gradient heatmap fill
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, maxR);
  grad.addColorStop(0, "rgba(255, 120, 0, 0.75)");
  grad.addColorStop(0.3, "rgba(255, 200, 0, 0.45)");
  grad.addColorStop(0.65, "rgba(180, 255, 0, 0.22)");
  grad.addColorStop(1, "rgba(0, 255, 100, 0.0)");
  ctx.beginPath();
  ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
  ctx.fillStyle = grad;
  ctx.fill();

  // Pulsing wavefront ring
  const pulse = Math.sin(tick * 0.08) * 0.5 + 0.5;
  ctx.beginPath();
  ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(255, 180, 0, ${0.4 + pulse * 0.4})`;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Source glow
  const srcGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 18);
  srcGrad.addColorStop(0, "rgba(255,80,0,0.9)");
  srcGrad.addColorStop(1, "rgba(255,80,0,0)");
  ctx.beginPath();
  ctx.arc(cx, cy, 18, 0, Math.PI * 2);
  ctx.fillStyle = srcGrad;
  ctx.fill();
}

function drawBio(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  src: SimPoint,
  radius: number,
  tick: number
) {
  const cx = src.x * w;
  const cy = src.y * h;
  const maxR = Math.sqrt(w * w + h * h) * radius;
  const innerR = maxR * 0.3;
  const pulse = Math.sin(tick * 0.06) * 0.5 + 0.5;

  // Outer exposure zone
  const outerGrad = ctx.createRadialGradient(cx, cy, innerR, cx, cy, maxR);
  outerGrad.addColorStop(0, "rgba(0, 220, 80, 0.28)");
  outerGrad.addColorStop(0.6, "rgba(0, 160, 60, 0.15)");
  outerGrad.addColorStop(1, "rgba(0, 100, 30, 0.0)");
  ctx.beginPath();
  ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
  ctx.fillStyle = outerGrad;
  ctx.fill();

  // Pulsing outer ring
  ctx.beginPath();
  ctx.arc(cx, cy, maxR, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(0, 255, 80, ${0.3 + pulse * 0.5})`;
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 6]);
  ctx.stroke();
  ctx.setLineDash([]);

  // Inner hotzone
  const innerGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, innerR);
  innerGrad.addColorStop(0, "rgba(200, 0, 0, 0.70)");
  innerGrad.addColorStop(0.5, "rgba(180, 0, 50, 0.40)");
  innerGrad.addColorStop(1, "rgba(100, 0, 0, 0.0)");
  ctx.beginPath();
  ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
  ctx.fillStyle = innerGrad;
  ctx.fill();

  // Bio hazard symbol (simplified)
  ctx.beginPath();
  ctx.arc(cx, cy, 8, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(0, 255, 80, ${0.6 + pulse * 0.4})`;
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx, cy, 8, 0, Math.PI * 2);
  ctx.strokeStyle = "rgba(0,0,0,0.5)";
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

function drawPersonMarkers(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  count: number,
  src: SimPoint | null,
  mode: SimMode,
  radius: number
) {
  if (count <= 0) return;
  // Deterministic scatter (stable across re-renders)
  const seed = [0.18, 0.72, 0.45, 0.91, 0.33, 0.61, 0.08, 0.55, 0.79, 0.27];
  const seedY = [0.25, 0.65, 0.42, 0.80, 0.15, 0.58, 0.35, 0.72, 0.50, 0.88];

  for (let i = 0; i < Math.min(count, 10); i++) {
    const pxNorm = seed[i % seed.length];
    const pyNorm = seedY[i % seedY.length];
    const px = pxNorm * w;
    const py = pyNorm * h;

    const inZone = isPointInZone(pxNorm, pyNorm, src, mode, radius);

    // Person icon
    ctx.beginPath();
    ctx.arc(px, py - 8, 5, 0, Math.PI * 2);
    ctx.fillStyle = inZone ? "rgba(255,60,60,0.95)" : "rgba(100,200,255,0.85)";
    ctx.fill();
    ctx.fillRect(px - 4, py - 3, 8, 10);

    if (inZone) {
      // Warning ring
      ctx.beginPath();
      ctx.arc(px, py - 4, 14, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(255,60,60,0.7)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ThreatSimulation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef    = useRef<number | null>(null);
  const tickRef   = useRef(0);

  const [mode,      setMode]      = useState<SimMode>("idle");
  const [srcPoint,  setSrcPoint]  = useState<SimPoint | null>(null);
  const [running,   setRunning]   = useState(false);
  const [radius,    setRadius]    = useState(0);      // 0–1
  const [elapsed,   setElapsed]   = useState(0);      // seconds
  const [persons,   setPersons]   = useState(0);      // from live API
  const [logBusy,   setLogBusy]   = useState(false);
  const [alertLog,  setAlertLog]  = useState<AlertEntry[]>([]);
  const [canvasSize, setCanvasSize] = useState({ w: 0, h: 0 });

  // Track running state in ref so rAF loop can read it without closure issues
  const runningRef   = useRef(false);
  const modeRef      = useRef<SimMode>("idle");
  const srcRef       = useRef<SimPoint | null>(null);
  const radiusRef    = useRef(0);
  const personsRef   = useRef(0);

  runningRef.current  = running;
  modeRef.current     = mode;
  srcRef.current      = srcPoint;
  radiusRef.current   = radius;
  personsRef.current  = persons;

  // ── Canvas resize ─────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    const sync = () => {
      const rect = parent.getBoundingClientRect();
      const w = Math.max(1, Math.round(rect.width));
      const h = Math.max(1, Math.round(rect.height));
      canvas.width  = w;
      canvas.height = h;
      setCanvasSize({ w, h });
    };

    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(parent);
    return () => ro.disconnect();
  }, []);

  // ── Live person count ─────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const s = await getStats();
        setPersons(s?.active_tracks ?? 0);
      } catch {
        setPersons(0);
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => clearInterval(id);
  }, []);

  // ── Timer while running ───────────────────────────────────────────
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  // ── rAF draw loop ─────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width: w, height: h } = canvas;

    tickRef.current += 1;
    const tick = tickRef.current;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#080d16";
    ctx.fillRect(0, 0, w, h);

    drawGrid(ctx, w, h);

    const src  = srcRef.current;
    const r    = radiusRef.current;
    const m    = modeRef.current;
    const pCnt = personsRef.current;

    if (src && m !== "idle" && runningRef.current) {
      // Grow radius (cap at 0.75 so it doesn't cover entire canvas)
      const increment = m === "chemical" ? 0.0025 : 0.0015;
      radiusRef.current = Math.min(radiusRef.current + increment, 0.75);
      setRadius(radiusRef.current);

      if (m === "chemical") drawChemical(ctx, w, h, src, radiusRef.current, tick);
      else                   drawBio(ctx, w, h, src, radiusRef.current, tick);
    } else if (src && m !== "idle" && !runningRef.current && r > 0) {
      // Paused — still draw at current radius
      if (m === "chemical") drawChemical(ctx, w, h, src, r, tick);
      else                   drawBio(ctx, w, h, src, r, tick);
    }

    // Draw source marker even when idle
    if (src) {
      const sx = src.x * w;
      const sy = src.y * h;
      ctx.beginPath();
      ctx.arc(sx, sy, 7, 0, Math.PI * 2);
      ctx.fillStyle = "white";
      ctx.fill();
      const pulse = Math.sin(tick * 0.1) * 0.5 + 0.5;
      ctx.beginPath();
      ctx.arc(sx, sy, 13 + pulse * 4, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,255,255,${0.4 + pulse * 0.3})`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    drawPersonMarkers(ctx, w, h, pCnt, src, m, radiusRef.current);

    rafRef.current = requestAnimationFrame(draw);
  }, []);

  useEffect(() => {
    rafRef.current = requestAnimationFrame(draw);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [draw]);

  const placeSrcPoint = useCallback((clientX: number, clientY: number) => {
    if (running) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    setSrcPoint({
      x: (clientX - rect.left) / rect.width,
      y: (clientY - rect.top)  / rect.height,
    });
  }, [running]);

  // ── Canvas click → place source ───────────────────────────────────
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    placeSrcPoint(e.clientX, e.clientY);
  }, [placeSrcPoint]);

  // ── Canvas keyboard → place source ────────────────────────────────
  const handleCanvasKeyDown = useCallback((e: React.KeyboardEvent<HTMLCanvasElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      placeSrcPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    } else if (e.key === "Escape") {
      setSrcPoint(null);
    }
  }, [placeSrcPoint]);

  // ── Controls ──────────────────────────────────────────────────────
  const start = () => {
    if (!srcPoint || mode === "idle") return;
    radiusRef.current = 0;
    setRadius(0);
    setElapsed(0);
    setRunning(true);
  };

  const stop = () => {
    setRunning(false);
    radiusRef.current = 0;
    setRadius(0);
    setElapsed(0);
    setSrcPoint(null);
    setMode("idle");
  };

  const personsInZone = running ? getPersonsInZone(persons, srcPoint, mode, radius) : 0;

  const handleLogAlert = async () => {
    if (!srcPoint || mode === "idle" || logBusy) return;
    setLogBusy(true);
    const radiusPct = Math.round(radius * 100);
    try {
      const result = await logSimulationAlert(
        mode as "chemical" | "bio",
        personsInZone,
        radiusPct
      );
      if (result) {
        const now = new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
        setAlertLog(prev => [{
          id: String(result.id),
          time: now,
          mode: mode as "chemical" | "bio",
          persons: personsInZone,
          radius: radiusPct,
        }, ...prev].slice(0, 6));
      }
    } finally {
      setLogBusy(false);
    }
  };
  const fmtTime = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div className="flex-1 overflow-auto" style={{ background: "var(--bg-primary)" }}>
      <div className="p-5">
        {/* Header */}
        <div className="mb-5">
          <h1 className="text-lg font-semibold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
            <FlaskConical className="w-5 h-5" style={{ color: "var(--accent)" }} />
            Threat Simulation
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            Simulate chemical or biological threat spread and correlate with live person detection data.
          </p>
        </div>

        <div className="flex gap-4" style={{ minHeight: 520 }}>
          {/* ── Canvas panel ─────────────────────────── */}
          <div className="flex-1 panel relative overflow-hidden" style={{ minHeight: 420 }}>
            {/* Alert banner */}
            {personsInZone > 0 && (
              <div
                className="absolute top-0 left-0 right-0 z-10 flex items-center gap-2 px-4 py-2"
                style={{
                  background: "rgba(220,20,20,0.92)",
                  animation: "flashRed 1s infinite",
                  fontWeight: 700,
                  fontSize: 12,
                  color: "white",
                }}
              >
                <Siren className="w-4 h-4 flex-shrink-0" />
                PERSONS DETECTED IN {mode.toUpperCase()} CONTAMINATION ZONE — {personsInZone} AT RISK
              </div>
            )}

            <canvas
              ref={canvasRef}
              className="absolute inset-0 w-full h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-accent"
              style={{ cursor: running ? "default" : (mode !== "idle" ? "crosshair" : "default") }}
              onClick={handleCanvasClick}
              onKeyDown={handleCanvasKeyDown}
              tabIndex={0}
              role="button"
              aria-label="Place source (Enter/Space)"
            />

            {/* Overlay instructions */}
            {!srcPoint && mode !== "idle" && (
              <div
                className="absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded text-xs pointer-events-none"
                style={{ background: "rgba(0,0,0,0.6)", color: "rgba(255,255,255,0.8)" }}
              >
                Click anywhere on the grid to place the release point
              </div>
            )}
            {!mode || mode === "idle" ? (
              <div
                className="absolute inset-0 flex items-center justify-center pointer-events-none"
                style={{ color: "rgba(255,255,255,0.2)", fontSize: 13 }}
              >
                Select a simulation mode to begin
              </div>
            ) : null}
          </div>

          {/* ── Controls panel ───────────────────────── */}
          <div className="flex flex-col gap-3" style={{ width: 260, flexShrink: 0 }}>

            {/* Mode selector */}
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Threat Type</span></div>
              <div className="p-3 flex flex-col gap-2">
                <button
                  onClick={() => { if (!running) { setMode("chemical"); setSrcPoint(null); setRadius(0); } }}
                  className="flex items-center gap-2.5 px-3 py-2.5 rounded-md text-left transition-all text-sm font-medium"
                  style={{
                    background: mode === "chemical" ? "rgba(255,140,0,0.18)" : "var(--bg-primary)",
                    border: `1px solid ${mode === "chemical" ? "rgba(255,140,0,0.5)" : "var(--border)"}`,
                    color: mode === "chemical" ? "rgb(255,160,40)" : "var(--text-secondary)",
                    cursor: running ? "not-allowed" : "pointer",
                    opacity: running ? 0.6 : 1,
                  }}
                >
                  <FlaskConical className="w-4 h-4 flex-shrink-0" />
                  <span>Chemical Threat</span>
                </button>
                <button
                  onClick={() => { if (!running) { setMode("bio"); setSrcPoint(null); setRadius(0); } }}
                  className="flex items-center gap-2.5 px-3 py-2.5 rounded-md text-left transition-all text-sm font-medium"
                  style={{
                    background: mode === "bio" ? "rgba(0,200,80,0.15)" : "var(--bg-primary)",
                    border: `1px solid ${mode === "bio" ? "rgba(0,200,80,0.5)" : "var(--border)"}`,
                    color: mode === "bio" ? "rgb(0,210,90)" : "var(--text-secondary)",
                    cursor: running ? "not-allowed" : "pointer",
                    opacity: running ? 0.6 : 1,
                  }}
                >
                  <Radiation className="w-4 h-4 flex-shrink-0" />
                  <span>Bio Threat</span>
                </button>
              </div>
            </div>

            {/* Simulation stats */}
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Simulation State</span></div>
              <div className="p-3 flex flex-col gap-2">
                {[
                  { label: "Status", value: running ? "RUNNING" : mode === "idle" ? "IDLE" : "READY", color: running ? "var(--success)" : "var(--text-muted)" },
                  { label: "Mode", value: mode === "idle" ? "—" : mode.charAt(0).toUpperCase() + mode.slice(1), color: mode === "chemical" ? "rgb(255,160,40)" : mode === "bio" ? "rgb(0,210,90)" : "var(--text-muted)" },
                  { label: "Spread radius", value: `${Math.round(radius * 100)}%`, color: "var(--text-secondary)" },
                  { label: "Elapsed", value: fmtTime(elapsed), color: "var(--text-secondary)" },
                  { label: "Persons in zone", value: String(personsInZone), color: personsInZone > 0 ? "var(--danger)" : "var(--text-muted)" },
                ].map(({ label, value, color }) => (
                  <div key={label} className="flex justify-between items-center">
                    <span className="data-label">{label}</span>
                    <span className="font-mono text-xs font-medium" style={{ color }}>{value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex flex-col gap-2">
              <button
                onClick={start}
                disabled={!srcPoint || mode === "idle" || running}
                className="flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all"
                style={{
                  background: (!srcPoint || mode === "idle" || running) ? "var(--bg-secondary)" : "var(--accent)",
                  color: (!srcPoint || mode === "idle" || running) ? "var(--text-dim)" : "white",
                  border: "1px solid var(--border)",
                  cursor: (!srcPoint || mode === "idle" || running) ? "not-allowed" : "pointer",
                  opacity: (!srcPoint || mode === "idle" || running) ? 0.5 : 1,
                }}
              >
                <Activity className="w-3.5 h-3.5" />
                Start Simulation
              </button>

              <button
                onClick={stop}
                disabled={mode === "idle" && !running}
                className="flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all"
                style={{
                  background: "var(--bg-secondary)",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border)",
                  cursor: (mode === "idle" && !running) ? "not-allowed" : "pointer",
                  opacity: (mode === "idle" && !running) ? 0.5 : 1,
                }}
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Stop &amp; Reset
              </button>

              <button
                onClick={handleLogAlert}
                disabled={!srcPoint || mode === "idle" || logBusy}
                className="flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-semibold transition-all"
                style={{
                  background: (!srcPoint || mode === "idle" || logBusy) ? "var(--bg-secondary)" : "rgba(220,20,20,0.85)",
                  color: (!srcPoint || mode === "idle" || logBusy) ? "var(--text-dim)" : "white",
                  border: `1px solid ${(!srcPoint || mode === "idle") ? "var(--border)" : "rgba(220,20,20,0.6)"}`,
                  cursor: (!srcPoint || mode === "idle" || logBusy) ? "not-allowed" : "pointer",
                  opacity: (!srcPoint || mode === "idle" || logBusy) ? 0.5 : 1,
                }}
              >
                <ShieldAlert className="w-3.5 h-3.5" />
                {logBusy ? "Logging…" : "Log Alert to Dashboard"}
              </button>
            </div>

            {/* Live detection stats */}
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Live Detection</span></div>
              <div className="p-3 flex flex-col gap-2">
                <div className="flex justify-between">
                  <span className="data-label">Active tracks</span>
                  <span className="font-mono text-xs" style={{ color: persons > 0 ? "var(--success)" : "var(--text-muted)" }}>{persons}</span>
                </div>
              </div>
            </div>

            {/* Alert log */}
            {alertLog.length > 0 && (
              <div className="panel">
                <div className="panel-header">
                  <span className="panel-title">Alert Log</span>
                </div>
                <div className="p-2 flex flex-col gap-1 max-h-40 overflow-y-auto">
                  {alertLog.map(a => (
                    <div key={a.id} className="flex items-center gap-2 py-1 px-2 rounded text-xs"
                      style={{ background: "var(--bg-primary)" }}>
                      <AlertTriangle className="w-3 h-3 flex-shrink-0"
                        style={{ color: a.mode === "chemical" ? "rgb(255,160,40)" : "rgb(0,200,80)" }} />
                      <span style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>{a.time}</span>
                      <span style={{ color: "var(--text-secondary)" }}>
                        {a.mode === "chemical" ? "CHEM" : "BIO"} · {a.persons}p · {a.radius}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

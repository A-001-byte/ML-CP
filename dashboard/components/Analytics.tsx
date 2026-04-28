"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Gauge, TrendingUp } from "lucide-react";
import { getAnalytics } from "@/lib/api";

interface CountPoint {
  count: number;
}

interface HourPoint extends CountPoint {
  hour: string;
}

interface DayPoint extends CountPoint {
  date: string;
}

interface LocationPoint extends CountPoint {
  location: string;
}

interface AnalyticsData {
  alerts_by_hour: HourPoint[];
  alerts_by_day: DayPoint[];
  risk_distribution: Record<"low" | "medium" | "high" | "critical", number>;
  weapon_types: Record<string, number>;
  top_locations: LocationPoint[];
  total_alerts: number;
  total_incidents: number;
  avg_risk_score: number;
  detection_rate_per_hour: number;
}

const RISK_COLORS: Record<keyof AnalyticsData["risk_distribution"], string> = {
  low: "#22c55e",
  medium: "#f59e0b",
  high: "#ef4444",
  critical: "#7f1d1d",
};

function StatCard({
  label,
  value,
  color,
  icon: Icon,
}: {
  label: string;
  value: string;
  color: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="panel">
      <div className="panel-body flex items-center gap-3">
        <div className="w-9 h-9 rounded-md flex items-center justify-center" style={{ background: "var(--accent-dim)", color }}>
          <Icon className="w-4 h-4" />
        </div>
        <div>
          <div className="data-label">{label}</div>
          <div className="data-value mt-1" style={{ color }}>{value}</div>
        </div>
      </div>
    </div>
  );
}

function formatHourLabel(hour: string): string {
  // hour could be "2026-04-28T14:00:00" or "14" or "14:00"
  if (hour.includes("T")) {
    const d = new Date(hour);
    return `${d.getHours().toString().padStart(2, "0")}:00`;
  }
  const h = parseInt(hour, 10);
  if (!isNaN(h)) return `${h.toString().padStart(2, "0")}:00`;
  return hour;
}

function Last24HoursChart({ data }: { data: HourPoint[] }) {
  const width = 720;
  const height = 260;
  const padding = 48;
  const rightPad = 36;
  const max = Math.max(1, ...data.map((item) => item.count));
  const allZero = data.every((item) => item.count === 0);
  const slot = (width - padding - rightPad) / Math.max(1, data.length);
  const barWidth = Math.max(4, slot * 0.62);
  const chartH = height - padding * 2;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: height - padding - chartH * f,
    label: Math.round(max * f).toString(),
  }));
  const showEvery = data.length <= 12 ? 1 : data.length <= 18 ? 2 : 3;

  if (allZero) {
    return (
      <div className="flex flex-col items-center justify-center h-72 gap-2">
        <Activity className="w-8 h-8" style={{ color: "var(--text-dim)" }} />
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>No data yet</span>
        <span className="text-xs" style={{ color: "var(--text-dim)" }}>Alerts will appear here once detections begin</span>
      </div>
    );
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-72">
      {/* Y-axis gridlines + labels */}
      {yTicks.map((tick) => (
        <g key={tick.label + tick.y}>
          <line x1={padding} y1={tick.y} x2={width - rightPad} y2={tick.y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
          <text x={padding - 8} y={tick.y + 4} textAnchor="end" fontSize="9" fill="var(--text-dim)">{tick.label}</text>
        </g>
      ))}
      {/* Bars */}
      {data.map((item, index) => {
        const barHeight = (chartH * item.count) / max;
        const x = padding + index * slot + (slot - barWidth) / 2;
        const y = height - padding - barHeight;
        const alpha = 0.3 + (item.count / max) * 0.7;
        return (
          <g key={`${item.hour}-${index}`}>
            <rect x={x} y={y} width={barWidth} height={barHeight} rx="4" fill={`rgba(59,130,246,${alpha})`} />
            {item.count > 0 && (
              <text x={x + barWidth / 2} y={y - 6} textAnchor="middle" fontSize="9" fontWeight="600" fill="var(--text-secondary)">
                {item.count}
              </text>
            )}
            {index % showEvery === 0 && (
              <text x={x + barWidth / 2} y={height - 12} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
                {formatHourLabel(item.hour)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function formatDayLabel(dateStr: string): string {
  // dateStr could be "2026-04-28" or "04-28"
  try {
    const d = new Date(dateStr.length <= 5 ? `2026-${dateStr}` : dateStr);
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    return `${days[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`;
  } catch {
    return dateStr.slice(5);
  }
}

function Last7DaysChart({ data }: { data: DayPoint[] }) {
  const width = 720;
  const height = 260;
  const padding = 48;
  const rightPad = 36;
  const max = Math.max(1, ...data.map((item) => item.count));
  const allZero = data.every((item) => item.count === 0);
  const chartH = height - padding * 2;
  const step = (width - padding - rightPad) / Math.max(1, data.length - 1);
  const points = data.map((item, index) => {
    const x = padding + step * index;
    const y = height - padding - (chartH * item.count) / max;
    return { x, y, label: formatDayLabel(item.date), count: item.count };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${padding},${height - padding} ${line} ${width - rightPad},${height - padding}`;
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: height - padding - chartH * f,
    label: Math.round(max * f).toString(),
  }));

  if (allZero) {
    return (
      <div className="flex flex-col items-center justify-center h-72 gap-2">
        <TrendingUp className="w-8 h-8" style={{ color: "var(--text-dim)" }} />
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>No data yet</span>
        <span className="text-xs" style={{ color: "var(--text-dim)" }}>Trend data will appear after the first day of detections</span>
      </div>
    );
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-72">
      {/* Y-axis gridlines + labels */}
      {yTicks.map((tick) => (
        <g key={tick.label + tick.y}>
          <line x1={padding} y1={tick.y} x2={width - rightPad} y2={tick.y} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
          <text x={padding - 8} y={tick.y + 4} textAnchor="end" fontSize="9" fill="var(--text-dim)">{tick.label}</text>
        </g>
      ))}
      <polygon points={area} fill="rgba(34,197,94,0.08)" />
      <polyline points={line} fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((point) => (
        <g key={point.label}>
          <circle cx={point.x} cy={point.y} r="5" fill="#22c55e" />
          {point.count > 0 && (
            <text x={point.x} y={point.y - 12} textAnchor="middle" fontSize="10" fontWeight="600" fill="var(--text-secondary)">
              {point.count}
            </text>
          )}
          <text x={point.x} y={height - 12} textAnchor="middle" fontSize="10" fill="var(--text-muted)">
            {point.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function RiskDonut({ data }: { data: AnalyticsData["risk_distribution"] }) {
  const total = Object.values(data).reduce((sum, value) => sum + value, 0);
  const radius = 58;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const segments = (Object.keys(data) as Array<keyof typeof data>).map((key) => {
    const value = data[key];
    const length = total > 0 ? (value / total) * circumference : 0;
    const segment = { key, value, length, offset };
    offset += length;
    return segment;
  });

  return (
    <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4 items-center">
      <svg viewBox="0 0 160 160" className="w-56 h-56 mx-auto">
        <circle cx="80" cy="80" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="24" />
        {segments.map((segment) => (
          <circle
            key={segment.key}
            cx="80"
            cy="80"
            r={radius}
            fill="none"
            stroke={RISK_COLORS[segment.key]}
            strokeWidth="24"
            strokeDasharray={`${segment.length} ${circumference - segment.length}`}
            strokeDashoffset={-segment.offset}
            transform="rotate(-90 80 80)"
          />
        ))}
        <text x="80" y="76" textAnchor="middle" fontSize="24" fontWeight="700" fill="var(--text-primary)">
          {total}
        </text>
        <text x="80" y="96" textAnchor="middle" fontSize="11" fill="var(--text-muted)">
          alerts
        </text>
      </svg>
      <div className="space-y-2">
        {segments.map((segment) => (
          <div key={segment.key} className="flex items-center justify-between rounded px-3 py-2" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
            <span className="flex items-center gap-2 text-sm capitalize" style={{ color: "var(--text-secondary)" }}>
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: RISK_COLORS[segment.key] }} />
              {segment.key}
            </span>
            <span className="data-value" style={{ color: RISK_COLORS[segment.key] }}>{segment.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function WeaponBars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).filter(([, count]) => count > 0);
  const total = Math.max(1, entries.reduce((sum, [, count]) => sum + count, 0));
  const rows: Array<[string, number]> = entries.length > 0 ? entries : [["gun", 0], ["knife", 0]];

  return (
    <div className="space-y-3">
      {rows.map(([weapon, count]) => {
        const percent = Math.round((count / total) * 100);
        return (
          <div key={weapon}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm capitalize" style={{ color: "var(--text-secondary)" }}>{weapon}</span>
              <span className="data-label">{percent}%</span>
            </div>
            <div className="h-8 rounded overflow-hidden" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
              <div className="h-full flex items-center px-3 text-xs font-mono" style={{ width: `${percent}%`, minWidth: count > 0 ? 42 : 0, background: "var(--accent-dim)", color: "var(--accent)" }}>
                {count}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TopLocations({ data }: { data: LocationPoint[] }) {
  const max = Math.max(1, ...data.map((item) => item.count));
  return (
    <div className="space-y-2">
      {data.length === 0 && <p className="text-sm" style={{ color: "var(--text-muted)" }}>No locations recorded yet.</p>}
      {data.map((item, index) => (
        <div key={item.location} className="relative overflow-hidden rounded px-3 py-3" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
          <div className="absolute inset-y-0 left-0" style={{ width: `${(item.count / max) * 100}%`, background: "var(--accent-dim)" }} />
          <div className="relative flex items-center justify-between">
            <span className="text-sm" style={{ color: "var(--text-primary)" }}>{index + 1}. {item.location}</span>
            <span className="data-value" style={{ color: "var(--accent)" }}>{item.count}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Analytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAnalytics()
      .then((payload: AnalyticsData) => {
        setData(payload);
        setError(null);
      })
      .catch((err) => {
        console.error("Failed to load analytics", err);
        setError("Could not load analytics");
      })
      .finally(() => setLoading(false));
  }, []);

  const statCards = useMemo(() => {
    if (!data) return [];
    return [
      { label: "Total Alerts", value: `${data.total_alerts}`, color: "var(--danger)", icon: AlertTriangle },
      { label: "Total Incidents", value: `${data.total_incidents}`, color: "var(--warning)", icon: Activity },
      { label: "Avg Risk Score", value: data.avg_risk_score.toFixed(2), color: "var(--accent)", icon: Gauge },
      { label: "Detections/Hour", value: data.detection_rate_per_hour.toFixed(2), color: "var(--success)", icon: TrendingUp },
    ];
  }, [data]);

  return (
    <div className="flex-1 overflow-auto p-6" style={{ background: "var(--bg-primary)" }}>
      <div className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Analytics</h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>Historical threat patterns from alert telemetry</p>
      </div>

      {error && (
        <div className="panel mb-4">
          <div className="panel-body text-sm" style={{ color: "var(--warning)" }}>{error}</div>
        </div>
      )}

      {loading || !data ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((item) => <div key={item} className="panel h-24 animate-pulse" />)}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {statCards.map((card) => <StatCard key={card.label} {...card} />)}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Alerts — Last 24 Hours</span></div>
              <div className="panel-body"><Last24HoursChart data={data.alerts_by_hour} /></div>
            </div>
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Alert Trend — Last 7 Days</span></div>
              <div className="panel-body"><Last7DaysChart data={data.alerts_by_day} /></div>
            </div>
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Risk Level Distribution</span></div>
              <div className="panel-body"><RiskDonut data={data.risk_distribution} /></div>
            </div>
            <div className="panel">
              <div className="panel-header"><span className="panel-title">Weapon Type</span></div>
              <div className="panel-body"><WeaponBars data={data.weapon_types} /></div>
            </div>
            <div className="panel xl:col-span-2">
              <div className="panel-header"><span className="panel-title">Top Locations</span></div>
              <div className="panel-body"><TopLocations data={data.top_locations} /></div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

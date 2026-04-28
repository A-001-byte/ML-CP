"use client";

import { useState, useEffect, useCallback } from "react";
import {
  MonitorPlay,
  AlertCircle,
  BarChart3,
  Camera,
  Users,
  Shield,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import { apiFetch } from "@/lib/api";

interface PipelineStatus {
  pipeline_running: boolean;
  camera_connected: boolean;
}

export default function Sidebar({ className = "" }: { className?: string }) {
  const pathname = usePathname();
  const { role } = useAuth();
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [alertCount, setAlertCount] = useState(0);

  const fetchStatus = useCallback(async () => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000/api";
    try {
      const res = await fetch(`${API_BASE}/system_status`);
      if (res.ok) {
        setStatus(await res.json());
      }
    } catch {
      setStatus(null);
    }
    // Fetch active alert count for badge (requires auth)
    try {
      const res = await apiFetch("/stats");
      if (res.ok) {
        const data = await res.json();
        setAlertCount(typeof data.high_risk_alerts === "number" ? data.high_risk_alerts : 0);
      }
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 8000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const allNavItems = [
    {
      id: "monitor",
      path: "/monitor",
      label: "Live Monitor",
      icon: MonitorPlay,
      roles: null,
    },
    {
      id: "cameras",
      path: "/cameras",
      label: "Cameras",
      icon: Camera,
      roles: null,
    },
    {
      id: "incidents",
      path: "/incidents",
      label: "Incidents",
      icon: AlertCircle,
      roles: null,
    },
    {
      id: "analytics",
      path: "/analytics",
      label: "Analytics",
      icon: BarChart3,
      roles: null,
    },
    {
      id: "performance",
      path: "/performance",
      label: "Model Performance",
      icon: BarChart3,
      roles: null,
    },
    {
      id: "users",
      path: "/users",
      label: "Operators",
      icon: Users,
      roles: ["admin"],
    },
  ];

  const navItems = allNavItems.filter((item) => {
    if (!item.roles) return true;
    return item.roles.includes(role || "");
  });

  const pipelineActive = status?.pipeline_running ?? false;

  return (
    <div
      className={`flex flex-col h-screen ${className}`}
      style={{ background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)' }}
    >
      {/* Logo */}
      <div className="p-4" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'var(--accent-dim)', border: '1px solid rgba(59, 130, 246, 0.2)' }}
          >
            <Shield className="w-4 h-4" style={{ color: 'var(--accent)' }} />
          </div>
          <div>
            <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)', letterSpacing: '0.02em' }}>
              ThreatSense
            </h2>
            <p className="text-[10px]" style={{ color: 'var(--text-dim)' }}>
              AI Surveillance
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-2 space-y-0.5 mt-2">
        <p className="px-3 mb-2 text-[10px] font-medium uppercase" style={{ color: 'var(--text-dim)', letterSpacing: '0.08em' }}>
          Navigation
        </p>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname?.startsWith(item.path);
          const showBadge = item.id === "monitor" && alertCount > 0;

          return (
            <Link
              key={item.id}
              href={item.path}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md transition-all text-sm relative"
              style={{
                background: isActive ? 'var(--accent-dim)' : 'transparent',
                color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
                fontWeight: isActive ? 500 : 400,
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              }}
            >
              <Icon className="w-4 h-4" />
              <span>{item.label}</span>
              {showBadge && (
                <span
                  className="ml-auto flex items-center justify-center text-[9px] font-bold rounded-full"
                  style={{
                    minWidth: '18px',
                    height: '18px',
                    padding: '0 5px',
                    background: 'var(--danger)',
                    color: 'white',
                    boxShadow: '0 0 6px rgba(239,68,68,0.4)',
                  }}
                >
                  {alertCount > 99 ? "99+" : alertCount}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Pipeline Status Footer — data-driven */}
      <div className="p-3" style={{ borderTop: '1px solid var(--border)' }}>
        <div className="p-3 rounded-md" style={{ background: 'var(--bg-primary)', border: '1px solid var(--border)' }}>
          <div className="flex items-center gap-1.5 mb-1">
            <div className={`status-dot ${pipelineActive ? 'status-dot-success animate-pulse-dot' : 'status-dot-muted'}`} />
            <span className="text-[11px] font-medium" style={{ color: pipelineActive ? 'var(--success)' : 'var(--text-muted)' }}>
              {pipelineActive ? "Pipeline Active" : "Pipeline Offline"}
            </span>
          </div>
          <p className="text-[10px]" style={{ color: 'var(--text-dim)' }}>
            {pipelineActive ? "AI detection running" : "No active pipeline"}
          </p>
        </div>
      </div>
    </div>
  );
}

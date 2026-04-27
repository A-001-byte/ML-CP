"use client";

import { useState, useEffect, useCallback } from "react";
import { LogOut, User } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";

interface SystemStatus {
  pipeline_running: boolean;
  camera_connected: boolean;
  fps: number;
}

export function Header() {
  const { role, username, logout } = useAuth();
  const [currentTime, setCurrentTime] = useState<Date | null>(null);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    setCurrentTime(new Date());
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000/api";
      const res = await fetch(`${API_BASE}/system_status`);
      if (res.ok) {
        const data = await res.json();
        setSystemStatus(data);
      }
    } catch {
      setSystemStatus(null);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const IST = "Asia/Kolkata";

  const formatDate = (date: Date) =>
    date.toLocaleDateString("en-IN", {
      timeZone: IST,
      year: "numeric",
      month: "short",
      day: "numeric",
    });

  const formatTime = (date: Date) =>
    date.toLocaleTimeString("en-IN", {
      timeZone: IST,
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });

  const pipelineRunning = systemStatus?.pipeline_running ?? false;
  const cameraConnected = systemStatus?.camera_connected ?? false;

  return (
    <div className="px-5 py-2.5" style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between">
        {/* Left: System status indicators — data-driven */}
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className={`status-dot ${pipelineRunning ? 'status-dot-success animate-pulse-dot' : 'status-dot-muted'}`} />
            <span className="data-label" style={{ fontSize: 10 }}>
              {pipelineRunning ? "Pipeline Active" : "Pipeline Offline"}
            </span>
          </div>

          <div className="h-3 w-px" style={{ background: 'var(--border)' }} />

          <div className="flex items-center gap-1.5">
            <div className={`status-dot ${cameraConnected ? 'status-dot-success' : 'status-dot-muted'}`} />
            <span className="data-label" style={{ fontSize: 10, color: cameraConnected ? 'var(--success)' : 'var(--text-muted)' }}>
              {cameraConnected ? "Camera Connected" : "Camera Offline"}
            </span>
          </div>

          {systemStatus?.fps ? (
            <>
              <div className="h-3 w-px" style={{ background: 'var(--border)' }} />
              <span className="data-label" style={{ fontSize: 10 }}>
                {systemStatus.fps} FPS
              </span>
            </>
          ) : null}
        </div>

        {/* Right: Date/Time + User + Logout */}
        <div className="flex items-center gap-3">
          {/* Date/Time */}
          <div className="flex items-center gap-1.5" style={{ fontFamily: 'var(--font-mono)' }}>
            <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              {currentTime ? formatDate(currentTime) : "—"}
            </span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>·</span>
            <span style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
              {currentTime ? formatTime(currentTime) : "--:--:--"}
            </span>
          </div>

          <div className="h-3 w-px" style={{ background: 'var(--border)' }} />

          {/* User badge */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded" style={{ background: 'var(--accent-dim)', border: '1px solid rgba(59, 130, 246, 0.15)' }}>
            <User className="w-3 h-3" style={{ color: 'var(--accent)' }} />
            <span style={{ color: 'var(--accent)', fontSize: 11, fontWeight: 500 }}>
              {username || "operator"} · {role || "viewer"}
            </span>
          </div>

          {/* Sign Out */}
          <button
            onClick={logout}
            className="flex items-center gap-1 px-2.5 py-1 rounded text-xs transition-colors"
            style={{
              background: 'var(--danger-dim)',
              border: '1px solid var(--danger-border)',
              color: 'var(--danger)',
              cursor: 'pointer',
            }}
            title="Sign out"
          >
            <LogOut className="w-3 h-3" />
            <span style={{ fontSize: 11, fontWeight: 500 }}>Sign Out</span>
          </button>
        </div>
      </div>
    </div>
  );
}

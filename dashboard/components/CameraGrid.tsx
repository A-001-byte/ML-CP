"use client";

import { useCallback, useEffect, useState } from "react";
import { Camera, Maximize2, VideoOff, X } from "lucide-react";
import { getCameraFeedUrl, getCameras } from "@/lib/api";

interface CameraInfo {
  id: string;
  location: string;
  source: string;
  running: boolean;
  fps: number;
  frame_count: number;
  last_frame_age_s: number | null;
  online: boolean;
}

function cameraFromUnknown(value: unknown): CameraInfo | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const id = typeof record.id === "string" ? record.id : null;
  if (!id) return null;
  return {
    id,
    location: typeof record.location === "string" ? record.location : "Unknown",
    source: typeof record.source === "string" ? record.source : "",
    running: Boolean(record.running),
    fps: typeof record.fps === "number" ? record.fps : 0,
    frame_count: typeof record.frame_count === "number" ? record.frame_count : 0,
    last_frame_age_s: typeof record.last_frame_age_s === "number" ? record.last_frame_age_s : null,
    online: Boolean(record.online),
  };
}

function EmptyState() {
  return (
    <div className="panel">
      <div className="panel-body text-center py-12">
        <VideoOff className="w-10 h-10 mx-auto mb-4" style={{ color: "var(--text-muted)" }} />
        <h2 className="text-base font-semibold mb-2" style={{ color: "var(--text-primary)" }}>No cameras configured</h2>
        <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>Register cameras through the environment before starting the backend.</p>
        <pre className="text-left text-xs rounded p-4 overflow-x-auto mx-auto max-w-3xl" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
{`CAMERAS_JSON='[
  {"id":"front-door","source":0,"location":"Main Entrance"},
  {"id":"back-lot","source":"rtsp://192.168.1.100/stream","location":"Back Lot"}
]'`}
        </pre>
        <p className="text-xs mt-4" style={{ color: "var(--text-dim)" }}>The default webcam stream is always available at /api/video_feed.</p>
      </div>
    </div>
  );
}

export default function CameraGrid() {
  const [cameras, setCameras] = useState<CameraInfo[]>([]);
  const [selected, setSelected] = useState<CameraInfo | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchCameras = useCallback(async () => {
    try {
      const payload = await getCameras();
      const list = Array.isArray(payload)
        ? payload.map(cameraFromUnknown).filter((camera): camera is CameraInfo => camera !== null)
        : [];
      setCameras(list);
    } catch (err) {
      console.error("Failed to load cameras", err);
      setCameras([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCameras();
    const timer = window.setInterval(fetchCameras, 10000);
    return () => window.clearInterval(timer);
  }, [fetchCameras]);

  return (
    <div className="flex-1 overflow-auto p-6" style={{ background: "var(--bg-primary)" }}>
      <div className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Cameras</h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>All registered camera feeds and health status</p>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map((item) => <div key={item} className="panel aspect-video animate-pulse" />)}
        </div>
      ) : cameras.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {cameras.map((camera) => (
            <button
              key={camera.id}
              type="button"
              onClick={() => setSelected(camera)}
              className="panel text-left overflow-hidden transition-transform hover:-translate-y-0.5"
            >
              <div className="relative aspect-video" style={{ background: "#0a0e14" }}>
                <img src={getCameraFeedUrl(camera.id)} alt={`${camera.id} feed`} className="w-full h-full object-cover" />
                {!camera.online && (
                  <div className="absolute inset-0 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.62)", color: "var(--text-muted)" }}>
                    Offline
                  </div>
                )}
                <div className="absolute top-2 right-2 rounded px-2 py-1 flex items-center gap-1" style={{ background: "rgba(15,20,25,0.88)", border: "1px solid var(--border)" }}>
                  <Maximize2 className="w-3 h-3" style={{ color: "var(--accent)" }} />
                </div>
              </div>
              <div className="p-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`status-dot ${camera.online ? "status-dot-success" : "status-dot-muted"}`} />
                    <span className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{camera.id}</span>
                  </div>
                  <p className="text-xs mt-1 truncate" style={{ color: "var(--text-muted)" }}>{camera.location}</p>
                </div>
                <span className="badge badge-low">{camera.fps.toFixed(1)} FPS</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 p-4 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.82)", backdropFilter: "blur(4px)" }}>
          <div className="w-full max-w-6xl rounded-lg overflow-hidden" style={{ background: "var(--bg-panel)", border: "1px solid var(--border-strong)" }}>
            <div className="panel-header">
              <div className="flex items-center gap-2">
                <Camera className="w-4 h-4" style={{ color: "var(--accent)" }} />
                <span className="panel-title">{selected.id} - {selected.location}</span>
              </div>
              <button type="button" onClick={() => setSelected(null)} className="btn btn-ghost" aria-label="Close camera">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="relative aspect-video" style={{ background: "#0a0e14" }}>
              <img src={getCameraFeedUrl(selected.id)} alt={`${selected.id} full-screen feed`} className="w-full h-full object-contain" />
              {!selected.online && (
                <div className="absolute inset-0 flex items-center justify-center text-lg" style={{ background: "rgba(0,0,0,0.62)", color: "var(--text-muted)" }}>
                  Offline
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

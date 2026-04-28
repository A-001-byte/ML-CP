"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, ArrowUp, Check, Download, Eye, Film, Filter, Search, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { escalateIncident, getApiToken, getIncidentClipUrl, getIncidents, resolveIncident } from "@/lib/api";
import { useWebSocket, WSMessage } from "@/lib/socket";

interface Incident {
  id: number;
  title: string;
  description: string;
  event_type: string;
  location: string;
  risk_level: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  clip_path: string | null;
  person_id: string | null;
}

function getRiskBadgeClass(risk: string) {
  const r = (risk || "").toLowerCase();
  if (r === "high" || r === "critical") return "badge badge-critical";
  if (r === "medium" || r === "suspicious") return "badge badge-medium";
  if (r === "low") return "badge badge-low";
  return "badge badge-low";
}

function getStatusBadgeClass(status: string) {
  const s = (status || "").toLowerCase();
  if (s === "resolved") return "badge badge-low";
  if (s === "under review") return "badge badge-medium";
  if (s === "escalated") return "badge badge-critical";
  if (s === "false alarm") return "badge";
  if (s === "open") return "badge badge-medium";
  return "badge";
}

function incidentFromMessage(data: Record<string, unknown>): Incident | null {
  if (typeof data.id !== "number") return null;
  return {
    id: data.id,
    title: typeof data.title === "string" ? data.title : "Incident",
    description: typeof data.description === "string" ? data.description : "",
    event_type: typeof data.event_type === "string" ? data.event_type : "Incident",
    location: typeof data.location === "string" ? data.location : "Main Entrance",
    risk_level: typeof data.risk_level === "string" ? data.risk_level : "low",
    status: typeof data.status === "string" ? data.status : "Open",
    created_at: typeof data.created_at === "string" ? data.created_at : "",
    resolved_at: typeof data.resolved_at === "string" ? data.resolved_at : null,
    clip_path: typeof data.clip_path === "string" ? data.clip_path : null,
    person_id: typeof data.person_id === "string" ? data.person_id : null,
  };
}

export default function IncidentHistory() {
  const searchParams = useSearchParams();
  const initialSearch = searchParams.get("search") || "";
  const modalRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [riskFilter, setRiskFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all-status");
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [clipError, setClipError] = useState(false);

  const fetchIncidents = useCallback(async () => {
    try {
      const data = await getIncidents();
      setIncidents(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      console.error("Failed to fetch incidents", err);
      setError("Failed to connect to backend");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIncidents();
  }, [fetchIncidents]);

  const handleWSMessage = useCallback((msg: WSMessage) => {
    if (msg.type === "new_incident" && msg.data) {
      const incident = incidentFromMessage(msg.data);
      if (incident) setIncidents((prev) => [incident, ...prev]);
    }
  }, []);

  useWebSocket(handleWSMessage);

  useEffect(() => {
    const urlSearch = searchParams.get("search");
    if (urlSearch) setSearchQuery(urlSearch);
  }, [searchParams]);

  useEffect(() => {
    if (!selectedIncident) return;

    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeModal();
        return;
      }
      if (event.key !== "Tab" || !modalRef.current) return;

      const focusable = Array.from(
        modalRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), video, [tabindex]:not([tabindex="-1"])'
        )
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [selectedIncident]);

  const handleResolve = async (incidentId: number) => {
    setActionLoading(incidentId);
    try {
      await resolveIncident(incidentId);
      await fetchIncidents();
      setError(null);
      if (selectedIncident?.id === incidentId) {
        setSelectedIncident((prev) => prev ? { ...prev, status: "Resolved" } : null);
      }
    } catch (err) {
      console.error("Failed to resolve incident:", err);
      setError(err instanceof Error ? err.message : "Failed to resolve incident");
    } finally {
      setActionLoading(null);
    }
  };

  const handleEscalate = async (incidentId: number) => {
    setActionLoading(incidentId);
    try {
      await escalateIncident(incidentId);
      await fetchIncidents();
      setError(null);
      if (selectedIncident?.id === incidentId) {
        setSelectedIncident((prev) => prev ? { ...prev, status: "Escalated" } : null);
      }
    } catch (err) {
      console.error("Failed to escalate incident:", err);
      setError(err instanceof Error ? err.message : "Failed to escalate incident");
    } finally {
      setActionLoading(null);
    }
  };

  const openModal = (incident: Incident) => {
    setSelectedIncident(incident);
    setClipError(false);
  };

  function closeModal() {
    setSelectedIncident(null);
    setClipError(false);
  }

  const filtered = incidents.filter((inc) => {
    const search = searchQuery.toLowerCase();
    const matchSearch =
      !search ||
      inc.title?.toLowerCase().includes(search) ||
      inc.event_type?.toLowerCase().includes(search) ||
      inc.description?.toLowerCase().includes(search);
    const matchRisk = riskFilter === "all" || inc.risk_level?.toLowerCase() === riskFilter;
    const matchStatus =
      statusFilter === "all-status" ||
      inc.status?.toLowerCase().replace(/\s+/g, "-") === statusFilter;
    return matchSearch && matchRisk && matchStatus;
  });

  return (
    <div className="flex-1 overflow-auto" style={{ background: "var(--bg-primary)" }}>
      <div className="p-6">
        <div className="mb-6">
          <h1 className="text-lg font-semibold" style={{ color: "var(--text-primary)" }}>Incident History</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>Review and analyze detection events</p>
        </div>

        {error && (
          <div className="mb-4 p-4 rounded-lg" style={{ background: "var(--warning-dim)", border: "1px solid rgba(245,158,11,0.3)" }}>
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" style={{ color: "var(--warning)" }} />
              <p className="text-sm" style={{ color: "var(--warning)" }}>{error}</p>
            </div>
          </div>
        )}

        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">Incident Log</span>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000/api"}/incidents/export/csv${getApiToken() ? `?token=${encodeURIComponent(getApiToken()!)}` : ""}`}
              download
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs transition-colors"
              style={{ background: "var(--accent-dim)", border: "1px solid rgba(59,130,246,0.2)", color: "var(--accent)" }}
            >
              <Download className="w-3 h-3" />
              Export CSV
            </a>
          </div>
          <div className="p-4">
            <div className="flex flex-wrap items-center gap-3 mb-4">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-dim)" }} />
                <input
                  aria-label="Search incidents"
                  placeholder="Search incidents..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10 pr-4 py-2.5 w-full rounded-md text-sm focus:outline-none transition-colors"
                  style={{ background: "var(--bg-primary)", border: "1px solid var(--border-strong)", color: "var(--text-primary)" }}
                />
              </div>
              <div className="relative">
                <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" style={{ color: "var(--text-dim)" }} />
                <select
                  aria-label="Filter by risk level"
                  value={riskFilter}
                  onChange={(e) => setRiskFilter(e.target.value)}
                  className="w-44 pl-10 pr-4 py-2.5 rounded-md text-xs focus:outline-none transition-colors appearance-none cursor-pointer"
                  style={{ background: "var(--bg-primary)", border: "1px solid var(--border-strong)", color: "var(--text-secondary)" }}
                >
                  <option value="all">All Risk Levels</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
              <select
                aria-label="Filter by status"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="w-44 px-4 py-2.5 rounded-md text-xs focus:outline-none transition-colors appearance-none cursor-pointer"
                style={{ background: "var(--bg-primary)", border: "1px solid var(--border-strong)", color: "var(--text-secondary)" }}
              >
                <option value="all-status">All Status</option>
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
                <option value="under-review">Under Review</option>
                <option value="escalated">Escalated</option>
                <option value="false-alarm">False Alarm</option>
              </select>
            </div>

            {loading ? (
              <div className="space-y-2">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="animate-pulse flex items-center gap-4 p-3 rounded" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                    <div className="h-4 rounded w-24" style={{ background: "var(--bg-elevated)" }} />
                    <div className="h-4 rounded w-32" style={{ background: "var(--bg-elevated)" }} />
                    <div className="h-4 rounded w-20" style={{ background: "var(--bg-elevated)" }} />
                    <div className="h-4 rounded w-16" style={{ background: "var(--bg-elevated)" }} />
                    <div className="h-4 rounded w-16" style={{ background: "var(--bg-elevated)" }} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-md overflow-x-auto" style={{ border: "1px solid var(--border)" }}>
                <table className="w-full text-left border-collapse min-w-[900px]">
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border)" }}>
                      <th className="p-4 table-header">Timestamp</th>
                      <th className="p-4 table-header">Event Type</th>
                      <th className="p-4 table-header">Location</th>
                      <th className="p-4 table-header">Risk Level</th>
                      <th className="p-4 table-header">Status</th>
                      <th className="p-4 table-header">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((incident) => {
                      const isResolved = incident.status?.toLowerCase() === "resolved";
                      const isEscalated = incident.status?.toLowerCase() === "escalated";
                      return (
                        <tr key={incident.id} className="transition-colors last:border-0" style={{ borderBottom: "1px solid var(--border)" }}>
                          <td className="p-4 text-xs font-mono" style={{ color: "var(--text-muted)" }}>{incident.created_at}</td>
                          <td className="p-4 text-xs" style={{ color: "var(--text-primary)" }}>
                            {incident.event_type || incident.title}
                            {incident.clip_path && (
                              <span
                                className="inline-flex items-center gap-1 ml-2 px-1.5 py-0.5 rounded text-[9px] font-medium"
                                style={{ background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid rgba(59,130,246,0.2)" }}
                                title="Video clip available"
                              >
                                <Film className="w-2.5 h-2.5" />
                                Clip
                              </span>
                            )}
                          </td>
                          <td className="p-4 text-xs" style={{ color: "var(--text-muted)" }}>{incident.location}</td>
                          <td className="p-4"><span className={getRiskBadgeClass(incident.risk_level)}>{incident.risk_level?.toUpperCase()}</span></td>
                          <td className="p-4"><span className={getStatusBadgeClass(incident.status)}>{incident.status}</span></td>
                          <td className="p-4">
                            <div className="flex flex-wrap items-center gap-2">
                              <button onClick={() => openModal(incident)} className="btn btn-ghost" title="View details">
                                <Eye className="w-3 h-3" />
                                View
                              </button>
                              {incident.clip_path && (
                                <button
                                  onClick={() => openModal(incident)}
                                  className="btn"
                                  style={{ color: "var(--accent)", borderColor: "rgba(59,130,246,0.28)", background: "var(--accent-dim)" }}
                                  title="View incident clip"
                                >
                                  ▶ View Clip
                                </button>
                              )}
                              {!isResolved && (
                                <button onClick={() => handleResolve(incident.id)} disabled={actionLoading === incident.id} className="btn btn-success" title="Resolve incident">
                                  <Check className="w-3 h-3" />
                                  {actionLoading === incident.id ? "..." : "Resolve"}
                                </button>
                              )}
                              {!isResolved && !isEscalated && (
                                <button onClick={() => handleEscalate(incident.id)} disabled={actionLoading === incident.id} className="btn btn-danger" title="Escalate incident">
                                  <ArrowUp className="w-3 h-3" />
                                  {actionLoading === incident.id ? "..." : "Escalate"}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={6} className="p-8 text-center text-sm" style={{ color: "var(--text-muted)" }}>No incidents matching criteria</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {selectedIncident && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4" style={{ background: "rgba(0,0,0,0.76)", backdropFilter: "blur(4px)" }}>
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="incident-dialog-title"
            className="max-w-4xl w-full max-h-[92vh] overflow-y-auto rounded-lg"
            style={{ background: "var(--bg-panel)", border: "1px solid var(--border-strong)" }}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: "1px solid var(--border)" }}>
              <div className="flex items-center gap-3 min-w-0">
                <h2 id="incident-dialog-title" className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>{selectedIncident.title}</h2>
                <span className={getRiskBadgeClass(selectedIncident.risk_level)}>{selectedIncident.risk_level?.toUpperCase()}</span>
              </div>
              <button ref={closeButtonRef} onClick={closeModal} className="btn btn-ghost" aria-label="Close incident clip">
                ×
              </button>
            </div>

            <div className="p-4 space-y-4">
              {!clipError && selectedIncident.clip_path ? (
                <video
                  key={selectedIncident.id}
                  controls
                  autoPlay
                  preload="metadata"
                  className="w-full rounded-md"
                  style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
                  src={getIncidentClipUrl(selectedIncident.id)}
                  onError={() => setClipError(true)}
                />
              ) : (
                <div className="rounded-md p-6 text-sm text-center" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-muted)" }}>
                  Clip not available
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {[
                  ["Timestamp", selectedIncident.created_at],
                  ["Location", selectedIncident.location],
                  ["Event Type", selectedIncident.event_type],
                  ["Risk Level", selectedIncident.risk_level],
                  ["Status", selectedIncident.status],
                  ["Person ID", selectedIncident.person_id || "Unknown"],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-md p-3" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                    <label className="data-label block mb-1">{label}</label>
                    <p className="text-sm" style={{ color: "var(--text-primary)" }}>{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

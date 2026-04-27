/**
 * api.ts
 * ──────
 * HTTP client for the ThreatSense-AI backend.
 *
 * Auth strategy:
 *   Primary  — HttpOnly cookie (ts_token), sent automatically via credentials:'include'.
 *              The browser never exposes this cookie to JS, eliminating XSS token theft.
 *   Fallback — in-memory Bearer token (set by AuthProvider after login).
 *              Used for cross-port dev environments where SameSite cookies may not flow.
 *
 * The token is NEVER written to localStorage.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:5000/api";

// In-memory token — set by AuthProvider, never persisted to storage.
let _inMemToken: string | null = null;

export function setApiToken(token: string | null): void {
  _inMemToken = token;
}

export function getApiToken(): string | null {
  return _inMemToken;
}

export function withAuthToken(url: string): string {
  return _inMemToken
    ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(_inMemToken)}`
    : url;
}

export function getApiBase(): string {
  return API_BASE;
}

// ── Auth error handler ────────────────────────────────────────────────────────

function handleAuthError(): void {
  if (typeof window === "undefined") return;
  // Clear display state only (role/username cached for UX)
  localStorage.removeItem("role");
  localStorage.removeItem("username");
  // Clear in-memory token
  _inMemToken = null;
  // Ask backend to clear the HttpOnly cookie
  fetch(`${API_BASE}/logout`, { method: "POST", credentials: "include" }).catch(
    () => {}
  );
  window.location.href = "/login";
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────

export async function apiFetch(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  // Attach in-memory token as Bearer fallback (cross-port dev)
  if (_inMemToken) {
    headers.set("Authorization", `Bearer ${_inMemToken}`);
  }

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
      credentials: "include", // send HttpOnly cookie automatically
    });

    if (res.status === 401) {
      res
        .clone()
        .json()
        .catch(() => ({}))
        .then((d) =>
          console.warn("[api] 401:", d?.detail || d?.error || "Unauthorized")
        );
      handleAuthError();
    }

    return res;
  } catch (err) {
    console.error("[api] network error", err);
    return new Response(
      JSON.stringify({
        error: `Network error. Is the backend running at ${API_BASE}?`,
      }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }
}

// ── Auth endpoints ────────────────────────────────────────────────────────────

export async function login(
  username: string,
  password: string
): Promise<{ token: string; role: string; username: string } | { error: string }> {
  const res = await fetch(`${API_BASE}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    credentials: "include", // receive the HttpOnly cookie
  });
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {});
}

export async function getMe(): Promise<{
  username: string;
  role: string;
} | null> {
  try {
    const res = await fetch(`${API_BASE}/me`, {
      credentials: "include",
      headers: _inMemToken
        ? { Authorization: `Bearer ${_inMemToken}` }
        : {},
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// ── Data endpoints ────────────────────────────────────────────────────────────

export async function getAlerts(limit = 50) {
  const res = await apiFetch(`/alerts?limit=${limit}`);
  return res.json();
}

export async function getIncidents(status?: string) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await apiFetch(`/incidents${qs}`);
  return res.json();
}

export async function getStats() {
  const res = await apiFetch("/stats");
  return res.json();
}

export async function getUsers() {
  const res = await apiFetch("/users");
  return res.json();
}

export async function bulkDismissAlerts() {
  const res = await apiFetch("/alerts/bulk-dismiss", { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

// ── Alert actions ─────────────────────────────────────────────────────────────

export async function dismissAlert(id: number) {
  const res = await apiFetch(`/alerts/${id}/dismiss`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function acknowledgeAlert(id: number) {
  const res = await apiFetch(`/alerts/${id}/acknowledge`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function resolveAlert(id: number) {
  const res = await apiFetch(`/alerts/${id}/resolve`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

// ── Incident actions ──────────────────────────────────────────────────────────

export async function getIncident(id: number) {
  const res = await apiFetch(`/incidents/${id}`);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function resolveIncident(id: number) {
  const res = await apiFetch(`/incidents/${id}/resolve`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function escalateIncident(id: number) {
  const res = await apiFetch(`/incidents/${id}/escalate`, { method: "POST" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export function getIncidentClipUrl(id: number): string {
  return withAuthToken(`${API_BASE}/incidents/${id}/clip`);
}

export interface ZonePoint {
  x: number;
  y: number;
}

export async function getDetectionZone(): Promise<{ points: ZonePoint[] }> {
  const res = await apiFetch("/detection_zone");
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
  return res.json();
}

export async function updateDetectionZone(points: ZonePoint[]) {
  const res = await apiFetch("/detection_zone", {
    method: "PUT",
    body: JSON.stringify({ points }),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
  return res.json();
}

export async function clearDetectionZone() {
  const res = await apiFetch("/detection_zone", { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
  return res.json();
}

export async function getModelPerformance() {
  const res = await apiFetch("/model_performance");
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Failed");
  return res.json();
}

export function getModelPerformancePlotUrl(filename: string): string {
  return withAuthToken(`${API_BASE}/model_performance/${encodeURIComponent(filename)}`);
}

export async function getAnalytics() {
  const res = await apiFetch("/analytics");
  return res.json();
}

// ── User management ───────────────────────────────────────────────────────────

export interface CreateUserData {
  username: string;
  password: string;
  role: "admin" | "operator" | "viewer" | "security";
}

export interface UpdateUserData {
  username?: string;
  password?: string;
  role?: "admin" | "operator" | "viewer" | "security";
  status?: "Active" | "Inactive";
}

export async function createUser(data: CreateUserData) {
  const res = await apiFetch("/users", {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function updateUser(id: number, data: UpdateUserData) {
  const res = await apiFetch(`/users/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

export async function deleteUser(id: number) {
  const res = await apiFetch(`/users/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "Failed");
  return res.json();
}

// ── Camera endpoints ──────────────────────────────────────────────────────────

export async function getCameras() {
  const res = await apiFetch("/cameras");
  return res.json();
}

/** Build MJPEG stream URL for a specific camera (includes token param for cross-port). */
export function getCameraFeedUrl(camId: string): string {
  const base = `${API_BASE}/cameras/${camId}/feed`;
  return _inMemToken ? `${base}?token=${encodeURIComponent(_inMemToken)}` : base;
}

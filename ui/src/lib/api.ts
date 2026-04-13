/**
 * API client for Cambium server.
 *
 * Base URL is configurable via ?api= query parameter for staging inspection.
 * Defaults to /api which Vite proxies to the Cambium server in dev,
 * and FastAPI serves directly in production.
 */

const params = new URLSearchParams(window.location.search);
// In dev, Vite proxies /api/* → backend with the prefix stripped.
// In production, the UI is served by FastAPI directly — no prefix needed.
const defaultBase = import.meta.env.DEV ? "/api" : "";
export const API_BASE = params.get("api") || defaultBase;

export async function apiGet<T>(
  path: string,
  options?: { params?: Record<string, string> },
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (options?.params) {
    for (const [k, v] of Object.entries(options.params)) {
      if (v !== undefined && v !== null) {
        url.searchParams.set(k, v);
      }
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`GET ${path}: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(`POST ${path}: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(`DELETE ${path}: ${res.status} ${res.statusText}`);
  }
}

/** Build a WebSocket URL for the terminal bridge. */
export function terminalWsUrl(path: string): string {
  const base = API_BASE.startsWith("http")
    ? API_BASE.replace(/^http/, "ws")
    : `ws://${window.location.host}${API_BASE}`;
  return `${base}${path}`;
}

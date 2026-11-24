// RepoCrew typed API client. All calls go to the same origin (in dev, Vite
// proxies /api and /ws to the FastAPI backend on :8000).
import type { Health, Issue, Metrics, PullRequestInfo, RunDetail, RunEvent } from "./types";

const BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/+$/, "") || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  issues: () => request<Issue[]>("/api/issues"),
  issue: (id: number) => request<Issue & { runs: { id: number; status: string }[] }>(`/api/issues/${id}`),
  runIssue: (id: number) =>
    request<{ run_id: number }>(`/api/issues/${id}/run`, { method: "POST" }),
  runAll: () => request<{ run_ids: number[] }>("/api/run-all", { method: "POST" }),
  run: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  approve: (id: number, comment?: string) =>
    request<{ status: string; pull_request: PullRequestInfo }>(`/api/runs/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ comment: comment || null }),
    }),
  reject: (id: number, comment?: string) =>
    request<{ status: string }>(`/api/runs/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ comment: comment || null }),
    }),
  metrics: () => request<Metrics>("/api/metrics"),
};

export function runStreamUrl(runId: number): string {
  const base = (import.meta.env.VITE_API_URL as string | undefined)?.trim();
  if (base && (base.startsWith("http://") || base.startsWith("https://"))) {
    const url = new URL(base);
    const proto = url.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${url.host}/ws/runs/${runId}`;
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws/runs/${runId}`;
}

export interface StreamMessage {
  kind: "backlog" | "event";
  events?: RunEvent[];
  event?: RunEvent;
}

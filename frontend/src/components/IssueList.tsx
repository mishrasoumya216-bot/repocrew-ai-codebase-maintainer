// RepoCrew issue list (left column): triage/status badges, labels,
// per-issue "Run RepoCrew" buttons and a "Run all" control.
import { ListChecks, Play, RefreshCw } from "lucide-react";
import type { Issue } from "../types";

export function statusBadge(status: string | null): { text: string; cls: string } {
  switch (status) {
    case "AWAITING_HUMAN":
      return { text: "Awaiting review", cls: "!border-warning/50 !text-warning" };
    case "PR_READY":
    case "PR_CREATED":
      return { text: "PR ready", cls: "!border-success/50 !text-success" };
    case "OUT_OF_SCOPE":
      return { text: "Out of scope", cls: "!border-muted/40 !text-muted" };
    case "BLOCKED_BY_GATE":
      return { text: "Blocked", cls: "!border-danger/50 !text-danger" };
    case "STOPPED_NEEDS_HUMAN":
    case "FAILED":
      return { text: "Stopped", cls: "!border-danger/50 !text-danger" };
    case "REJECTED_BY_HUMAN":
      return { text: "Rejected", cls: "!border-danger/50 !text-danger" };
    case "RUNNING":
    case "QUEUED":
      return { text: "Running", cls: "!border-accent/50 !text-accent" };
    default:
      return { text: "Not run yet", cls: "" };
  }
}

interface Props {
  issues: Issue[];
  selectedId: number | null;
  onSelect: (issue: Issue) => void;
  onRunIssue: (issue: Issue) => void;
  onRunAll: () => void;
  busy: boolean;
  error: string | null;
  onRetryLoad: () => void;
}

export default function IssueList({
  issues, selectedId, onSelect, onRunIssue, onRunAll, busy, error, onRetryLoad,
}: Props) {
  const anyActive = issues.some(
    (i) => i.latest_run_status === "RUNNING" || i.latest_run_status === "QUEUED",
  );
  return (
    <aside className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-bold uppercase tracking-wider text-muted">
          Seeded issues
        </h2>
        <button
          className="btn-primary"
          onClick={onRunAll}
          disabled={busy || anyActive}
          title="Runs all in-scope-candidate issues sequentially"
        >
          <ListChecks size={14} /> Run all
        </button>
      </div>
      {error && (
        <div className="card border-danger/40 p-3 text-[12px] text-danger">
          Could not load issues: {error}{" "}
          <button className="underline" onClick={onRetryLoad}>
            <RefreshCw size={11} className="inline" /> retry
          </button>
        </div>
      )}
      {!error && issues.length === 0 && (
        <div className="card p-4 text-[13px] text-muted">
          {busy ? "Loading issues…" : "No issues found. The backend seeds five issues on first start."}
        </div>
      )}
      <div className="flex flex-col gap-2">
        {issues.map((issue) => {
          const badge = statusBadge(issue.latest_run_status);
          const active = issue.latest_run_status === "RUNNING" || issue.latest_run_status === "QUEUED";
          return (
            <button
              key={issue.id}
              onClick={() => onSelect(issue)}
              className={`card group p-3 text-left transition-all duration-150 hover:border-accent/50 ${
                selectedId === issue.id ? "border-accent/70 shadow-[0_0_0_1px_rgba(34,211,238,0.35)]" : ""
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-[13px] font-semibold leading-snug">
                  <span className="mr-1 font-mono text-[11px] text-muted">#{issue.number}</span>
                  {issue.title}
                </div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                {issue.labels.map((l) => (
                  <span key={l} className="chip">{l}</span>
                ))}
                <span className={`chip ${badge.cls}`}>{badge.text}</span>
                <span className="ml-auto" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn-ghost !px-2 !py-1 !text-[11px]"
                    disabled={busy || active}
                    onClick={() => onRunIssue(issue)}
                    title={active ? "Run in progress" : "Start a RepoCrew run for this issue"}
                  >
                    <Play size={11} /> Run RepoCrew
                  </button>
                </span>
              </div>
            </button>
          );
        })}
      </div>
      <p className="px-1 text-[11px] leading-relaxed text-muted/80">
        RepoCrew never merges: every run ends with a human decision. Triage may skip
        out-of-scope issues before any code is written.
      </p>
    </aside>
  );
}

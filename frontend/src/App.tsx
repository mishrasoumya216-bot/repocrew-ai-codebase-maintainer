// RepoCrew single-page app: top bar, metrics strip, seeded issues (left) and
// the selected run (main area).
import { useCallback, useEffect, useState } from "react";
import { Bot, Play } from "lucide-react";
import { api } from "./api";
import type { Health, Issue, Metrics } from "./types";
import TopBar from "./components/TopBar";
import MetricsStrip from "./components/MetricsStrip";
import IssueList from "./components/IssueList";
import RunView from "./components/RunView";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [selectedIssueId, setSelectedIssueId] = useState<number | null>(null);
  const [pendingRuns, setPendingRuns] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);
  const [issuesError, setIssuesError] = useState<string | null>(null);
  const [fatalError, setFatalError] = useState<string | null>(null);

  const loadIssues = useCallback(async () => {
    try {
      const data = await api.issues();
      setIssues(data);
      setIssuesError(null);
    } catch (e) {
      setIssuesError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const loadMetrics = useCallback(async () => {
    try {
      setMetrics(await api.metrics());
    } catch {
      /* metrics card shows placeholders until the backend answers */
    }
  }, []);

  const refreshAll = useCallback(() => {
    void loadIssues();
    void loadMetrics();
  }, [loadIssues, loadMetrics]);

  useEffect(() => {
    (async () => {
      try {
        setHealth(await api.health());
        setFatalError(null);
      } catch (e) {
        setFatalError(e instanceof Error ? e.message : String(e));
      }
      await loadIssues();
      await loadMetrics();
      setSelectedIssueId((cur) => cur);
    })();
  }, [loadIssues, loadMetrics]);

  // default-select the first issue once loaded
  useEffect(() => {
    if (selectedIssueId === null && issues.length > 0) {
      setSelectedIssueId(issues[0].id);
    }
  }, [issues, selectedIssueId]);

  // keep badges/metrics fresh while runs progress (e.g. during Run all)
  useEffect(() => {
    const t = window.setInterval(refreshAll, 2500);
    return () => window.clearInterval(t);
  }, [refreshAll]);

  const runIssue = async (issue: Issue) => {
    setBusy(true);
    try {
      const { run_id } = await api.runIssue(issue.id);
      setPendingRuns((m) => ({ ...m, [issue.id]: run_id }));
      setSelectedIssueId(issue.id);
      await loadIssues();
    } catch (e) {
      setIssuesError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const runAll = async () => {
    setBusy(true);
    try {
      const { run_ids } = await api.runAll();
      if (run_ids.length > 0) {
        // select the first issue that was just queued
        const first = issues.find((i) => pendingRuns[i.id] === undefined) ?? issues[0];
        if (first) setSelectedIssueId(first.id);
      }
      await loadIssues();
    } catch (e) {
      setIssuesError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const selectedIssue = issues.find((i) => i.id === selectedIssueId) ?? null;
  const selectedRunId = selectedIssue
    ? pendingRuns[selectedIssue.id] ?? selectedIssue.latest_run_id
    : null;

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar health={health} />
      <main className="mx-auto flex w-full max-w-[1480px] flex-1 flex-col gap-4 px-5 py-4">
        {fatalError && !issuesError && issues.length === 0 && (
          <div className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-[13px] text-danger">
            Cannot reach the RepoCrew backend ({fatalError}). Start it with{" "}
            <code className="font-mono">./run.sh</code> or{" "}
            <code className="font-mono">./run.ps1</code>, then reload.
          </div>
        )}
        <MetricsStrip metrics={metrics} />
        <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
          <IssueList
            issues={issues}
            selectedId={selectedIssueId}
            onSelect={(i) => setSelectedIssueId(i.id)}
            onRunIssue={(i) => void runIssue(i)}
            onRunAll={() => void runAll()}
            busy={busy}
            error={issuesError && issues.length === 0 ? issuesError : issuesError}
            onRetryLoad={() => void loadIssues()}
          />
          <section className="min-w-0">
            {selectedIssue && selectedRunId ? (
              <RunView key={selectedRunId} runId={selectedRunId} onChanged={refreshAll} />
            ) : selectedIssue ? (
              <div className="card flex h-full min-h-[420px] flex-col items-center justify-center gap-3 text-center">
                <Bot size={30} className="text-accent opacity-70" />
                <div>
                  <p className="text-[15px] font-bold">
                    Issue #{selectedIssue.number}: {selectedIssue.title}
                  </p>
                  <p className="mx-auto mt-1 max-w-md text-[13px] leading-relaxed text-muted">
                    RepoCrew has not looked at this issue yet. Start a run and watch Triage,
                    the Coder, the Tester (real pytest in the sandbox), the Reviewer and the
                    Safety Gate work through it — then make the final call yourself.
                  </p>
                </div>
                <button
                  className="btn-primary"
                  disabled={busy}
                  onClick={() => void runIssue(selectedIssue)}
                >
                  <Play size={14} /> Run RepoCrew on this issue
                </button>
              </div>
            ) : (
              <div className="card flex h-full min-h-[420px] flex-col items-center justify-center gap-2 text-center text-muted">
                <Bot size={30} className="opacity-60" />
                <p className="max-w-sm text-[13px] leading-relaxed">
                  {issuesError
                    ? "Waiting for the backend to come online…"
                    : "Select an issue on the left to inspect its RepoCrew run."}
                </p>
              </div>
            )}
          </section>
        </div>
      </main>
      <footer className="border-t border-line py-3">
        <p className="text-center text-[11px] text-muted/70">
          RepoCrew — issues in, reviewed pull requests out. A human always approves; nothing is ever merged by the agents.
        </p>
      </footer>
    </div>
  );
}

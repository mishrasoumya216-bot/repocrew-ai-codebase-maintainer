// RepoCrew run view: pipeline stepper, live event timeline (WebSocket +
// polling fallback), and tabs for Diff / Tests / Safety Gate / Pull Request,
// with the human decision bar pinned at the bottom while AWAITING_HUMAN.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { api, runStreamUrl, type StreamMessage } from "../api";
import type { RunDetail, RunEvent, RunStatus } from "../types";
import Stepper from "./Stepper";
import Timeline from "./Timeline";
import DiffViewer from "./DiffViewer";
import TestsPanel from "./TestsPanel";
import GatePanel from "./GatePanel";
import PRPanel from "./PRPanel";
import DecisionBar from "./DecisionBar";
import { statusBadge } from "./IssueList";

const TERMINAL = new Set<RunStatus>([
  "AWAITING_HUMAN",
  "OUT_OF_SCOPE",
  "BLOCKED_BY_GATE",
  "STOPPED_NEEDS_HUMAN",
  "PR_READY",
  "PR_CREATED",
  "REJECTED_BY_HUMAN",
  "FAILED",
]);

const TABS = [
  { id: "diff", label: "Diff" },
  { id: "tests", label: "Tests" },
  { id: "gate", label: "Safety Gate" },
  { id: "pr", label: "Pull Request" },
] as const;

type TabId = (typeof TABS)[number]["id"];

interface Props {
  runId: number;
  onChanged: () => void;
}

export default function RunView({ runId, onChanged }: Props) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [tab, setTab] = useState<TabId>("diff");
  const [diffAttempt, setDiffAttempt] = useState<number | null>(null);
  const [testAttempt, setTestAttempt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const terminalRef = useRef(false);

  const mergeEvents = useCallback((incoming: RunEvent[]) => {
    setEvents((prev) => {
      if (incoming.length === 0) return prev;
      const seen = new Set(prev.map((e) => e.id));
      const additions = incoming.filter((e) => !seen.has(e.id));
      if (additions.length === 0) return prev;
      return [...prev, ...additions].sort((a, b) => a.id - b.id);
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const detail = await api.run(runId);
      setRun(detail);
      mergeEvents(detail.events);
      setError(null);
      const isTerminal = TERMINAL.has(detail.status);
      if (isTerminal && !terminalRef.current) {
        terminalRef.current = true;
        onChanged();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [runId, mergeEvents, onChanged]);

  // initial load + reset when the selected run changes
  useEffect(() => {
    setRun(null);
    setEvents([]);
    setError(null);
    setDiffAttempt(null);
    setTestAttempt(null);
    terminalRef.current = false;
    void refresh();
  }, [refresh]);

  // WebSocket live stream (polling below keeps state fresh as a fallback)
  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    try {
      ws = new WebSocket(runStreamUrl(runId));
      ws.onmessage = (msg) => {
        try {
          const parsed = JSON.parse(msg.data) as StreamMessage;
          if (parsed.kind === "backlog" && parsed.events) mergeEvents(parsed.events);
          if (parsed.kind === "event" && parsed.event) {
            mergeEvents([parsed.event]);
            if (parsed.event.type === "status") void refresh();
          }
        } catch {
          /* malformed frame — ignore */
        }
      };
      ws.onerror = () => {
        /* polling fallback covers us */
      };
    } catch {
      /* WebSocket unavailable — polling fallback covers us */
    }
    return () => {
      closed = true;
      if (ws && ws.readyState <= WebSocket.OPEN) {
        ws.onmessage = null;
        try {
          if (!closed) return;
          ws.close();
        } catch {
          /* already closed */
        }
      }
    };
  }, [runId, mergeEvents, refresh]);

  // polling fallback / run-state refresher
  useEffect(() => {
    const t = window.setInterval(() => {
      if (!terminalRef.current) void refresh();
    }, 1600);
    return () => window.clearInterval(t);
  }, [refresh]);

  const latestPatch = useMemo(
    () => (run && run.patches.length > 0 ? run.patches[run.patches.length - 1] : null),
    [run],
  );

  const approve = async (comment: string) => {
    await api.approve(runId, comment || undefined);
    await refresh();
    onChanged();
  };
  const reject = async (comment: string) => {
    await api.reject(runId, comment || undefined);
    await refresh();
    onChanged();
  };

  if (error && !run) {
    return (
      <div className="card flex h-64 flex-col items-center justify-center gap-2 text-center">
        <AlertTriangle size={22} className="text-danger" />
        <p className="text-[13px] text-danger">Could not load this run: {error}</p>
        <button className="btn-ghost" onClick={() => void refresh()}>
          Try again
        </button>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="card flex h-64 items-center justify-center gap-3 text-muted">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-[13px]">Loading run…</span>
      </div>
    );
  }

  const badge = statusBadge(run.status);
  const live = run.status === "RUNNING" || run.status === "QUEUED";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="card flex flex-wrap items-center gap-3 px-4 py-2.5">
        <span className={`chip ${badge.cls} !text-[11px]`}>{badge.text}</span>
        <span className="font-mono text-[11px] text-muted">
          run #{run.id} · issue #{run.issue_number} · {run.mode} mode
        </span>
        {run.summary && (
          <span className="w-full text-[12px] text-ink/80 sm:w-auto sm:flex-1">{run.summary}</span>
        )}
      </div>

      <Stepper
        agentStates={run.agent_states}
        attempts={run.attempts}
        maxAttempts={run.max_attempts}
        status={run.status}
      />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-2">
        <Timeline events={events} live={live} />
        <div className="card flex min-h-0 flex-1 flex-col">
          <div className="flex border-b border-line px-2">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`tab-btn ${tab === t.id ? "tab-btn-active" : ""}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {tab === "diff" && (
              <DiffViewer
                patches={run.patches}
                selectedAttempt={diffAttempt}
                onSelectAttempt={setDiffAttempt}
              />
            )}
            {tab === "tests" && (
              <TestsPanel
                results={run.test_results}
                selectedAttempt={testAttempt}
                onSelectAttempt={setTestAttempt}
              />
            )}
            {tab === "gate" && <GatePanel gate={run.gate_result} status={run.status} />}
            {tab === "pr" && <PRPanel run={run} latestPatch={latestPatch} />}
          </div>
        </div>
      </div>

      {run.status === "AWAITING_HUMAN" && <DecisionBar onApprove={approve} onReject={reject} />}
      {run.status === "REJECTED_BY_HUMAN" && (
        <div className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
          Rejected by a human reviewer{run.human_comment ? `: ${run.human_comment}` : "."}
        </div>
      )}
      {run.error && (
        <div className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 font-mono text-[11px] text-danger">
          {run.error}
        </div>
      )}
    </div>
  );
}

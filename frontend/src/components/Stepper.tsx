// RepoCrew agent pipeline stepper: Triage -> Coder -> Tester -> Reviewer -> Gate -> Human.
// Nodes show idle / working (animated pulse + glow) / passed / failed, plus an attempt counter.
import { Check, CircleDashed, Loader2, X } from "lucide-react";
import { agentMeta } from "../agentMeta";
import type { AgentStates } from "../types";

const ORDER = ["triage", "coder", "tester", "reviewer", "gate", "human"] as const;

function NodeIcon({ state }: { state: string }) {
  if (state === "working")
    return <Loader2 size={13} className="animate-spin" />;
  if (state === "passed") return <Check size={13} />;
  if (state === "failed") return <X size={13} />;
  return <CircleDashed size={13} />;
}

interface Props {
  agentStates: AgentStates;
  attempts: number;
  maxAttempts: number;
  status: string;
}

export default function Stepper({ agentStates, attempts, maxAttempts, status }: Props) {
  return (
    <div className="card px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
          Agent pipeline
        </span>
        <span className="rounded-md border border-line bg-raised px-2 py-0.5 font-mono text-[11px] text-ink/85">
          Attempt {Math.max(attempts, status === "QUEUED" ? 0 : 1)}/{maxAttempts}
        </span>
      </div>
      <div className="flex items-center">
        {ORDER.map((agent, idx) => {
          const meta = agentMeta(agent);
          const state =
            agent === "human" && status === "AWAITING_HUMAN"
              ? "working"
              : agentStates[agent] ?? "idle";
          return (
            <div key={agent} className="flex flex-1 items-center last:flex-none">
              <div className="flex min-w-[64px] flex-col items-center gap-1">
                <div
                  className={`flex h-7 w-7 items-center justify-center rounded-full border text-[10px] font-bold transition-all duration-200 ${
                    state === "working" ? "agent-working" : ""
                  }`}
                  style={{
                    color: meta.color,
                    borderColor: state === "idle" ? "#1C3048" : meta.color,
                    backgroundColor: state === "idle" ? "transparent" : `${meta.color}18`,
                    opacity: state === "idle" ? 0.55 : 1,
                  }}
                  title={`${meta.label}: ${state}`}
                >
                  <NodeIcon state={state} />
                </div>
                <span
                  className="text-[10px] font-semibold"
                  style={{ color: state === "idle" ? "#8AA0B8" : meta.color }}
                >
                  {meta.label}
                </span>
              </div>
              {idx < ORDER.length - 1 && (
                <div
                  className="mx-1 mb-4 h-px flex-1 transition-colors duration-200"
                  style={{
                    backgroundColor:
                      agentStates[ORDER[idx + 1]] && agentStates[ORDER[idx + 1]] !== "idle"
                        ? meta.color
                        : "#1C3048",
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

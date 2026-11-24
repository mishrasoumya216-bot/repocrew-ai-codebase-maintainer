// RepoCrew Safety Gate tab: the structured scorecard (score, threshold,
// per-check results, blocked reasons).
import { CheckCircle2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import type { GateResult } from "../types";

export default function GatePanel({ gate, status }: { gate: GateResult | null; status: string }) {
  if (!gate) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted">
        <ShieldCheck size={20} className="opacity-50" />
        <p className="text-[13px]">
          The Safety Gate scorecard appears here once the Reviewer approves a patch.
        </p>
      </div>
    );
  }
  const pct = Math.round(gate.score * 100);
  const thresholdPct = Math.round(gate.threshold * 100);
  return (
    <div className="flex flex-col gap-4">
      <div className="card-raised flex items-center gap-5 p-4">
        <div className="text-center">
          <div
            className={`text-3xl font-extrabold ${gate.allowed ? "text-success" : "text-danger"}`}
          >
            {gate.score.toFixed(2)}
          </div>
          <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">
            confidence score
          </div>
        </div>
        <div className="flex-1">
          <div className="relative h-2.5 overflow-hidden rounded-full bg-line/70">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                gate.allowed ? "bg-success" : "bg-danger"
              }`}
              style={{ width: `${pct}%` }}
            />
            <div
              className="absolute inset-y-0 w-0.5 bg-ink/70"
              style={{ left: `${thresholdPct}%` }}
              title={`threshold ${gate.threshold}`}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-muted">
            <span>0</span>
            <span>threshold {gate.threshold.toFixed(1)}</span>
            <span>1.0</span>
          </div>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[12px] font-bold ${
            gate.allowed
              ? "border-success/50 bg-success/10 text-success"
              : "border-danger/50 bg-danger/10 text-danger"
          }`}
        >
          {gate.allowed ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
          {gate.allowed ? "PR allowed" : status === "BLOCKED_BY_GATE" ? "PR blocked" : "Below threshold"}
        </span>
      </div>

      <div className="card-raised divide-y divide-line/70">
        {gate.checks.map((c) => (
          <div key={c.name} className="flex items-center gap-3 px-4 py-2.5">
            {c.passed ? (
              <CheckCircle2 size={15} className="shrink-0 text-success" />
            ) : (
              <XCircle size={15} className="shrink-0 text-danger" />
            )}
            <div className="flex-1">
              <div className="text-[13px] font-semibold">{c.name}</div>
              <div className="font-mono text-[11px] text-muted">{c.detail}</div>
            </div>
            <span
              className={`text-[10px] font-bold uppercase ${c.passed ? "text-success" : "text-danger"}`}
            >
              {c.passed ? "pass" : "fail"}
            </span>
          </div>
        ))}
      </div>

      {gate.blocked_reasons.length > 0 && (
        <div className="rounded-lg border border-danger/50 bg-danger/10 p-3">
          <div className="mb-1 flex items-center gap-2 text-[12px] font-bold text-danger">
            <ShieldAlert size={14} /> Blocked paths touched
          </div>
          <ul className="ml-5 list-disc font-mono text-[11px] text-danger/90">
            {gate.blocked_reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[11px] text-muted/80">
        Score formula: 0.5 × tests-passed + 0.3 × reviewer-verdict + 0.1 × small-diff (&le;40
        lines) + 0.1 × includes-test-change. A PR requires score ≥ {gate.threshold} and zero
        blocked paths (.github/**, .env*, *secret*, *.pem, *.key, Dockerfile*, CI configs).
      </p>
    </div>
  );
}

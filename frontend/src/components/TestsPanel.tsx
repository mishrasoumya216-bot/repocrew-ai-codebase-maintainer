// RepoCrew Tests tab: real pytest output in a terminal-style panel with
// pass/fail counts, per attempt.
import { CheckCircle2, CircleX, TerminalSquare } from "lucide-react";
import type { TestResultRow } from "../types";

function colorized(raw: string) {
  return raw.split("\n").map((line, i) => {
    let cls = "text-ink/75";
    if (line.includes("FAILED") || line.includes("ERROR") || line.startsWith("E "))
      cls = "text-danger";
    else if (line.includes("PASSED")) cls = "text-success";
    else if (line.includes("=====") || line.includes("short test summary")) cls = "text-warning";
    else if (line.includes("REPOCREW")) cls = "text-accent";
    return (
      <div key={i} className={`whitespace-pre-wrap break-all ${cls}`}>
        {line || " "}
      </div>
    );
  });
}

interface Props {
  results: TestResultRow[];
  selectedAttempt: number | null;
  onSelectAttempt: (a: number) => void;
}

export default function TestsPanel({ results, selectedAttempt, onSelectAttempt }: Props) {
  const active =
    results.find((r) => r.attempt === selectedAttempt) ?? results[results.length - 1] ?? null;

  if (results.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted">
        <TerminalSquare size={20} className="opacity-50" />
        <p className="text-[13px]">
          No test run yet — the Tester applies each patch in the sandbox and streams real pytest output here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold text-muted">Attempt:</span>
        {results.map((r) => (
          <button
            key={r.id}
            onClick={() => onSelectAttempt(r.attempt)}
            className={`rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors duration-150 ${
              active?.attempt === r.attempt
                ? "border-accent/60 bg-accent/10 text-accent"
                : "border-line text-muted hover:text-ink"
            }`}
          >
            {r.attempt}
          </button>
        ))}
        {active && (
          <span
            className={`ml-auto inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-bold ${
              active.passed
                ? "border-success/50 bg-success/10 text-success"
                : "border-danger/50 bg-danger/10 text-danger"
            }`}
          >
            {active.passed ? <CheckCircle2 size={12} /> : <CircleX size={12} />}
            {active.passed ? "PASS" : "FAIL"} — {active.passed_count} passed, {active.failed} failed
            <span className="font-normal text-muted">({active.engine})</span>
          </span>
        )}
      </div>
      {active && (
        <p className="rounded-lg border border-line bg-raised/60 px-3 py-2 font-mono text-[11px] text-muted">
          {active.detail}
        </p>
      )}
      <div className="max-h-[420px] overflow-y-auto rounded-lg border border-line bg-[#030810] p-3 font-mono text-[11px] leading-[1.55]">
        {active ? colorized(active.raw_output) : null}
      </div>
      <p className="text-[11px] text-muted/80">
        Real pytest output from a sandboxed run against a fresh copy of the repo.
        Because RepoCrew never merges, main stays red by design — a patch "passes" when it
        introduces no regressions versus the unpatched baseline and fixes its target test(s).
      </p>
    </div>
  );
}

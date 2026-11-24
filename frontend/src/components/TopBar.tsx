// RepoCrew top bar: logo (three linked nodes in crew formation), wordmark,
// mode badge (DEMO/LIVE) and sandbox badge (green isolated / yellow fallback).
import { FlaskConical, Radio, ShieldAlert, ShieldCheck } from "lucide-react";
import type { Health } from "../types";

function LogoMark() {
  return (
    <svg width="30" height="28" viewBox="0 0 32 30" aria-hidden="true">
      <circle cx="16" cy="6.5" r="3.6" fill="#22D3EE" />
      <circle cx="6.5" cy="23.5" r="3.6" fill="none" stroke="#8B5CF6" strokeWidth="2" />
      <circle cx="25.5" cy="23.5" r="3.6" fill="none" stroke="#34D399" strokeWidth="2" />
      <path
        d="M13.6 9.2 8.8 20.6M18.4 9.2l4.8 11.4M10.2 23.5h11.6"
        stroke="#22D3EE"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function TopBar({ health }: { health: Health | null }) {
  const mode = health?.mode ?? "demo";
  const sandbox = health?.sandbox;
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1480px] items-center gap-4 px-5">
        <div className="flex items-center gap-2.5">
          <LogoMark />
          <span className="text-[17px] font-extrabold tracking-tight">
            Repo<span className="text-accent">Crew</span>
          </span>
          <span className="hidden text-[11px] text-muted sm:inline">
            multi-agent codebase maintainer
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {mode === "demo" ? (
            <span className="chip !border-warning/50 !text-warning" title="Scripted deterministic trajectories; the Tester still runs real pytest in the sandbox.">
              <FlaskConical size={12} /> DEMO MODE
            </span>
          ) : (
            <span className="chip !border-accent/50 !text-accent" title={`Live Claude tool-use agents (${health?.model ?? ""})`}>
              <Radio size={12} /> LIVE MODE
            </span>
          )}
          {sandbox && (
            <span
              className={
                sandbox.isolated
                  ? "chip !border-success/50 !text-success"
                  : "chip !border-warning/50 !text-warning"
              }
              title={sandbox.message}
            >
              {sandbox.isolated ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
              Sandbox: {sandbox.isolated ? "Docker isolated" : "Docker not found: running in local fallback (NOT isolated)"}
            </span>
          )}
        </div>
      </div>
    </header>
  );
}

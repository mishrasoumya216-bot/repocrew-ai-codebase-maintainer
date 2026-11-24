// RepoCrew live agent activity: a scrolling timeline of run events with agent
// avatars, colored per agent; tool calls, tool results, logs and messages as
// they stream over WebSocket. Auto-scolls with a "pause scroll" toggle.
import { useEffect, useRef, useState } from "react";
import { PauseCircle, PlayCircle, TerminalSquare } from "lucide-react";
import { agentMeta } from "../agentMeta";
import type { RunEvent } from "../types";

const TYPE_STYLE: Record<string, { label: string; cls: string }> = {
  step: { label: "step", cls: "text-ink" },
  message: { label: "msg", cls: "text-ink/90" },
  tool_call: { label: "tool →", cls: "text-accent font-mono" },
  tool_result: { label: "← result", cls: "text-muted font-mono" },
  status: { label: "status", cls: "text-violet font-semibold" },
  log: { label: "log", cls: "text-muted font-mono" },
};

function timeOf(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour12: false }) +
    "." + String(d.getMilliseconds()).padStart(3, "0").slice(0, 2);
}

export default function Timeline({ events, live }: { events: RunEvent[]; live: boolean }) {
  const [paused, setPaused] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight;
    }
  }, [events, paused]);

  return (
    <div className="card flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-line px-4 py-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
          Live agent activity
        </span>
        <div className="flex items-center gap-2">
          {live && (
            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-accent">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" /> streaming
            </span>
          )}
          <button
            className="btn-ghost !px-2 !py-0.5 !text-[11px]"
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? <PlayCircle size={12} /> : <PauseCircle size={12} />}
            {paused ? "resume scroll" : "pause scroll"}
          </button>
        </div>
      </div>
      <div ref={boxRef} className="min-h-[220px] flex-1 overflow-y-auto px-3 py-2">
        {events.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 py-10 text-muted">
            <TerminalSquare size={22} className="opacity-50" />
            <p className="text-[13px]">The crew's conversation appears here the moment a run starts.</p>
          </div>
        )}
        {events.map((ev) => {
          const meta = agentMeta(ev.agent);
          const style = TYPE_STYLE[ev.type] ?? TYPE_STYLE.log;
          return (
            <div key={ev.id} className="fade-up flex gap-2.5 border-l-2 px-2 py-1.5"
              style={{ borderColor: `${meta.color}55` }}>
              <div
                className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[9px] font-bold"
                style={{ backgroundColor: `${meta.color}1f`, color: meta.color }}
                title={meta.label}
              >
                {meta.initial}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-[10px] font-bold" style={{ color: meta.color }}>
                    {meta.label}
                  </span>
                  <span className={`text-[9px] uppercase tracking-wide ${style.cls}`}>
                    {style.label}
                  </span>
                  <span className="ml-auto font-mono text-[9px] text-muted/70">{timeOf(ev.ts)}</span>
                </div>
                <p
                  className={`whitespace-pre-wrap break-words text-[12px] leading-relaxed ${
                    ev.type === "tool_call" || ev.type === "tool_result" || ev.type === "log"
                      ? "font-mono text-[11px]"
                      : ""
                  } ${ev.type === "log" ? "text-muted" : "text-ink/90"}`}
                >
                  {ev.text}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

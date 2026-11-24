// RepoCrew agent identity: consistent colors + labels across the stepper,
// the timeline and the avatars.
import type { AgentName } from "./types";

export const AGENT_META: Record<AgentName, { label: string; color: string; initial: string }> = {
  orchestrator: { label: "Orchestrator", color: "#94A3B8", initial: "O" },
  triage: { label: "Triage", color: "#FBBF24", initial: "T" },
  coder: { label: "Coder", color: "#22D3EE", initial: "C" },
  tester: { label: "Tester", color: "#34D399", initial: "Te" },
  reviewer: { label: "Reviewer", color: "#A78BFA", initial: "R" },
  gate: { label: "Safety Gate", color: "#F472B6", initial: "G" },
};

export function agentMeta(agent: string) {
  return (
    AGENT_META[agent as AgentName] ?? { label: agent, color: "#94A3B8", initial: agent.slice(0, 1) }
  );
}

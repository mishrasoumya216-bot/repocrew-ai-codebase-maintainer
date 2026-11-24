// RepoCrew API domain types (mirror backend JSON payloads).

export type AgentName =
  | "orchestrator"
  | "triage"
  | "coder"
  | "tester"
  | "reviewer"
  | "gate";

export type EventType =
  | "step"
  | "message"
  | "tool_call"
  | "tool_result"
  | "status"
  | "log";

export interface RunEvent {
  id: number;
  run_id: number;
  ts: number;
  agent: AgentName;
  type: EventType;
  text: string;
  data?: Record<string, unknown> | null;
}

export type RunStatus =
  | "QUEUED"
  | "RUNNING"
  | "AWAITING_HUMAN"
  | "OUT_OF_SCOPE"
  | "BLOCKED_BY_GATE"
  | "STOPPED_NEEDS_HUMAN"
  | "PR_READY"
  | "PR_CREATED"
  | "REJECTED_BY_HUMAN"
  | "FAILED";

export interface Issue {
  id: number;
  number: number;
  title: string;
  body: string;
  labels: string[];
  reporter: string;
  created_at: string;
  latest_run_id: number | null;
  latest_run_status: RunStatus | null;
}

export interface PatchRow {
  id: number;
  attempt: number;
  diff: string;
  created_at: string;
}

export interface TestResultRow {
  id: number;
  attempt: number;
  passed: boolean;
  total: number;
  failed: number;
  passed_count: number;
  raw_output: string;
  detail: string;
  engine: string;
  created_at: string;
}

export interface GateCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface GateResult {
  score: number;
  threshold: number;
  checks: GateCheck[];
  blocked_reasons: string[];
  allowed: boolean;
  changed_lines: number;
  paths: string[];
}

export interface PullRequestInfo {
  id?: number;
  kind: "github" | "preview";
  url: string | null;
  branch: string | null;
  title: string;
  body: string;
  created_at?: string;
}

export interface AgentStates {
  [agent: string]: "idle" | "working" | "passed" | "failed";
}

export interface RunDetail {
  id: number;
  issue_id: number;
  issue_number: number;
  issue_title: string;
  status: RunStatus;
  mode: string;
  attempts: number;
  max_attempts: number;
  current_agent: string;
  agent_states: AgentStates;
  triage_result: Record<string, unknown> | null;
  reviews: { attempt: number; verdict: string; notes: string[] }[];
  gate_result: GateResult | null;
  pr_title: string | null;
  pr_body: string | null;
  human_comment: string | null;
  summary: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  patches: PatchRow[];
  test_results: TestResultRow[];
  pull_request: PullRequestInfo | null;
  events: RunEvent[];
}

export interface Metrics {
  issues_processed: number;
  patches_approved: number;
  test_pass_rate: number;
  retries_used: number;
  avg_run_time_seconds: number;
}

export interface Health {
  status: string;
  service: string;
  mode: "demo" | "live" | string;
  model: string;
  sandbox: { engine: string; isolated: boolean; message: string };
  github_configured: boolean;
}

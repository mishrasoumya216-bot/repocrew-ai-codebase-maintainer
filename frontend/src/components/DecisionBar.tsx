// RepoCrew human decision bar: pinned at the bottom of a run when the status
// is AWAITING_HUMAN. Approve opens the PR (or generates the preview); Reject
// ends the run and saves the optional comment.
import { useState } from "react";
import { ThumbsDown, ThumbsUp, UserCheck } from "lucide-react";

interface Props {
  onApprove: (comment: string) => Promise<void>;
  onReject: (comment: string) => Promise<void>;
}

export default function DecisionBar({ onApprove, onReject }: Props) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (which: "approve" | "reject") => {
    setBusy(which);
    setError(null);
    try {
      if (which === "approve") await onApprove(comment);
      else await onReject(comment);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card border-warning/50 bg-warning/5 p-3 shadow-[0_-6px_24px_rgba(5,11,20,0.6)]">
      <div className="mb-2 flex items-center gap-2 text-[13px] font-bold text-warning">
        <UserCheck size={15} /> Human decision required
        <span className="text-[11px] font-medium text-muted">
          — RepoCrew never merges; approving opens a PR with human review required
        </span>
      </div>
      {error && (
        <div className="mb-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-1.5 text-[12px] text-danger">
          {error}
        </div>
      )}
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional comment (saved with your decision)…"
          className="flex-1 rounded-lg border border-line bg-bg px-3 py-1.5 text-[13px] text-ink placeholder:text-muted/60 focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/40"
        />
        <div className="flex gap-2">
          <button className="btn-success" disabled={busy !== null} onClick={() => act("approve")}>
            <ThumbsUp size={13} /> {busy === "approve" ? "Approving…" : "Approve"}
          </button>
          <button className="btn-danger" disabled={busy !== null} onClick={() => act("reject")}>
            <ThumbsDown size={13} /> {busy === "reject" ? "Rejecting…" : "Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}

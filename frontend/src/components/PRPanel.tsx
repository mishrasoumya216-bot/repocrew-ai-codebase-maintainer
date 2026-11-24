// RepoCrew Pull Request tab: the GitHub PR link when a token is configured,
// otherwise a full PR preview (title + markdown body) with Copy and
// Download .patch buttons — labelled "PR preview (no GitHub token configured)".
import { useState } from "react";
import { Check, Copy, Download, ExternalLink, GitPullRequest } from "lucide-react";
import type { PatchRow, RunDetail } from "../types";

interface Props {
  run: RunDetail;
  latestPatch: PatchRow | null;
}

export default function PRPanel({ run, latestPatch }: Props) {
  const [copied, setCopied] = useState(false);
  const pr = run.pull_request;

  const previewAvailable =
    !!pr || (run.status === "AWAITING_HUMAN" && !!run.pr_body && !!run.pr_title);

  if (!previewAvailable) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted">
        <GitPullRequest size={20} className="opacity-50" />
        <p className="text-[13px]">
          The pull request appears here once the Safety Gate passes and a human approves.
        </p>
      </div>
    );
  }

  const title = pr?.title ?? run.pr_title ?? "";
  const body = pr?.body ?? run.pr_body ?? "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${title}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard may be unavailable in some contexts */
    }
  };

  const downloadPatch = () => {
    if (!latestPatch) return;
    const blob = new Blob([latestPatch.diff], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `repocrew-issue-${run.issue_number}-attempt-${latestPatch.attempt}.patch`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-3">
      {pr?.kind === "github" && pr.url ? (
        <a
          href={pr.url}
          target="_blank"
          rel="noreferrer"
          className="card-raised flex items-center gap-3 p-4 transition-colors hover:border-accent/60"
        >
          <GitPullRequest size={18} className="text-success" />
          <div className="flex-1">
            <div className="text-[14px] font-bold">{pr.title}</div>
            <div className="font-mono text-[11px] text-muted">
              branch {pr.branch} · opened via the GitHub REST API
            </div>
          </div>
          <ExternalLink size={15} className="text-accent" />
        </a>
      ) : (
        <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[12px] font-semibold text-warning">
          PR preview (no GitHub token configured)
        </div>
      )}

      <div className="card-raised p-4">
        <div className="mb-1 flex items-center gap-2">
          <GitPullRequest size={15} className="text-success" />
          <span className="text-[14px] font-bold">{title}</span>
          {pr?.branch && (
            <span className="chip font-mono">{pr.branch}</span>
          )}
        </div>
        <pre className="mt-2 max-h-[340px] overflow-y-auto whitespace-pre-wrap rounded-lg border border-line bg-[#030810] p-3 font-mono text-[11px] leading-relaxed text-ink/85">
          {body}
        </pre>
        <div className="mt-3 flex items-center gap-2">
          <button className="btn-primary" onClick={copy}>
            {copied ? <Check size={13} /> : <Copy size={13} />} {copied ? "Copied" : "Copy body"}
          </button>
          <button className="btn-ghost" onClick={downloadPatch} disabled={!latestPatch}>
            <Download size={13} /> Download .patch
          </button>
        </div>
      </div>
    </div>
  );
}

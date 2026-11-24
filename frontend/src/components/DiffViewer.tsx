// RepoCrew custom unified-diff viewer (no heavy dependency):
// unified / side-by-side toggle plus an attempt selector so judges can
// compare attempt 1 vs attempt 2 of the Coder.
import { Fragment, useMemo, useState } from "react";
import { Columns2, FileCode2, Rows3 } from "lucide-react";
import type { PatchRow } from "../types";

interface DiffLine {
  kind: "ctx" | "add" | "del" | "meta";
  oldLn: number | null;
  newLn: number | null;
  text: string;
}
interface Hunk {
  header: string;
  lines: DiffLine[];
}
interface DiffFile {
  path: string;
  isNew: boolean;
  hunks: Hunk[];
}

export function parseDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: Hunk | null = null;
  let oldLn = 0;
  let newLn = 0;
  let pendingOld = "";
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("--- ")) {
      pendingOld = raw.slice(4).trim();
      continue;
    }
    if (raw.startsWith("+++ ")) {
      const path = raw.slice(4).trim().replace(/^b\//, "");
      file = { path, isNew: pendingOld === "/dev/null", hunks: [] };
      files.push(file);
      hunk = null;
      continue;
    }
    if (raw.startsWith("@@ ")) {
      if (!file) continue;
      const m = raw.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      oldLn = m ? parseInt(m[1], 10) : 1;
      newLn = m ? parseInt(m[2], 10) : 1;
      hunk = { header: raw, lines: [] };
      file.hunks.push(hunk);
      continue;
    }
    if (!hunk) continue;
    if (raw.startsWith("+")) {
      hunk.lines.push({ kind: "add", oldLn: null, newLn: newLn++, text: raw.slice(1) });
    } else if (raw.startsWith("-")) {
      hunk.lines.push({ kind: "del", oldLn: oldLn++, newLn: null, text: raw.slice(1) });
    } else if (raw.startsWith("\\")) {
      hunk.lines.push({ kind: "meta", oldLn: null, newLn: null, text: raw });
    } else {
      hunk.lines.push({ kind: "ctx", oldLn: oldLn++, newLn: newLn++, text: raw.slice(1) });
    }
  }
  return files;
}

function UnifiedFile({ file }: { file: DiffFile }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="flex items-center gap-2 border-b border-line bg-raised px-3 py-1.5">
        <FileCode2 size={13} className="text-accent" />
        <span className="font-mono text-[11px] text-ink/90">{file.path}</span>
        {file.isNew && (
          <span className="rounded bg-success/15 px-1.5 py-0.5 text-[10px] font-bold text-success">
            new file
          </span>
        )}
      </div>
      <table className="w-full border-collapse font-mono text-[11px] leading-5">
        <tbody>
          {file.hunks.map((h, hi) => (
            <Fragment key={`h${hi}`}>
              <tr>
                <td colSpan={3} className="bg-violet/10 px-3 py-1 text-[10px] text-violet">
                  {h.header}
                </td>
              </tr>
              {h.lines.map((ln, li) => (
                <tr
                  key={`${hi}-${li}`}
                  className={
                    ln.kind === "add"
                      ? "bg-[rgba(52,211,153,0.09)]"
                      : ln.kind === "del"
                        ? "bg-[rgba(248,113,113,0.09)]"
                        : ""
                  }
                >
                  <td className="w-10 select-none border-r border-line/60 px-2 text-right text-muted/60">
                    {ln.oldLn ?? ""}
                  </td>
                  <td className="w-10 select-none border-r border-line/60 px-2 text-right text-muted/60">
                    {ln.newLn ?? ""}
                  </td>
                  <td
                    className={`whitespace-pre-wrap break-all px-3 ${
                      ln.kind === "add"
                        ? "text-success"
                        : ln.kind === "del"
                          ? "text-danger"
                          : ln.kind === "meta"
                            ? "text-muted italic"
                            : "text-ink/85"
                    }`}
                  >
                    {ln.kind === "add" ? "+ " : ln.kind === "del" ? "- " : "  "}
                    {ln.text}
                  </td>
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface SplitRow {
  left: DiffLine | null;
  right: DiffLine | null;
}

function splitRows(h: Hunk): SplitRow[] {
  const rows: SplitRow[] = [];
  let i = 0;
  while (i < h.lines.length) {
    const ln = h.lines[i];
    if (ln.kind === "ctx") {
      rows.push({ left: ln, right: ln });
      i++;
    } else if (ln.kind === "del") {
      const dels: DiffLine[] = [];
      while (i < h.lines.length && h.lines[i].kind === "del") dels.push(h.lines[i++]);
      const adds: DiffLine[] = [];
      while (i < h.lines.length && h.lines[i].kind === "add") adds.push(h.lines[i++]);
      const n = Math.max(dels.length, adds.length);
      for (let k = 0; k < n; k++) rows.push({ left: dels[k] ?? null, right: adds[k] ?? null });
    } else if (ln.kind === "add") {
      rows.push({ left: null, right: ln });
      i++;
    } else {
      i++;
    }
  }
  return rows;
}

function SplitFile({ file }: { file: DiffFile }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <div className="flex items-center gap-2 border-b border-line bg-raised px-3 py-1.5">
        <FileCode2 size={13} className="text-accent" />
        <span className="font-mono text-[11px] text-ink/90">{file.path}</span>
        {file.isNew && (
          <span className="rounded bg-success/15 px-1.5 py-0.5 text-[10px] font-bold text-success">
            new file
          </span>
        )}
      </div>
      {file.hunks.map((h, hi) => (
        <table key={hi} className="w-full table-fixed border-collapse font-mono text-[11px] leading-5">
          <tbody>
            <tr>
              <td colSpan={2} className="bg-violet/10 px-3 py-1 text-[10px] text-violet">
                {h.header}
              </td>
            </tr>
            {splitRows(h).map((row, ri) => (
              <tr key={ri}>
                <td
                  className={`w-1/2 whitespace-pre-wrap break-all border-r border-line/60 px-3 ${
                    row.left?.kind === "del"
                      ? "bg-[rgba(248,113,113,0.09)] text-danger"
                      : "text-ink/85"
                  }`}
                >
                  {row.left ? (
                    <>
                      <span className="mr-2 inline-block w-6 text-right text-muted/60">
                        {row.left.oldLn ?? ""}
                      </span>
                      {row.left.kind === "del" ? "- " : "  "}
                      {row.left.text}
                    </>
                  ) : null}
                </td>
                <td
                  className={`w-1/2 whitespace-pre-wrap break-all px-3 ${
                    row.right?.kind === "add"
                      ? "bg-[rgba(52,211,153,0.09)] text-success"
                      : "text-ink/85"
                  }`}
                >
                  {row.right ? (
                    <>
                      <span className="mr-2 inline-block w-6 text-right text-muted/60">
                        {row.right.newLn ?? ""}
                      </span>
                      {row.right.kind === "add" ? "+ " : "  "}
                      {row.right.text}
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ))}
    </div>
  );
}

interface Props {
  patches: PatchRow[];
  selectedAttempt: number | null;
  onSelectAttempt: (a: number) => void;
}

export default function DiffViewer({ patches, selectedAttempt, onSelectAttempt }: Props) {
  const [mode, setMode] = useState<"unified" | "split">("unified");
  const active =
    patches.find((p) => p.attempt === selectedAttempt) ?? patches[patches.length - 1] ?? null;
  const files = useMemo(() => (active ? parseDiff(active.diff) : []), [active]);

  if (patches.length === 0) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted">
        <FileCode2 size={20} className="opacity-50" />
        <p className="text-[13px]">No patch yet — the Coder's diff appears here as soon as it is produced.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-semibold text-muted">Attempt:</span>
        {patches.map((p) => (
          <button
            key={p.id}
            onClick={() => onSelectAttempt(p.attempt)}
            className={`rounded-md border px-2 py-0.5 font-mono text-[11px] transition-colors duration-150 ${
              active?.attempt === p.attempt
                ? "border-accent/60 bg-accent/10 text-accent"
                : "border-line text-muted hover:text-ink"
            }`}
          >
            {p.attempt}
          </button>
        ))}
        <div className="ml-auto flex overflow-hidden rounded-lg border border-line">
          <button
            className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold ${
              mode === "unified" ? "bg-accent/15 text-accent" : "text-muted"
            }`}
            onClick={() => setMode("unified")}
          >
            <Rows3 size={12} /> Unified
          </button>
          <button
            className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold ${
              mode === "split" ? "bg-accent/15 text-accent" : "text-muted"
            }`}
            onClick={() => setMode("split")}
          >
            <Columns2 size={12} /> Side by side
          </button>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {files.map((f, i) =>
          mode === "unified" ? <UnifiedFile key={i} file={f} /> : <SplitFile key={i} file={f} />,
        )}
      </div>
    </div>
  );
}

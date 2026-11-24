"""RepoCrew unified-diff helpers.

- ``make_file_diff``: build a ``git apply``-compatible unified diff from two
  versions of a file (used by the deterministic demo scripts so hunk headers
  are always exact).
- ``apply_unified_diff``: pure-Python fallback patch applier for environments
  without ``git`` (e.g. a bare Windows machine). Strict context matching is
  fine here because diffs are produced from real file contents.
- ``changed_paths`` / ``count_changed_lines``: used by the safety gate and the
  GitHub PR client.
"""
from __future__ import annotations

import difflib
from pathlib import Path


def make_file_diff(path: str, old: str | None, new: str) -> str:
    """Unified diff for one file. ``old=None`` means the file is new."""
    old_lines = [] if old is None else old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    fromfile = "/dev/null" if old is None else f"a/{path}"
    diff = difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=f"b/{path}")
    return "".join(diff)


def check_snippet_matches_once(file_text: str, snippet: str) -> None:
    """Verify that a target snippet appears exactly once in the file text."""
    if not snippet.strip():
        return
    count = file_text.count(snippet)
    if count == 0:
        raise ValueError("snippet does not match: context not found in target file")
    if count > 1:
        raise ValueError(f"ambiguous snippet match: found {count} occurrences in target file (must match once)")



def changed_paths(diff_text: str) -> list[str]:
    paths: list[str] = []
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("--- "):
            raw = line[4:].split("\t")[0].strip()
            current = None if raw == "/dev/null" else raw
        elif line.startswith("+++ "):
            raw = line[4:].split("\t")[0].strip()
            target = current if raw == "/dev/null" else raw
            if target:
                for prefix in ("a/", "b/"):
                    if target.startswith(prefix):
                        target = target[len(prefix):]
                        break
                paths.append(target)
            current = None
    return paths


def count_changed_lines(diff_text: str) -> int:
    n = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            n += 1
    return n


def _parse_hunks(lines: list[str]) -> list[dict]:
    """Parse a patch into per-file dicts: {path, new_file, hunks:[(a_start, a_len, body)]}."""
    files: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- "):
            old_raw = line[4:].split("\t")[0].strip()
            new_raw = lines[i + 1][4:].split("\t")[0].strip()
            i += 2
            path = new_raw if old_raw == "/dev/null" else new_raw
            for prefix in ("a/", "b/"):
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            new_file = old_raw == "/dev/null"
            hunks: list[tuple[int, int, list[str]]] = []
            while i < len(lines) and lines[i].startswith("@@ "):
                header = lines[i]
                # @@ -a,b +c,d @@
                a_part = header.split(" ")[1]  # like -a,b
                a_vals = a_part[1:].split(",")
                a_start = int(a_vals[0])
                a_len = int(a_vals[1]) if len(a_vals) > 1 else 1
                i += 1
                body: list[str] = []
                while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                    body.append(lines[i])
                    i += 1
                hunks.append((a_start, a_len, body))
            files.append({"path": path, "new_file": new_file, "hunks": hunks})
        else:
            i += 1
    return files


def apply_unified_diff(target_dir: Path, diff_text: str) -> None:
    """Strict pure-Python unified-diff applier (Windows-safe, no git needed)."""
    if not diff_text.strip():
        raise ValueError("empty patch: nothing to apply")
    files = _parse_hunks(diff_text.splitlines())
    if not files:
        raise ValueError("no file sections found in patch")
    for f in files:
        target = target_dir / f["path"]
        old_lines: list[str] = []
        if not f["new_file"]:
            if not target.exists():
                raise ValueError(f"patch target not found: {f['path']}")
            old_lines = target.read_text(encoding="utf-8").splitlines()
        result: list[str] = []
        cursor = 0
        for a_start, _a_len, body in f["hunks"]:
            idx = max(a_start - 1, 0)
            if old_lines[cursor:idx] != [] and cursor > idx:
                raise ValueError(f"overlapping hunks in {f['path']}")
            result.extend(old_lines[cursor:idx])
            cursor = idx
            for line in body:
                if line.startswith(" "):
                    if cursor >= len(old_lines) or old_lines[cursor] != line[1:]:
                        raise ValueError(
                            f"context mismatch in {f['path']} at line {cursor + 1}: "
                            f"expected {line[1:]!r}"
                        )
                    result.append(old_lines[cursor])
                    cursor += 1
                elif line.startswith("-"):
                    if cursor >= len(old_lines) or old_lines[cursor] != line[1:]:
                        raise ValueError(f"removed-line mismatch in {f['path']} at line {cursor + 1}")
                    cursor += 1
                elif line.startswith("+"):
                    result.append(line[1:])
                elif line.startswith("\\"):
                    pass  # "\ No newline at end of file"
        result.extend(old_lines[cursor:])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(result) + "\n", encoding="utf-8")

"""RepoCrew GitHub REST client.

Used only when GITHUB_TOKEN and RC_GITHUB_REPO are configured: creates a
branch ``repocrew/issue-<n>``, commits the patch file-by-file, pushes, and
opens a pull request. RepoCrew NEVER merges — the PR always ends with the
line "Opened by RepoCrew. Human review required before merge."
"""
from __future__ import annotations

import base64

import httpx

from . import config
from .diffutil import apply_unified_diff, changed_paths

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _apply_patch_to_content(original_b64: str, rel_path: str, diff_text: str) -> str:
    """Apply a unified diff to a single file's base64 content via an in-memory dir."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(prefix="repocrew-gh-") as td:
        root = Path(td)
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel_path not in changed_paths(diff_text):
            raise GitHubError(f"file {rel_path} not present in patch")
        old = base64.b64decode(original_b64).decode("utf-8") if original_b64 else None
        if old is not None:
            target.write_text(old, encoding="utf-8")
        apply_unified_diff(root, diff_text)
        return target.read_text(encoding="utf-8")


def open_pull_request(issue_number: int, title: str, body: str, diff_text: str) -> dict:
    """Create branch + commit + PR through the GitHub REST API. Returns {url, branch}."""
    repo = config.RC_GITHUB_REPO
    branch = f"repocrew/issue-{issue_number}"
    with httpx.Client(base_url=f"{API}/repos/{repo}", headers=_headers(), timeout=30) as client:
        repo_info = client.get("").json()
        base_branch = repo_info.get("default_branch", "main")

        ref = client.get(f"/git/ref/heads/{base_branch}")
        if ref.status_code != 200:
            raise GitHubError(f"cannot read base ref: {ref.text}")
        base_sha = ref.json()["object"]["sha"]

        create_ref = client.post("/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base_sha})
        if create_ref.status_code not in (200, 201) and "Reference already exists" not in create_ref.text:
            raise GitHubError(f"cannot create branch {branch}: {create_ref.text}")

        diff_paths = changed_paths(diff_text)
        for path in diff_paths:
            single = _file_only_diff(diff_text, path)
            existing = client.get(f"/contents/{path}", params={"ref": base_branch})
            sha = None
            old_b64 = ""
            if existing.status_code == 200 and isinstance(existing.json(), dict):
                sha = existing.json().get("sha")
                old_b64 = existing.json().get("content", "")
            new_content = _apply_patch_to_content(old_b64, path, single)
            payload = {
                "message": f"RepoCrew: fix issue #{issue_number} ({path})",
                "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            put = client.put(f"/contents/{path}", json=payload)
            if put.status_code not in (200, 201):
                raise GitHubError(f"cannot commit {path}: {put.text}")

        pr = client.post("/pulls", json={
            "title": title, "head": branch, "base": base_branch, "body": body,
        })
        if pr.status_code not in (200, 201):
            raise GitHubError(f"cannot open PR: {pr.text}")
        return {"url": pr.json()["html_url"], "branch": branch}


def comment_on_issue(issue_number: int, comment: str) -> dict:
    """Post a comment on an issue via the GitHub REST API."""
    repo = config.RC_GITHUB_REPO
    with httpx.Client(base_url=f"{API}/repos/{repo}", headers=_headers(), timeout=30) as client:
        resp = client.post(f"/issues/{issue_number}/comments", json={"body": comment})
        if resp.status_code not in (200, 201):
            raise GitHubError(f"cannot comment on issue {issue_number}: {resp.text}")
        return resp.json()


def _file_only_diff(diff_text: str, path: str) -> str:
    """Extract the single-file section of a multi-file unified diff."""
    sections: list[list[str]] = []
    current_section: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("--- "):
            if current_section:
                sections.append(current_section)
            current_section = [line]
        elif current_section:
            current_section.append(line)
    if current_section:
        sections.append(current_section)

    for sec in sections:
        header = "".join(sec[:2])
        if f"b/{path}" in header or f"a/{path}" in header:
            return "".join(sec)

    raise GitHubError(f"no diff section found for {path}")


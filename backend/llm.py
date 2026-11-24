"""RepoCrew live-mode LLM agent loops (RC_MODE=live).

Each agent is a real Claude tool-use loop (official ``anthropic`` SDK) with its
own system prompt and a restricted tool set, capped at
``config.MAX_AGENT_TOOL_STEPS`` (12) tool steps per agent. The model is read
from ``RC_MODEL`` (default "claude-sonnet-5-5").

The Coder and Reviewer are separate agent instances with separate system
prompts, so the author of a patch never approves its own work.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import config

TRIAGE_SYSTEM = (
    "You are the RepoCrew Triage Agent. You decide whether a GitHub issue is a good "
    "candidate for an automated maintenance run on a small Python library. "
    "Skip vague, risky, or large issues (in_scope=false), e.g. full rewrites, "
    "architectural changes, or anything without a concrete failure signal. "
    "Respond with ONLY a JSON object of the form "
    '{"category": "bug|feature|question|duplicate", "difficulty": "easy|medium|hard", '
    '"confidence": 0-1, "in_scope": true|false, "reason": "concise", '
    '"comment_to_reporter": "polite handback comment or null"}.'
)

CODER_SYSTEM = (
    "You are the RepoCrew Coder Agent. You produce a MINIMAL unified diff that fixes "
    "the given issue and nothing else. Before editing source files, you must produce a "
    "failing test that proves the bug (either an existing test on the unpatched repo or "
    "a new test file named tests/test_repocrew_issue_<number>.py). Never edit existing "
    "test files; only the new repro test file is allowed. Use search_code and read_file "
    "to understand the code, then call apply_patch exactly once with a complete unified diff "
    "(a/ and b/ path prefixes). On a retry you receive your previous diff plus failing "
    "test output or reviewer feedback — use it. Never touch CI config, .env files, "
    "secret material, keys, or Dockerfiles. Do not add features that were not asked for."
)

REVIEWER_SYSTEM = (
    "You are the RepoCrew Reviewer Agent — an INDEPENDENT reviewer. You did not write "
    "this patch; be critical. Check: does the diff address the issue, does it avoid "
    "unrelated changes, does it match project style, is the change covered by adequate "
    "tests (request changes if a bug fix adds no regression test)? Use read_file to "
    "inspect the real files. Respond with ONLY a JSON object: "
    '{"verdict": "APPROVE|CHANGES_REQUESTED|REJECT", "notes": ["..."]}.'
)

TESTER_SYSTEM = (
    "You are the RepoCrew Tester Agent. You never edit code. You run the full pytest "
    "suite in the sandbox via run_tests and report what actually happened."
)


class AgentStepLimit(RuntimeError):
    pass


def _client():
    import anthropic  # imported lazily: only needed in live mode

    return anthropic.Anthropic(timeout=60.0)  # reads ANTHROPIC_API_KEY from the environment


def run_agent_loop(
    system: str,
    tools: list[dict],
    tool_impls: dict[str, Callable[[dict], Any]],
    initial_message: str,
    on_event: Callable[[str, str, dict | None], None] | None = None,
) -> str:
    """Run one tool-use loop; returns the final assistant text.

    on_event(kind, text, data) reports tool_call/tool_result activity so the
    orchestrator can record and stream it just like in demo mode.
    """
    client = _client()

    def note(kind: str, text: str, data: dict | None = None) -> None:
        if on_event:
            on_event(kind, text, data)

    messages: list[dict] = [{"role": "user", "content": initial_message}]
    steps = 0
    while True:
        response = client.messages.create(
            model=config.RC_MODEL,
            max_tokens=4096,
            system=system,
            tools=tools or anthropic_not_given(),
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        steps += len(tool_uses)
        if steps > config.MAX_AGENT_TOOL_STEPS:
            raise AgentStepLimit(
                f"agent exceeded the {config.MAX_AGENT_TOOL_STEPS}-tool-step safety cap"
            )
        results = []
        for call in tool_uses:
            note("tool_call", f"{call.name}({json.dumps(call.input)[:200]})",
                 {"tool": call.name, "input": call.input})
            impl = tool_impls.get(call.name)
            try:
                output = impl(call.input) if impl else f"ERROR: tool {call.name} not allowed"
            except Exception as exc:  # noqa: BLE001 - tool errors are reported back to the model
                output = f"ERROR: {exc}"
            note("tool_result", str(output)[:500], {"tool": call.name})
            results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": str(output)[:6000],
            })
        messages.append({"role": "user", "content": results})


def anthropic_not_given():
    from anthropic import NOT_GIVEN

    return NOT_GIVEN


def extract_json(text: str) -> dict:
    """Lenient JSON extraction from a model's final message."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object in agent output: {text[:200]}")
    return json.loads(text[start:end + 1])

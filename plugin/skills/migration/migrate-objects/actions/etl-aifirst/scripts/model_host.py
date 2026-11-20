"""Supported model host for AI-First Stage 0, sidecar produce, and Gates A/B.

Production default is Cortex Code (`cortex exec`). The plugin already runs inside Cortex,
so sidecar authoring and the gates must not depend on a developer-only `claude` CLI.

`AIFIRST_VERIFIER_CLI` / `--cli` remain test and developer overrides. A missing host is
UNMEASURED, never clean.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Optional, Tuple

DEFAULT_CLI = "cortex"


def default_cli() -> str:
    return os.environ.get("AIFIRST_VERIFIER_CLI") or os.environ.get("GATE_VERIFIER_CLI") or DEFAULT_CLI


def resolve_cli(cli: Optional[str] = None) -> Optional[str]:
    name = cli or default_cli()
    found = shutil.which(name)
    if found:
        return found
    if os.path.isfile(name):
        return name
    return None


def host_kind(resolved: str) -> str:
    base = os.path.basename(resolved).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    if base == "cortex" or base.startswith("cortex-"):
        return "cortex"
    return "claude"


def missing_host_error(cli: str) -> str:
    return (
        "verifier CLI %r not found. Pass --cli /path/to/cortex or set AIFIRST_VERIFIER_CLI. "
        "A gate that cannot reach its verifier is UNMEASURED, which is a different claim from clean."
        % cli
    )


def isolation_note(kind: str) -> str:
    if kind == "cortex":
        return "disabled via cortex exec --no-mcp --no-history --bypass"
    return "disabled via --safe-mode (CLAUDE.md, auto-memory, skills, plugins, hooks, MCP)"


def argv_for_isolated_call(
    resolved: str,
    prompt: str,
    *,
    view: str,
    settings_path: Optional[str] = None,
    model: Optional[str] = None,
    max_budget_usd: Optional[float] = None,
    tools: str = "Read,Grep,Glob,Write",
    output_format: str = "json",
    extra: Optional[list[str]] = None,
) -> list[str]:
    """Headless argv for one isolated call whose cwd/world is `view`."""
    kind = host_kind(resolved)
    extra = extra or []
    if kind == "cortex":
        # cortex exec accepts only text|json; stream-json is a Claude CLI format.
        if output_format not in ("text", "json"):
            output_format = "json"
        # The prompt must precede --allowed: --allowed is variadic, so a trailing
        # prompt is parsed as another tool name and `exec` then reports no message.
        argv = [
            resolved, "exec", prompt,
            "--bypass",
            "--no-history",
            "--no-mcp",
            "--format", output_format,
            "--max-turns", "20",
            "-w", view,
            "--allowed", tools,
        ]
        if model:
            argv += ["-m", model]
        return argv + extra
    argv = [resolved, "-p", prompt, "--tools", tools]
    if settings_path:
        argv += ["--settings", settings_path]
    argv += [
        "--permission-mode", "acceptEdits",
        "--safe-mode",
        "--output-format", output_format,
    ]
    if model:
        argv += ["--model", model]
    if max_budget_usd:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    argv += extra
    return argv


def redact_prompt(argv: list[str], prompt: str) -> list[str]:
    out = list(argv)
    for i, part in enumerate(out):
        if part == prompt:
            out[i] = "<CLI_PROMPT>"
    return out


DEFAULT_SIDECAR_MODEL_CMD = (
    "cortex exec --bypass --no-history --no-mcp --format json"
)

_FENCE_OPEN = re.compile(r"```(?:json)?\s*", re.S)
_VERDICT_KEYS = ("claims", "answers", "obligations", "verdicts")


def _as_envelope(obj: Any) -> Optional[dict]:
    if isinstance(obj, dict) and "type" in obj and "result" in obj:
        return obj
    return None


def unwrap_cli_stdout(out: Optional[str]) -> Tuple[str, Optional[dict]]:
    """Turn CLI stdout into (result_text, envelope_or_none).

    Accepts every host we actually run:

    * one Claude ``-p --output-format json`` envelope
    * a Cortex ``exec --format json`` JSONL stream (last ``type=result`` event wins)
    * a bare answer (``cat canned.json`` stubs) — envelope is None, text is stdout

    Cortex prints one JSON object per line (init, assistant, context_usage, result).
    ``json.loads`` of the whole stream fails; walking objects and taking the last
    ``type=result`` event is the same unwrap the Claude envelope already got.
    """
    if out is None:
        return "", None
    text = out if isinstance(out, str) else out.decode("utf-8", "replace")

    try:
        obj = json.loads(text)
    except Exception:
        obj = None
    env = _as_envelope(obj)
    if env is not None:
        return (env.get("result") or ""), env
    if obj is not None:
        return text, None

    found = None
    decoder = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, i)
        except Exception:
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl + 1
            continue
        cand = _as_envelope(obj)
        if cand is not None and cand.get("type") == "result":
            found = cand
        i = end
    if found is not None:
        return (found.get("result") or ""), found
    return text, None


def json_object_from_text(text: Optional[str]) -> Optional[dict]:
    """A bare JSON object, or one inside a ```json fence. None otherwise."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    m = _FENCE_OPEN.search(raw)
    brace = raw.find("{", m.end()) if m else raw.find("{")
    if brace == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw, brace)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def verdict_from_result_text(text: Optional[str]) -> Optional[dict]:
    """If the CLI result *is* a verdict object (Cortex printed it), return it.

    Gates require ``./verdict.json`` in the view. Cortex sometimes answers in the
    result envelope instead of using Write. Recovering a well-shaped object is
    lossless; inventing claims from prose is not.
    """
    obj = json_object_from_text(text)
    if obj is None:
        return None
    if any(k in obj for k in _VERDICT_KEYS):
        return obj
    return None

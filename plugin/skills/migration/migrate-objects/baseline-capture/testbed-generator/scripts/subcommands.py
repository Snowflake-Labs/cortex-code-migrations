"""Typed wrappers over the `scai testbed` mine-phase subcommands.

The CLI is the single source of truth for testbed state; this module reads only
the machine-readable `--json` envelope and never touches the opaque state.bin.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TESTBED_SUFFIX = ".testbed.json"


def _env_timeout(default: int = 3600) -> int:
    # Generous by design: catches a hung scai without tripping on a slow but
    # progressing whole-workload scan. A non-numeric SCAI_TESTBED_TIMEOUT must
    # degrade to the default, not raise ValueError at import before any driver runs.
    try:
        return int(os.environ.get("SCAI_TESTBED_TIMEOUT", default))
    except ValueError:
        return default


DEFAULT_TIMEOUT_SECONDS = _env_timeout()

# argv is everything after the `scai` program name; cwd is required by `init`;
# stdin feeds Console.In — propose-enrichments reads the whole envelope from it.
CliRunner = Callable[[list[str], str | None, str | None], subprocess.CompletedProcess]


@dataclass(frozen=True)
class TestbedError:
    code: str
    message: str = ""
    suggestion: str = ""


@dataclass(frozen=True)
class Envelope:
    success: bool
    result: dict | None
    error: TestbedError | None


def default_runner(scai_bin: str | None = None,
                   timeout: float | None = DEFAULT_TIMEOUT_SECONDS) -> CliRunner:
    program = scai_bin or os.environ.get("SCAI", "scai")

    def _run(argv: list[str], cwd: str | None = None,
             stdin: str | None = None) -> subprocess.CompletedProcess:
        # The two failures that strike before scai can emit an envelope — an
        # unlaunchable binary and a hang past the bound — become a non-zero
        # CompletedProcess so _envelope reports EXEC instead of raising or
        # blocking the whole skill forever.
        try:
            return subprocess.run(
                [program, *argv], input=stdin, capture_output=True, text=True, cwd=cwd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                [program, *argv], 124, "", f"scai timed out after {timeout}s: {' '.join(argv)}")
        except OSError as exc:
            return subprocess.CompletedProcess(
                [program, *argv], 127, "", f"could not execute scai ({program}): {exc}")

    return _run


def parse_envelope(stdout: str) -> Envelope:
    doc = json.loads(stdout)
    err = doc.get("error")
    return Envelope(
        success=bool(doc.get("success")),
        result=doc.get("result"),
        error=TestbedError(err["code"], err.get("message", ""), err.get("suggestion", ""))
        if err else None,
    )


class TestbedCli:
    def __init__(self, runner: CliRunner):
        self._run = runner

    def init(self, project_dir: str) -> Envelope:
        # init infers artifacts/workspace from the project, so cwd must be the project.
        return self._envelope(self._run(["testbed", "init", "--json"], project_dir))

    def compile(self, project_dir: str) -> Envelope:
        # compile is RequiresProject=true and infers its paths from the project,
        # so cwd must be the project (like init). It takes no artifacts path.
        return self._envelope(self._run(["testbed", "compile", "--json"], project_dir))

    def propose_enrichments(self, project_dir: str, envelope_json: str) -> Envelope:
        # RequiresProject=true: cwd is the project (like init/compile). The command reads the whole
        # envelope from stdin (Console.In.ReadToEnd); reject codes come back in the stdout envelope.
        return self._envelope(
            self._run(["testbed", "propose-enrichments", "--json"], project_dir, envelope_json))

    def validate(self, project_dir: str) -> Envelope:
        # validate is RequiresProject=true and reads the mined state to report
        # readiness (fk gaps / type conflicts / unsatisfied constraints), so cwd
        # must be the project (like compile). It takes no artifacts path.
        return self._envelope(self._run(["testbed", "validate", "--json"], project_dir))

    def generate(self, project_dir: str, out: str,
                 rows: int | None = None, seed: int | None = None) -> Envelope:
        # generate is RequiresProject=true; --out is the flat dir the CSV pool +
        # manifest.json land in. rows/seed are optional generator knobs.
        argv = ["testbed", "generate", "--out", out]
        if rows is not None:
            argv += ["--rows", str(rows)]
        if seed is not None:
            argv += ["--seed", str(seed)]
        argv.append("--json")
        return self._envelope(self._run(argv, project_dir))

    def inspect_branches(self, artifacts_path: str, stem: str) -> Envelope:
        argv = ["testbed", "inspect-branches", stem, "--artifacts-path", artifacts_path, "--json"]
        return self._envelope(self._run(argv, None))

    def list_unsolved(self, artifacts_path: str) -> Envelope:
        # Whole-workload scan. Per-object list-unsolved (a `stem` arg) has no caller
        # yet; it's a one-line add back the day per-object scanning is needed.
        argv = ["testbed", "list-unsolved", "--artifacts-path", artifacts_path, "--json"]
        return self._envelope(self._run(argv, None))

    @staticmethod
    def _envelope(cp: subprocess.CompletedProcess) -> Envelope:
        # In --json mode the testbed commands write the envelope (success OR error) to stdout.
        try:
            return parse_envelope(cp.stdout)
        except (json.JSONDecodeError, KeyError, TypeError):
            detail = (cp.stderr or cp.stdout or "").strip()[:500]
            return Envelope(False, None, TestbedError("EXEC", detail or "no parseable envelope"))


def enumerate_stems(artifacts_path: str) -> list[str]:
    """List artifact file stems under artifacts/**/testbed/*.testbed.json (sorted)."""
    root = Path(artifacts_path)
    return sorted(
        p.name[: -len(TESTBED_SUFFIX)]
        for p in root.glob(f"**/testbed/*{TESTBED_SUFFIX}")
    )

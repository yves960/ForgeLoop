from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Final, NamedTuple

from agent_backend import call_agent
from java_ut_verifier import (
    ProfileVerifierRequest,
    VerifierFeedback,
    render_verifier_feedback,
    verify_profile,
)
from run_config_store import RunConfig, load_run_config
from run_store import LoopResult

COMPLETION_PROMISE: Final = "COMPLETE"
ABORT_PROMISE: Final = "LOOP_BLOCKED"
RUNTIME_DIR_NAME: Final = ".loop"


class AdapterRequest(NamedTuple):
    run_dir: Path
    run_config: Path
    entrypoint: Path
    python_executable: str


class IterationArgumentError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Missing required iteration adapter argument: --run-config")


def verifier_request(config: RunConfig) -> ProfileVerifierRequest:
    verifier = config["profile"].get("verifier", {})
    return ProfileVerifierRequest(
        worktree_root=Path(config["worktreeRoot"]),
        module_dir=Path(config["moduleDir"]),
        module_rel=config["moduleRel"],
        base_tree=config["baseTree"],
        test=config["test"],
        maven=config["maven"],
        run_dir=Path(config["runDir"]),
        allowed_paths=tuple(config["profile"].get("allowedPathSuffixes", ())),
        forbidden_added_patterns=tuple(
            config["profile"].get("forbiddenAddedPatterns", ())
        ),
        verifier_type=verifier.get("type", "java-ut"),
        arguments=tuple(verifier.get("arguments", ())),
        pass_reason=verifier.get("passReason", "TARGET_UT_PASSED"),
        fail_reason=verifier.get("failReason", "TARGET_UT_FAILED"),
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(content)


def _next_iteration(runtime_dir: Path) -> int:
    path = runtime_dir / "iteration-counter.txt"
    current = 0
    if path.exists():
        try:
            current = int(path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, UnicodeError, ValueError):
            current = 0
    current += 1
    _write_text(path, str(current))
    return current


def _failure_reason(agent_output: str) -> str:
    interactive_markers = (
        "--skip-safe-check",
        "Continue? [y/N]",
        "Safety check declined",
    )
    if any(marker in agent_output for marker in interactive_markers):
        return "AGENT_INTERACTIVE_CONFIRMATION_REQUIRED"
    return "AGENT_EXECUTION_FAILED"


def _blocked_result(
    config: RunConfig,
    exit_code: int,
    reason: str,
) -> LoopResult:
    return LoopResult(
        status="BLOCKED",
        reason=reason,
        exitCode=exit_code,
        agentCommand=config["agent"]["command"],
    )


def _persist_agent_failure(
    config: RunConfig,
    iteration: int,
    agent_output: str,
    exit_code: int,
) -> None:
    runtime_dir = Path(config["moduleDir"]) / RUNTIME_DIR_NAME
    reason = _failure_reason(agent_output)
    feedback = render_verifier_feedback(
        VerifierFeedback(
            "VERIFIER_FAIL",
            reason,
            config["test"],
            f"agent exit code: {exit_code}\n"
            + f"See .loop/iterations/{iteration:03d}/agent-output.txt",
        )
    )
    _write_text(runtime_dir / "verifier-result.md", feedback)
    _write_text(
        runtime_dir / "result.json",
        json.dumps(
            _blocked_result(config, exit_code, reason),
            ensure_ascii=False,
            indent=2,
        ),
    )


def _print_agent_failure(
    config: RunConfig,
    iteration: int,
    agent_output: str,
    exit_code: int,
) -> None:
    print(f"[loop] iteration {iteration}: coding agent failed ({exit_code})")
    print(f"[loop] agent command: {config['agent']['command']}")
    if agent_output.strip():
        print("[loop] coding agent output:")
        for line in agent_output.rstrip().splitlines()[-40:]:
            print(f"  {line}")
    else:
        print("[loop] coding agent produced no output")
    if "--skip-safe-check" in agent_output:
        print(
            "[loop] hint: the configured agent requires a trust confirmation in each new worktree."
        )
        print(
            "[loop] configure its non-interactive trust flag once, for trusted repositories only:"
        )
        print("[loop]   loop config agent-arg --value=--skip-safe-check")
    print(f"[loop] full output: .loop/iterations/{iteration:03d}/agent-output.txt")


def run_iteration(config_path: Path) -> int:
    config = load_run_config(config_path)
    module_dir = Path(config["moduleDir"])
    runtime_dir = module_dir / RUNTIME_DIR_NAME
    runtime_dir.mkdir(parents=True, exist_ok=True)
    iteration = _next_iteration(runtime_dir)
    iteration_dir = runtime_dir / "iterations" / f"{iteration:03d}"
    iteration_dir.mkdir(parents=True, exist_ok=True)

    print(f"[loop] iteration {iteration}: starting coding agent")
    completed = call_agent(config["agent"], module_dir)
    agent_output = completed.stdout or ""
    _write_text(iteration_dir / "agent-output.txt", agent_output)
    if completed.returncode != 0:
        _persist_agent_failure(
            config,
            iteration,
            agent_output,
            completed.returncode,
        )
        _print_agent_failure(
            config,
            iteration,
            agent_output,
            completed.returncode,
        )
        print(f"<promise>{ABORT_PROMISE}</promise>")
        return completed.returncode or 1

    print(f"[loop] iteration {iteration}: running deterministic verifier")
    outcome = verify_profile(verifier_request(config), iteration_dir)
    if outcome.passed:
        print("[loop] verifier PASSED")
        print(f"<promise>{COMPLETION_PROMISE}</promise>")
        return 0

    reason = next(
        (
            line.split("=", 1)[1]
            for line in outcome.feedback.splitlines()
            if line.startswith("REASON=")
        ),
        "UNKNOWN",
    )
    print(f"[loop] verifier FAILED: {reason}")
    print("[loop] feedback saved to .loop/verifier-result.md")
    return 0


def run_iteration_cli(argv: list[str]) -> int:
    for index, value in enumerate(argv):
        if value == "--run-config" and index + 1 < len(argv):
            return run_iteration(Path(argv[index + 1]))
        prefix = "--run-config="
        if value.startswith(prefix):
            return run_iteration(Path(value[len(prefix) :]))
    raise IterationArgumentError()


def create_iteration_adapter(request: AdapterRequest) -> Path:
    if os.name == "nt":
        adapter = request.run_dir / "iteration-adapter.cmd"
        content = (
            "@echo off\r\n"
            f'"{request.python_executable}" "{request.entrypoint}" '
            f'_iteration --run-config "{request.run_config}"\r\n'
            "exit /b %ERRORLEVEL%\r\n"
        )
        with adapter.open("w", encoding="utf-8", newline="") as stream:
            _ = stream.write(content)
        return adapter

    adapter = request.run_dir / "iteration-adapter.sh"
    command = " ".join(
        shlex.quote(str(value))
        for value in (
            request.python_executable,
            request.entrypoint,
            "_iteration",
            "--run-config",
            request.run_config,
        )
    )
    with adapter.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(f"#!/bin/sh\nexec {command}\n")
    adapter.chmod(adapter.stat().st_mode | 0o100)
    return adapter

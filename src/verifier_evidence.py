from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict


class VerifierFeedback(NamedTuple):
    status: Literal["VERIFIER_PASS", "VERIFIER_FAIL"]
    reason: str
    test: str
    detail: str = ""


class VerificationOutcome(NamedTuple):
    passed: bool
    feedback: str
    blocked: bool = False


class PolicyViolationResult(TypedDict):
    status: Literal["FAIL"]
    reason: Literal["POLICY_VIOLATION"]
    test: str
    violations: list[str]


class TestBypassResult(TypedDict):
    status: Literal["FAIL"]
    reason: Literal["TEST_BYPASS_PATTERN"]
    test: str
    findings: list[str]


class CommandResult(TypedDict):
    status: Literal["PASS", "FAIL", "BLOCKED"]
    reason: str
    test: str
    exitCode: int


class VerificationEvidence(NamedTuple):
    outcome: VerificationOutcome
    result: PolicyViolationResult | TestBypassResult | CommandResult
    command_output: str | None = None


class EvidenceRequest(NamedTuple):
    module_dir: Path
    run_dir: Path


class VerifierError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def render_verifier_feedback(feedback: VerifierFeedback) -> str:
    lines = [
        feedback.status,
        "",
        f"REASON={feedback.reason}",
        f"TEST={feedback.test}",
    ]
    if feedback.detail:
        lines.extend(("", feedback.detail.rstrip()))
    return "\n".join(lines).rstrip() + "\n"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(content)


def persist_verification(
    request: EvidenceRequest,
    iteration_dir: Path,
    evidence: VerificationEvidence,
    runtime_safe: bool = True,
) -> VerificationOutcome:
    result_json = json.dumps(evidence.result, ensure_ascii=False, indent=2)
    _write_text(
        request.run_dir / "latest-verifier-result.md", evidence.outcome.feedback
    )
    _write_text(request.run_dir / "latest-result.json", result_json)
    if evidence.command_output is not None:
        _write_text(
            request.run_dir / "latest-maven-output.txt", evidence.command_output
        )
    if not runtime_safe:
        return evidence.outcome

    runtime_dir = request.module_dir / ".loop"
    _write_text(runtime_dir / "verifier-result.md", evidence.outcome.feedback)
    _write_text(iteration_dir / "verifier-output.txt", evidence.outcome.feedback)
    _write_text(runtime_dir / "result.json", result_json)
    if evidence.command_output is not None:
        _write_text(runtime_dir / "maven-output.txt", evidence.command_output)
        _write_text(iteration_dir / "maven-output.txt", evidence.command_output)
    return evidence.outcome

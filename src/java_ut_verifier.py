from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

from java_ut_policy import (
    ProfilePolicyRequest,
    find_policy_violations,
    find_test_bypass_additions,
)
from process_runner import run_process
from worktree_manager import build_worktree_tree


class ProfileVerifierRequest(NamedTuple):
    worktree_root: Path
    module_dir: Path
    module_rel: str
    base_tree: str
    test: str
    maven: str
    run_dir: Path
    allowed_paths: tuple[str, ...]
    forbidden_added_patterns: tuple[str, ...]
    verifier_type: Literal["java-ut", "maven"]
    arguments: tuple[str, ...]
    pass_reason: str
    fail_reason: str


class VerifierFeedback(NamedTuple):
    status: Literal["VERIFIER_PASS", "VERIFIER_FAIL"]
    reason: str
    test: str
    detail: str = ""


class VerificationOutcome(NamedTuple):
    passed: bool
    feedback: str


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


class MavenResult(TypedDict):
    status: Literal["PASS", "FAIL"]
    reason: str
    test: str
    exitCode: int


class VerificationEvidence(NamedTuple):
    outcome: VerificationOutcome
    result: PolicyViolationResult | TestBypassResult | MavenResult
    maven_output: str | None = None


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


def _persist_verification(
    request: ProfileVerifierRequest,
    iteration_dir: Path,
    evidence: VerificationEvidence,
) -> VerificationOutcome:
    runtime_dir = request.module_dir / ".loop"
    _write_text(runtime_dir / "verifier-result.md", evidence.outcome.feedback)
    _write_text(iteration_dir / "verifier-output.txt", evidence.outcome.feedback)
    _write_text(
        runtime_dir / "result.json",
        json.dumps(evidence.result, ensure_ascii=False, indent=2),
    )
    if evidence.maven_output is not None:
        _write_text(runtime_dir / "maven-output.txt", evidence.maven_output)
        _write_text(iteration_dir / "maven-output.txt", evidence.maven_output)
    return evidence.outcome


def verify_profile(
    request: ProfileVerifierRequest,
    iteration_dir: Path,
    baseline: bool = False,
) -> VerificationOutcome:
    if not request.base_tree:
        raise VerifierError("Verifier config is missing baseTree/baseCommit")
    iteration_dir.mkdir(parents=True, exist_ok=True)

    if not baseline:
        current_tree = build_worktree_tree(
            request.worktree_root,
            request.run_dir / "indexes",
            f"verify-{iteration_dir.name}",
        )
        policy_request = ProfilePolicyRequest(
            worktree_root=request.worktree_root,
            module_rel=request.module_rel,
            base_tree=request.base_tree,
            allowed_paths=request.allowed_paths,
            forbidden_added_patterns=request.forbidden_added_patterns,
        )
        violations = find_policy_violations(policy_request, current_tree)
        if violations:
            feedback = render_verifier_feedback(
                VerifierFeedback(
                    "VERIFIER_FAIL",
                    "POLICY_VIOLATION",
                    request.test,
                    "Unauthorized changed files:\n"
                    + "\n".join(f"- {path}" for path in violations),
                )
            )
            result: PolicyViolationResult = {
                "status": "FAIL",
                "reason": "POLICY_VIOLATION",
                "test": request.test,
                "violations": violations,
            }
            return _persist_verification(
                request,
                iteration_dir,
                VerificationEvidence(VerificationOutcome(False, feedback), result),
            )

        findings = find_test_bypass_additions(policy_request, current_tree)
        if findings:
            feedback = render_verifier_feedback(
                VerifierFeedback(
                    "VERIFIER_FAIL",
                    "TEST_BYPASS_PATTERN",
                    request.test,
                    "Potential test-bypass additions detected:\n"
                    + "\n".join(f"- {finding}" for finding in findings),
                )
            )
            bypass_result: TestBypassResult = {
                "status": "FAIL",
                "reason": "TEST_BYPASS_PATTERN",
                "test": request.test,
                "findings": findings,
            }
            return _persist_verification(
                request,
                iteration_dir,
                VerificationEvidence(
                    VerificationOutcome(False, feedback),
                    bypass_result,
                ),
            )

    arguments = (
        (f"-Dtest={request.test}", "test")
        if request.verifier_type == "java-ut"
        else tuple(
            argument.replace("{{TARGET}}", request.test)
            for argument in request.arguments
        )
    )
    completed = run_process(
        [request.maven, *arguments],
        cwd=request.module_dir,
        check=False,
    )
    maven_output = completed.stdout or ""
    passed = completed.returncode == 0
    reason = request.pass_reason if passed else request.fail_reason
    status: Literal["VERIFIER_PASS", "VERIFIER_FAIL"] = (
        "VERIFIER_PASS" if passed else "VERIFIER_FAIL"
    )
    detail = (
        ""
        if passed
        else (
            f"Maven exit code: {completed.returncode}\n"
            + "Read .loop/maven-output.txt before the next change."
        )
    )
    feedback = render_verifier_feedback(
        VerifierFeedback(status, reason, request.test, detail)
    )
    maven_result: MavenResult = {
        "status": "PASS" if passed else "FAIL",
        "reason": reason,
        "test": request.test,
        "exitCode": completed.returncode,
    }
    return _persist_verification(
        request,
        iteration_dir,
        VerificationEvidence(
            VerificationOutcome(passed, feedback),
            maven_result,
            maven_output,
        ),
    )

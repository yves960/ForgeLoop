from __future__ import annotations

from pathlib import Path
from typing import Final, Literal, NamedTuple

from process_runner import run_process
from verifier_evidence import (
    CommandResult,
    VerificationEvidence,
    VerificationOutcome,
    VerifierFeedback,
    render_verifier_feedback,
)

_INFRASTRUCTURE_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("the requested profile", "MAVEN_PROFILE_NOT_CONFIGURED"),
    ("non-resolvable parent pom", "MAVEN_DEPENDENCY_RESOLUTION_FAILED"),
    ("could not resolve dependencies", "MAVEN_DEPENDENCY_RESOLUTION_FAILED"),
    ("could not transfer artifact", "MAVEN_NETWORK_FAILURE"),
    ("pluginresolutionexception", "MAVEN_PLUGIN_RESOLUTION_FAILED"),
    ("no plugin found for prefix", "MAVEN_PLUGIN_NOT_CONFIGURED"),
    ("unknown host", "MAVEN_NETWORK_FAILURE"),
    ("connection timed out", "MAVEN_NETWORK_FAILURE"),
    ("pkix path building failed", "MAVEN_NETWORK_FAILURE"),
    ("java_home", "JAVA_RUNTIME_UNAVAILABLE"),
    ("could not find or load main class", "JAVA_RUNTIME_UNAVAILABLE"),
)


class MavenVerificationRequest(NamedTuple):
    executable: str
    arguments: tuple[str, ...]
    module_dir: Path
    target: str
    pass_reason: str
    fail_reason: str
    required_output_patterns: tuple[str, ...]
    baseline: bool


def execute_maven_verifier(request: MavenVerificationRequest) -> VerificationEvidence:
    try:
        completed = run_process(
            [request.executable, *request.arguments],
            cwd=request.module_dir,
            check=False,
        )
    except OSError as error:
        feedback = render_verifier_feedback(
            VerifierFeedback(
                "VERIFIER_FAIL",
                "VERIFIER_LAUNCH_FAILED",
                request.target,
                str(error),
            )
        )
        result = CommandResult(
            status="BLOCKED",
            reason="VERIFIER_LAUNCH_FAILED",
            test=request.target,
            exitCode=2,
        )
        return VerificationEvidence(VerificationOutcome(False, feedback, True), result)

    output = completed.stdout or ""
    passed = completed.returncode == 0
    missing_evidence = next(
        (
            pattern
            for pattern in request.required_output_patterns
            if pattern.lower() not in output.lower()
        ),
        None,
    )
    infrastructure_reason = next(
        (
            reason
            for marker, reason in _INFRASTRUCTURE_MARKERS
            if marker in output.lower()
        ),
        None,
    )
    if infrastructure_reason is not None:
        passed = False
    blocked = infrastructure_reason is not None
    if missing_evidence is not None:
        passed = False
        blocked = blocked or request.baseline

    if blocked:
        reason = infrastructure_reason or "VERIFIER_INFRASTRUCTURE_FAILURE"
    elif missing_evidence is not None:
        reason = "VERIFIER_EVIDENCE_MISSING"
    else:
        reason = request.pass_reason if passed else request.fail_reason
    status: Literal["VERIFIER_PASS", "VERIFIER_FAIL"] = (
        "VERIFIER_PASS" if passed else "VERIFIER_FAIL"
    )
    detail = ""
    if not passed:
        detail = f"Maven exit code: {completed.returncode}\n"
        if missing_evidence is not None:
            detail += f"Required verifier output not found: {missing_evidence}\n"
        detail += "Read .loop/maven-output.txt before the next change."
    feedback = render_verifier_feedback(
        VerifierFeedback(status, reason, request.target, detail)
    )
    result = CommandResult(
        status="BLOCKED" if blocked else "PASS" if passed else "FAIL",
        reason=reason,
        test=request.target,
        exitCode=completed.returncode,
    )
    return VerificationEvidence(
        VerificationOutcome(passed, feedback, blocked), result, output
    )

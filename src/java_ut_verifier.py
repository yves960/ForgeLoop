from __future__ import annotations

from pathlib import Path
from typing import Literal, NamedTuple

from java_ut_policy import (
    ProfilePolicyRequest,
    find_policy_violations,
    find_test_bypass_additions,
)
from maven_verifier import MavenVerificationRequest, execute_maven_verifier
from runtime_safety import UnsafeRuntimePathError, prepare_verifier_directory
from verifier_evidence import (
    CommandResult,
    EvidenceRequest,
    PolicyViolationResult,
    TestBypassResult,
    VerificationEvidence,
    VerificationOutcome,
    VerifierError,
    VerifierFeedback,
    persist_verification,
    render_verifier_feedback,
)
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
    required_paths: tuple[str, ...]
    required_output_patterns: tuple[str, ...]


def verify_profile(
    request: ProfileVerifierRequest,
    iteration_dir: Path,
    baseline: bool = False,
) -> VerificationOutcome:
    if not request.base_tree:
        raise VerifierError("Verifier config is missing baseTree/baseCommit")
    evidence_request = EvidenceRequest(request.module_dir, request.run_dir)
    try:
        iteration_dir = prepare_verifier_directory(request.module_dir, iteration_dir)
    except UnsafeRuntimePathError as error:
        feedback = render_verifier_feedback(
            VerifierFeedback(
                "VERIFIER_FAIL",
                "UNSAFE_RUNTIME_PATH",
                request.test,
                str(error),
            )
        )
        blocked_result: CommandResult = {
            "status": "BLOCKED",
            "reason": "UNSAFE_RUNTIME_PATH",
            "test": request.test,
            "exitCode": 2,
        }
        return persist_verification(
            evidence_request,
            iteration_dir,
            VerificationEvidence(
                VerificationOutcome(False, feedback, True), blocked_result
            ),
            runtime_safe=False,
        )

    missing_paths = [
        path
        for path in request.required_paths
        if not (request.module_dir / path).is_file()
        or (request.module_dir / path).is_symlink()
    ]
    if missing_paths:
        reason = "VERIFIER_REQUIRED_PATH_MISSING" if baseline else "POLICY_VIOLATION"
        feedback = render_verifier_feedback(
            VerifierFeedback(
                "VERIFIER_FAIL",
                reason,
                request.test,
                "Required verifier paths missing:\n"
                + "\n".join(f"- {path}" for path in missing_paths),
            )
        )
        if baseline:
            required_result = CommandResult(
                status="BLOCKED",
                reason=reason,
                test=request.test,
                exitCode=2,
            )
            evidence = VerificationEvidence(
                VerificationOutcome(False, feedback, True), required_result
            )
        else:
            policy_result = PolicyViolationResult(
                status="FAIL",
                reason="POLICY_VIOLATION",
                test=request.test,
                violations=missing_paths,
            )
            evidence = VerificationEvidence(
                VerificationOutcome(False, feedback), policy_result
            )
        return persist_verification(evidence_request, iteration_dir, evidence)

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
            return persist_verification(
                evidence_request,
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
            return persist_verification(
                evidence_request,
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
    evidence = execute_maven_verifier(
        MavenVerificationRequest(
            request.maven,
            arguments,
            request.module_dir,
            request.test,
            request.pass_reason,
            request.fail_reason,
            request.required_output_patterns,
            baseline,
        )
    )
    return persist_verification(
        evidence_request,
        iteration_dir,
        evidence,
    )

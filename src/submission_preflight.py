from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import NamedTuple

from delivery_adapter import (
    commit_tree,
    current_branch,
    current_commit,
    delivery_diff,
)
from iteration_runner import verifier_request
from java_ut_verifier import verify_profile
from run_config_store import RunConfig, load_run_config
from run_store import RunRecord, SubmissionRecord, load_run_record, write_run_record
from runtime_store import archive_runtime
from worktree_manager import build_worktree_tree, tree_changed_files


class SubmitOptions(NamedTuple):
    run_id: str
    confirmed: bool
    message: str | None
    message_file: str | None
    commit_template: str | None
    review_command: str | None
    no_review: bool
    keep_worktree: bool


class SubmissionContext(NamedTuple):
    options: SubmitOptions
    run_dir: Path
    record: RunRecord
    repo_root: Path
    worktree_root: Path
    branch: str | None
    source_head: str
    base_tree: str
    config: RunConfig


class SubmissionChanges(NamedTuple):
    delivery: list[str]
    baseline: list[str]
    loop: list[str]


class SubmissionError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def submission_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def load_submission_context(options: SubmitOptions) -> SubmissionContext:
    run_dir, record = load_run_record(options.run_id)
    if record.get("status") != "PASS":
        raise SubmissionError(
            f"Run {options.run_id} is not in PASS state "
            + f"(status={record.get('status')}). Only verified runs can be submitted."
        )

    repo_root = Path(record["repoRoot"])
    worktree_root = Path(record["worktreeRoot"])
    branch = record.get("branch")
    source_head = record.get("sourceHead")
    base_tree = record.get("baseTree") or record.get("baseCommit")
    if not worktree_root.exists():
        raise SubmissionError(f"Run worktree no longer exists: {worktree_root}")
    if not source_head or not base_tree:
        raise SubmissionError(
            "Run metadata is missing sourceHead/baseTree; cannot submit safely."
        )

    actual_branch = current_branch(worktree_root)
    if branch and actual_branch != branch:
        raise SubmissionError(
            f"Worktree branch changed: expected {branch}, "
            + f"found {actual_branch or '(detached)'}"
        )
    if current_commit(worktree_root) != source_head:
        raise SubmissionError(
            "The Loop worktree already contains a commit not created by the "
            + "v0.1.3 runtime. To avoid rewriting or duplicating history, submit "
            + "it manually or start a new run."
        )

    config_path = run_dir / "run-config.json"
    if not config_path.exists():
        raise SubmissionError(f"Run config not found: {config_path}")
    config = load_run_config(config_path)
    config["baseTree"] = base_tree
    return SubmissionContext(
        options,
        run_dir,
        record,
        repo_root,
        worktree_root,
        branch,
        source_head,
        base_tree,
        config,
    )


def _verifier_reason(feedback: str) -> str:
    return next(
        (
            line.split("=", 1)[1]
            for line in feedback.splitlines()
            if line.startswith("REASON=")
        ),
        "VERIFIER_FAILED",
    )


def run_final_verifier(context: SubmissionContext) -> bool:
    module_dir = Path(context.config["moduleDir"])
    print(f"[loop] submit: {context.options.run_id}")
    print(f"[loop] branch: {context.branch}")
    print("[loop] re-running deterministic verifier before git add/commit...")
    outcome = verify_profile(
        verifier_request(context.config),
        module_dir / ".loop" / "iterations" / "submit-final",
    )
    archive_runtime(module_dir, context.run_dir, namespace="submission")
    if outcome.passed:
        return True

    context.record["submission"] = SubmissionRecord(
        status="BLOCKED",
        reason=_verifier_reason(outcome.feedback),
        verifiedAt=submission_timestamp(),
    )
    write_run_record(context.run_dir, context.record)
    print("[loop] submit blocked: final verifier failed")
    return False


def collect_submission_changes(
    context: SubmissionContext,
) -> SubmissionChanges:
    final_tree = build_worktree_tree(
        context.worktree_root,
        context.run_dir / "indexes",
        "submit-final",
    )
    source_tree = commit_tree(context.worktree_root, context.source_head)
    changes = SubmissionChanges(
        delivery=tree_changed_files(
            context.worktree_root,
            source_tree,
            final_tree,
        ),
        baseline=tree_changed_files(
            context.worktree_root,
            source_tree,
            context.base_tree,
        ),
        loop=tree_changed_files(
            context.worktree_root,
            context.base_tree,
            final_tree,
        ),
    )
    if not changes.delivery:
        raise SubmissionError(
            "Nothing to submit: final worktree matches the original source HEAD."
        )

    diff = delivery_diff(context.worktree_root, source_tree, final_tree)
    print("\nDelivery changes relative to the original source HEAD:")
    print(diff.names or "  (none)")
    if diff.stat:
        print("\nDiff stat:")
        print(diff.stat)
    _print_change_group(
        "Pre-existing developer changes carried into the runtime baseline:",
        changes.baseline,
    )
    _print_change_group(
        "Loop-attributed changes relative to the runtime baseline:",
        changes.loop,
    )
    return changes


def _print_change_group(title: str, changes: list[str]) -> None:
    print(f"\n{title}")
    if changes:
        for relative_path in changes:
            print(f"  - {relative_path}")
    else:
        print("  (none)")

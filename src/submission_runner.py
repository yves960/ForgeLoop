from __future__ import annotations

from typing import NamedTuple

from config_store import DeliveryConfig, delivery_config
from delivery_adapter import (
    CommitRequest,
    create_commit,
    current_commit,
    run_review,
    stage_all,
)
from run_store import SubmissionRecord, write_run_record
from submission_preflight import (
    SubmissionChanges,
    SubmissionContext,
    SubmissionError,
    SubmitOptions,
    collect_submission_changes,
    load_submission_context,
    run_final_verifier,
    submission_timestamp,
)
from worktree_lifecycle import CleanupRequest, cleanup_worktree


class CommitAttempt(NamedTuple):
    submission: SubmissionRecord | None
    exit_code: int


def _user_confirmed(context: SubmissionContext) -> bool:
    if context.options.confirmed:
        return True
    answer = input("\nProceed with git add -> git commit -> review? [y/N]: ")
    return answer.strip().lower() in ("y", "yes")


def _commit(
    context: SubmissionContext,
    changes: SubmissionChanges,
    configured: DeliveryConfig,
) -> CommitAttempt:
    print("[loop] git add -A")
    staged = stage_all(context.worktree_root)
    if staged.returncode != 0:
        raise SubmissionError("git add failed:\n" + (staged.stdout or ""))

    print("[loop] git commit (existing Git hooks are enabled)")
    completed = create_commit(
        CommitRequest(
            context.worktree_root,
            context.options.message,
            context.options.message_file,
            context.options.commit_template or configured.get("commitTemplate"),
        )
    )
    if completed.returncode != 0:
        context.record["submission"] = SubmissionRecord(
            status="COMMIT_FAILED",
            failedAt=submission_timestamp(),
        )
        write_run_record(context.run_dir, context.record)
        print("[loop] commit failed or was cancelled; review was not invoked")
        return CommitAttempt(None, completed.returncode or 1)

    commit_sha = current_commit(context.worktree_root)
    submission = SubmissionRecord(
        status="COMMITTED",
        commit=commit_sha,
        committedAt=submission_timestamp(),
        deliveryChanges=changes.delivery,
        baselineChanges=changes.baseline,
        loopChanges=changes.loop,
    )
    return CommitAttempt(submission, 0)


def _save_submission(
    context: SubmissionContext,
    submission: SubmissionRecord,
) -> None:
    context.record["submission"] = submission
    write_run_record(context.run_dir, context.record)


def _review(
    context: SubmissionContext,
    submission: SubmissionRecord,
    configured: DeliveryConfig,
) -> int:
    commit_sha = submission.get("commit")
    if not commit_sha:
        raise SubmissionError("Committed submission is missing its commit SHA")
    if context.options.no_review:
        submission["reviewStatus"] = "SKIPPED"
        _save_submission(context, submission)
        print(f"[loop] committed: {commit_sha}")
        print("[loop] review skipped by --no-review")
        return 0

    command = context.options.review_command or configured.get("reviewCommand")
    if not command:
        submission["reviewStatus"] = "NOT_CONFIGURED"
        _save_submission(context, submission)
        print(f"[loop] committed: {commit_sha}")
        print(
            "[loop] no review command configured; commit is preserved for "
            + "manual review submission"
        )
        return 0

    print(f"[loop] review: {command}")
    completed = run_review(command, context.worktree_root)
    submission["reviewCommand"] = command
    submission["reviewExitCode"] = completed.returncode
    submission["reviewStatus"] = "SUBMITTED" if completed.returncode == 0 else "FAILED"
    submission["reviewedAt"] = submission_timestamp()
    _save_submission(context, submission)
    if completed.returncode != 0:
        print(
            f"[loop] commit created ({commit_sha}), but review command failed "
            + f"({completed.returncode})"
        )
        return completed.returncode or 1

    print(f"[loop] delivery complete: commit={commit_sha}")
    return _cleanup_after_review(context, submission)


def _cleanup_after_review(
    context: SubmissionContext,
    submission: SubmissionRecord,
) -> int:
    if context.options.keep_worktree:
        submission["cleanupStatus"] = "KEPT"
        _save_submission(context, submission)
        print(f"[loop] worktree retained by --keep-worktree: {context.worktree_root}")
        print(f"[loop] cleanup when finished: loop cleanup {context.options.run_id}")
        return 0

    print(f"[loop] removing submitted worktree: {context.worktree_root}")
    outcome = cleanup_worktree(
        CleanupRequest(
            context.repo_root,
            context.worktree_root,
            context.record.get("baselineRef"),
        )
    )
    if not outcome.success:
        submission["cleanupStatus"] = "FAILED"
        submission["cleanupError"] = outcome.detail
        _save_submission(context, submission)
        if outcome.failure_stage == "WORKTREE_REMOVE_FAILED":
            print("[loop] review succeeded, but automatic worktree cleanup failed")
        else:
            print("[loop] worktree removed, but runtime baseline cleanup failed")
        print(f"[loop] retry cleanup with: loop cleanup {context.options.run_id}")
        return 1

    submission["cleanupStatus"] = "CLEANED"
    submission["worktreeRemoved"] = True
    context.record["cleanedAt"] = submission_timestamp()
    _save_submission(context, submission)
    print("[loop] submitted worktree removed; branch and evidence preserved")
    print(f"[loop] evidence: {context.run_dir / 'evidence'}")
    return 0


def submit_run(options: SubmitOptions) -> int:
    context = load_submission_context(options)
    if not run_final_verifier(context):
        return 1
    changes = collect_submission_changes(context)
    if not _user_confirmed(context):
        print("[loop] submission cancelled; worktree was not staged or committed")
        return 0

    configured = delivery_config()
    attempt = _commit(context, changes, configured)
    if attempt.submission is None:
        return attempt.exit_code
    return _review(context, attempt.submission, configured)

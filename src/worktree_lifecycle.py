from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal, NamedTuple

from process_runner import run_process
from worktree_manager import delete_runtime_baseline_ref

CleanupFailureStage = Literal[
    "WORKTREE_REMOVE_FAILED",
    "BRANCH_DELETE_FAILED",
    "BASELINE_REF_DELETE_FAILED",
]


class CleanupRequest(NamedTuple):
    repo_root: Path
    worktree_root: Path
    baseline_ref: str | None
    branch: str | None = None
    delete_branch: bool = False


class CleanupOutcome(NamedTuple):
    success: bool
    worktree_present: bool
    worktree_removed: bool
    branch_deleted: bool
    failure_stage: CleanupFailureStage | None = None
    detail: str = ""


class WorktreeCleanupError(RuntimeError):
    outcome: CleanupOutcome

    def __init__(
        self,
        outcome: CleanupOutcome,
        baseline_ref: str | None,
    ) -> None:
        self.outcome = outcome
        messages: dict[CleanupFailureStage, str] = {
            "WORKTREE_REMOVE_FAILED": "Failed to remove worktree:\n" + outcome.detail,
            "BRANCH_DELETE_FAILED": "Failed to delete branch:\n" + outcome.detail,
            "BASELINE_REF_DELETE_FAILED": (
                f"Failed to delete runtime baseline ref: {baseline_ref}"
            ),
        }
        stage = outcome.failure_stage or "BASELINE_REF_DELETE_FAILED"
        super().__init__(messages[stage])


def _git(
    args: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return run_process(["git", *args], cwd=cwd, capture=True, check=False)


def cleanup_worktree(request: CleanupRequest) -> CleanupOutcome:
    worktree_present = request.worktree_root.exists()
    worktree_removed = False
    if worktree_present:
        completed = _git(
            ["worktree", "remove", "--force", str(request.worktree_root)],
            request.repo_root,
        )
        if completed.returncode != 0:
            return CleanupOutcome(
                False,
                True,
                False,
                False,
                "WORKTREE_REMOVE_FAILED",
                (completed.stdout or "").strip(),
            )
        worktree_removed = True

    branch_deleted = False
    if request.delete_branch and request.branch:
        completed = _git(["branch", "-D", request.branch], request.repo_root)
        if completed.returncode != 0:
            return CleanupOutcome(
                False,
                worktree_present,
                worktree_removed,
                False,
                "BRANCH_DELETE_FAILED",
                (completed.stdout or "").strip(),
            )
        branch_deleted = True

    if not delete_runtime_baseline_ref(request.repo_root, request.baseline_ref):
        return CleanupOutcome(
            False,
            worktree_present,
            worktree_removed,
            branch_deleted,
            "BASELINE_REF_DELETE_FAILED",
            "BASELINE_REF_DELETE_FAILED",
        )
    return CleanupOutcome(
        True,
        worktree_present,
        worktree_removed,
        branch_deleted,
    )

from __future__ import annotations

import sys

from run_preparation import PreparedRun, run_timestamp
from run_store import RunRecord, write_run_record
from worktree_manager import WorktreeResult


def persist_run_error(prepared: PreparedRun, worktree: WorktreeResult) -> None:
    record = RunRecord(
        runId=prepared.run_id,
        profileName=prepared.options.profile,
        test=prepared.test,
        repoRoot=str(prepared.repository.root),
        worktreeRoot=str(worktree.root),
        moduleRel=prepared.repository.module_rel,
        branch=worktree.branch,
        sourceHead=worktree.source_head,
        baseTree=worktree.baseline_tree,
        baselineRef=worktree.baseline_ref,
        runDir=str(prepared.run_dir),
        status="ERROR",
        endedAt=run_timestamp(),
    )
    try:
        write_run_record(prepared.run_dir, record)
    except (OSError, UnicodeError) as error:
        print(
            f"[loop] warning: failed to persist error metadata: {error}",
            file=sys.stderr,
            flush=True,
        )


def persist_unsafe_runtime(
    prepared: PreparedRun,
    worktree: WorktreeResult,
) -> int:
    record = RunRecord(
        runId=prepared.run_id,
        profileName=prepared.options.profile,
        test=prepared.test,
        repoRoot=str(prepared.repository.root),
        worktreeRoot=str(worktree.root),
        moduleRel=prepared.repository.module_rel,
        branch=worktree.branch,
        runDir=str(prepared.run_dir),
        status="BLOCKED",
        reason="UNSAFE_RUNTIME_PATH",
    )
    write_run_record(prepared.run_dir, record)
    print("[loop] BLOCKED: unsafe .loop runtime path")
    print(f"[loop] worktree preserved: {worktree.root}")
    return 2

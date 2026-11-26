from __future__ import annotations

import sys

from run_preparation import PreparedRun, run_timestamp
from run_store import RunRecord, write_run_record
from worktree_manager import WorktreeResult


def _run_record_with_status(
    prepared: PreparedRun,
    worktree: WorktreeResult,
    status: str,
) -> RunRecord:
    return RunRecord(
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
        status=status,
        endedAt=run_timestamp(),
    )


def persist_run_interrupted(
    prepared: PreparedRun, worktree: WorktreeResult
) -> None:
    """蔚 2026-11-26 N1：中断路径落态——此前 KeyboardInterrupt 直穿 main 处理器，
    run.json 永停 RUNNING 无 endedAt（真机 20261126-100127-c92e95 三连泄漏之首）。
    """
    record = _run_record_with_status(prepared, worktree, "INTERRUPTED")
    try:
        write_run_record(prepared.run_dir, record)
    except (OSError, UnicodeError) as error:
        print(
            f"[loop] warning: failed to persist interrupted metadata: {error}",
            file=sys.stderr,
            flush=True,
        )


def persist_run_environment(prepared: PreparedRun, worktree: WorktreeResult) -> None:
    """蔚 2026-11-26 N2：环境失败终态——JDK 缺位等不进迭代的死因可辨识。"""
    record = _run_record_with_status(prepared, worktree, "ENVIRONMENT")
    try:
        write_run_record(prepared.run_dir, record)
    except (OSError, UnicodeError) as error:
        print(
            f"[loop] warning: failed to persist environment metadata: {error}",
            file=sys.stderr,
            flush=True,
        )


def persist_run_error(prepared: PreparedRun, worktree: WorktreeResult) -> None:
    record = _run_record_with_status(prepared, worktree, "ERROR")
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

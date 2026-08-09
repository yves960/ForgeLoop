from __future__ import annotations

import os
import sys
from pathlib import Path

from iteration_runner import (
    ABORT_PROMISE,
    COMPLETION_PROMISE,
    AdapterRequest,
    create_iteration_adapter,
    verifier_request,
)
from java_ut_verifier import verify_profile
from process_runner import run_process
from run_config_store import RunConfig, write_run_config
from run_environment import render_task
from run_preparation import (
    PreparedRun,
    RunOptions,
    build_run_config,
    create_isolated_worktree,
    initial_run_record,
    prepare_run,
    run_timestamp,
)
from run_store import LoopResult, RunRecord, read_loop_result, write_run_record
from runtime_store import archive_runtime
from worktree_lifecycle import (
    CleanupRequest,
    WorktreeCleanupError,
    cleanup_worktree,
)
from worktree_manager import (
    WorktreeResult,
    build_worktree_tree,
    tree_changed_files,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(text)


def _baseline_noop(
    prepared: PreparedRun,
    worktree: WorktreeResult,
    record: RunRecord,
) -> int:
    record["status"] = "NOOP"
    record["endedAt"] = run_timestamp()
    write_run_record(prepared.run_dir, record)
    archive_runtime(worktree.module_dir, prepared.run_dir)
    cleanup = cleanup_worktree(
        CleanupRequest(
            prepared.repository.root,
            worktree.root,
            worktree.baseline_ref,
            worktree.branch,
            delete_branch=True,
        )
    )
    if not cleanup.success:
        raise WorktreeCleanupError(cleanup, worktree.baseline_ref)
    print(f"[loop] {prepared.test} already passes at baseline. Nothing changed.")
    return 0


def _ralph_command(
    prepared: PreparedRun,
    config: RunConfig,
    prompt_template: Path,
) -> list[str]:
    return [
        prepared.bun,
        str(prepared.ralph_ts),
        "Execute the engineering repair task defined in .loop/task.md",
        "--agent",
        "claude-code",
        "--max-iterations",
        str(config["maxIterations"]),
        "--completion-promise",
        COMPLETION_PROMISE,
        "--abort-promise",
        ABORT_PROMISE,
        "--no-commit",
        "--no-stream",
        "--no-questions",
        "--prompt-template",
        str(prompt_template),
    ]


def _print_final(
    record: RunRecord,
    result: LoopResult,
    changes: list[str],
) -> None:
    print("\n" + "=" * 68)
    print("Loop Engineering Result")
    print("=" * 68)
    print(f"Run ID:      {record['runId']}")
    print(f"Profile:     {record['profileName']}")
    print(f"Status:      {result.get('status', 'UNKNOWN')}")
    print(f"Reason:      {result.get('reason', '-')}")
    print(f"Target:      {record['test']}")
    print(f"Branch:      {record['branch']}")
    print(f"Worktree:    {record['worktreeRoot']}")
    print(f"Evidence:    {Path(record['runDir']) / 'evidence'}")
    print("Changed files:")
    if changes:
        for relative_path in changes:
            print(f"  - {relative_path}")
    else:
        print("  (none)")
    print("\nReview the worktree first. No delivery commit has been created.")
    print(
        f"Submit through the configured Git delivery flow:\n  loop submit {record['runId']}"
    )
    print(f"Or discard/cleanup:\n  loop cleanup {record['runId']}")


def _execute_active_run(
    prepared: PreparedRun,
    worktree: WorktreeResult,
) -> int:
    runtime_dir = worktree.module_dir / ".loop"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    _write_text(
        runtime_dir / "task.md",
        render_task(
            prepared.options.profiles_dir,
            prepared.options.profile,
            prepared.test,
        ),
    )
    config = build_run_config(prepared, worktree)
    config_path = prepared.run_dir / "run-config.json"
    write_run_config(config_path, config)
    adapter = create_iteration_adapter(
        AdapterRequest(
            prepared.run_dir,
            config_path,
            prepared.options.entrypoint,
            prepared.options.python_executable,
        )
    )
    record = initial_run_record(config)
    write_run_record(prepared.run_dir, record)

    print(f"[loop] worktree: {worktree.root}")
    print(f"[loop] branch:   {worktree.branch}")
    print(f"[loop] maven:    {config['maven']}")
    print("[loop] baseline verification...")
    baseline = verify_profile(
        verifier_request(config),
        runtime_dir / "iterations" / "000-baseline",
        baseline=True,
    )
    if baseline.passed:
        print("[loop] baseline already PASSED; no repair loop is needed.")
        return _baseline_noop(prepared, worktree, record)

    print("[loop] baseline failed as expected; starting controlled iterations...")
    prompt_template = prepared.run_dir / "ralph-prompt-template.txt"
    _write_text(
        prompt_template,
        "You are executing one iteration of an engineering repair loop. "
        + "Read .loop/task.md first. Then read .loop/verifier-result.md and "
        + ".loop/maven-output.txt if they exist. Inspect the current git diff "
        + "and repository state. Perform actual code changes required by the "
        + "task, not just analysis or recommendations. Never output any promise "
        + "tag. The deterministic external verifier decides whether the task is "
        + "complete. Exit normally after completing this iteration.",
    )
    environment = os.environ.copy()
    environment["RALPH_CLAUDE_BINARY"] = str(adapter)
    completed = run_process(
        _ralph_command(prepared, config, prompt_template),
        cwd=worktree.module_dir,
        env=environment,
        capture=False,
        check=False,
    )

    result = read_loop_result(worktree.module_dir)
    record["status"] = result.get("status", "UNKNOWN")
    record["reason"] = result.get("reason")
    record["ralphExitCode"] = completed.returncode
    record["endedAt"] = run_timestamp()
    final_tree = build_worktree_tree(
        worktree.root,
        prepared.run_dir / "indexes",
        "final",
    )
    changes = tree_changed_files(
        worktree.root,
        worktree.baseline_tree,
        final_tree,
    )
    record["finalTree"] = final_tree
    record["changedFiles"] = changes
    write_run_record(prepared.run_dir, record)
    archive_runtime(worktree.module_dir, prepared.run_dir)
    _print_final(record, result, changes)
    return 0 if result.get("status") == "PASS" else 1


def _persist_run_error(
    prepared: PreparedRun,
    worktree: WorktreeResult,
) -> None:
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


def execute_run(options: RunOptions) -> int:
    prepared = prepare_run(options)
    worktree = create_isolated_worktree(prepared)
    try:
        return _execute_active_run(prepared, worktree)
    except (OSError, UnicodeError, RuntimeError, ValueError):
        _persist_run_error(prepared, worktree)
        raise

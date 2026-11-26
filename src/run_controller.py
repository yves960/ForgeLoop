from __future__ import annotations

import os
from pathlib import Path

from hook_notify import notify_run_complete
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
from run_environment import RunEnvironmentError
from run_failure import (
    persist_run_environment,
    persist_run_error,
    persist_run_interrupted,
    persist_unsafe_runtime,
)
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
from runtime_safety import UnsafeRuntimePathError, prepare_runtime_directory
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
    runtime_dir = prepare_runtime_directory(worktree.module_dir, ".loop")
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
    if baseline.blocked:
        result = read_loop_result(worktree.module_dir, prepared.run_dir)
        record["status"] = "BLOCKED"
        record["reason"] = result.get("reason", "VERIFIER_INFRASTRUCTURE_FAILURE")
        record["endedAt"] = run_timestamp()
        write_run_record(prepared.run_dir, record)
        archive_runtime(worktree.module_dir, prepared.run_dir)
        print(f"[loop] baseline BLOCKED: {record['reason']}")
        print(f"[loop] worktree preserved: {worktree.root}")
        return 2
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

    result = read_loop_result(worktree.module_dir, prepared.run_dir)
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
    _ = notify_run_complete(prepared.run_dir)
    _print_final(record, result, changes)
    return 0 if result.get("status") == "PASS" else 1


def _cleanup_failed_run_resources(prepared: PreparedRun, worktree: WorktreeResult) -> None:
    """蔚 2026-11-19 P2-2 落地、2026-11-26 N1 抽取复用：失败/中断 run 当场回收
    worktree+branch——run dir 照留（审计设计不动）。清场失败不掩盖原始错误。"""
    try:
        from worktree_lifecycle import CleanupRequest, cleanup_worktree

        cleanup_worktree(
            CleanupRequest(
                repo_root=prepared.repository.root,
                worktree_root=worktree.root,
                baseline_ref=worktree.baseline_ref,
                branch=worktree.branch,
                delete_branch=True,
            )
        )
        print("[loop] 失败回收：worktree+branch 已清（run dir 保留审计）")
    except Exception as cleanup_error:  # noqa: BLE001
        print(f"[loop] 警告：失败回收未完成（{cleanup_error}）——可 loop cleanup 手动清")


def _sigterm_as_interrupt(signum, frame) -> None:  # noqa: ANN001
    """蔚 2026-11-26 N1：SIGTERM 转译为 KeyboardInterrupt——走同一条中断回收链。
    SIGKILL 不可捕获（物理上限，蔚已知）。"""
    raise KeyboardInterrupt()


def execute_run(options: RunOptions) -> int:
    prepared = prepare_run(options)
    worktree = create_isolated_worktree(prepared)
    import signal

    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _sigterm_as_interrupt)
    try:
        try:
            # 蔚 2026-11-26 N2：迭代前 JDK preflight（doctor 同源探测复用）。此前
            # 环境失败被 verifier 判 TARGET_UT_FAILED 进 10 轮 agent 燃烧（83% CPU
            # 修不可能绿的问题）——maven 口径修复带来的失败经济学回退。无 JDK 直接
            # ENVIRONMENT 终态退出，不烧一轮。注意 raise 必须落在 except 守区内
            # （首版放守区外：exit 1 对了但 persist+cleanup 双旁路，残留 1/1 实锤）。
            from loop_doctor import check_java_runtime

            java_check = check_java_runtime()
            if java_check.state != "✓":
                raise RunEnvironmentError(
                    "JDK 缺位，run 不进迭代（doctor 同口径）："
                    + (java_check.detail or "JAVA_HOME / /usr/libexec/java_home / PATH 均无")
                    + "。fix: brew install --cask temurin@17 或设 JAVA_HOME"
                )
            return _execute_active_run(prepared, worktree)
        except UnsafeRuntimePathError:
            return persist_unsafe_runtime(prepared, worktree)
        except RunEnvironmentError:
            # 蔚 2026-11-26 N2：环境类错误落 ENVIRONMENT 终态（区别于通用 ERROR）——
            # run.json 可辨识「死于环境」而非「死于代码」，JDK/loop 可执行缺位同归此类
            persist_run_environment(prepared, worktree)
            _cleanup_failed_run_resources(prepared, worktree)
            raise
        except KeyboardInterrupt:
            # 蔚 2026-11-26 N1：中断路径——此前直穿 loop_cli:347 的 main 级处理器
            # （return 130），不 persist 不清场：run.json 永停 RUNNING、worktree+
            # branch 双泄漏、status 读作活实例（真机 20261126-100127-c92e95）。
            # 落 INTERRUPTED 终态 + endedAt + 复用回收钩子；re-raise 保 130 语义。
            persist_run_interrupted(prepared, worktree)
            _cleanup_failed_run_resources(prepared, worktree)
            raise
        except (OSError, UnicodeError, RuntimeError, ValueError):
            persist_run_error(prepared, worktree)
            _cleanup_failed_run_resources(prepared, worktree)
            raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)

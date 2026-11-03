from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

from cli_parser import CliArguments, CliHandlers, build_parser
from config_commands import (
    add_agent_argument,
    clear_agent,
    clear_agent_arguments,
    clear_delivery,
    clear_hook_on_complete,
    clear_runtime_root,
    configure_agent,
    configure_commit_template,
    configure_hook_on_complete,
    configure_review_command,
    configure_runtime_root,
    show_config,
)
from iteration_runner import run_iteration_cli
from run_controller import execute_run
from run_preparation import RunOptions
from run_store import load_run_record, write_run_record
from runtime_store import (
    RunNotFoundError,
    find_zombie_runs,
    list_run_index,
    mark_zombie_runs,
    prune_run_index,
)
from loop_doctor import fix_venv_tools, render_doctor, run_doctor
from status_report import (
    StatusReportRequest,
    build_status_document,
    render_status_report,
)
from submission_preflight import SubmitOptions
from submission_runner import submit_run
from worktree_lifecycle import (
    CleanupRequest,
    WorktreeCleanupError,
    cleanup_worktree,
)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
PROFILES_DIR = ROOT_DIR / "profiles"


def eprint(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def local_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def cmd_run(args: CliArguments) -> int:
    known_profiles = (
        sorted(entry.name for entry in PROFILES_DIR.iterdir() if (entry / "profile.json").is_file())
        if PROFILES_DIR.is_dir()
        else []
    )
    if args.profile not in known_profiles:
        eprint(f"[loop] ERROR: Unknown profile: {args.profile}")
        eprint(
            "        Available: "
            + (", ".join(known_profiles) if known_profiles else f"(none found under {PROFILES_DIR})")
        )
        return 1
    if not (args.test or args.target):
        eprint("[loop] ERROR: one of --test / --target is required")
        eprint("        e.g. loop run java-ut-fixer --test com.example.FooTest")
        return 1
    return execute_run(
        RunOptions(
            args.profile,
            args.target or args.test,
            args.max_iterations,
            args.agent_command,
            args.agent_protocol,
            args.agent_arg,
            args.maven,
            args.require_clean,
            Path.cwd().resolve(),
            PROFILES_DIR,
            SCRIPT_DIR / "loop_cli.py",
            sys.executable,
            args.execution_id,
        )
    )


def cmd_status(args: CliArguments) -> int:
    if args.list_runs:
        return print_run_list(status_filter=args.status_filter or None)
    try:
        run_dir, meta = load_run_record(args.run_id)
    except RunNotFoundError:
        eprint(f"[loop] ERROR: Run not found: {args.run_id}")
        eprint("        Use 'loop status --list' to see available runs.")
        return 1
    request = StatusReportRequest(args.run_id, run_dir, meta, os.name == "nt")
    if args.json:
        print(json.dumps(build_status_document(request), ensure_ascii=False, indent=2))
        return 0
    print(render_status_report(request))
    return 0


def print_run_list(limit: int = 20, status_filter: str | None = None) -> int:
    entries = sorted(
        list_run_index().items(),
        key=lambda item: item[1].created_at,
        reverse=True,
    )
    if status_filter:
        wanted = status_filter.lower()
        entries = [item for item in entries if item[1].status == wanted]
    entries = entries[:limit]
    if not entries:
        print("[loop] no matching runs in the index")
        return 0
    print(f"{'RUN ID':<40} {'STATUS':<10} {'CREATED':<20} PATH")
    for run_id, entry in entries:
        # 1970 epoch 兜底只影响人读表格；--json 保持机器契约不变
        created = entry.created_at[:19]
        if created.startswith("1970"):
            created = "<mtime-unknown>"
        print(f"{run_id[:39]:<40} {entry.status[:9]:<10} {created:<20} {entry.path}")
    return 0


def cmd_cleanup(args: CliArguments) -> int:
    try:
        run_dir, meta = load_run_record(args.run_id)
    except RunNotFoundError:
        eprint(f"[loop] ERROR: Run not found: {args.run_id}")
        eprint("        Use 'loop status --list' to see available runs.")
        return 1
    repo_root = Path(meta["repoRoot"])
    wt_root = Path(meta["worktreeRoot"])
    branch = meta.get("branch")

    worktree_present = wt_root.exists()
    if worktree_present:
        print(f"[loop] removing worktree: {wt_root}")
    else:
        print("[loop] worktree already absent")

    if args.delete_branch and branch:
        print(f"[loop] deleting branch: {branch}")
    outcome = cleanup_worktree(
        CleanupRequest(
            repo_root,
            wt_root,
            meta.get("baselineRef"),
            branch,
            args.delete_branch,
        )
    )
    if not outcome.success:
        raise WorktreeCleanupError(outcome, meta.get("baselineRef"))
    meta["cleanedAt"] = local_now().isoformat(timespec="seconds")
    write_run_record(run_dir, meta)
    print(f"[loop] evidence preserved: {run_dir / 'evidence'}")
    return 0


def cmd_submit(args: CliArguments) -> int:
    return submit_run(
        SubmitOptions(
            args.run_id,
            args.yes,
            args.message,
            args.message_file,
            args.commit_template,
            args.review_command,
            args.no_review,
            args.keep_worktree,
        )
    )


def cmd_config_commit_template(args: CliArguments) -> int:
    return configure_commit_template(args.path)


def cmd_config_review_command(args: CliArguments) -> int:
    return configure_review_command(args.command)


def cmd_config_clear_delivery(_args: CliArguments) -> int:
    return clear_delivery()


def cmd_config_agent(args: CliArguments) -> int:
    return configure_agent(args.command, args.protocol)


def cmd_config_agent_arg(args: CliArguments) -> int:
    return add_agent_argument(args.value)


def cmd_config_clear_agent_args(_args: CliArguments) -> int:
    return clear_agent_arguments()


def cmd_config_runtime_root(args: CliArguments) -> int:
    return configure_runtime_root(args.path)


def cmd_config_clear_runtime_root(_args: CliArguments) -> int:
    return clear_runtime_root()


def cmd_config_show(_args: CliArguments) -> int:
    return show_config()


def cmd_config_clear_agent(_args: CliArguments) -> int:
    return clear_agent()


def cmd_config_hook_on_complete(args: CliArguments) -> int:
    return configure_hook_on_complete(args.url)


def cmd_config_clear_hook_on_complete(_args: CliArguments) -> int:
    return clear_hook_on_complete()


def parse_max_age(value: str) -> int:
    text = str(value or "").strip().lower()
    if text.endswith("d"):
        text = text[:-1]
    days = int(text) if text.isdigit() else 0
    if days < 1:
        raise ValueError("--max-age 需为正整数天数，支持 Nd 后缀或纯数字（如 7d 或 30）")
    return days


def cmd_gc(args: CliArguments) -> int:
    dry_run = args.dry_run or not args.prune
    # 蔚 11-03 工单#1：僵尸 RUNNING 治理——报告模式列出，--prune 转 failed:abandoned
    zombies = find_zombie_runs()
    for run_id, started, _path in zombies:
        verb = "zombie→failed:abandoned" if not dry_run else "zombie（--prune 转 failed:abandoned）"
        print(f"[loop] gc: {verb} {run_id} (started {started})")
    if zombies and not dry_run:
        mark_zombie_runs()
    removed = prune_run_index(dry_run=dry_run, max_age_days=parse_max_age(args.max_age))
    if not removed and not zombies:
        print("[loop] gc: nothing to prune")
        return 0
    verb = "would prune" if dry_run else "pruned"
    for run_id, status, path in removed:
        print(f"[loop] gc: {verb} {run_id} (status={status}) {path}")
    return 0


def cmd_doctor(args: CliArguments) -> int:
    if args.fix:
        print(f"[loop] doctor --fix: {fix_venv_tools(ROOT_DIR)}")
    report, failures = render_doctor(run_doctor(ROOT_DIR))
    print(report)
    warns = sum(1 for line in report.splitlines() if "⚠" in line)
    strict = args.strict or bool(os.environ.get("LOOP_DOCTOR_STRICT"))
    if strict and (failures or warns):
        eprint(f"[loop] doctor --strict: 存在 ✗/{fails_hint(warns)}，环境未就绪")
        return 1
    if failures:
        eprint("[loop] doctor: 存在必须修复项（✗），见上方 fix 提示")
        return 1
    return 0


def fails_hint(warns: int) -> str:
    return f"⚠×{warns}" if warns else "✗"


def cli_handlers() -> CliHandlers:
    return CliHandlers(
        run=cmd_run,
        submit=cmd_submit,
        config_agent=cmd_config_agent,
        config_agent_arg=cmd_config_agent_arg,
        config_clear_agent_args=cmd_config_clear_agent_args,
        config_commit_template=cmd_config_commit_template,
        config_review_command=cmd_config_review_command,
        config_clear_delivery=cmd_config_clear_delivery,
        config_runtime_root=cmd_config_runtime_root,
        config_clear_runtime_root=cmd_config_clear_runtime_root,
        config_show=cmd_config_show,
        config_clear_agent=cmd_config_clear_agent,
        config_hook_on_complete=cmd_config_hook_on_complete,
        config_clear_hook_on_complete=cmd_config_clear_hook_on_complete,
        status=cmd_status,
        cleanup=cmd_cleanup,
        gc=cmd_gc,
        doctor=cmd_doctor,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_iteration":
        return run_iteration_cli(argv[1:])

    parser = build_parser(cli_handlers())
    args = parser.parse_args(argv, namespace=CliArguments())
    try:
        return args.func(args)
    except KeyboardInterrupt:
        eprint("\n[loop] interrupted")
        return 130
    except RunNotFoundError as exc:
        eprint(f"[loop] ERROR: {exc}")
        eprint("        Use 'loop status --list' to see available runs.")
        return 1
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        eprint(f"[loop] ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

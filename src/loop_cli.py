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
from runtime_store import RunNotFoundError, list_run_index, prune_run_index
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
        return print_run_list()
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


def print_run_list(limit: int = 20) -> int:
    entries = sorted(
        list_run_index().items(),
        key=lambda item: item[1].created_at,
        reverse=True,
    )[:limit]
    if not entries:
        print("[loop] no runs registered yet")
        return 0
    print(f"{'RUN ID':<40} {'STATUS':<10} {'CREATED':<20} PATH")
    for run_id, entry in entries:
        print(f"{run_id[:39]:<40} {entry.status[:9]:<10} {entry.created_at[:19]:<20} {entry.path}")
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


def cmd_gc(args: CliArguments) -> int:
    dry_run = args.dry_run or not args.prune
    removed = prune_run_index(dry_run=dry_run)
    if not removed:
        print("[loop] gc: nothing to prune")
        return 0
    verb = "would prune" if dry_run else "pruned"
    for run_id, status, path in removed:
        print(f"[loop] gc: {verb} {run_id} (status={status}) {path}")
    return 0


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

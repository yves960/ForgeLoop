from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import NamedTuple

from agent_backend import AGENT_PROTOCOLS


def _missing_handler(_args: argparse.Namespace) -> int:
    return 2


class CliArguments(argparse.Namespace):
    command: str = ""
    config_command: str = ""
    profile: str = ""
    test: str = ""
    target: str = ""
    max_iterations: int | None = None
    execution_id: str | None = None
    agent_command: str | None = None
    agent_protocol: str | None = None
    agent_arg: list[str] | None = None
    maven: str | None = None
    require_clean: bool = False
    run_id: str = ""
    json: bool = False
    yes: bool = False
    message: str | None = None
    message_file: str | None = None
    commit_template: str | None = None
    review_command: str | None = None
    no_review: bool = False
    keep_worktree: bool = False
    path: str = ""
    protocol: str | None = None
    value: str = ""
    delete_branch: bool = False
    func: Callable[[CliArguments], int] = _missing_handler


class CliHandlers(NamedTuple):
    run: Callable[[CliArguments], int]
    submit: Callable[[CliArguments], int]
    config_agent: Callable[[CliArguments], int]
    config_agent_arg: Callable[[CliArguments], int]
    config_clear_agent_args: Callable[[CliArguments], int]
    config_commit_template: Callable[[CliArguments], int]
    config_review_command: Callable[[CliArguments], int]
    config_clear_delivery: Callable[[CliArguments], int]
    config_runtime_root: Callable[[CliArguments], int]
    config_clear_runtime_root: Callable[[CliArguments], int]
    config_show: Callable[[CliArguments], int]
    config_clear_agent: Callable[[CliArguments], int]
    config_hook_on_complete: Callable[[CliArguments], int]
    config_clear_hook_on_complete: Callable[[CliArguments], int]
    status: Callable[[CliArguments], int]
    cleanup: Callable[[CliArguments], int]


def build_parser(handlers: CliHandlers) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loop",
        description="Loop Engineering: controlled engineering loops for complex tasks.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a Loop Engineering profile")
    _ = run.add_argument("profile")
    target = run.add_mutually_exclusive_group(required=True)
    _ = target.add_argument(
        "--test",
        help="JUnit test class or Class#method (java-ut-fixer)",
    )
    _ = target.add_argument(
        "--target",
        help="Profile-specific scan, rule set, component, or dependency target",
    )
    _ = run.add_argument("--max-iterations", type=int, default=None)
    _ = run.add_argument(
        "--execution-id",
        default=None,
        help=(
            "External execution id (e.g. WorkMesh exec-YYYYMMDD-XXXXXX); "
            + "persisted to run.json, echoed in the worktree branch name and "
            + "the on-complete webhook payload"
        ),
    )
    _ = run.add_argument(
        "--agent-command",
        default=None,
        help="Override coding-agent command/path for this run",
    )
    _ = run.add_argument(
        "--agent-protocol",
        default=None,
        choices=AGENT_PROTOCOLS,
        help="Agent CLI protocol",
    )
    _ = run.add_argument(
        "--agent-arg",
        action="append",
        default=None,
        help=(
            "Fixed coding-agent arg for this run; repeatable. For flags "
            + "beginning with -- use --agent-arg=--flag"
        ),
    )
    _ = run.add_argument("--maven", default=None, help="Override mvnw.cmd/mvn path")
    _ = run.add_argument(
        "--require-clean",
        action="store_true",
        help=(
            "Strict mode: refuse a dirty source checkout instead of "
            + "snapshotting local changes"
        ),
    )
    run.set_defaults(func=handlers.run)

    submit = sub.add_parser(
        "submit",
        help="Submit a verified run through git add -> git commit -> review",
    )
    _ = submit.add_argument("run_id")
    _ = submit.add_argument(
        "--yes",
        action="store_true",
        help="Skip the pre-submit confirmation prompt",
    )
    message = submit.add_mutually_exclusive_group()
    _ = message.add_argument(
        "--message",
        default=None,
        help="Commit message; Git hooks still run",
    )
    _ = message.add_argument(
        "--message-file",
        default=None,
        help="Commit message file; Git hooks still run",
    )
    _ = submit.add_argument(
        "--commit-template",
        default=None,
        help="Override configured git commit template for this submit",
    )
    _ = submit.add_argument(
        "--review-command",
        default=None,
        help="Override configured review command for this submit",
    )
    _ = submit.add_argument(
        "--no-review",
        action="store_true",
        help="Commit but do not invoke the review command",
    )
    _ = submit.add_argument(
        "--keep-worktree",
        action="store_true",
        help="Keep the worktree and runtime baseline after review succeeds",
    )
    submit.set_defaults(func=handlers.submit)

    config = sub.add_parser(
        "config",
        help="Configure Loop Engineering once per machine",
    )
    config_sub = config.add_subparsers(dest="config_command", required=True)
    agent = config_sub.add_parser("agent", help="Set the coding-agent backend")
    _ = agent.add_argument(
        "command",
        help="Agent executable/batch path or command name",
    )
    _ = agent.add_argument(
        "--protocol",
        default=None,
        choices=AGENT_PROTOCOLS,
        help="Infer from command when omitted",
    )
    agent.set_defaults(func=handlers.config_agent)

    agent_arg = config_sub.add_parser(
        "agent-arg",
        help="Add a fixed argument passed to the coding-agent on every run",
    )
    _ = agent_arg.add_argument(
        "--value",
        required=True,
        help="Argument value. For flags beginning with --, use --value=--flag",
    )
    agent_arg.set_defaults(func=handlers.config_agent_arg)
    clear_agent_args = config_sub.add_parser(
        "clear-agent-args",
        help="Clear all fixed coding-agent arguments",
    )
    clear_agent_args.set_defaults(func=handlers.config_clear_agent_args)

    template = config_sub.add_parser(
        "commit-template",
        help="Set the enterprise git commit template",
    )
    _ = template.add_argument("path")
    template.set_defaults(func=handlers.config_commit_template)
    review = config_sub.add_parser(
        "review-command",
        help="Set the delivery review command",
    )
    _ = review.add_argument("command", help="Command string, e.g. git review")
    review.set_defaults(func=handlers.config_review_command)
    clear_delivery = config_sub.add_parser(
        "clear-delivery",
        help="Clear delivery configuration",
    )
    clear_delivery.set_defaults(func=handlers.config_clear_delivery)

    runtime = config_sub.add_parser(
        "runtime-root",
        help="Set the root directory for runs, worktrees and evidence",
    )
    _ = runtime.add_argument("path")
    runtime.set_defaults(func=handlers.config_runtime_root)
    clear_runtime = config_sub.add_parser(
        "clear-runtime-root",
        help="Use the target repository drive for runtime data",
    )
    clear_runtime.set_defaults(func=handlers.config_clear_runtime_root)
    show = config_sub.add_parser("show", help="Show current configuration")
    show.set_defaults(func=handlers.config_show)
    clear_agent = config_sub.add_parser(
        "clear-agent",
        help="Clear the configured coding agent",
    )
    clear_agent.set_defaults(func=handlers.config_clear_agent)

    hook_on_complete = config_sub.add_parser(
        "hook-on-complete",
        help="Set a webhook URL fired once when a run reaches a terminal status",
    )
    _ = hook_on_complete.add_argument("url", help="HTTP(S) webhook URL")
    hook_on_complete.set_defaults(func=handlers.config_hook_on_complete)
    clear_hook = config_sub.add_parser(
        "clear-hook-on-complete",
        help="Clear the on-complete webhook",
    )
    clear_hook.set_defaults(func=handlers.config_clear_hook_on_complete)

    status = sub.add_parser("status", help="Show metadata for a run")
    _ = status.add_argument("run_id")
    _ = status.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable status document (for the AICP bridge)",
    )
    status.set_defaults(func=handlers.status)
    cleanup = sub.add_parser(
        "cleanup",
        help="Remove a run worktree while preserving evidence",
    )
    _ = cleanup.add_argument("run_id")
    _ = cleanup.add_argument("--delete-branch", action="store_true")
    cleanup.set_defaults(func=handlers.cleanup)
    return parser

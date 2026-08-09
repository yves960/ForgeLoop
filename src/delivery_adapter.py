from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NamedTuple

from process_runner import run_process


class CommitRequest(NamedTuple):
    worktree_root: Path
    message: str | None
    message_file: str | None
    template: str | None


class DeliveryDiff(NamedTuple):
    names: str
    stat: str


class DeliveryAdapterError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def _git(
    args: list[str],
    cwd: Path,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_process(
        ["git", *args],
        cwd=cwd,
        capture=capture,
        check=False,
    )


def current_branch(worktree_root: Path) -> str:
    completed = _git(["branch", "--show-current"], worktree_root)
    if completed.returncode != 0:
        raise DeliveryAdapterError(completed.stdout or "git branch failed")
    return completed.stdout.strip()


def current_commit(worktree_root: Path) -> str:
    completed = _git(["rev-parse", "HEAD"], worktree_root)
    if completed.returncode != 0:
        raise DeliveryAdapterError(completed.stdout or "git rev-parse HEAD failed")
    return completed.stdout.strip()


def commit_tree(worktree_root: Path, commit: str) -> str:
    completed = _git(["rev-parse", f"{commit}^{{tree}}"], worktree_root)
    if completed.returncode != 0:
        raise DeliveryAdapterError(completed.stdout or "git rev-parse tree failed")
    return completed.stdout.strip()


def delivery_diff(
    worktree_root: Path,
    old_tree: str,
    new_tree: str,
) -> DeliveryDiff:
    names = _git(
        ["diff", "--name-status", old_tree, new_tree, "--"],
        worktree_root,
    )
    stat = _git(
        ["diff", "--stat", old_tree, new_tree, "--"],
        worktree_root,
    )
    if names.returncode != 0:
        raise DeliveryAdapterError(names.stdout or "git diff --name-status failed")
    if stat.returncode != 0:
        raise DeliveryAdapterError(stat.stdout or "git diff --stat failed")
    return DeliveryDiff(names.stdout.rstrip(), stat.stdout.rstrip())


def stage_all(worktree_root: Path) -> subprocess.CompletedProcess[str]:
    return _git(["add", "-A"], worktree_root)


def _commit_arguments(request: CommitRequest) -> list[str]:
    arguments = ["commit"]
    if request.message is not None:
        arguments.extend(("-m", request.message))
        return arguments
    if request.message_file:
        message_file = Path(request.message_file).resolve()
        if not message_file.exists():
            raise DeliveryAdapterError(f"Commit message file not found: {message_file}")
        arguments.extend(("-F", str(message_file)))
        return arguments
    if request.template:
        template = Path(request.template).resolve()
        if not template.exists():
            raise DeliveryAdapterError(
                f"Configured commit template not found: {template}"
            )
        arguments.extend(("-t", str(template)))
    return arguments


def create_commit(request: CommitRequest) -> subprocess.CompletedProcess[str]:
    return _git(
        _commit_arguments(request),
        request.worktree_root,
        capture=False,
    )


def run_review(
    command: str,
    worktree_root: Path,
) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return run_process(
            [comspec, "/d", "/s", "/c", command],
            cwd=worktree_root,
            capture=False,
            check=False,
        )
    return run_process(
        ["/bin/sh", "-lc", command],
        cwd=worktree_root,
        capture=False,
        check=False,
    )

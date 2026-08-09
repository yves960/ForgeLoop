from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from process_runner import run_process
from worktree_manager import normalize_git_path, tree_changed_files


class ProfilePolicyRequest(NamedTuple):
    worktree_root: Path
    module_rel: str
    base_tree: str
    allowed_paths: tuple[str, ...]
    forbidden_added_patterns: tuple[str, ...]


def find_policy_violations(
    request: ProfilePolicyRequest,
    current_tree: str,
) -> list[str]:
    module_prefix = normalize_git_path(request.module_rel).rstrip("/")
    module_path = f"{module_prefix}/" if module_prefix else ""
    runtime_prefixes = (
        (f"{module_prefix}/.loop/", f"{module_prefix}/.ralph/")
        if module_prefix
        else (".loop/", ".ralph/")
    )
    return [
        path
        for path in tree_changed_files(
            request.worktree_root,
            request.base_tree,
            current_tree,
        )
        if not any(
            (
                path == module_path + allowed.rstrip("/")
                if not allowed.endswith("/")
                else path.startswith(module_path + allowed)
            )
            for allowed in request.allowed_paths
        )
        and not any(path.startswith(prefix) for prefix in runtime_prefixes)
    ]


def find_test_bypass_additions(
    request: ProfilePolicyRequest,
    current_tree: str,
) -> list[str]:
    patterns = tuple(pattern.lower() for pattern in request.forbidden_added_patterns)
    if not patterns:
        return []
    output = run_process(
        [
            "git",
            "diff",
            "--unified=0",
            request.base_tree,
            current_tree,
            "--",
        ],
        cwd=request.worktree_root,
        check=True,
    ).stdout
    findings: list[str] = []
    for line in output.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lowered = line.lower()
            if any(pattern in lowered for pattern in patterns):
                findings.append(line[1:].strip())
    return findings

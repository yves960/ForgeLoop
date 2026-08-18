from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Final, NamedTuple, TypedDict

from process_runner import run_process

INTERNAL_RUNTIME_PARTS: Final[frozenset[str]] = frozenset({".loop", ".ralph"})


class SourceSnapshot(TypedDict):
    trackedPatch: bool
    untrackedFiles: list[str]


class WorktreeRequest(NamedTuple):
    repo_root: Path
    module_rel: str
    profile: str
    run_id: str
    run_dir: Path
    snapshot_local_changes: bool = True
    execution_id: str | None = None


class WorktreeResult(NamedTuple):
    root: Path
    module_dir: Path
    branch: str
    source_head: str
    baseline_tree: str
    baseline_ref: str
    source_snapshot: SourceSnapshot


class WorktreeError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def _git(
    args: list[str], cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return run_process(["git", *args], cwd=cwd, capture=True, check=check)


def normalize_git_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def source_status(repo_root: Path) -> str:
    return _git(["status", "--porcelain"], repo_root).stdout.strip()


def _is_internal_runtime_path(relative_path: str) -> bool:
    parts = (part for part in normalize_git_path(relative_path).split("/") if part)
    return any(part in INTERNAL_RUNTIME_PARTS for part in parts)


def _untracked_source_files(repo_root: Path) -> list[str]:
    output = _git(["ls-files", "--others", "--exclude-standard"], repo_root).stdout
    return [
        relative_path
        for line in output.splitlines()
        if (relative_path := normalize_git_path(line.strip()))
        and not _is_internal_runtime_path(relative_path)
    ]


def _write_source_patch(repo_root: Path, patch_path: Path) -> bool:
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    with patch_path.open("wb") as stream:
        completed = subprocess.run(
            ["git", "diff", "--binary", "--full-index", "HEAD", "--"],
            cwd=str(repo_root),
            stdout=stream,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace")
        raise WorktreeError(f"Failed to snapshot local tracked changes:\n{detail}")
    return patch_path.stat().st_size > 0


def _import_source_working_tree(
    repo_root: Path,
    worktree_root: Path,
    run_dir: Path,
) -> SourceSnapshot:
    patch_path = run_dir / "source-working-tree.patch"
    has_patch = _write_source_patch(repo_root, patch_path)
    if has_patch:
        completed = _git(
            ["apply", "--whitespace=nowarn", str(patch_path)],
            worktree_root,
            check=False,
        )
        if completed.returncode != 0:
            raise WorktreeError(
                "Failed to apply the current working-tree snapshot into the isolated "
                + f"worktree.\n{completed.stdout or ''}"
            )

    untracked_files = _untracked_source_files(repo_root)
    for relative_path in untracked_files:
        source = repo_root / relative_path
        destination = worktree_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            os.symlink(os.readlink(source), destination)
        elif source.is_file():
            _ = shutil.copy2(source, destination)

    snapshot: SourceSnapshot = {
        "trackedPatch": has_patch,
        "untrackedFiles": untracked_files,
    }
    metadata_path = run_dir / "source-untracked.json"
    with metadata_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(untracked_files, stream, ensure_ascii=False, indent=2)
    return snapshot


def build_worktree_tree(repo_root: Path, scratch_dir: Path, label: str) -> str:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    index_path = scratch_dir / f"{label}-{uuid.uuid4().hex[:8]}.index"
    environment = os.environ.copy()
    environment["GIT_INDEX_FILE"] = str(index_path.resolve())
    try:
        _ = run_process(
            ["git", "read-tree", "HEAD"], cwd=repo_root, env=environment, check=True
        )
        _ = run_process(
            ["git", "add", "-A", "--", "."],
            cwd=repo_root,
            env=environment,
            check=True,
        )
        completed = run_process(
            ["git", "ls-files", "--cached"],
            cwd=repo_root,
            env=environment,
            check=True,
        )
        internal_paths = [
            normalize_git_path(line.strip())
            for line in completed.stdout.splitlines()
            if line.strip() and _is_internal_runtime_path(line)
        ]
        for relative_path in internal_paths:
            _ = run_process(
                ["git", "update-index", "--force-remove", "--", relative_path],
                cwd=repo_root,
                env=environment,
                check=True,
            )

        tree = run_process(
            ["git", "write-tree"],
            cwd=repo_root,
            env=environment,
            check=True,
        ).stdout.strip()
        if not tree:
            raise WorktreeError("git write-tree returned an empty tree id")
        return tree
    finally:
        index_path.unlink(missing_ok=True)


def delete_runtime_baseline_ref(repo_root: Path, reference: str | None) -> bool:
    if reference is None:
        return True
    return _git(["update-ref", "-d", reference], repo_root, check=False).returncode == 0


def tree_changed_files(repo_root: Path, base_tree: str, current_tree: str) -> list[str]:
    output = _git(
        ["diff", "--name-only", base_tree, current_tree, "--"],
        repo_root,
    ).stdout
    return list(
        dict.fromkeys(
            relative_path
            for line in output.splitlines()
            if (relative_path := normalize_git_path(line.strip()))
        )
    )


def create_worktree(request: WorktreeRequest) -> WorktreeResult:
    source_head = _git(["rev-parse", "HEAD"], request.repo_root).stdout.strip()
    # External correlation wins: loop/<profile>/<execution-id> when the caller
    # supplied one, otherwise the legacy loop/<profile>/<run_id> shape.
    branch_suffix = request.execution_id or request.run_id
    branch = f"loop/{request.profile}/{branch_suffix}"
    runtime_root = request.run_dir.parent.parent
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", request.repo_root.name).strip("-")
    worktree_root = runtime_root / "worktrees" / (safe_name or "repo") / request.run_id
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    _ = _git(
        ["worktree", "add", "-b", branch, str(worktree_root), source_head],
        request.repo_root,
    )

    snapshot: SourceSnapshot = {"trackedPatch": False, "untrackedFiles": []}
    if request.snapshot_local_changes:
        snapshot = _import_source_working_tree(
            request.repo_root,
            worktree_root,
            request.run_dir,
        )

    baseline_tree = build_worktree_tree(
        worktree_root,
        request.run_dir / "indexes",
        "baseline",
    )
    baseline_ref = f"refs/loop-engineering/baselines/{request.run_id}"
    _ = _git(["update-ref", baseline_ref, baseline_tree], worktree_root)
    module_dir = (
        worktree_root / request.module_rel if request.module_rel else worktree_root
    )
    if not module_dir.exists():
        raise WorktreeError(f"Module path not found in worktree: {module_dir}")
    return WorktreeResult(
        root=worktree_root,
        module_dir=module_dir,
        branch=branch,
        source_head=source_head,
        baseline_tree=baseline_tree,
        baseline_ref=baseline_ref,
        source_snapshot=snapshot,
    )

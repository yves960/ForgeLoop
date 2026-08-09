from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Final, NamedTuple

from agent_backend import AgentBackend, AgentOverrides, resolve_agent_backend
from config_store import load_global_config
from process_runner import run_process
from worktree_manager import normalize_git_path

_UNSAFE_COMMAND_TARGET: Final = re.compile(r'[\x00-\x1f&|<>^%!()"]')
_JAVA_TEST_SELECTOR: Final = re.compile(
    r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*" + r"(?:#[A-Za-z_$][\w$]*)?"
)


class RepositoryContext(NamedTuple):
    root: Path
    module_dir: Path
    module_rel: str


class RunEnvironmentError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def _git(
    args: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return run_process(["git", *args], cwd=cwd, capture=True, check=False)


def require_command(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RunEnvironmentError(f"Required command not found on PATH: {name}")
    return executable


def find_repository(start: Path) -> RepositoryContext:
    completed = _git(["rev-parse", "--show-toplevel"], start)
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RunEnvironmentError(
            f"Current directory is not inside a Git worktree: {start}\n"
            + "Run loop from the target repository (or one of its subdirectories)."
        )
    repo_root = Path(completed.stdout.strip()).resolve()

    current = start.resolve()
    module_dir: Path | None = None
    while True:
        if (current / "pom.xml").exists():
            module_dir = current
            break
        if current == repo_root or current.parent == current:
            break
        current = current.parent
    if module_dir is None:
        module_dir = start.resolve()

    try:
        module_rel = normalize_git_path(str(module_dir.relative_to(repo_root)))
    except ValueError as error:
        raise RunEnvironmentError(
            f"Resolved module is outside Git root: {module_dir}"
        ) from error
    return RepositoryContext(
        repo_root,
        module_dir,
        "" if module_rel == "." else module_rel,
    )


def make_run_id() -> str:
    now = dt.datetime.now(dt.timezone.utc).astimezone()
    return now.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def resolve_agent(
    explicit_command: str | None,
    explicit_protocol: str | None,
    explicit_args: list[str] | None = None,
) -> AgentBackend:
    overrides = AgentOverrides(
        command=explicit_command,
        protocol=explicit_protocol,
        args=tuple(explicit_args) if explicit_args is not None else None,
    )
    return resolve_agent_backend(
        overrides,
        load_global_config().get("agent"),
        os.environ,
    )


def find_maven(
    module_dir: Path,
    repo_root: Path,
    explicit: str | None,
) -> str:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return str(path.resolve())
        executable = shutil.which(explicit)
        if executable:
            return executable
        raise RunEnvironmentError(f"Maven command not found: {explicit}")

    current = module_dir.resolve()
    repository = repo_root.resolve()
    while True:
        for name in ("mvnw.cmd", "mvnw"):
            path = current / name
            if path.exists():
                return str(path)
        if current == repository or current.parent == current:
            break
        current = current.parent

    executable = shutil.which("mvn.cmd") or shutil.which("mvn")
    if executable:
        return executable
    raise RunEnvironmentError(
        "Could not find mvnw.cmd/mvnw in repository and mvn is not on PATH."
    )


def find_ralph_ts() -> Path:
    override = os.environ.get("LOOP_RALPH_TS")
    if override:
        path = Path(override)
        if path.exists():
            return path.resolve()
        raise RunEnvironmentError(f"LOOP_RALPH_TS does not exist: {override}")

    npm = require_command("npm")
    completed = run_process([npm, "root", "-g"], capture=True, check=True)
    candidate = (
        Path(completed.stdout.strip()) / "@th0rgal" / "ralph-wiggum" / "ralph.ts"
    )
    if not candidate.exists():
        raise RunEnvironmentError(
            "Open Ralph Wiggum not found. Install @th0rgal/ralph-wiggum globally "
            + f"first.\nExpected: {candidate}"
        )
    return candidate.resolve()


def normalize_test_selector(value: str) -> str:
    raw = normalize_profile_target(value)

    if "#" in raw:
        class_part, method_part = raw.split("#", 1)
        suffix = f"#{method_part}" if method_part else ""
    else:
        class_part, suffix = raw, ""

    class_part = class_part.replace("\\", "/")
    marker = "src/test/java/"
    marker_index = class_part.lower().find(marker)
    if marker_index >= 0:
        class_part = class_part[marker_index + len(marker) :]
    if class_part.lower().endswith(".java"):
        class_part = class_part[:-5]
    class_part = class_part.strip("/")
    if "/" in class_part:
        class_part = class_part.replace("/", ".")
    if not class_part:
        raise RunEnvironmentError(f"Invalid --test value: {value}")
    selector = class_part + suffix
    if _JAVA_TEST_SELECTOR.fullmatch(selector) is None:
        raise RunEnvironmentError(f"Invalid --test value: {value}")
    return selector


def normalize_profile_target(value: str) -> str:
    target = value.strip().strip('"')
    if not target:
        raise RunEnvironmentError("--target cannot be empty")
    if _UNSAFE_COMMAND_TARGET.search(target) is not None:
        raise RunEnvironmentError("Target contains unsafe command characters")
    return target


def render_task(
    profiles_dir: Path,
    profile_name: str,
    test: str,
) -> str:
    template = profiles_dir / profile_name / "task-template.md"
    return (
        template.read_text(encoding="utf-8")
        .replace("{{TEST}}", test)
        .replace("{{TARGET}}", test)
    )

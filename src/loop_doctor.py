"""`loop doctor` — 一次性自检：解释器/VCS/构建工具/venv 工具/run-index 健康。

设计约束（蔚 10-15 工单）：单文件、零新依赖、✓/⚠/✗ 三态 + 修法建议。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runtime_store import list_run_index

OK = "✓"
WARN = "⚠"
FAIL = "✗"

DEV_REQUIREMENTS_HINT = ".venv/bin/pip install -r requirements-dev.txt"


@dataclass
class CheckResult:
    name: str
    state: str  # OK / WARN / FAIL
    detail: str = ""
    hint: str = ""


def _tool_version(argv: list[str]) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0] if lines else f"exit {result.returncode}"


def check_path_command(name: str, binary: str, *, optional: bool = False, hint: str = "") -> CheckResult:
    path = shutil.which(binary)
    if not path:
        return CheckResult(
            name,
            WARN if optional else FAIL,
            "not installed",
            hint or f"install {binary} and ensure it is on PATH",
        )
    version = _tool_version([binary, "--version"])
    return CheckResult(name, OK, f"{path} ({version})" if version else path)


def _check_venv_tool(repo_root: Path, tool: str) -> CheckResult:
    python = repo_root / ".venv" / "bin" / "python"
    if not python.exists():
        return CheckResult(tool, WARN, ".venv 未创建", "python3 -m venv .venv && " + DEV_REQUIREMENTS_HINT)
    probe = subprocess.run(
        [str(python), "-m", tool, "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        return CheckResult(tool, WARN, "venv 存在但未安装", DEV_REQUIREMENTS_HINT)
    lines = (probe.stdout or probe.stderr).strip().splitlines()
    return CheckResult(tool, OK, lines[0] if lines else ".venv 内可用")


def check_run_index_health() -> CheckResult:
    index = list_run_index()
    total = len(index)
    if total == 0:
        return CheckResult("run-index health", OK, "empty（还没有注册过 run）")
    alive = sum(1 for entry in index.values() if entry.status != "missing")
    percent = round(alive * 100 / total)
    state = OK if percent >= 80 else WARN
    hint = "loop gc --prune 清理死条目" if percent < 80 else ""
    return CheckResult("run-index health", state, f"{alive}/{total} real（{percent}%）", hint)


def run_doctor(repo_root: Path) -> list[CheckResult]:
    return [
        check_path_command("python3", "python3"),
        check_path_command("git", "git"),
        check_path_command("maven (mvn)", "mvn", optional=True, hint="brew install maven，或 loop run --maven 指定 mvnw 路径"),
        _check_venv_tool(repo_root, "pytest"),
        _check_venv_tool(repo_root, "pyright"),
        _check_venv_tool(repo_root, "ruff"),
        check_run_index_health(),
    ]


def fix_venv_tools(repo_root: Path) -> str:
    """--fix：给缺失的 venv 工具补装 dev 依赖（幂等）。"""
    python = repo_root / ".venv" / "bin" / "python"
    if not python.exists():
        return "skip: .venv 不存在，先 python3 -m venv .venv"
    subprocess.run(
        [str(python), "-m", "pip", "install", "-q", "-r", str(repo_root / "requirements-dev.txt")],
        check=False,
        timeout=600,
    )
    return "ran: .venv/bin/pip install -r requirements-dev.txt"


def render_doctor(results: list[CheckResult]) -> tuple[str, int]:
    lines = ["[loop] doctor:"]
    failures = 0
    for item in results:
        detail = f": {item.detail}" if item.detail else ""
        lines.append(f"  - {item.name}{detail} {item.state}")
        if item.state != OK and item.hint:
            lines.append(f"        fix: {item.hint}")
        if item.state == FAIL:
            failures += 1
    return "\n".join(lines), failures

"""`loop doctor` — 一次性自检：解释器/VCS/构建工具/venv 工具/run-index 健康。

设计约束（蔚 10-15 工单）：单文件、零新依赖、✓/⚠/✗ 三态 + 修法建议。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runtime_store import find_zombie_runs, list_run_index

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


def _check_venv_tool(repo_root: Path, tool: str, label: str | None = None) -> CheckResult:
    name = label or tool
    python = repo_root / ".venv" / "bin" / "python"
    if not python.exists():
        return CheckResult(name, WARN, ".venv 未创建", "python3 -m venv .venv && " + DEV_REQUIREMENTS_HINT)
    probe = subprocess.run(
        [str(python), "-m", tool, "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if probe.returncode != 0:
        return CheckResult(name, WARN, "venv 存在但未安装", DEV_REQUIREMENTS_HINT)
    lines = (probe.stdout or probe.stderr).strip().splitlines()
    return CheckResult(name, OK, lines[0] if lines else ".venv 内可用")


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


def check_java_runtime() -> CheckResult:
    """蔚 11-03 P1：此前不查 Java 运行时——本机 mvn 在而 JDK 缺位时
    绿灯是假阳性（mvn 直接报 Unable to locate a Java Runtime，5/5 profile 全 Maven 系）。"""
    java_home = os.environ.get("JAVA_HOME", "").strip()
    if java_home and (Path(java_home) / "bin" / "java").exists():
        return CheckResult("java runtime (JDK)", OK, f"JAVA_HOME → {java_home}")
    finder = "/usr/libexec/java_home"
    if Path(finder).exists():
        try:
            out = subprocess.run([finder], capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                return CheckResult("java runtime (JDK)", OK, f"/usr/libexec/java_home → {out.stdout.strip()}")
            # macOS 权威判据：finder 在而非零 = 无 JDK——不能落到 PATH（/usr/bin/java
            # 是系统 stub，存在但执行即报错，which 命中是假阳性，蔚 11-03 实测 mvn 即炸）
            return CheckResult(
                "java runtime (JDK)",
                WARN,
                "无 JDK（/usr/libexec/java_home 无可用 JVM）——mvn 将报 Unable to locate a Java Runtime，run 闭环在本机不可用",
                "brew install --cask temurin@17 或设 JAVA_HOME（owner 已知会）",
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    which = shutil.which("java")
    if which:
        return CheckResult("java runtime (JDK)", OK, which)
    return CheckResult(
        "java runtime (JDK)",
        WARN,
        "未找到 JDK（JAVA_HOME / /usr/libexec/java_home / PATH 均无）——mvn 将报 Unable to locate a Java Runtime，run 闭环在本机不可用",
        "brew install --cask temurin@17 或设 JAVA_HOME（owner 已知会）",
    )


def check_maven_runtime() -> CheckResult:
    """蔚 11-03 P1：PATH 之外纳入历史 run.json 里配置过的 mvn 路径（假阴性修正
    ——本机 mvn 常年活在 ~/.local/opt 下不在 PATH，其实配过却判未就绪）。"""
    found = shutil.which("mvn")
    if found:
        return CheckResult("maven (mvn)", OK, found)
    seen: set[str] = set()
    for entry in list_run_index().values():
        try:
            document = json.loads((Path(entry.path) / "run.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        maven = document.get("maven")
        if isinstance(maven, str) and maven and maven not in seen:
            seen.add(maven)
            if Path(maven).exists():
                return CheckResult("maven (mvn)", OK, f"历史 run.json → {maven}（不在 PATH，但可用）")
    return CheckResult(
        "maven (mvn)",
        WARN,
        "PATH 与历史 run.json 均无可用 mvn",
        "brew install maven，或 loop run --maven 指定路径",
    )


def check_zombie_runs() -> CheckResult:
    """蔚 11-03 工单#1：RUNNING 超 7 天的僵尸计数——孤儿 run 永无出口的反面镜子。"""
    zombies = find_zombie_runs()
    if not zombies:
        return CheckResult("zombie runs", OK, "0（RUNNING 超 7 天）")
    preview = ", ".join(run_id for run_id, _, _ in zombies[:3])
    return CheckResult(
        "zombie runs",
        WARN,
        f"{len(zombies)} 条 RUNNING 超 7 天（{preview}{'…' if len(zombies) > 3 else ''}）",
        "loop gc --prune 转 failed:abandoned（保留历史与现场）",
    )


def run_doctor(repo_root: Path) -> list[CheckResult]:
    return [
        check_path_command("python3", "python3"),
        check_path_command("git", "git"),
        check_maven_runtime(),
        check_java_runtime(),
        _check_venv_tool(repo_root, "pytest", label=".venv pytest"),
        _check_venv_tool(repo_root, "pyright", label=".venv pyright"),
        _check_venv_tool(repo_root, "ruff", label=".venv ruff"),
        check_run_index_health(),
        check_zombie_runs(),
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

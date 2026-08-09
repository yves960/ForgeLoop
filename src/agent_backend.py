from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal, NamedTuple, TypedDict

from config_store import AgentConfig
from process_runner import run_process

AgentProtocol = Literal["claude-code", "opencode"]

AGENT_PROTOCOLS: Final[tuple[AgentProtocol, ...]] = ("claude-code", "opencode")
_PROTOCOLS_BY_NAME: Final[dict[str, AgentProtocol]] = {
    "claude-code": "claude-code",
    "opencode": "opencode",
}
_CANDIDATES: Final[dict[AgentProtocol, tuple[str, ...]]] = {
    "claude-code": ("claude.cmd", "claude.exe", "claude"),
    "opencode": ("opencode.cmd", "opencode.exe", "opencode"),
}


class AgentBackend(TypedDict):
    command: str
    protocol: AgentProtocol
    args: list[str]
    source: Literal["configured", "auto-detected"]


class AgentOverrides(NamedTuple):
    command: str | None
    protocol: str | None
    args: tuple[str, ...] | None


class SavedAgent(NamedTuple):
    command: str | None
    protocol: str | None
    args: tuple[str, ...]


def _saved_agent(config: AgentConfig | None) -> SavedAgent:
    if config is None:
        return SavedAgent(None, None, ())
    return SavedAgent(
        command=config.get("command"),
        protocol=config.get("protocol"),
        args=tuple(config.get("args", ())),
    )


def _protocol(value: str | None) -> AgentProtocol | None:
    if value is None:
        return None
    return _PROTOCOLS_BY_NAME.get(value)


def _infer_protocol(command: str) -> AgentProtocol:
    if Path(command).name.lower().startswith("opencode"):
        return "opencode"
    return "claude-code"


def resolve_executable(value: str) -> str | None:
    raw = value.strip().strip('"')
    path = Path(raw)

    if os.name == "nt":
        suffix = path.suffix.lower()
        if suffix in (".cmd", ".bat", ".exe") and path.exists():
            return str(path.resolve())
        if ("\\" in raw or "/" in raw) and not suffix:
            for extension in (".cmd", ".bat", ".exe"):
                candidate = Path(raw + extension)
                if candidate.exists():
                    return str(candidate.resolve())
        if (
            "\\" not in raw
            and "/" not in raw
            and suffix
            not in (
                ".cmd",
                ".bat",
                ".exe",
            )
        ):
            for extension in (".cmd", ".bat", ".exe"):
                resolved = shutil.which(raw + extension)
                if resolved:
                    return str(Path(resolved).resolve())

    if path.exists():
        return str(path.resolve())
    resolved = shutil.which(raw)
    return str(Path(resolved).resolve()) if resolved else None


def resolve_agent_backend(
    overrides: AgentOverrides,
    config: AgentConfig | None,
    environment: Mapping[str, str],
) -> AgentBackend:
    saved = _saved_agent(config)
    command = (
        overrides.command or environment.get("LOOP_AGENT_COMMAND") or saved.command
    )
    requested_name = (
        overrides.protocol or environment.get("LOOP_AGENT_PROTOCOL") or saved.protocol
    )
    requested_protocol = _protocol(requested_name)
    if requested_name and requested_protocol is None:
        raise RuntimeError(
            f"Unsupported agent protocol: {requested_name}. "
            + f"Currently supported: {', '.join(AGENT_PROTOCOLS)}."
        )

    if overrides.args is not None:
        fixed_args = list(overrides.args)
    elif environment.get("LOOP_AGENT_ARGS"):
        fixed_args = shlex.split(environment["LOOP_AGENT_ARGS"], posix=False)
    else:
        fixed_args = list(saved.args)

    if command:
        resolved = resolve_executable(command)
        if not resolved:
            raise RuntimeError(
                f"Configured agent command not found: {command}\n"
                + "Reconfigure once with: loop config agent <command-or-path>"
            )
        return {
            "command": resolved,
            "protocol": requested_protocol or _infer_protocol(resolved),
            "args": fixed_args,
            "source": "configured",
        }

    protocols = (requested_protocol,) if requested_protocol else AGENT_PROTOCOLS
    for protocol in protocols:
        for candidate in _CANDIDATES[protocol]:
            resolved = resolve_executable(candidate)
            if resolved:
                return {
                    "command": resolved,
                    "protocol": protocol,
                    "args": fixed_args,
                    "source": "auto-detected",
                }

    raise RuntimeError(
        "No coding-agent backend is configured. Configure it once, for example:\n"
        + "  loop config agent opencode --protocol opencode\n"
        + "  loop config agent D:\\path\\to\\your-company-agent.bat --protocol claude-code\n\n"
        + "Or set LOOP_AGENT_COMMAND / pass --agent-command for this run."
    )


def call_agent(
    agent: AgentBackend,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    prompt = "READ_FILE=.loop/task.md"
    commands: dict[AgentProtocol, list[str]] = {
        "claude-code": [agent["command"], *agent["args"], "-p", prompt],
        "opencode": [agent["command"], "run", *agent["args"], prompt],
    }
    return run_process(
        commands[agent["protocol"]],
        cwd=cwd,
        capture=True,
        check=False,
        non_interactive=True,
    )

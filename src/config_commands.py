from __future__ import annotations

import json
from pathlib import Path

from agent_backend import resolve_executable
from config_store import (
    AgentConfig,
    DeliveryConfig,
    global_config_path,
    load_global_config,
    save_global_config,
)
from runtime_store import run_index_path


class ConfigCommandError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def configure_commit_template(value: str) -> int:
    path = Path(value).resolve()
    if not path.exists() or not path.is_file():
        raise ConfigCommandError(f"Commit template not found: {path}")
    config = load_global_config()
    delivery = DeliveryConfig(config.get("delivery", {}))
    delivery["commitTemplate"] = str(path)
    config["delivery"] = delivery
    save_global_config(config)
    print(f"[loop] commit template configured: {path}")
    return 0


def configure_review_command(command: str) -> int:
    config = load_global_config()
    delivery = DeliveryConfig(config.get("delivery", {}))
    delivery["reviewCommand"] = command
    config["delivery"] = delivery
    save_global_config(config)
    print(f"[loop] review command configured: {command}")
    return 0


def clear_delivery() -> int:
    config = load_global_config()
    _ = config.pop("delivery", None)
    save_global_config(config)
    print(f"[loop] delivery configuration cleared: {global_config_path()}")
    return 0


def configure_agent(command: str, protocol: str | None) -> int:
    resolved = resolve_executable(command)
    if not resolved:
        raise ConfigCommandError(f"Agent command not found: {command}")
    selected_protocol = protocol or (
        "opencode"
        if Path(resolved).name.lower().startswith("opencode")
        else "claude-code"
    )
    config = load_global_config()
    previous = config.get("agent")
    config["agent"] = AgentConfig(
        command=resolved,
        protocol=selected_protocol,
        args=list(previous.get("args", ())) if previous is not None else [],
    )
    save_global_config(config)
    print(f"[loop] agent configured: {resolved}")
    print(f"[loop] protocol:         {selected_protocol}")
    print(f"[loop] config:           {global_config_path()}")
    return 0


def add_agent_argument(value: str) -> int:
    config = load_global_config()
    agent = config.get("agent")
    if agent is None or not agent.get("command"):
        raise ConfigCommandError(
            "Configure the coding-agent command first: "
            + "loop config agent <command-or-path>"
        )
    current = list(agent.get("args", ()))
    if value not in current:
        current.append(value)
    agent["args"] = current
    config["agent"] = agent
    save_global_config(config)
    print(f"[loop] agent fixed arg added: {value}")
    print(f"[loop] agent args: {' '.join(current) if current else '(none)'}")
    return 0


def clear_agent_arguments() -> int:
    config = load_global_config()
    agent = config.get("agent")
    if agent is not None:
        agent["args"] = []
        config["agent"] = agent
        save_global_config(config)
    print(f"[loop] agent fixed args cleared: {global_config_path()}")
    return 0


def configure_runtime_root(value: str) -> int:
    root = Path(value).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    config = load_global_config()
    config["runtimeRoot"] = str(root)
    save_global_config(config)
    print(f"[loop] runtime root configured: {root}")
    print("[loop] future runs/worktrees/evidence will use this location")
    return 0


def clear_runtime_root() -> int:
    config = load_global_config()
    _ = config.pop("runtimeRoot", None)
    save_global_config(config)
    print(
        "[loop] runtime-root override cleared; future runs will follow the "
        + "repository drive"
    )
    return 0


def show_config() -> int:
    config = load_global_config()
    print(json.dumps(config, ensure_ascii=False, indent=2) if config else "{}")
    print(f"\nConfig file: {global_config_path()}")
    print(f"Run index:   {run_index_path()}")
    return 0


def clear_agent() -> int:
    config = load_global_config()
    _ = config.pop("agent", None)
    save_global_config(config)
    print(f"[loop] agent configuration cleared: {global_config_path()}")
    return 0

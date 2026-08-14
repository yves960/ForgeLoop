from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Final, TypedDict

from runtime_store import user_config_root
from structured_json import (
    JsonStructureError,
    json_node_object,
    json_node_string,
    json_node_string_list,
    json_object_document,
)

DEFAULT_REVIEW_COMMAND: Final = "git review"


class AgentConfig(TypedDict, total=False):
    command: str
    protocol: str
    args: list[str]


class DeliveryConfig(TypedDict, total=False):
    commitTemplate: str
    reviewCommand: str


class HooksConfig(TypedDict, total=False):
    onComplete: str


class LoopConfig(TypedDict, total=False):
    agent: AgentConfig
    delivery: DeliveryConfig
    hooks: HooksConfig
    runtimeRoot: str


class ConfigReadError(RuntimeError):
    path: Path
    detail: str

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid Loop Engineering config: {path}: {detail}")


def global_config_path() -> Path:
    return user_config_root() / "config.json"


def _agent_config(node: ast.expr | None) -> AgentConfig | None:
    if node is None:
        return None
    values = json_node_object(node)
    command = json_node_string(values.get("command"))
    if command is None:
        return None
    config = AgentConfig(
        command=command, args=json_node_string_list(values.get("args"))
    )
    protocol = json_node_string(values.get("protocol"))
    if protocol is not None:
        config["protocol"] = protocol
    return config


def _delivery_config(node: ast.expr | None) -> DeliveryConfig | None:
    if node is None:
        return None
    values = json_node_object(node)
    config = DeliveryConfig()
    commit_template = json_node_string(values.get("commitTemplate"))
    review_command = json_node_string(values.get("reviewCommand"))
    if commit_template is not None:
        config["commitTemplate"] = commit_template
    if review_command is not None:
        config["reviewCommand"] = review_command
    return config if config else None


def _hooks_config(node: ast.expr | None) -> HooksConfig | None:
    if node is None:
        return None
    values = json_node_object(node)
    on_complete = json_node_string(values.get("onComplete"))
    if on_complete is None:
        return None
    return HooksConfig(onComplete=on_complete)


def _parse_config(content: str, path: Path) -> LoopConfig:
    try:
        values = json_object_document(content, path)
    except JsonStructureError as error:
        raise ConfigReadError(path, error.detail) from error

    config = LoopConfig()
    agent = _agent_config(values.get("agent"))
    delivery = _delivery_config(values.get("delivery"))
    hooks = _hooks_config(values.get("hooks"))
    runtime_root = json_node_string(values.get("runtimeRoot"))
    if agent is not None:
        config["agent"] = agent
    if delivery is not None:
        config["delivery"] = delivery
    if hooks is not None:
        config["hooks"] = hooks
    if runtime_root is not None:
        config["runtimeRoot"] = runtime_root
    return config


def load_global_config() -> LoopConfig:
    path = global_config_path()
    if not path.exists():
        return LoopConfig()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConfigReadError(path, str(error)) from error
    return _parse_config(content, path)


def save_global_config(config: LoopConfig) -> None:
    path = global_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(json.dumps(config, ensure_ascii=False, indent=2))


def delivery_config() -> DeliveryConfig:
    configured = load_global_config().get("delivery")
    delivery = DeliveryConfig(reviewCommand=DEFAULT_REVIEW_COMMAND)
    if configured is not None:
        delivery.update(configured)
    return delivery


def on_complete_webhook() -> str | None:
    hooks = load_global_config().get("hooks")
    if hooks is None:
        return None
    url = hooks.get("onComplete")
    return url or None

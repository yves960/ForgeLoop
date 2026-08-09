from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal, TypedDict

from agent_backend import AgentBackend, AgentProtocol
from profile_store import EngineeringProfile, parse_engineering_profile
from structured_json import (
    JsonStructureError,
    json_node_boolean,
    json_node_integer,
    json_node_is_null,
    json_node_object,
    json_node_string,
    json_node_string_list,
    json_object_document,
)
from worktree_manager import SourceSnapshot

AgentSource = Literal["configured", "auto-detected"]
_AGENT_PROTOCOLS: Final[dict[str, AgentProtocol]] = {
    "claude-code": "claude-code",
    "opencode": "opencode",
}
_AGENT_SOURCES: Final[dict[str, AgentSource]] = {
    "configured": "configured",
    "auto-detected": "auto-detected",
}


class RequiredRunConfig(TypedDict):
    runId: str
    profileName: str
    profile: EngineeringProfile
    test: str
    repoRoot: str
    worktreeRoot: str
    moduleDir: str
    moduleRel: str
    branch: str
    sourceHead: str
    baseTree: str
    baselineRef: str | None
    sourceSnapshot: SourceSnapshot
    maven: str
    agent: AgentBackend
    maxIterations: int
    runDir: str


class RunConfig(RequiredRunConfig, total=False):
    baseCommit: str


class RunConfigReadError(RuntimeError):
    path: Path
    detail: str

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid run config: {path}: {detail}")


def parse_agent_backend(node: ast.expr | None) -> AgentBackend | None:
    if node is None:
        return None
    values = json_node_object(node)
    command = json_node_string(values.get("command"))
    protocol = _AGENT_PROTOCOLS.get(json_node_string(values.get("protocol")) or "")
    source = _AGENT_SOURCES.get(json_node_string(values.get("source")) or "")
    if command is None or protocol is None or source is None:
        return None
    return AgentBackend(
        command=command,
        protocol=protocol,
        args=json_node_string_list(values.get("args")),
        source=source,
    )


def parse_source_snapshot(node: ast.expr | None) -> SourceSnapshot | None:
    if node is None:
        return None
    values = json_node_object(node)
    tracked_patch = json_node_boolean(values.get("trackedPatch"))
    if tracked_patch is None:
        return None
    return SourceSnapshot(
        trackedPatch=tracked_patch,
        untrackedFiles=json_node_string_list(values.get("untrackedFiles")),
    )


def _required_string(
    values: Mapping[str, ast.expr],
    key: str,
    path: Path,
) -> str:
    value = json_node_string(values.get(key))
    if value is None:
        raise RunConfigReadError(path, f"missing string field: {key}")
    return value


def _required_integer(
    values: Mapping[str, ast.expr],
    key: str,
    path: Path,
) -> int:
    value = json_node_integer(values.get(key))
    if value is None:
        raise RunConfigReadError(path, f"missing integer field: {key}")
    return value


def _parse_run_config(
    values: Mapping[str, ast.expr],
    path: Path,
) -> RunConfig:
    profile_node = values.get("profile")
    agent = parse_agent_backend(values.get("agent"))
    snapshot = parse_source_snapshot(values.get("sourceSnapshot"))
    if profile_node is None:
        raise RunConfigReadError(path, "missing object field: profile")
    if agent is None:
        raise RunConfigReadError(path, "missing or invalid object field: agent")
    if snapshot is None:
        raise RunConfigReadError(
            path, "missing or invalid object field: sourceSnapshot"
        )

    base_tree = json_node_string(values.get("baseTree"))
    if base_tree is None:
        base_tree = _required_string(values, "baseCommit", path)
    baseline_node = values.get("baselineRef")
    baseline_ref = json_node_string(baseline_node)
    if baseline_ref is None and not json_node_is_null(baseline_node):
        raise RunConfigReadError(path, "missing string/null field: baselineRef")

    return RunConfig(
        runId=_required_string(values, "runId", path),
        profileName=_required_string(values, "profileName", path),
        profile=parse_engineering_profile(profile_node, path),
        test=_required_string(values, "test", path),
        repoRoot=_required_string(values, "repoRoot", path),
        worktreeRoot=_required_string(values, "worktreeRoot", path),
        moduleDir=_required_string(values, "moduleDir", path),
        moduleRel=_required_string(values, "moduleRel", path),
        branch=_required_string(values, "branch", path),
        sourceHead=_required_string(values, "sourceHead", path),
        baseTree=base_tree,
        baselineRef=baseline_ref,
        sourceSnapshot=snapshot,
        maven=_required_string(values, "maven", path),
        agent=agent,
        maxIterations=_required_integer(values, "maxIterations", path),
        runDir=_required_string(values, "runDir", path),
    )


def load_run_config(path: Path) -> RunConfig:
    try:
        values = json_object_document(path.read_text(encoding="utf-8"), path)
        return _parse_run_config(values, path)
    except (OSError, UnicodeError, JsonStructureError) as error:
        detail = error.detail if isinstance(error, JsonStructureError) else str(error)
        raise RunConfigReadError(path, detail) from error


def write_run_config(path: Path, config: RunConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(json.dumps(config, ensure_ascii=False, indent=2))

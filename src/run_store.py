from __future__ import annotations

import ast
import json
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from agent_backend import AgentBackend
from config_store import load_global_config
from run_config_store import parse_agent_backend, parse_source_snapshot
from runtime_store import locate_run
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


class LoopResult(TypedDict, total=False):
    status: str
    reason: str
    test: str
    exitCode: int
    agentCommand: str
    violations: list[str]
    findings: list[str]


class SubmissionRecord(TypedDict, total=False):
    status: str
    reason: str
    verifiedAt: str
    failedAt: str
    commit: str
    committedAt: str
    deliveryChanges: list[str]
    baselineChanges: list[str]
    loopChanges: list[str]
    reviewStatus: str
    reviewCommand: str
    reviewExitCode: int
    reviewedAt: str
    cleanupStatus: str
    cleanupError: str
    worktreeRemoved: bool


class RunIdentity(TypedDict):
    runId: str
    profileName: str
    status: str
    test: str
    repoRoot: str
    worktreeRoot: str
    moduleRel: str
    branch: str
    runDir: str


class RunRecord(RunIdentity, total=False):
    reason: str | None
    moduleDir: str
    sourceHead: str
    baseTree: str
    baseCommit: str
    baselineRef: str | None
    sourceSnapshot: SourceSnapshot
    maven: str
    agent: AgentBackend
    maxIterations: int
    startedAt: str
    endedAt: str
    ralphExitCode: int
    finalTree: str
    changedFiles: list[str]
    cleanedAt: str
    submission: SubmissionRecord


class RunRecordReadError(RuntimeError):
    path: Path
    detail: str

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Invalid run metadata: {path}: {detail}")


def _submission(node: ast.expr | None) -> SubmissionRecord | None:
    if node is None:
        return None
    values = json_node_object(node)
    record = SubmissionRecord()
    for key in (
        "status",
        "reason",
        "verifiedAt",
        "failedAt",
        "commit",
        "committedAt",
        "reviewStatus",
        "reviewCommand",
        "reviewedAt",
        "cleanupStatus",
        "cleanupError",
    ):
        value = json_node_string(values.get(key))
        if value is not None:
            record[key] = value
    for key in ("deliveryChanges", "baselineChanges", "loopChanges"):
        if key in values:
            record[key] = json_node_string_list(values.get(key))
    review_exit_code = json_node_integer(values.get("reviewExitCode"))
    worktree_removed = json_node_boolean(values.get("worktreeRemoved"))
    if review_exit_code is not None:
        record["reviewExitCode"] = review_exit_code
    if worktree_removed is not None:
        record["worktreeRemoved"] = worktree_removed
    return record


def _required_string(
    nodes: Mapping[str, ast.expr],
    key: str,
    path: Path,
) -> str:
    value = json_node_string(nodes.get(key))
    if value is None:
        raise RunRecordReadError(path, f"missing string field: {key}")
    return value


def _run_record(nodes: Mapping[str, ast.expr], path: Path) -> RunRecord:
    record = RunRecord(
        runId=_required_string(nodes, "runId", path),
        profileName=_required_string(nodes, "profileName", path),
        status=_required_string(nodes, "status", path),
        test=_required_string(nodes, "test", path),
        repoRoot=_required_string(nodes, "repoRoot", path),
        worktreeRoot=_required_string(nodes, "worktreeRoot", path),
        moduleRel=_required_string(nodes, "moduleRel", path),
        branch=_required_string(nodes, "branch", path),
        runDir=_required_string(nodes, "runDir", path),
    )
    for key in (
        "moduleDir",
        "sourceHead",
        "baseTree",
        "baseCommit",
        "maven",
        "startedAt",
        "endedAt",
        "finalTree",
        "cleanedAt",
    ):
        value = json_node_string(nodes.get(key))
        if value is not None:
            record[key] = value
    reason_node = nodes.get("reason")
    reason = json_node_string(reason_node)
    if reason is not None or json_node_is_null(reason_node):
        record["reason"] = reason
    baseline_ref_node = nodes.get("baselineRef")
    baseline_ref = json_node_string(baseline_ref_node)
    if baseline_ref is not None or json_node_is_null(baseline_ref_node):
        record["baselineRef"] = baseline_ref
    for key in ("maxIterations", "ralphExitCode"):
        value = json_node_integer(nodes.get(key))
        if value is not None:
            record[key] = value
    if "changedFiles" in nodes:
        record["changedFiles"] = json_node_string_list(nodes.get("changedFiles"))
    snapshot = parse_source_snapshot(nodes.get("sourceSnapshot"))
    agent = parse_agent_backend(nodes.get("agent"))
    submission = _submission(nodes.get("submission"))
    if snapshot is not None:
        record["sourceSnapshot"] = snapshot
    if agent is not None:
        record["agent"] = agent
    if submission is not None:
        record["submission"] = submission
    return record


def read_loop_result(module_dir: Path, run_dir: Path | None = None) -> LoopResult:
    external = run_dir / "latest-result.json" if run_dir is not None else None
    path = (
        external
        if external is not None and external.exists()
        else module_dir / ".loop" / "result.json"
    )
    if not path.exists():
        return LoopResult(status="UNKNOWN", reason="RESULT_NOT_FOUND")
    try:
        values = json_object_document(path.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeError, JsonStructureError):
        return LoopResult(status="UNKNOWN", reason="RESULT_INVALID")
    result = LoopResult()
    for key in ("status", "reason", "test", "agentCommand"):
        value = json_node_string(values.get(key))
        if value is not None:
            result[key] = value
    exit_code = json_node_integer(values.get("exitCode"))
    if exit_code is not None:
        result["exitCode"] = exit_code
    for key in ("violations", "findings"):
        if key in values:
            result[key] = json_node_string_list(values.get(key))
    return result


def write_run_record(run_dir: Path, record: RunRecord) -> None:
    path = run_dir / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(json.dumps(record, ensure_ascii=False, indent=2))


def load_run_record(run_id: str) -> tuple[Path, RunRecord]:
    configured_root = load_global_config().get("runtimeRoot")
    run_dir = locate_run(run_id, configured_root)
    return read_run_record(run_dir)


def read_run_record(run_dir: Path) -> RunRecord:
    path = run_dir / "run.json"
    try:
        values = json_object_document(path.read_text(encoding="utf-8"), path)
    except (OSError, UnicodeError, JsonStructureError) as error:
        raise RunRecordReadError(path, str(error)) from error
    return _run_record(values, path)

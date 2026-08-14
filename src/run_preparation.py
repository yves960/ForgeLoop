from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import NamedTuple

from agent_backend import AgentBackend
from config_store import load_global_config
from profile_store import (
    EngineeringProfile,
    load_engineering_profile,
    resolve_max_iterations,
)
from run_config_store import RunConfig
from run_environment import (
    RepositoryContext,
    find_maven,
    find_ralph_ts,
    find_repository,
    make_run_id,
    normalize_profile_target,
    normalize_test_selector,
    require_command,
    resolve_agent,
)
from run_store import RunRecord
from runtime_store import register_run, runtime_data_root
from worktree_manager import (
    WorktreeRequest,
    WorktreeResult,
    create_worktree,
    source_status,
)


class RunOptions(NamedTuple):
    profile: str
    test: str
    max_iterations: int | None
    agent_command: str | None
    agent_protocol: str | None
    agent_args: list[str] | None
    maven: str | None
    require_clean: bool
    start: Path
    profiles_dir: Path
    entrypoint: Path
    python_executable: str


class PreparedRun(NamedTuple):
    options: RunOptions
    test: str
    profile: EngineeringProfile
    repository: RepositoryContext
    local_status: str
    run_id: str
    runtime_root: Path
    run_dir: Path
    ralph_ts: Path
    bun: str
    agent: AgentBackend


class RunPreparationError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def run_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _log(message: str) -> None:
    print(message, flush=True)


def prepare_run(options: RunOptions) -> PreparedRun:
    profile = load_engineering_profile(options.profiles_dir, options.profile)
    verifier = profile.get("verifier", {})
    test = (
        normalize_test_selector(options.test)
        if verifier.get("type", "java-ut") == "java-ut"
        else normalize_profile_target(options.test)
    )
    _log(f"[loop] starting from: {options.start}")
    _log(
        f"[loop] test:     {options.test} -> {test}"
        if test != options.test
        else f"[loop] test:     {test}"
    )

    _log("[loop] checking profile and runtime dependencies...")
    _ = require_command("git")
    bun = require_command("bun")
    _ = require_command("npm")
    _log("[loop] locating Open Ralph...")
    ralph_ts = find_ralph_ts()
    _log(f"[loop] ralph:    {ralph_ts}")

    _log("[loop] resolving coding-agent backend...")
    agent = resolve_agent(
        options.agent_command,
        options.agent_protocol,
        options.agent_args,
    )
    _log(f"[loop] agent:    {agent['command']} ({agent['protocol']})")
    if agent["args"]:
        _log(f"[loop] agent args: {' '.join(agent['args'])}")

    _log("[loop] locating Git repository and Maven module...")
    repository = find_repository(options.start)
    local_status = source_status(repository.root)
    if options.require_clean and local_status:
        raise RunPreparationError(
            "Base checkout is not clean and --require-clean was requested.\n\n"
            + local_status
        )

    run_id = make_run_id()
    runtime_root = runtime_data_root(
        repository.root,
        load_global_config().get("runtimeRoot"),
    )
    run_dir = runtime_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    register_run(run_id, run_dir)
    return PreparedRun(
        options,
        test,
        profile,
        repository,
        local_status,
        run_id,
        runtime_root,
        run_dir,
        ralph_ts,
        bun,
        agent,
    )


def create_isolated_worktree(prepared: PreparedRun) -> WorktreeResult:
    print(f"[loop] run:      {prepared.run_id}")
    print(f"[loop] profile:  {prepared.options.profile}")
    print(f"[loop] repo:     {prepared.repository.root}")
    print(f"[loop] data:     {prepared.runtime_root}")
    print(f"[loop] module:   {prepared.repository.module_rel or '.'}")
    if prepared.local_status:
        print(
            "[loop] local changes detected; snapshotting them into the isolated baseline"
        )
        print("[loop] source checkout will not be modified")
    print("[loop] creating isolated worktree...")
    return create_worktree(
        WorktreeRequest(
            repo_root=prepared.repository.root,
            module_rel=prepared.repository.module_rel,
            profile=prepared.options.profile,
            run_id=prepared.run_id,
            run_dir=prepared.run_dir,
        )
    )


def build_run_config(
    prepared: PreparedRun,
    worktree: WorktreeResult,
) -> RunConfig:
    maximum = prepared.options.max_iterations or resolve_max_iterations(
        prepared.profile
    )
    return RunConfig(
        runId=prepared.run_id,
        profileName=prepared.options.profile,
        profile=prepared.profile,
        test=prepared.test,
        repoRoot=str(prepared.repository.root),
        worktreeRoot=str(worktree.root),
        moduleDir=str(worktree.module_dir),
        moduleRel=prepared.repository.module_rel,
        branch=worktree.branch,
        sourceHead=worktree.source_head,
        baseTree=worktree.baseline_tree,
        baselineRef=worktree.baseline_ref,
        sourceSnapshot=worktree.source_snapshot,
        maven=find_maven(
            worktree.module_dir,
            worktree.root,
            prepared.options.maven,
        ),
        agent=prepared.agent,
        maxIterations=maximum,
        runDir=str(prepared.run_dir),
    )


def initial_run_record(config: RunConfig) -> RunRecord:
    return RunRecord(
        runId=config["runId"],
        profileName=config["profileName"],
        test=config["test"],
        repoRoot=config["repoRoot"],
        worktreeRoot=config["worktreeRoot"],
        moduleDir=config["moduleDir"],
        moduleRel=config["moduleRel"],
        branch=config["branch"],
        sourceHead=config["sourceHead"],
        baseTree=config["baseTree"],
        baselineRef=config["baselineRef"],
        sourceSnapshot=config["sourceSnapshot"],
        maven=config["maven"],
        agent=config["agent"],
        maxIterations=config["maxIterations"],
        runDir=config["runDir"],
        startedAt=run_timestamp(),
        status="RUNNING",
    )

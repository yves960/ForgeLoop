from __future__ import annotations

import ast
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from runtime_safety import UnsafeRuntimePathError, validate_runtime_directory

APP_NAME = "loop-engineering"
_RUNTIME_DIRECTORY_NAMES = (".loop", ".ralph")


class RunNotFoundError(LookupError):
    pass


def user_config_root() -> Path:
    local_root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local_root:
        return Path(local_root) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def runtime_data_root(repo_root: Path, configured_root: str | None) -> Path:
    environment_root = os.environ.get("LOOP_ENGINEERING_HOME")
    selected_root = environment_root or configured_root
    if selected_root:
        return Path(selected_root).expanduser().resolve()
    return (repo_root.parent / ".loop-engineering").resolve()


def run_index_path() -> Path:
    return user_config_root() / "run-index.json"


def _load_run_index() -> dict[str, str]:
    path = run_index_path()
    if not path.exists():
        return {}
    try:
        expression = ast.parse(path.read_text(encoding="utf-8"), mode="eval")
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return {}
    if not isinstance(expression.body, ast.Dict):
        return {}
    index: dict[str, str] = {}
    for key_node, value_node in zip(
        expression.body.keys,
        expression.body.values,
    ):
        if isinstance(key_node, ast.Constant) and isinstance(value_node, ast.Constant):
            key = key_node.value
            value = value_node.value
            if isinstance(key, str) and isinstance(value, str):
                index[key] = value
    return index


def _save_run_index(index: Mapping[str, str]) -> None:
    path = run_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(dict(index), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_run(run_id: str, run_dir: Path) -> None:
    index = _load_run_index()
    index[run_id] = str(run_dir.resolve())
    _save_run_index(index)


def locate_run(run_id: str, configured_root: str | None) -> Path:
    candidates: list[Path] = []
    indexed = _load_run_index().get(run_id)
    if indexed:
        candidates.append(Path(indexed))
    if configured_root:
        candidates.append(Path(configured_root) / "runs" / run_id)
    candidates.append(user_config_root() / "runs" / run_id)

    for run_dir in candidates:
        if (run_dir / "run.json").exists():
            return run_dir
    raise RunNotFoundError(f"Run not found: {run_id}")


def archive_runtime(
    module_dir: Path,
    run_dir: Path,
    namespace: str | None = None,
) -> None:
    evidence_dir = run_dir / "evidence"
    if namespace:
        evidence_dir = evidence_dir / namespace
    evidence_dir.mkdir(parents=True, exist_ok=True)

    for name in _RUNTIME_DIRECTORY_NAMES:
        source = module_dir / name
        if not source.exists():
            continue
        try:
            source = validate_runtime_directory(module_dir, name)
        except UnsafeRuntimePathError:
            continue
        destination = evidence_dir / name.lstrip(".")
        if destination.exists():
            shutil.rmtree(destination)
        _ = shutil.copytree(source, destination, symlinks=True)
        shutil.rmtree(source)

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from runtime_safety import UnsafeRuntimePathError, validate_runtime_directory

APP_NAME = "loop-engineering"
_RUNTIME_DIRECTORY_NAMES = (".loop", ".ralph")


class RunNotFoundError(LookupError):
    pass


@dataclass
class RunIndexEntry:
    path: str
    status: str  # running / verified / submitted / failed / cleaned / missing
    created_at: str  # ISO 8601
    last_seen: str  # ISO 8601


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _path_timestamp(path: Path) -> str:
    try:
        stamp = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
    except OSError:
        stamp = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return stamp.isoformat(timespec="seconds")


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


def _run_index_entry_from_mapping(values: Mapping[str, object]) -> RunIndexEntry | None:
    path = values.get("path")
    if not isinstance(path, str):
        return None
    fallback = _path_timestamp(Path(path) / "run.json")
    status = values.get("status")
    created_at = values.get("created_at")
    last_seen = values.get("last_seen")
    return RunIndexEntry(
        path=path,
        status=status if isinstance(status, str) else "unknown",
        created_at=created_at if isinstance(created_at, str) else fallback,
        last_seen=(last_seen if isinstance(last_seen, str) else (created_at if isinstance(created_at, str) else fallback)),
    )


def _load_run_index() -> dict[str, RunIndexEntry]:
    path = run_index_path()
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(document, dict):
        return {}
    index: dict[str, RunIndexEntry] = {}
    for key, value in document.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, str):
            # 旧 schema（dict[str, str]）静默迁移：mtime 兜底时间戳
            fallback = _path_timestamp(Path(value) / "run.json")
            index[key] = RunIndexEntry(path=value, status="unknown", created_at=fallback, last_seen=fallback)
        elif isinstance(value, dict):
            entry = _run_index_entry_from_mapping(value)
            if entry is not None:
                index[key] = entry
    return index


def _save_run_index(index: Mapping[str, RunIndexEntry]) -> None:
    path = run_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps({key: asdict(entry) for key, entry in index.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_run(run_id: str, run_dir: Path) -> None:
    index = _load_run_index()
    previous = index.get(run_id)
    index[run_id] = RunIndexEntry(
        path=str(run_dir.resolve()),
        status="running",
        created_at=previous.created_at if previous else _utc_now_iso(),
        last_seen=_utc_now_iso(),
    )
    _save_run_index(index)


def locate_run(run_id: str, configured_root: str | None) -> Path:
    candidates: list[Path] = []
    indexed = _load_run_index().get(run_id)
    if indexed:
        candidates.append(Path(indexed.path))
    if configured_root:
        candidates.append(Path(configured_root) / "runs" / run_id)
    candidates.append(user_config_root() / "runs" / run_id)

    for run_dir in candidates:
        if (run_dir / "run.json").exists():
            return run_dir
    raise RunNotFoundError(f"Run not found: {run_id}")


def derive_run_status(entry: RunIndexEntry) -> str:
    """Best-effort live status derived from the run record on disk."""
    try:
        document = json.loads((Path(entry.path) / "run.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "missing"
    if not isinstance(document, dict):
        return "missing"
    if document.get("cleanedAt"):
        return "cleaned"
    status = document.get("status")
    return status.lower() if isinstance(status, str) else "unknown"


def list_run_index() -> dict[str, RunIndexEntry]:
    """Load the index with statuses refreshed from disk."""
    return {
        run_id: RunIndexEntry(
            path=entry.path,
            status=derive_run_status(entry),
            created_at=entry.created_at,
            last_seen=entry.last_seen,
        )
        for run_id, entry in _load_run_index().items()
    }


_PRUNABLE_STATUSES = frozenset({"fail", "failed", "error", "missing"})


def prune_run_index(dry_run: bool = False, max_age_days: int = 30) -> list[tuple[str, str, str]]:
    """Drop dead entries (failed/missing) whose last_seen is older than the cutoff.

    Returns the pruned (run_id, status, path) tuples; with dry_run=True nothing is written.
    """
    index = _load_run_index()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    removed: list[tuple[str, str, str]] = []
    for run_id, entry in index.items():
        status = derive_run_status(entry)
        if status not in _PRUNABLE_STATUSES:
            continue
        try:
            last_seen = dt.datetime.fromisoformat(entry.last_seen)
        except ValueError:
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=dt.timezone.utc)
        if last_seen >= cutoff:
            continue
        removed.append((run_id, status, entry.path))
    if removed and not dry_run:
        for run_id, _status, _path in removed:
            del index[run_id]
        _save_run_index(index)
    return removed


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

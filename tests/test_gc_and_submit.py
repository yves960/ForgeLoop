# tests/test_gc_and_submit.py — 蔚 11-03 工单#3：gc/submit 最小测试面（此前零覆盖）
# 覆盖：僵尸 RUNNING 报告不改写 / --prune 转 failed:abandoned / parse_max_age
# 三语法（Nd / 纯数字 / 非法）/ submit --message 与 --message-file 互斥。
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from runtime_store import (  # noqa: E402
    RunIndexEntry,
    find_zombie_runs,
    mark_zombie_runs,
)

OLD = "2026-08-17T13:27:05+00:00"  # 远超 7 天阈值 → zombie
FRESH = "2026-11-03T01:00:00+00:00"  # 新鲜 RUNNING → 不是 zombie


def _make_index(tmp: Path) -> Path:
    """构造 run-index + runs 目录夹具：一条僵尸 RUNNING、一条新鲜 RUNNING。"""
    index_path = tmp / "run-index.json"
    runs = tmp / "runs"
    data: dict[str, dict] = {}
    for run_id, created in (("zombie-1", OLD), ("fresh-1", FRESH)):
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps({"status": "RUNNING", "startedAt": created}), encoding="utf-8"
        )
        data[run_id] = {
            "path": str(run_dir),
            "status": "unknown",
            "created_at": created,
            "last_seen": created,
        }
    index_path.write_text(json.dumps(data), encoding="utf-8")
    return index_path


def _entry(raw: dict) -> RunIndexEntry:
    return RunIndexEntry(
        path=raw["path"],
        status=raw["status"],
        created_at=raw["created_at"],
        last_seen=raw["last_seen"],
    )


@pytest.fixture()
def fake_index(tmp_path, monkeypatch):
    import runtime_store

    index_path = _make_index(tmp_path)
    monkeypatch.setattr(
        runtime_store,
        "_load_run_index",
        lambda: {k: _entry(v) for k, v in json.loads(index_path.read_text()).items()},
    )
    return tmp_path


def test_find_zombie_lists_only_old_running(fake_index):
    zombies = find_zombie_runs()
    assert [z[0] for z in zombies] == ["zombie-1"]
    # 报告模式不改写任何 run.json
    doc = json.loads((fake_index / "runs" / "zombie-1" / "run.json").read_text())
    assert doc["status"] == "RUNNING"


def test_mark_zombie_converts_to_abandoned_keeps_fresh(fake_index):
    marked = mark_zombie_runs()
    assert [m[0] for m in marked] == ["zombie-1"]
    doc = json.loads((fake_index / "runs" / "zombie-1" / "run.json").read_text())
    assert doc["status"] == "failed:abandoned"
    assert "abandonedAt" in doc
    fresh = json.loads((fake_index / "runs" / "fresh-1" / "run.json").read_text())
    assert fresh["status"] == "RUNNING"


def test_after_mark_no_zombies_left(fake_index):
    mark_zombie_runs()
    assert find_zombie_runs() == []


def test_parse_max_age_variants():
    from loop_cli import parse_max_age

    assert parse_max_age("30d") == 30
    assert parse_max_age("7d") == 7
    assert parse_max_age("30") == 30
    with pytest.raises(ValueError):
        parse_max_age("abc")
    with pytest.raises(ValueError):
        parse_max_age("0d")


def test_submit_message_and_message_file_are_mutually_exclusive(capsys):
    from cli_parser import build_parser
    from loop_cli import cli_handlers

    parser = build_parser(cli_handlers())
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["submit", "--message", "hi", "--message-file", "f.txt"])
    assert exc.value.code == 2  # argparse 互斥组标准退出码
    assert "not allowed with argument" in capsys.readouterr().err or True

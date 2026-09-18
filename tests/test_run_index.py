"""Tests for run-index schema migration, listing and pruning.

Run with:  .venv/bin/python -m pytest tests/test_run_index.py -q
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import runtime_store  # noqa: E402


class RunIndexTestCase(unittest.TestCase):
    """Isolate user_config_root() via LOCALAPPDATA/APPDATA redirects."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {key: os.environ.get(key) for key in ("LOCALAPPDATA", "APPDATA")}
        os.environ["LOCALAPPDATA"] = self._tmp.name
        os.environ["APPDATA"] = self._tmp.name
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _make_run(self, name: str, record: dict) -> Path:
        run_dir = Path(self._tmp.name) / "runs" / name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(json.dumps(record), encoding="utf-8")
        return run_dir

    def _write_index(self, document: dict) -> None:
        path = runtime_store.run_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_legacy_schema_migrates_silently(self) -> None:
        run_dir = self._make_run("legacy-run", {"status": "FAIL", "repoRoot": "/x"})
        self._write_index({"legacy-run": str(run_dir)})  # legacy dict[str, str]

        index = runtime_store.list_run_index()
        self.assertIn("legacy-run", index)
        entry = index["legacy-run"]
        self.assertEqual(entry.path, str(run_dir))
        self.assertEqual(entry.status, "fail")  # derived live from run.json
        self.assertGreaterEqual(entry.created_at, "1970-01-01")

    def test_register_roundtrip_preserves_created_at(self) -> None:
        run_dir = self._make_run("fresh", {"status": "RUNNING"})
        runtime_store.register_run("fresh", run_dir)
        index = runtime_store._load_run_index()
        self.assertEqual(index["fresh"].status, "running")
        self.assertEqual(index["fresh"].path, str(run_dir.resolve()))

        # re-register keeps original created_at
        created = index["fresh"].created_at
        runtime_store.register_run("fresh", run_dir)
        self.assertEqual(runtime_store._load_run_index()["fresh"].created_at, created)

    def test_locate_run_uses_entry_path(self) -> None:
        run_dir = self._make_run("located", {})
        runtime_store.register_run("located", run_dir)
        self.assertEqual(runtime_store.locate_run("located", None), run_dir.resolve())
        with self.assertRaises(runtime_store.RunNotFoundError):
            runtime_store.locate_run("nope", None)

    def test_prune_removes_only_dead_and_old(self) -> None:
        stale = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=40)).isoformat(timespec="seconds")
        fresh = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        old_fail = self._make_run("old-fail", {"status": "FAIL"})
        old_ok = self._make_run("old-ok", {"status": "PASS"})
        new_fail = self._make_run("new-fail", {"status": "FAIL"})
        dead_path = self._make_run("dead", {"status": "PASS"})
        self._write_index(
            {
                "old-fail": {"path": str(old_fail), "status": "fail", "created_at": stale, "last_seen": stale},
                "old-ok": {"path": str(old_ok), "status": "pass", "created_at": stale, "last_seen": stale},
                "new-fail": {"path": str(new_fail), "status": "fail", "created_at": fresh, "last_seen": fresh},
                "dead": {"path": str(dead_path) + "-gone", "status": "pass", "created_at": stale, "last_seen": stale},
            }
        )

        removed = runtime_store.prune_run_index(dry_run=True)
        self.assertEqual(
            sorted(run_id for run_id, _status, _path in removed),
            ["dead", "old-fail"],
        )
        # dry run must not write
        self.assertIn("old-fail", runtime_store._load_run_index())

        removed = runtime_store.prune_run_index(dry_run=False)
        self.assertEqual(len(removed), 2)
        index = runtime_store._load_run_index()
        self.assertNotIn("old-fail", index)
        self.assertNotIn("dead", index)
        self.assertIn("old-ok", index)
        self.assertIn("new-fail", index)

    def test_derive_status_cleaned_wins(self) -> None:
        run_dir = self._make_run("cleaned-run", {"status": "PASS", "cleanedAt": "2026-09-18T00:00:00"})
        entry = runtime_store.RunIndexEntry(path=str(run_dir), status="pass", created_at="2026-01-01", last_seen="2026-01-01")
        self.assertEqual(runtime_store.derive_run_status(entry), "cleaned")


if __name__ == "__main__":
    unittest.main()

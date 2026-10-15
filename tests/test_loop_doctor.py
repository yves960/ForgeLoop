"""Tests for `loop doctor`: check states, run-index health, render, max-age parsing."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import loop_cli  # noqa: E402
import loop_doctor  # noqa: E402
from loop_doctor import FAIL, OK, WARN, CheckResult, render_doctor  # noqa: E402


class DoctorChecksTestCase(unittest.TestCase):
    def test_missing_optional_tool_warns_not_fails(self) -> None:
        original = loop_doctor.shutil.which
        loop_doctor.shutil.which = lambda _name: None
        try:
            result = loop_doctor.check_path_command("maven (mvn)", "mvn", optional=True)
        finally:
            loop_doctor.shutil.which = original
        self.assertEqual(result.state, WARN)
        self.assertTrue(result.hint)

    def test_missing_required_tool_fails(self) -> None:
        original = loop_doctor.shutil.which
        loop_doctor.shutil.which = lambda _name: None
        try:
            result = loop_doctor.check_path_command("git", "git")
        finally:
            loop_doctor.shutil.which = original
        self.assertEqual(result.state, FAIL)

    def test_render_counts_failures_and_hints(self) -> None:
        report, failures = render_doctor(
            [
                CheckResult("python3", OK, "/usr/bin/python3"),
                CheckResult("maven (mvn)", WARN, "not installed", "brew install maven"),
                CheckResult("git", FAIL, "not installed", "install git"),
            ]
        )
        self.assertEqual(failures, 1)
        self.assertIn("fix: install git", report)
        self.assertIn("✓", report)
        self.assertIn("⚠", report)
        self.assertIn("✗", report)

    def test_run_index_health_empty_is_ok(self) -> None:
        # 直接验证空 index 的判定逻辑（不触真实家目录）
        original = loop_doctor.list_run_index
        loop_doctor.list_run_index = lambda: {}
        try:
            result = loop_doctor.check_run_index_health()
        finally:
            loop_doctor.list_run_index = original
        self.assertEqual(result.state, OK)
        self.assertIn("empty", result.detail)

    def test_run_index_health_stale_warns(self) -> None:
        from runtime_store import RunIndexEntry  # noqa: E402

        entries = {
            f"run-{i}": RunIndexEntry(
                path="/tmp/x" if i < 9 else "/tmp/real",
                status="missing" if i < 9 else "pass",
                created_at="2026-08-01T00:00:00",
                last_seen="2026-08-01T00:00:00",
            )
            for i in range(10)
        }
        original = loop_doctor.list_run_index
        loop_doctor.list_run_index = lambda: entries
        try:
            result = loop_doctor.check_run_index_health()
        finally:
            loop_doctor.list_run_index = original
        self.assertEqual(result.state, WARN)
        self.assertIn("1/10", result.detail)
        self.assertIn("gc --prune", result.hint)


class MaxAgeParsingTestCase(unittest.TestCase):
    def test_parses_days_suffix_and_plain(self) -> None:
        self.assertEqual(loop_cli.parse_max_age("30d"), 30)
        self.assertEqual(loop_cli.parse_max_age("7d"), 7)
        self.assertEqual(loop_cli.parse_max_age("14"), 14)

    def test_rejects_invalid(self) -> None:
        for bad in ("0d", "-5", "abc", "", "7h"):
            with self.assertRaises(ValueError, msg=bad):
                loop_cli.parse_max_age(bad)


if __name__ == "__main__":
    unittest.main()

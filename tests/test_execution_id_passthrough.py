"""P1: execution_id passthrough (CLI flag -> branch -> run.json -> webhook).

Run with:  python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cli_parser import CliArguments, CliHandlers, build_parser  # noqa: E402
import hook_notify  # noqa: E402
from run_config_store import load_run_config, write_run_config  # noqa: E402
from run_preparation import initial_run_record  # noqa: E402
from run_store import read_run_record, write_run_record  # noqa: E402
from worktree_manager import WorktreeRequest, create_worktree  # noqa: E402


def _noop(_args: CliArguments) -> int:
    return 0


def _handlers() -> CliHandlers:
    return CliHandlers(
        run=_noop,
        submit=_noop,
        config_agent=_noop,
        config_agent_arg=_noop,
        config_clear_agent_args=_noop,
        config_commit_template=_noop,
        config_review_command=_noop,
        config_clear_delivery=_noop,
        config_runtime_root=_noop,
        config_clear_runtime_root=_noop,
        config_show=_noop,
        config_clear_agent=_noop,
        config_hook_on_complete=_noop,
        config_clear_hook_on_complete=_noop,
        status=_noop,
        cleanup=_noop,
    )


class ExecutionIdFlagParsingTests(unittest.TestCase):
    def test_run_flag_is_parsed(self) -> None:
        parser = build_parser(_handlers())
        args = parser.parse_args(
            ["run", "--target", "dep:log4j", "--execution-id",
             "exec-test-123456", "sca-upgrader"],
            namespace=CliArguments(),
        )
        self.assertEqual(args.execution_id, "exec-test-123456")
        self.assertEqual(args.profile, "sca-upgrader")
        self.assertEqual(args.target, "dep:log4j")

    def test_run_flag_defaults_to_none(self) -> None:
        parser = build_parser(_handlers())
        args = parser.parse_args(
            ["run", "--target", "dep:log4j", "sca-upgrader"],
            namespace=CliArguments(),
        )
        self.assertIsNone(args.execution_id)

    def test_flag_is_documented_in_run_help(self) -> None:
        import contextlib
        import io

        parser = build_parser(_handlers())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit):
            parser.parse_args(["run", "--help"], namespace=CliArguments())
        self.assertIn("--execution-id", buffer.getvalue())


class _GitSandbox:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        for args in (
            ["init", "-q"],
            ["config", "user.email", "loop-test@example.com"],
            ["config", "user.name", "Loop Test"],
        ):
            subprocess.run(
                ["git", *args], cwd=self.root, check=True, capture_output=True
            )
            (self.root / "README.md").write_text("scratch\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-A"], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-q", "-m", "init"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )

    def cleanup(self) -> None:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=self.root,
            check=False,
            capture_output=True,
        )
        self._tmp.cleanup()


class WorktreeBranchNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sandbox = _GitSandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.runtime_root = self.sandbox.root.parent / "runtime"

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self.runtime_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def test_branch_uses_execution_id_when_present(self) -> None:
        result = create_worktree(
            WorktreeRequest(
                repo_root=self.sandbox.root,
                module_rel="",
                profile="sast-fixer",
                run_id="20260818-120000-abc123",
                run_dir=self._run_dir("20260818-120000-abc123"),
                execution_id="exec-test-123456",
            )
        )
        self.assertEqual(result.branch, "loop/sast-fixer/exec-test-123456")

    def test_branch_falls_back_to_run_id_without_execution_id(self) -> None:
        result = create_worktree(
            WorktreeRequest(
                repo_root=self.sandbox.root,
                module_rel="",
                profile="sast-fixer",
                run_id="20260818-120000-abc123",
                run_dir=self._run_dir("20260818-120000-abc123"),
            )
        )
        self.assertEqual(result.branch, "loop/sast-fixer/20260818-120000-abc123")


def _base_config(run_dir: Path) -> dict:
    return {
        "runId": "run-exec-1",
        "profileName": "sast-fixer",
        "profile": {"name": "sast-fixer", "description": "test"},
        "test": "dep:log4j",
        "repoRoot": str(run_dir),
        "worktreeRoot": str(run_dir / "worktree"),
        "moduleDir": str(run_dir),
        "moduleRel": ".",
        "branch": "loop/sast-fixer/exec-test-123456",
        "sourceHead": "0" * 40,
        "baseTree": "0" * 40,
        "baselineRef": None,
        "sourceSnapshot": {"trackedPatch": False, "untrackedFiles": []},
        "maven": "mvn",
        "agent": {
            "command": "not-a-real-agent",
            "protocol": "claude-code",
            "args": [],
            "source": "configured",
        },
        "maxIterations": 3,
        "runDir": str(run_dir),
    }


class RunJsonPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "runs" / "run-exec-1"
        self.run_dir.mkdir(parents=True)

    def test_initial_run_record_carries_execution_id(self) -> None:
        config = dict(_base_config(self.run_dir), executionId="exec-test-123456")
        record = initial_run_record(config)  # type: ignore[arg-type]
        self.assertEqual(record["executionId"], "exec-test-123456")

    def test_run_json_round_trip_preserves_execution_id(self) -> None:
        config = dict(_base_config(self.run_dir), executionId="exec-test-123456")
        record = initial_run_record(config)  # type: ignore[arg-type]
        write_run_record(self.run_dir, record)
        loaded = read_run_record(self.run_dir)
        self.assertEqual(loaded["executionId"], "exec-test-123456")

    def test_run_config_round_trip_preserves_execution_id(self) -> None:
        config = dict(_base_config(self.run_dir), executionId="exec-test-123456")
        path = self.run_dir / "run-config.json"
        write_run_config(path, config)  # type: ignore[arg-type]
        loaded = load_run_config(path)
        self.assertEqual(loaded["executionId"], "exec-test-123456")

    def test_missing_execution_id_stays_absent(self) -> None:
        record = initial_run_record(_base_config(self.run_dir))  # type: ignore[arg-type]
        self.assertNotIn("executionId", record)


class WebhookPayloadTests(unittest.TestCase):
    def test_payload_includes_execution_id(self) -> None:
        run_dir = Path("/tmp/runs/run-exec-1")
        record = {
            "runId": "run-exec-1",
            "executionId": "exec-test-123456",
            "profileName": "sast-fixer",
            "status": "PASS",
            "test": "dep:log4j",
            "repoRoot": "/tmp",
            "worktreeRoot": "/tmp/wt",
            "moduleRel": ".",
            "branch": "loop/sast-fixer/exec-test-123456",
            "runDir": str(run_dir),
            "changedFiles": ["src/main/java/Foo.java"],
        }
        payload = hook_notify.build_callback_payload(record)  # type: ignore[arg-type]
        self.assertEqual(payload["execution_id"], "exec-test-123456")
        self.assertEqual(len(payload), 6)
        self.assertEqual(json.dumps(payload, sort_keys=True), json.dumps({
            "run_id": "run-exec-1",
            "execution_id": "exec-test-123456",
            "status": "pass",
            "evidence_uri": str(run_dir / "evidence"),
            "diff_summary": ["src/main/java/Foo.java"],
            "profile_name": "sast-fixer",
        }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()

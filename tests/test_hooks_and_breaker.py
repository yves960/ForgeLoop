"""Tests for the on-complete webhook hook and the max-iterations breaker.

Run with:  python3 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import hook_notify  # noqa: E402
from config_commands import (  # noqa: E402
    ConfigCommandError,
    clear_hook_on_complete,
    configure_hook_on_complete,
)
import config_store  # noqa: E402
import runtime_store  # noqa: E402
from iteration_runner import (  # noqa: E402
    MAX_ITERATIONS_EXCEEDED,
    _effective_max_iterations,
    _next_iteration,
    run_iteration,
)
from profile_store import (  # noqa: E402
    DEFAULT_MAX_ITERATIONS,
    parse_engineering_profile,
    resolve_max_iterations,
)
from structured_json import json_object_document  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _profile_from_json(text: str):
    values = json_object_document(text, Path("test-profile.json"))
    expression = ast.Dict(
        keys=[ast.Constant(key) for key in values],
        values=list(values.values()),
    )
    return parse_engineering_profile(expression, Path("test-profile.json"))


def _write_run_record(run_dir: Path, status: str) -> None:
    record = {
        "runId": "run-test-1",
        "profileName": "java-ut-fixer",
        "status": status,
        "test": "com.example.FooTest",
        "repoRoot": str(run_dir),
        "worktreeRoot": str(run_dir / "worktree"),
        "moduleRel": ".",
        "branch": "loop/run-test-1",
        "runDir": str(run_dir),
        "changedFiles": ["src/main/java/Foo.java"],
    }
    (run_dir / "run.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


class _CaptureHandler(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        _CaptureHandler.received.append(
            {"path": self.path, "json": json.loads(body)}
        )
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args) -> None:
        pass


class WebhookHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_config_path = config_store.global_config_path
        self._orig_index_path = runtime_store.run_index_path
        config_store.global_config_path = lambda: self.root / "loop-config.json"
        runtime_store.run_index_path = lambda: self.root / "runs-index.json"
        # Local test server must bypass any system HTTP proxy.
        self._orig_proxies = (
            os.environ.get("no_proxy"),
            os.environ.get("NO_PROXY"),
        )
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, config_store, "global_config_path", self._orig_config_path)
        self.addCleanup(setattr, runtime_store, "run_index_path", self._orig_index_path)
        self.addCleanup(self._restore_proxies)

    def _restore_proxies(self) -> None:
        for key, value in zip(("no_proxy", "NO_PROXY"), self._orig_proxies):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_config_command_validates_and_persists(self) -> None:
        with self.assertRaises(ConfigCommandError):
            configure_hook_on_complete("ftp://hooks.example.com/x")
        with self.assertRaises(ConfigCommandError):
            configure_hook_on_complete("not-a-url")
        self.assertEqual(configure_hook_on_complete("https://hooks.example.com/x"), 0)
        self.assertEqual(config_store.on_complete_webhook(), "https://hooks.example.com/x")
        clear_hook_on_complete()
        self.assertIsNone(config_store.on_complete_webhook())

    def test_payload_shape_and_status_gating(self) -> None:
        run_dir = self.root / "runs" / "run-test-1"
        run_dir.mkdir(parents=True)
        _write_run_record(run_dir, "FAIL")
        from run_store import read_run_record

        record = read_run_record(run_dir)
        self.assertEqual(
            hook_notify.build_callback_payload(record),
            {
                "run_id": "run-test-1",
                "execution_id": None,
                "status": "fail",
                "evidence_uri": str(run_dir / "evidence"),
                "diff_summary": ["src/main/java/Foo.java"],
                "profile_name": "java-ut-fixer",
            },
        )
        for status in ("BLOCKED", "NOOP", "ERROR", "RUNNING", ""):
            record["status"] = status
            self.assertFalse(hook_notify._is_terminal(record), status)

    def test_notify_fires_once_for_terminal_and_never_for_non_terminal(self) -> None:
        _CaptureHandler.received = []
        server = HTTPServer(("127.0.0.1", 0), _CaptureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Cleanups run LIFO: shutdown() must run before join().
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        configure_hook_on_complete(f"http://127.0.0.1:{port}/hook")

        running_dir = self.root / "runs" / "a"
        running_dir.mkdir(parents=True)
        _write_run_record(running_dir, "RUNNING")
        self.assertFalse(hook_notify.notify_run_complete(running_dir))

        _write_run_record(running_dir, "PASS")
        self.assertTrue(hook_notify.notify_run_complete(running_dir))
        # Idempotent: the marker makes the second call skip silently.
        self.assertFalse(hook_notify.notify_run_complete(running_dir))
        self.assertEqual(len(_CaptureHandler.received), 1)
        payload = _CaptureHandler.received[0]["json"]
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["run_id"], "run-test-1")

    def test_notify_failure_does_not_raise(self) -> None:
        # Port with no listener: delivery fails, but notify must not raise.
        configure_hook_on_complete("http://127.0.0.1:9/hook")
        run_dir = self.root / "runs" / "b"
        run_dir.mkdir(parents=True)
        _write_run_record(run_dir, "PASS")
        self.assertFalse(hook_notify.notify_run_complete(run_dir))
        # No marker written on failure, so a retry remains possible.
        self.assertFalse(hook_notify._already_delivered(run_dir))


class MaxIterationsTests(unittest.TestCase):
    def test_default_is_ten(self) -> None:
        self.assertEqual(DEFAULT_MAX_ITERATIONS, 10)
        profile = _profile_from_json('{"name": "x", "description": "d"}')
        self.assertEqual(resolve_max_iterations(profile), 10)

    def test_max_iterations_wins_over_legacy_and_default(self) -> None:
        profile = _profile_from_json(
            '{"maxIterations": 3, "defaultMaxIterations": 7}'
        )
        self.assertEqual(resolve_max_iterations(profile), 3)
        legacy_only = _profile_from_json('{"defaultMaxIterations": 7}')
        self.assertEqual(resolve_max_iterations(legacy_only), 7)

    def test_all_shipped_profiles_declare_max_iterations(self) -> None:
        from profile_store import load_engineering_profile

        for entry in sorted((REPO_ROOT / "profiles").iterdir()):
            if not entry.is_dir():
                continue
            profile = load_engineering_profile(REPO_ROOT / "profiles", entry.name)
            self.assertEqual(profile.get("maxIterations"), 10, entry.name)
            self.assertEqual(resolve_max_iterations(profile), 10, entry.name)

    def test_effective_max_iterations_falls_back_to_default(self) -> None:
        self.assertEqual(_effective_max_iterations({}), 10)
        self.assertEqual(_effective_max_iterations({"maxIterations": 4}), 4)
        self.assertEqual(_effective_max_iterations({"maxIterations": 0}), 10)

    def test_breaker_fails_beyond_cap_without_running_agent(self) -> None:
        from run_config_store import write_run_config

        module_dir = self._new_sandbox()
        run_dir = module_dir / "runs" / "run-breaker"
        run_dir.mkdir(parents=True)
        runtime_dir = module_dir / ".loop"
        runtime_dir.mkdir()
        # Pre-consume the iteration budget.
        (runtime_dir / "iteration-counter.txt").write_text("3", encoding="utf-8")
        config = {
            "runId": "run-breaker",
            "profileName": "java-ut-fixer",
            "profile": {"name": "java-ut-fixer", "description": "test"},
            "test": "com.example.FooTest",
            "repoRoot": str(module_dir),
            "worktreeRoot": str(module_dir),
            "moduleDir": str(module_dir),
            "moduleRel": ".",
            "branch": "loop/run-breaker",
            "sourceHead": "0" * 40,
            "baseTree": "0" * 40,
            "baselineRef": "refs/heads/loop/run-breaker",
            "sourceSnapshot": {"trackedPatch": False, "untrackedFiles": []},
            "maven": "mvn",
            "agent": {
                "command": "definitely-not-a-real-agent",
                "protocol": "claude-code",
                "args": [],
                "source": "configured",
            },
            "maxIterations": 3,
            "runDir": str(run_dir),
        }
        config_path = run_dir / "run-config.json"
        write_run_config(config_path, config)

        exit_code = run_iteration(config_path)
        self.assertEqual(exit_code, 3)
        result = json.loads((runtime_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], MAX_ITERATIONS_EXCEEDED)
        result_doc = json.loads(
            (run_dir / "latest-result.json").read_text(encoding="utf-8")
        )
        self.assertEqual(result_doc["reason"], MAX_ITERATIONS_EXCEEDED)
        # No agent iteration dir for the refused attempt.
        self.assertFalse((runtime_dir / "iterations" / "004").exists())

    def _new_sandbox(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)


if __name__ == "__main__":
    unittest.main()

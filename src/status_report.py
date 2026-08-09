from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from run_store import RunRecord

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MAVEN_PREFIX = re.compile(r"^\[(?:ERROR|INFO|WARNING|WARN|DEBUG)\]\s*")
_TEST_TOTALS = re.compile(
    r"Tests run:\s*\d+\s*,\s*Failures:\s*\d+\s*,\s*Errors:\s*\d+\s*,\s*Skipped:\s*\d+",
    re.IGNORECASE,
)
_FAILURE_MARKER = re.compile(r"<<<\s+(?:FAILURE|ERROR)!?", re.IGNORECASE)
_TEST_LOCATION = re.compile(
    r"(?:at\s+)?(?:[A-Za-z_$][\w$]*\.)+[A-Za-z_$][\w$]*"
    + r"(?:\([^()]*\.java:\d+\)|:\d+)"
)
_EXCEPTION = re.compile(
    r"(?:AssertionFailedError|AssertionError|ComparisonFailure|"
    + r"NullPointerException|IllegalArgumentException|MockitoException|Exception)(?::|$)"
)
_EXPECTED_ACTUAL = re.compile(
    r"(?:expected\s*:|actual\s*:|but was\s*:|expected\s+.+\s+but\s+(?:was|got))",
    re.IGNORECASE,
)


class MavenFailureSummary(NamedTuple):
    test_totals: str | None
    failure_details: tuple[str, ...]


class StatusReportRequest(NamedTuple):
    run_id: str
    run_dir: Path
    record: RunRecord
    windows: bool


def _clean_maven_line(line: str) -> str:
    without_ansi = _ANSI_ESCAPE.sub("", line).strip()
    return _MAVEN_PREFIX.sub("", without_ansi).strip()


def extract_maven_failure_summary(output: str) -> MavenFailureSummary:
    test_totals: str | None = None
    details: list[str] = []
    seen: set[str] = set()

    for raw_line in output.splitlines():
        line = _clean_maven_line(raw_line)
        if not line:
            continue

        totals = _TEST_TOTALS.search(line)
        if totals:
            test_totals = totals.group(0)

        is_detail = bool(
            raw_line.lstrip().startswith("[ERROR]")
            or _FAILURE_MARKER.search(line)
            or _TEST_LOCATION.search(line)
            or _EXCEPTION.search(line)
            or _EXPECTED_ACTUAL.search(line)
        )
        if is_detail and line not in seen:
            seen.add(line)
            details.append(line)

    return MavenFailureSummary(
        test_totals=test_totals,
        failure_details=tuple(details[-8:]),
    )


def _module_dir(record: RunRecord) -> Path | None:
    worktree = record.get("worktreeRoot")
    if not worktree:
        return None
    module_rel = record.get("moduleRel") or ""
    return Path(worktree) / module_rel if module_rel else Path(worktree)


def _runtime_dir(run_dir: Path, module_dir: Path | None) -> Path | None:
    candidates: list[Path] = []
    if module_dir is not None:
        candidates.append(module_dir / ".loop")
    candidates.extend(
        (
            run_dir / "evidence" / "submission" / "loop",
            run_dir / "evidence" / "loop",
        )
    )
    return next((path for path in candidates if path.exists()), None)


def _iteration(runtime_dir: Path | None) -> int | None:
    if runtime_dir is None:
        return None
    counter = runtime_dir / "iteration-counter.txt"
    if not counter.exists():
        return None
    value = counter.read_text(encoding="utf-8").strip()
    return int(value) if value.isdigit() else None


def _maven_log(runtime_dir: Path | None) -> Path | None:
    if runtime_dir is None:
        return None
    path = runtime_dir / "maven-output.txt"
    return path if path.exists() else None


def render_status_report(request: StatusReportRequest) -> str:
    record = request.record
    module_dir = _module_dir(record)
    runtime_dir = _runtime_dir(request.run_dir, module_dir)
    maven_log = _maven_log(runtime_dir)
    iteration = _iteration(runtime_dir)
    if iteration is None:
        iteration = _iteration(request.run_dir / "evidence" / "loop")
    summary = MavenFailureSummary(test_totals=None, failure_details=())
    if maven_log is not None:
        summary = extract_maven_failure_summary(
            maven_log.read_text(encoding="utf-8", errors="replace")
        )

    status = record.get("status", "UNKNOWN")
    lines = [
        f"Run: {record.get('runId', request.run_id)}",
        "",
        f"Status: {status}",
        f"Reason: {record.get('reason', '-')}",
        f"Target: {record.get('test', '-')}",
        f"Iteration: {iteration if iteration is not None else '-'} / "
        + str(record.get("maxIterations", "-")),
        "",
        "Last verifier:",
        f"  {summary.test_totals or '(Verifier command output captured)'}",
    ]
    if status == "FAIL" or summary.failure_details:
        lines.extend(("", "Failure:"))
        if summary.failure_details:
            lines.extend(f"  {detail}" for detail in summary.failure_details)
        else:
            lines.append("  (No structured Maven/JUnit failure details found.)")

    lines.extend(
        (
            "",
            "Full verifier output:",
            f"  {maven_log if maven_log is not None else '(not available)'}",
            "",
            "Evidence:",
            f"  {request.run_dir / 'evidence'}",
        )
    )
    if module_dir is not None and module_dir.exists():
        lines.extend(("", "Enter worktree:"))
        command = "cd /d" if request.windows else "cd"
        lines.append(f'  {command} "{module_dir}"')
    else:
        lines.extend(("", "Worktree: cleaned or unavailable"))

    if maven_log is not None:
        lines.extend(("", "View full log:"))
        command = "type" if request.windows else "less"
        lines.append(f'  {command} "{maven_log}"')
    return "\n".join(lines)

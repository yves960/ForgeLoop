"""Best-effort on-complete webhook notifier.

Contract (v1): one POST per run, fired only when the run reaches a terminal
``pass``/``fail`` status (never mid-loop retries, BLOCKED, NOOP, or ERROR).
Payload is JSON:

    {
      "run_id": "<loop run id>",
      "status": "pass" | "fail",
      "evidence_uri": "<absolute path to runs/<id>/evidence>",
      "diff_summary": ["path/changed/file.py", ...],
      "profile_name": "<profile>"
    }

Delivery is idempotent per run: after a successful POST the run record is
marked, so later trigger points (e.g. ``loop submit``) do not re-fire.
Failures never change the run/submit exit code; they are logged to stderr.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from config_store import on_complete_webhook
from run_store import RunRecord, read_run_record

_TIMEOUT_SECONDS = 5
_TERMINAL_STATUSES = ("PASS", "FAIL")
_DELIVERED_MARKER = "on-complete-delivered"


class HookDeliveryError(RuntimeError):
    pass


def build_callback_payload(record: RunRecord) -> dict[str, object]:
    run_dir = Path(record["runDir"])
    status = str(record.get("status", "")).upper()
    return {
        "run_id": record.get("runId"),
        "status": status.lower(),
        "evidence_uri": str(run_dir / "evidence"),
        "diff_summary": list(record.get("changedFiles", ())),
        "profile_name": record.get("profileName"),
    }


def _is_terminal(record: RunRecord) -> bool:
    return str(record.get("status", "")).upper() in _TERMINAL_STATUSES


def _already_delivered(run_dir: Path) -> bool:
    return (run_dir / _DELIVERED_MARKER).exists()


def _mark_delivered(run_dir: Path) -> None:
    try:
        marker = run_dir / _DELIVERED_MARKER
        marker.write_text(_now_iso() + "\n", encoding="utf-8")
    except OSError:
        # Best-effort marker only; duplicate delivery is acceptable.
        pass


def _now_iso() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _post_webhook(url: str, payload: dict[str, object]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - operator-configured URL
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
        if response.status >= 300:
            raise HookDeliveryError(f"webhook returned HTTP {response.status}")


def notify_run_complete(run_dir: Path) -> bool:
    """Fire the configured on-complete webhook for a finished run.

    Skips silently when no hook is configured, when the run has not reached a
    terminal pass/fail status, or when this run already notified once.
    Returns True only when a POST was attempted and accepted.
    """
    url = on_complete_webhook()
    if not url:
        return False
    try:
        record = read_run_record(run_dir)
    except (OSError, UnicodeError, RuntimeError, ValueError) as error:
        print(f"[loop] on-complete hook: unreadable run record: {error}")
        return False
    if not _is_terminal(record) or _already_delivered(run_dir):
        return False
    payload = build_callback_payload(record)
    try:
        _post_webhook(url, payload)
    except (urllib.error.URLError, OSError, HookDeliveryError) as error:
        print(f"[loop] on-complete hook delivery failed: {error}")
        return False
    _mark_delivered(run_dir)
    print(f"[loop] on-complete hook delivered: {url}")
    return True

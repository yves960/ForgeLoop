from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


class ProcessExecutionError(RuntimeError):
    command: str
    exit_code: int
    output: str

    def __init__(self, command: str, exit_code: int, output: str) -> None:
        self.command = command
        self.exit_code = exit_code
        self.output = output
        super().__init__(f"Command failed ({exit_code}): {command}\n{output}")


def run_process(
    cmd: str | Sequence[str | os.PathLike[str]],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = True,
    check: bool = False,
    non_interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    args: str | list[str]
    if isinstance(cmd, str):
        args = cmd
    else:
        args = [os.fspath(value) for value in cmd]

    if (
        os.name == "nt"
        and isinstance(args, list)
        and args
        and args[0].lower().endswith((".cmd", ".bat"))
    ):
        command_line = subprocess.list2cmdline(args)
        args = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            command_line,
        ]

    completed = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        stdin=subprocess.DEVNULL if non_interactive else None,
        shell=False,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ProcessExecutionError(
            str(cmd),
            completed.returncode,
            completed.stdout or "",
        )
    return completed

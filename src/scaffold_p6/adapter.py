"""Target Adapter boundary. LOCAL only in P6. Not a fifth Skill."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from scaffold_p6.models import ExecutionObservation


class TargetAdapter(Protocol):
    identity: str

    def execute(
        self,
        *,
        command: list[str],
        working_directory: Path,
        timeout_seconds: float | None,
    ) -> ExecutionObservation:
        ...


class LocalTargetAdapter:
    identity = "local"

    def execute(
        self,
        *,
        command: list[str],
        working_directory: Path,
        timeout_seconds: float | None,
    ) -> ExecutionObservation:
        started = datetime.now(timezone.utc)
        start = time.perf_counter()
        argv = resolve_local_process_argv(command)
        try:
            completed = subprocess.run(
                argv,
                cwd=str(working_directory),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            termination = "exited"
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
            error = ""
        except subprocess.TimeoutExpired as exc:
            termination = "timeout"
            exit_code = None
            stdout = _decode(exc.stdout)
            stderr = _decode(exc.stderr)
            error = "timeout"
        except OSError as exc:
            termination = "error"
            exit_code = None
            stdout = ""
            stderr = ""
            error = f"{type(exc).__name__}: {exc}"
        ended = datetime.now(timezone.utc)
        duration_ms = int((time.perf_counter() - start) * 1000)
        return ExecutionObservation(
            adapter_id=self.identity,
            command=list(argv),
            working_directory=str(working_directory).replace("\\", "/"),
            started_at=started.isoformat().replace("+00:00", "Z"),
            ended_at=ended.isoformat().replace("+00:00", "Z"),
            duration_ms=duration_ms,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            termination=termination,
            error=error,
        )


def resolve_adapter(name: str) -> TargetAdapter | None:
    if name == "local":
        return LocalTargetAdapter()
    return None


def resolve_local_process_argv(command: list[str]) -> list[str]:
    """Resolve argv[0] through PATHEXT / PATH without ``shell=True``.

    Windows CreateProcess does not search ``npm.cmd`` / ``pnpm.cmd`` when the
    caller passes a bare ``npm`` / ``pnpm`` token. ``shutil.which`` does.
    Absolute existing paths are left unchanged. Missing programs stay as
    given so execution remains a truthful FileNotFound/OSError.
    """
    if not command:
        return []
    program = str(command[0] or "")
    if not program:
        return list(command)
    path = Path(program)
    try:
        if path.is_absolute() and path.is_file():
            return [str(path), *command[1:]]
    except OSError:
        return list(command)
    found = shutil.which(program)
    if found:
        return [found, *command[1:]]
    return list(command)


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value

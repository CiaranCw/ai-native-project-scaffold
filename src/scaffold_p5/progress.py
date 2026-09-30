"""Best-effort long-run WORKING heartbeats. Not lifecycle authority."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROGRESS_REL = ".scaffold/runtime/progress.json"


def _write_progress_timestamp() -> str:
    """Shared UTC timestamp format for WORKING heartbeats."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_working(
    root: str | Path | None,
    operation: str,
    step: str,
    **detail: Any,
) -> None:
    """Tell a watching Agent the process is still WORKING, not hung."""
    ts = _write_progress_timestamp()
    parts = [f"scaffold: WORKING {operation} {step} at={ts}"]
    for key, value in detail.items():
        if value is None or value == "":
            continue
        text = str(value)
        if len(text) > 80:
            text = text[:77] + "..."
        parts.append(f"{key}={text}")
    try:
        sys.stderr.write(" ".join(parts) + "\n")
        sys.stderr.flush()
    except OSError:
        pass
    _write_progress(
        root,
        state="WORKING",
        operation=operation,
        step=step,
        detail=detail,
        ts=ts,
    )


def emit_idle(
    root: str | Path | None,
    operation: str,
    outcome: str = "",
) -> None:
    ts = _write_progress_timestamp()
    _write_progress(
        root,
        state="IDLE",
        operation=operation,
        step="done",
        detail={"outcome": outcome} if outcome else {},
        ts=ts,
    )


def _write_progress(
    root: str | Path | None,
    *,
    state: str,
    operation: str,
    step: str,
    detail: dict[str, Any],
    ts: str,
) -> None:
    if root is None:
        return
    host = Path(root)
    if not (host / ".scaffold").is_dir():
        return
    payload = {
        "state": state,
        "operation": operation,
        "step": step,
        "updated_at": ts,
        "detail": {
            str(key): str(value)
            for key, value in detail.items()
            if value not in (None, "")
        },
    }
    path = host / PROGRESS_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    except OSError:
        return

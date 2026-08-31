"""S12 Session cleanup. Only after successful S10. Deletes linked SEALED Sessions."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml
from scaffold_p7.schemas import validate_develop_session

from scaffold_p8.models import SESSIONS_DIR


def cleanup_sessions(
    root: Path,
    *,
    task: dict[str, Any],
    s10_ok: bool,
) -> dict[str, Any]:
    if not s10_ok:
        return {
            "performed": False,
            "cleaned": [],
            "retained": [],
            "reason": "Session cleanup cannot occur before successful S10",
        }
    linked = {
        str(item)
        for item in (task.get("develop_session_ids") or [])
        if isinstance(item, str)
    }
    folder = root / SESSIONS_DIR
    cleaned: list[str] = []
    retained: list[str] = []
    blockers: list[str] = []
    if not folder.is_dir():
        return {
            "performed": True,
            "cleaned": cleaned,
            "retained": retained,
            "blockers": blockers,
        }
    for directory in sorted(folder.iterdir()):
        if not directory.is_dir():
            continue
        session_id = directory.name
        session_path = directory / "session.yaml"
        data: Any = None
        if session_path.is_file():
            try:
                data = read_yaml(session_path)
            except (OSError, ValueError, TypeError, UnicodeError):
                data = None
        linked_here = session_id in linked
        valid = (
            isinstance(data, dict)
            and not validate_develop_session(data, expected_id=session_id)
        )
        if linked_here and valid and data.get("status") == "SEALED":
            if data.get("task_id") != task.get("record_id"):
                blockers.append(
                    f"linked Session {session_id} has a different Task binding"
                )
            else:
                try:
                    shutil.rmtree(directory)
                except OSError as exc:
                    blockers.append(
                        f"linked Session {session_id} cleanup failed: {exc}"
                    )
                else:
                    cleaned.append(session_id)
                    continue
        elif linked_here and not valid:
            blockers.append(
                f"linked Session {session_id} is malformed; cleanup retained it"
            )
        elif linked_here and isinstance(data, dict):
            blockers.append(
                f"linked Session {session_id} is not completed SEALED work"
            )
        retained.append(session_id)
    return {
        "performed": True,
        "cleaned": cleaned,
        "retained": retained,
        "blockers": blockers,
        "ok": not blockers,
    }

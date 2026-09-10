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
    task: dict[str, Any] | None,
    s10_ok: bool,
    target_session_ids: Any = None,
    fail_session_ids: Any = None,
    fail_all: bool = False,
) -> dict[str, Any]:
    if not s10_ok:
        return {
            "performed": False,
            "cleaned": [],
            "retained": [],
            "reason": "Session cleanup cannot occur before successful S10",
            "ok": True,
        }
    fail_ids = {
        str(item)
        for item in (fail_session_ids or [])
        if isinstance(item, str)
    }
    if target_session_ids is None:
        linked = {
            str(item)
            for item in ((task or {}).get("develop_session_ids") or [])
            if isinstance(item, str)
        }
    else:
        linked = {
            str(item)
            for item in (target_session_ids or [])
            if isinstance(item, str)
        }
    folder = root / SESSIONS_DIR
    cleaned: list[str] = []
    retained: list[str] = []
    blockers: list[str] = []
    needs_human = False
    if not folder.is_dir():
        return {
            "performed": True,
            "cleaned": cleaned,
            "retained": retained,
            "blockers": blockers,
            "ok": True,
            "needs_human": False,
        }
    for directory in sorted(folder.iterdir()):
        if not directory.is_dir():
            continue
        session_id = directory.name
        session_path = directory / "session.yaml"
        data: Any = None
        unreadable = False
        if session_path.is_file():
            try:
                data = read_yaml(session_path)
            except (OSError, ValueError, TypeError, UnicodeError):
                data = None
                unreadable = True
        linked_here = session_id in linked
        valid = (
            isinstance(data, dict)
            and not validate_develop_session(data, expected_id=session_id)
        )
        if linked_here and valid and data.get("status") == "SEALED":
            if data.get("task_id") != (task or {}).get("record_id"):
                blockers.append(
                    f"linked Session {session_id} has a different Task binding"
                )
                needs_human = True
            elif fail_all or session_id in fail_ids:
                blockers.append(
                    f"linked Session {session_id} cleanup failed: injected cleanup failure"
                )
                retained.append(session_id)
                continue
            else:
                try:
                    shutil.rmtree(directory)
                except OSError as exc:
                    blockers.append(
                        f"linked Session {session_id} cleanup failed: {exc}"
                    )
                    retained.append(session_id)
                    continue
                else:
                    cleaned.append(session_id)
                    continue
        elif linked_here and (not valid or unreadable):
            blockers.append(
                f"linked Session {session_id} is malformed; cleanup retained it"
            )
            needs_human = True
        retained.append(session_id)
    return {
        "performed": True,
        "cleaned": cleaned,
        "retained": retained,
        "blockers": blockers,
        "ok": not blockers,
        "needs_human": needs_human,
    }

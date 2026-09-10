"""Observational S3 skills.lock review authority. Does not edit the lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.currentness import evaluate_understanding_currentness
from scaffold_p5.host_state import inspect_lock, inspect_project
from scaffold_p5.io_util import file_digest
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.scm import tracked_project_paths
from scaffold_p8.models import EXECUTABLE_COMPAT

SKILLS_LOCK = ".scaffold/skills.lock"


INITIAL_ADOPTION_LOCK_CREATION = "initial_adoption_lock_creation"
ORDINARY_LOCK_CHANGE = "ordinary_lock_change"


def evaluate_skills_lock_review_authority(
    root: str | Path,
    *,
    real_diff: dict[str, Any],
    project: dict[str, Any] | None,
    preflight: Any = None,
) -> dict[str, Any]:
    """Classify whether a real Diff skills.lock change is lawful initial creation."""
    host = Path(root)
    paths = [
        str(item)
        for item in (real_diff.get("paths") or [])
        if isinstance(item, str) and item
    ]
    entries = [
        row
        for row in (real_diff.get("entries") or [])
        if isinstance(row, dict) and str(row.get("path") or "") == SKILLS_LOCK
    ]
    present = SKILLS_LOCK in paths or bool(entries)
    result: dict[str, Any] = {
        "kind": "none",
        "lawful": True,
        "blockers": [],
        "lock_in_diff": present,
        "change": "",
        "classification": "",
        "lock_digest": "",
        "understanding_currentness": "",
    }
    if not present:
        return result

    change = _lock_change(entries)
    result["change"] = change
    lock_path = host / SKILLS_LOCK
    if lock_path.is_file():
        result["lock_digest"] = file_digest(lock_path)

    if change == "deleted" or (not lock_path.is_file() and change in {"deleted", ""}):
        result["kind"] = ORDINARY_LOCK_CHANGE
        result["lawful"] = False
        result["classification"] = "lock_deleted"
        result["blockers"] = [
            "skills.lock deletion requires Understand compatibility review: "
            + SKILLS_LOCK
        ]
        return result

    tracked = set(tracked_project_paths(host))
    baseline_has_lock = SKILLS_LOCK in tracked
    initial_creation = (not baseline_has_lock) and change in {"untracked", "added"}
    if not initial_creation:
        result["kind"] = ORDINARY_LOCK_CHANGE
        result["lawful"] = False
        result["classification"] = "ordinary_lock_modification"
        result["blockers"] = [
            "core skills.lock change requires Understand compatibility review: "
            + SKILLS_LOCK
        ]
        return result

    result["kind"] = INITIAL_ADOPTION_LOCK_CREATION
    blockers: list[str] = []
    ownership = resolve_ownership((project or {}).get("ownership") or {}, SKILLS_LOCK)
    if ownership.status == "UNKNOWN":
        blockers.append("initial skills.lock ownership is UNKNOWN")
    elif ownership.status != "RESOLVED" or ownership.mode != "GENERATED":
        blockers.append(
            "initial skills.lock ownership must resolve GENERATED; "
            f"observed {ownership.status}/{ownership.mode or 'none'}"
        )

    lock_view = inspect_lock(lock_path)
    if not lock_view.complete_authoritative:
        blockers.append(
            "initial skills.lock is not complete_authoritative: "
            + "; ".join(lock_view.reasons or [lock_view.status])
        )

    project_view = inspect_project(host / ".scaffold/project.yaml")
    lifecycle = ""
    if project_view.data:
        lifecycle = str(project_view.data.get("lifecycle") or "")
    if lifecycle != "ACTIVE":
        blockers.append(
            "initial skills.lock review requires ACTIVE host lifecycle"
        )

    currentness = evaluate_understanding_currentness(host)
    result["understanding_currentness"] = str(currentness.get("currentness") or "")
    if currentness.get("currentness") != "CURRENT":
        if currentness.get("structural_changed"):
            blockers.append(
                "skills.lock digest does not match current Understand structural authority"
            )
        else:
            blockers.append("Understanding is not CURRENT for initial skills.lock creation")
    elif result["lock_digest"]:
        observed = currentness.get("observed") or {}
        bound = (currentness.get("snapshot") or {}).get("structural_digest")
        live = observed.get("structural_digest")
        if bound and live and bound != live:
            blockers.append(
                "skills.lock digest does not match current Understand structural authority"
            )

    compatibility = getattr(preflight, "compatibility", None) if preflight is not None else None
    allowed = bool(getattr(preflight, "allowed", False)) if preflight is not None else False
    if not allowed or compatibility not in EXECUTABLE_COMPAT:
        blockers.append(
            "initial skills.lock review requires executable Submit package compatibility "
            "(EXACT or COMPATIBLE)"
        )

    result["lawful"] = not blockers
    result["blockers"] = blockers
    result["classification"] = (
        "initial_adoption_lock_creation" if result["lawful"] else "initial_lock_unproven"
    )
    return result


def _lock_change(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return ""
    kinds = {
        str(row.get("change") or "")
        for row in entries
        if str(row.get("change") or "")
    }
    if "deleted" in kinds:
        return "deleted"
    if "modified" in kinds:
        return "modified"
    if "untracked" in kinds:
        return "untracked"
    if "added" in kinds:
        return "added"
    if "renamed" in kinds or "copied" in kinds or "type_changed" in kinds:
        return next(iter(sorted(kinds)))
    return next(iter(sorted(kinds))) if kinds else ""

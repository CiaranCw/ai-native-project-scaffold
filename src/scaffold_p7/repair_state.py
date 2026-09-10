"""Supporting Repair recovery state. Not a fourth canonical development record."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.lifecycle import evaluate_ready_for_review
from scaffold_p7.models import REPAIR_STATE_DIR
from scaffold_p7.tasks import resolve_task


def repair_state_path(root: Path, task_id: str) -> Path:
    return root / REPAIR_STATE_DIR / f"{task_id}.yaml"


def load_repair_state(root: Path, task_id: str) -> dict[str, Any] | None:
    path = repair_state_path(root, task_id)
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def persist_repair_state(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or "")
    if not task_id:
        raise ValueError("repair supporting state requires task_id")
    data = {
        "schema_version": "1",
        "kind": "repair_state",
        "record_type": "repair_state",
        "task_id": task_id,
        "status": str(payload.get("status") or "pending"),
        "target_stage_ids": list(payload.get("target_stage_ids") or []),
        "target_mapping": payload.get("target_mapping") or "explicit",
        "candidate_digest": payload.get("candidate_digest") or "",
        "consumed_task_revision": payload.get("consumed_task_revision"),
        "resulting_task_revision": payload.get("resulting_task_revision"),
        "session_id": payload.get("session_id") or "",
        "blockers": list(payload.get("blockers") or []),
        "evidence_refs": list(payload.get("evidence_refs") or []),
        "fail_ids": list(payload.get("fail_ids") or []),
        "report_id": payload.get("report_id") or "",
        "reason": payload.get("reason") or "",
        "updated_at": _iso_utc(),
    }
    path = repair_state_path(root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, data)
    return data


def consumed_repair_replay(
    root: Path,
    *,
    task: dict[str, Any],
    handoff: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Replay of an already-consumed Stage reopen must not duplicate authority."""
    if not isinstance(handoff, dict):
        return None
    task_id = str(task.get("record_id") or "")
    state = load_repair_state(root, task_id)
    if not isinstance(state, dict) or state.get("status") != "consumed":
        return None
    targets = [
        item
        for item in (handoff.get("target_stage_ids") or [])
        if isinstance(item, str) and item.strip()
    ]
    prior = [
        item
        for item in (state.get("target_stage_ids") or [])
        if isinstance(item, str) and item.strip()
    ]
    if not targets or targets != prior:
        return None
    if task.get("status") != "IN_PROGRESS":
        return None
    by_id = {
        str(row.get("stage_id") or ""): row
        for row in (task.get("stages") or [])
        if isinstance(row, dict)
    }
    for stage_id in targets:
        stage = by_id.get(stage_id)
        if not isinstance(stage, dict) or stage.get("status") != "IN_PROGRESS":
            return None
        decision = stage.get("completion_decision")
        if not isinstance(decision, dict) or decision.get("outcome") != "UNKNOWN":
            return None
    return dict(state)


def reconstruct_repair_view(root: Path, task_id: str) -> dict[str, Any]:
    """Fresh-process Repair recovery from Task Book + supporting runtime state."""
    resolved = resolve_task(root, task_id=task_id)
    state = load_repair_state(root, task_id)
    candidate = observe_candidate(root)
    task = resolved.task if resolved.ok else None
    stages: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    if isinstance(task, dict):
        for row in task.get("stages") or []:
            if not isinstance(row, dict):
                continue
            decision = row.get("completion_decision")
            stages.append(
                {
                    "stage_id": row.get("stage_id"),
                    "status": row.get("status"),
                    "completion_decision": decision,
                }
            )
            if isinstance(decision, dict) and (
                decision.get("outcome") == "UNKNOWN" or decision.get("supersedes")
            ):
                stale.append(
                    {
                        "kind": "stage_completion_decision",
                        "stage_id": row.get("stage_id"),
                        "outcome": decision.get("outcome"),
                        "supersedes": decision.get("supersedes"),
                    }
                )
        task_decision = task.get("task_completion_decision")
        if isinstance(task_decision, dict) and (
            task_decision.get("outcome") == "UNKNOWN" or task_decision.get("supersedes")
        ):
            stale.append(
                {
                    "kind": "task_completion_decision",
                    "outcome": task_decision.get("outcome"),
                    "supersedes": task_decision.get("supersedes"),
                }
            )
    ready_ok = False
    ready_reason = "Task Book is not reconstructable"
    if isinstance(task, dict) and candidate.usable:
        ready_ok, ready_reason = evaluate_ready_for_review(
            task,
            candidate_digest=candidate.digest,
            root=root,
        )
    status = (state or {}).get("status") if state else None
    next_action = _next_action(
        task=task,
        state=state,
        ready_ok=ready_ok,
    )
    return {
        "ok": bool(resolved.ok and task is not None),
        "task_id": task_id,
        "task_status": task.get("status") if isinstance(task, dict) else None,
        "task_revision": task.get("record_revision") if isinstance(task, dict) else None,
        "target_stage_ids": list((state or {}).get("target_stage_ids") or []),
        "target_mapping": (state or {}).get("target_mapping"),
        "reason": (state or {}).get("reason") or "",
        "blockers": list((state or {}).get("blockers") or []),
        "evidence_refs": list((state or {}).get("evidence_refs") or []),
        "fail_ids": list((state or {}).get("fail_ids") or []),
        "report_id": (state or {}).get("report_id") or "",
        "candidate_digest": candidate.digest if candidate.usable else (
            (state or {}).get("candidate_digest") or ""
        ),
        "consumed_task_revision": (state or {}).get("consumed_task_revision"),
        "session_id": (state or {}).get("session_id") or "",
        "repair_state_status": status,
        "stages": stages,
        "task_completion_decision": (
            task.get("task_completion_decision") if isinstance(task, dict) else None
        ),
        "stale_completion_authority": stale,
        "ready_possible": ready_ok,
        "ready_reason": ready_reason,
        "next": next_action,
        "blockers_from_task_resolution": list(resolved.blockers or []),
    }


def _next_action(
    *,
    task: dict[str, Any] | None,
    state: dict[str, Any] | None,
    ready_ok: bool,
) -> str:
    if ready_ok:
        return "Repair loop is complete; Task is READY_FOR_REVIEW"
    if not isinstance(task, dict):
        return "Task Book is not reconstructable from project-local truth"
    status = (state or {}).get("status")
    targets = list((state or {}).get("target_stage_ids") or [])
    if status == "pending" and not targets:
        return (
            "Test failure is recorded but target Stage mapping is unresolved; "
            "human clarification is required"
        )
    if task.get("status") == "IN_PROGRESS":
        return (
            "Complete reopened Stages against the current candidate, obtain "
            "current Test Evidence, then publish new SATISFIED Stage/Task "
            "Completion Decisions before READY_FOR_REVIEW"
        )
    if task.get("status") == "READY_FOR_REVIEW":
        return "READY_FOR_REVIEW is not currently reconstructable from completion authority"
    return "Inspect current Task Book and Repair supporting state"


def _iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

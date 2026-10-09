"""Supporting Repair recovery state. Not a fourth canonical development record."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.lifecycle import (
    decision_is_satisfied_current,
    evaluate_ready_for_review,
    stage_completion_decision_binding,
)
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


def _failure_episode(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(state.get("status") or ""),
        "fail_ids": list(state.get("fail_ids") or []),
        "report_id": state.get("report_id") or "",
        "candidate_digest": state.get("candidate_digest") or "",
        "session_id": state.get("session_id") or "",
        "target_stage_ids": list(state.get("target_stage_ids") or []),
        "resolved_by_report_id": state.get("resolved_by_report_id") or "",
        "resolved_by_session_id": state.get("resolved_by_session_id") or "",
        "resolved_candidate_digest": state.get("resolved_candidate_digest") or "",
    }


def _episodes_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        str(left.get("status") or "") == str(right.get("status") or "")
        and list(left.get("fail_ids") or []) == list(right.get("fail_ids") or [])
        and str(left.get("report_id") or "") == str(right.get("report_id") or "")
    )


def _retained_failure_history(
    existing: dict[str, Any] | None,
    payload: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Keep prior failure evidence when a later write omits ``failure_history``.

    An explicit history on the payload is stored as given. Otherwise the
    on-disk history is copied. A changed episode that already recorded
    fail ids, or a resolved episode, is appended once. Rewriting the same
    status, fail ids, and report id does not append.
    """
    if "failure_history" in payload:
        history = payload.get("failure_history")
        return list(history) if isinstance(history, list) else []
    if not isinstance(existing, dict):
        return None
    history = [
        dict(item)
        for item in (existing.get("failure_history") or [])
        if isinstance(item, dict)
    ]
    prior = _failure_episode(existing)
    incoming = {
        "status": str(payload.get("status") or "pending"),
        "fail_ids": list(payload.get("fail_ids") or []),
        "report_id": payload.get("report_id") or "",
    }
    changed = not _episodes_match(prior, incoming)
    evidence = bool(prior["fail_ids"]) or prior["status"] == "resolved" or bool(history)
    if changed and evidence and (not history or not _episodes_match(history[-1], prior)):
        history.append(prior)
    if not history:
        return None
    return history


def persist_repair_state(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(payload.get("task_id") or "")
    if not task_id:
        raise ValueError("repair supporting state requires task_id")
    existing = load_repair_state(root, task_id)
    retained_history = _retained_failure_history(existing, payload)
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
    if retained_history is not None:
        data["failure_history"] = retained_history
    for key in (
        "resolved_by_report_id",
        "resolved_by_session_id",
        "resolved_candidate_digest",
    ):
        if key in payload:
            data[key] = payload[key]
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
        "failure_history": list((state or {}).get("failure_history") or []),
        "resolved_by_report_id": (state or {}).get("resolved_by_report_id") or "",
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


def reconcile_pending_repair(
    root: Path,
    *,
    task: dict[str, Any],
    covering: dict[str, Any],
) -> dict[str, Any] | None:
    """Resolve pending Repair only when later same-task authority covers it.

    A PASS that is not TEST_COMPLETE, a different Task or Stage, or a
    candidate the covering execution does not currently bind leaves the
    pending record unchanged. Failure history is retained. A second call
    with the record already resolved does not append history.
    """
    if not isinstance(task, dict) or not isinstance(covering, dict):
        return None
    task_id = str(task.get("record_id") or "")
    if not task_id or str(covering.get("task_id") or "") != task_id:
        return None
    state = load_repair_state(root, task_id)
    if not isinstance(state, dict):
        return None
    if state.get("status") == "resolved":
        return state
    if state.get("status") != "pending":
        return None
    if covering.get("test_pass") is not True or covering.get("test_complete") is not True:
        return None
    candidate = observe_candidate(root)
    if not candidate.usable:
        return None
    live = candidate.digest
    if str(covering.get("candidate_digest") or "") != live:
        return None
    report_id = str(covering.get("report_id") or "")
    if not report_id or report_id == str(state.get("report_id") or ""):
        return None
    targets = [
        str(item)
        for item in (state.get("target_stage_ids") or [])
        if isinstance(item, str) and item.strip()
    ]
    if not targets:
        return None
    stages = [
        row for row in (task.get("stages") or []) if isinstance(row, dict)
    ]
    by_id: dict[str, dict[str, Any]] = {}
    for row in stages:
        stage_id = str(row.get("stage_id") or "")
        if not stage_id or stage_id in by_id:
            return None
        by_id[stage_id] = row
    for stage_id in targets:
        stage = by_id.get(stage_id)
        if stage is None:
            return None
        decision = stage.get("completion_decision")
        bound, _reason = stage_completion_decision_binding(
            decision, stage_id=stage_id, stages=stages
        )
        if not bound or not decision_is_satisfied_current(
            decision, live, root=root
        ):
            return None
    history = list(state.get("failure_history") or [])
    history.append(
        {
            "status": "pending",
            "fail_ids": list(state.get("fail_ids") or []),
            "report_id": state.get("report_id") or "",
            "candidate_digest": state.get("candidate_digest") or "",
            "session_id": state.get("session_id") or "",
            "target_stage_ids": list(targets),
        }
    )
    return persist_repair_state(
        root,
        {
            "task_id": task_id,
            "status": "resolved",
            "target_stage_ids": list(targets),
            "target_mapping": state.get("target_mapping") or "explicit",
            "candidate_digest": live,
            "consumed_task_revision": state.get("consumed_task_revision"),
            "resulting_task_revision": state.get("resulting_task_revision"),
            "session_id": state.get("session_id") or "",
            "blockers": list(state.get("blockers") or []),
            "evidence_refs": list(state.get("evidence_refs") or []),
            "fail_ids": list(state.get("fail_ids") or []),
            "report_id": state.get("report_id") or "",
            "reason": state.get("reason") or "",
            "failure_history": history,
            "resolved_by_report_id": report_id,
            "resolved_by_session_id": str(covering.get("session_id") or ""),
            "resolved_candidate_digest": live,
        },
    )


def _next_action(
    *,
    task: dict[str, Any] | None,
    state: dict[str, Any] | None,
    ready_ok: bool,
) -> str:
    status = (state or {}).get("status")
    if ready_ok and status == "pending":
        return (
            "READY completion is current but pending Repair is not covered "
            "by later authoritative execution of the same Task"
        )
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

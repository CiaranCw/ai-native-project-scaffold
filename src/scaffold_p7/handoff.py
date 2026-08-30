"""Bounded Develop ↔ Test handoff. Not chat history. Test remains standalone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p6.engine import TestEngine
from scaffold_p7.schemas import SESSION_ID_RE, TASK_ID_RE


def validate_repair_handoff(
    handoff: Any,
    *,
    task_id: str,
    candidate_digest: str,
) -> tuple[bool, str]:
    """Test→Develop repair must bind current Task + current candidate + failure."""
    if not isinstance(handoff, dict):
        return False, "repair requires bounded failure/blocker handoff context"
    kind = handoff.get("kind")
    if kind not in {"test_to_develop", "submit_to_develop", "repair_handoff"}:
        return False, "repair handoff kind is missing or unknown"
    bound_task = handoff.get("task_id")
    if bound_task in (None, ""):
        return False, "repair handoff is missing task binding"
    if not isinstance(bound_task, str) or not TASK_ID_RE.fullmatch(bound_task):
        return False, "repair handoff task binding is malformed"
    if bound_task != task_id:
        return False, "repair handoff is bound to a different Task Book"
    bound_candidate = handoff.get("candidate_digest")
    if bound_candidate in (None, ""):
        return False, "repair handoff is missing candidate binding"
    if not isinstance(bound_candidate, str) or not bound_candidate.strip():
        return False, "repair handoff candidate binding is malformed"
    if bound_candidate != candidate_digest:
        return False, (
            "repair handoff candidate does not match the current workspace "
            "candidate; stale failure context cannot authorize Repair"
        )
    if "session_id" in handoff:
        session_id = handoff.get("session_id")
        if session_id not in (None, "") and (
            not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id)
        ):
            return False, "repair handoff session identity is malformed"
    blockers = handoff.get("blockers")
    if blockers is not None:
        if not isinstance(blockers, list) or any(
            not isinstance(item, str) or not item.strip() for item in blockers
        ):
            return False, "repair handoff blockers are malformed"
    test_pass = handoff.get("test_pass")
    if test_pass is not None and not isinstance(test_pass, bool):
        return False, "repair handoff test_pass is malformed"
    if test_pass is True and not blockers:
        return False, "repair cannot start from TEST_PASS without a blocker"
    if test_pass is False or blockers:
        return True, "bounded task- and candidate-bound failure context accepted"
    return False, "repair handoff has no failure or blocker"


def build_develop_to_test(
    *,
    task: dict[str, Any],
    session_id: str,
    candidate_digest: str,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    requirement_ids: list[str] = []
    for item in task.get("final_tests") or []:
        if isinstance(item, dict) and item.get("requirement_id"):
            requirement_ids.append(str(item["requirement_id"]))
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict) and item.get("requirement_id"):
                requirement_ids.append(str(item["requirement_id"]))
    payload = {
        "kind": "develop_to_test",
        "task_id": task.get("record_id"),
        "session_id": session_id,
        "candidate_digest": candidate_digest,
        "mode": "scoped_verification",
        "test_requirement": {
            "requirement_ids": sorted(set(requirement_ids)),
            "selected": list(selected or []),
        },
    }
    return payload


def invoke_test(
    host: Path,
    payload: dict[str, Any],
    *,
    test_package: Path,
) -> Any:
    selected = list((payload.get("test_requirement") or {}).get("selected") or [])
    engine = TestEngine(host, test_package)
    opts: dict[str, Any] = {
        "task_book": payload.get("task_id"),
        "develop_session": payload.get("session_id"),
    }
    if selected:
        opts["selected"] = selected
    return engine.run("scoped_verification", **opts)


def build_test_to_develop(
    *,
    task_id: str,
    session_id: str,
    candidate_digest: str,
    test_result: Any,
) -> dict[str, Any]:
    extras = getattr(test_result, "extras", {}) or {}
    report = extras.get("report") if isinstance(extras, dict) else None
    evidence_refs = []
    if isinstance(report, dict):
        evidence_refs = list(report.get("evidence_refs") or [])
    elif extras.get("report_id"):
        evidence_refs = list(getattr(test_result, "evidence", []) or [])
    return {
        "kind": "test_to_develop",
        "task_id": task_id,
        "session_id": session_id,
        "candidate_digest": candidate_digest,
        "test_pass": bool(extras.get("test_pass")) if extras.get("test_pass") is not None else None,
        "test_complete": extras.get("test_complete"),
        "report_id": extras.get("report_id"),
        "outcome": getattr(test_result, "outcome", None),
        "blockers": list(getattr(test_result, "blockers", []) or []),
        "evidence_refs": evidence_refs,
        "mutations": getattr(test_result, "mutations", "none"),
    }


def build_submit_route(*, task_id: str, candidate_digest: str) -> dict[str, Any]:
    return {
        "kind": "develop_to_submit",
        "task_id": task_id,
        "candidate_digest": candidate_digest,
        "task_status": "READY_FOR_REVIEW",
        "submit_authorized": False,
    }

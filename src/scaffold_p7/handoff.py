"""Bounded Develop ↔ Test handoff. Not chat history. Test remains standalone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p7.lifecycle import automated_execution_profile_id
from scaffold_p7.schemas import SESSION_ID_RE, TASK_ID_RE


def validate_repair_handoff(
    handoff: Any,
    *,
    task_id: str,
    candidate_digest: str,
) -> tuple[bool, str]:
    """Test→Develop repair must bind current Task + current candidate + failure."""
    return _validate_repair_binding(
        handoff,
        task_id=task_id,
        candidate_digest=candidate_digest,
        allowed_kinds={"test_to_develop", "submit_to_develop", "repair_handoff"},
        require_targets=False,
        task=None,
    )


def validate_ready_repair_handoff(
    handoff: Any,
    *,
    task: dict[str, Any],
    candidate_digest: str,
) -> tuple[bool, str]:
    """READY repair requires a current Stage-targeted submit_to_develop handoff."""
    ok, reason = _validate_repair_binding(
        handoff,
        task_id=str(task.get("record_id") or ""),
        candidate_digest=candidate_digest,
        allowed_kinds={"submit_to_develop"},
        require_targets=True,
        task=task,
    )
    if not ok:
        return False, reason
    assert isinstance(handoff, dict)
    if _handoff_escalates(handoff):
        return False, (
            "repair handoff attempts Commit, Push, or Submit authorization "
            "and cannot escalate Develop permissions"
        )
    return True, "bounded Stage-targeted submit_to_develop repair accepted"


def _validate_repair_binding(
    handoff: Any,
    *,
    task_id: str,
    candidate_digest: str,
    allowed_kinds: set[str],
    require_targets: bool,
    task: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not isinstance(handoff, dict):
        return False, "repair requires bounded failure/blocker handoff context"
    kind = handoff.get("kind")
    if kind not in allowed_kinds:
        if require_targets:
            return False, "READY repair requires kind=submit_to_develop"
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
    if require_targets:
        targets = handoff.get("target_stage_ids")
        if not isinstance(targets, list) or not targets:
            return False, (
                "READY repair requires nonempty target_stage_ids; "
                "Develop does not guess repair Stages"
            )
        if any(not isinstance(item, str) or not item.strip() for item in targets):
            return False, "repair target_stage_ids are malformed"
        if task is None:
            return False, "READY repair requires current Task Book authority"
        by_id = {
            str(stage.get("stage_id")): stage
            for stage in (task.get("stages") or [])
            if isinstance(stage, dict) and stage.get("stage_id")
        }
        for target in targets:
            stage = by_id.get(target)
            if stage is None:
                return False, f"repair target Stage {target!r} does not exist"
            if stage.get("status") != "COMPLETE":
                return False, (
                    f"repair target Stage {target!r} is not legal to reopen "
                    "from COMPLETE"
                )
    if test_pass is True and not blockers:
        return False, "repair cannot start from TEST_PASS without a blocker"
    if require_targets and test_pass is False:
        if not isinstance(blockers, list) or not [
            item for item in blockers if isinstance(item, str) and item.strip()
        ]:
            return False, (
                "READY repair with non-pass verification requires nonempty "
                "blocker context"
            )
    if test_pass is False or blockers:
        return True, "bounded task- and candidate-bound failure context accepted"
    return False, "repair handoff has no failure or blocker"


def _handoff_escalates(handoff: dict[str, Any]) -> bool:
    for key in ("commit", "push", "submit_authorized"):
        if handoff.get(key) is True:
            return True
    capabilities = handoff.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    return any(capabilities.get(key) is True for key in ("commit", "push", "submit_authorized"))


def build_develop_to_test(
    *,
    task: dict[str, Any],
    session_id: str,
    candidate_digest: str,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    requirement_ids: list[str] = []
    requirement_bindings: list[dict[str, str]] = []
    bound_profiles: list[str] = []
    for item in _task_test_refs(task):
        requirement_id = str(item.get("requirement_id") or "")
        if requirement_id:
            requirement_ids.append(requirement_id)
        profile_id = automated_execution_profile_id(item)
        if requirement_id and profile_id:
            requirement_bindings.append(
                {"requirement_id": requirement_id, "profile_id": profile_id}
            )
            bound_profiles.append(profile_id)
    selected_ids = list(selected or bound_profiles)
    payload = {
        "kind": "develop_to_test",
        "task_id": task.get("record_id"),
        "session_id": session_id,
        "candidate_digest": candidate_digest,
        "mode": "scoped_verification",
        "test_requirement": {
            "requirement_ids": sorted(set(requirement_ids)),
            "requirement_bindings": requirement_bindings,
            "selected": selected_ids,
        },
        "scope": {
            "paths": list((task.get("scope") or {}).get("paths") or []),
            "modules": list((task.get("scope") or {}).get("modules") or []),
        },
    }
    return payload


def _task_test_refs(task: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in task.get("final_tests") or []:
        if isinstance(item, dict):
            refs.append(item)
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict):
                refs.append(item)
    return refs


def invoke_test(
    host: Path,
    payload: dict[str, Any],
    *,
    test_package: Path,
) -> Any:
    requirement = payload.get("test_requirement") or {}
    selected = list(requirement.get("selected") or [])
    if not selected:
        selected = [
            str(item.get("profile_id"))
            for item in (requirement.get("requirement_bindings") or [])
            if isinstance(item, dict) and item.get("profile_id")
        ]
    from scaffold_p6.engine import TestEngine
    from scaffold_p6.sav import reconstruct_sav_plan

    engine = TestEngine(host, test_package)
    opts: dict[str, Any] = {
        "task_book": payload.get("task_id"),
        "develop_session": payload.get("session_id"),
        "scope_paths": list((payload.get("scope") or {}).get("paths") or []),
        "scope_modules": list((payload.get("scope") or {}).get("modules") or []),
    }
    if selected:
        opts["selected"] = selected
    task_id = str(payload.get("task_id") or "").strip()
    requirement_ids = [
        str(item)
        for item in (requirement.get("requirement_ids") or [])
        if str(item).strip()
    ]
    if not requirement_ids:
        requirement_ids = [
            str(item.get("requirement_id") or "").strip()
            for item in (requirement.get("requirement_bindings") or [])
            if isinstance(item, dict) and str(item.get("requirement_id") or "").strip()
        ]
    for requirement_id in requirement_ids:
        if not task_id:
            break
        reconstructed = reconstruct_sav_plan(
            host, task_id=task_id, requirement_id=requirement_id
        )
        if reconstructed.get("ok"):
            opts["task_id"] = task_id
            opts["requirement_id"] = requirement_id
            break
    return engine.run("scoped_verification", **opts)


def consume_published_test_report(
    host: Path,
    *,
    report_id: str,
    test_package: Path,
    task: dict[str, Any] | None = None,
) -> Any:
    from scaffold_p6.engine import TestEngine
    from scaffold_p6.published import (
        consume_published_report,
        published_report_skill_result,
    )

    loaded = consume_published_report(host, report_id, task=task)
    engine = TestEngine(host, test_package)
    return published_report_skill_result(
        loaded, skill_version=engine.skill_version or ""
    )


def build_test_to_develop(
    *,
    task_id: str,
    session_id: str,
    candidate_digest: str,
    test_result: Any,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extras = getattr(test_result, "extras", {}) or {}
    report = extras.get("report") if isinstance(extras, dict) else None
    evidence_refs = []
    if isinstance(report, dict):
        evidence_refs = list(report.get("evidence_refs") or [])
    elif extras.get("report_id"):
        evidence_refs = list(getattr(test_result, "evidence", []) or [])
    payload = {
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
    from scaffold_p7.repair_targets import attach_test_failure_targets

    if payload.get("test_pass") is False:
        payload = attach_test_failure_targets(
            payload, task=task, test_result=test_result
        )
    return payload


def build_submit_route(*, task_id: str, candidate_digest: str) -> dict[str, Any]:
    return {
        "kind": "develop_to_submit",
        "task_id": task_id,
        "candidate_digest": candidate_digest,
        "task_status": "READY_FOR_REVIEW",
        "submit_authorized": False,
    }

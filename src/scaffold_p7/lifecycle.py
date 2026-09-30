"""FA2-FND-002 Stage/Task completion decisions. P7-owned; P6 owns Evidence."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scaffold_p5.io_util import read_yaml
from scaffold_p7.models import SESSIONS_DIR

if TYPE_CHECKING:
    from scaffold_p6.engine import TestEngine


DECISION_OUTCOMES = ("SATISFIED", "UNSATISFIED", "UNKNOWN")
EVIDENCE_BASIS_KINDS = frozenset(
    {"test_evidence", "ci_evidence", "external_evidence", "human_observation"}
)
UNCITED_HUMAN_KINDS = frozenset(
    {"human_observation", "human", "chat", "user_statement", "session_memory"}
)
FORBIDDEN_BASIS_KINDS = frozenset(
    {"chat", "user_statement", "session_memory", "raw_report"}
)
P6_RESULT_TO_OBSERVED = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "NOT_RUN": "NOT_EXECUTED",
    "BLOCKED": "UNKNOWN",
}


def task_structurally_complete(task: dict[str, Any]) -> bool:
    stages = task.get("stages") or []
    if not stages:
        return False
    return all(
        isinstance(stage, dict) and stage.get("status") == "COMPLETE"
        for stage in stages
    )


def evaluate_ready_for_review(
    task: dict[str, Any],
    *,
    candidate_digest: str | None,
    root: Path | None,
) -> tuple[bool, str]:
    """Constitution §6 / Records §11 READY gates. Fail-closed without currentness."""
    if not isinstance(candidate_digest, str) or not candidate_digest.strip():
        return False, "READY_FOR_REVIEW requires the actual current candidate"
    if root is None:
        return False, "READY_FOR_REVIEW requires current repository/Evidence authority"
    if not task_structurally_complete(task):
        return False, "TASK_COMPLETE does not hold; READY_FOR_REVIEW is blocked"
    stages = task.get("stages") or []
    if not stages:
        return False, "TASK_COMPLETE does not hold; READY_FOR_REVIEW is blocked"
    for stage in stages:
        if not isinstance(stage, dict):
            return False, "Stage authority is malformed"
        decision = stage.get("completion_decision")
        bound, bound_reason = stage_completion_decision_binding(
            decision,
            stage_id=str(stage.get("stage_id") or ""),
            stages=stages,
        )
        if not bound:
            return False, bound_reason
        if not decision_is_satisfied_current(
            decision, candidate_digest, root=root
        ):
            return False, (
                "Stage Completion Decision is not SATISFIED and current "
                "for the actual candidate"
            )
        tests = evaluate_required_tests(
            stage.get("required_tests") or [],
            root=root,
            candidate_digest=candidate_digest,
        )
        if not tests["ok"]:
            return False, tests["reason"]
    finals = evaluate_required_tests(
        task.get("final_tests") or [],
        root=root,
        candidate_digest=candidate_digest,
    )
    if not finals["ok"]:
        return False, (
            "task-level final required tests do not satisfy defined acceptance"
            if finals["reason"]
            else "task-level final required tests do not satisfy defined acceptance"
        )
    if not isinstance(task.get("acceptance"), str) or not str(task["acceptance"]).strip():
        return False, "declared Task-level acceptance is UNKNOWN"
    task_decision = task.get("task_completion_decision")
    if not decision_is_satisfied_current(
        task_decision, candidate_digest, root=root
    ):
        return False, (
            "Task Completion Decision is not SATISFIED and current "
            "for the actual candidate"
        )
    if cited_evidence_stale(task, root=root, candidate_digest=candidate_digest):
        return False, "completion decision Evidence is not current for the actual candidate"
    return True, "READY_FOR_REVIEW gates hold"


def prepare_lifecycle(
    task: dict[str, Any],
    *,
    root: Path,
    candidate_digest: str,
    test_result: Any = None,
    stage_completion_decision: Any = None,
    task_completion_decision: Any = None,
    stage_completion_decisions: Any = None,
    request_stage_complete: bool = False,
    revalidate_complete_stages: bool = False,
    request_ready_for_review: bool = False,
) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Compose in-memory candidate-bound completion mutations. Does not publish."""
    updated = deepcopy(task)
    extras: dict[str, Any] = {
        "stage_completion_attempted": False,
        "revalidation_attempted": False,
        "evidence_bound": False,
    }
    updated = bind_published_evidence(updated, root=root, test_result=test_result)
    if updated != task:
        extras["evidence_bound"] = True

    batch_decisions = _normalized_batch_decisions(stage_completion_decisions)
    if batch_decisions is not None:
        extras["stage_completion_batch_size"] = len(batch_decisions)
        batch_error = _batch_stage_decisions_error(
            batch_decisions,
            task=updated,
            existing_stage_completion_decision=stage_completion_decision,
        )
        if batch_error:
            extras["stage_completion_rejected"] = True
            return updated, [batch_error], extras

    apply_complete = bool(
        request_stage_complete
        or stage_completion_decision
        or batch_decisions
    )
    revalidate = bool(revalidate_complete_stages or request_ready_for_review)
    extras["stage_completion_attempted"] = apply_complete
    extras["revalidation_attempted"] = revalidate

    if stage_completion_decision is not None:
        authority_error = _stage_completion_authority_error(
            stage_completion_decision, updated
        )
        if authority_error:
            extras["stage_completion_rejected"] = True
            return updated, [authority_error], extras

    stages = []
    for stage in updated.get("stages") or []:
        if not isinstance(stage, dict):
            stages.append(stage)
            continue
        row = dict(stage)
        status = row.get("status")
        if apply_complete and status == "IN_PROGRESS":
            stage_spec = _stage_spec_for_stage(
                stage_completion_decision,
                batch_decisions,
                row,
            )
            if stage_spec is not None or (
                stage_completion_decision is None and not batch_decisions
            ):
                row = apply_stage_decision(
                    row,
                    spec=stage_spec,
                    candidate_digest=candidate_digest,
                    root=root,
                )
            row = maybe_complete_stage(row, root=root, candidate_digest=candidate_digest)
        elif revalidate and status == "COMPLETE":
            revalidate_spec = _stage_spec_for_stage(
                stage_completion_decision,
                batch_decisions,
                row,
            )
            row = revalidate_complete_stage(
                row,
                spec=revalidate_spec,
                candidate_digest=candidate_digest,
                root=root,
            )
        stages.append(row)
    updated["stages"] = stages

    if task_completion_decision is not None:
        updated["task_completion_decision"] = normalize_task_decision(
            task_completion_decision,
            candidate_digest=candidate_digest,
            prior=task.get("task_completion_decision"),
            root=root,
            required_tests=updated.get("final_tests"),
        )
    extras["task_complete"] = task_structurally_complete(updated)
    return updated, [], extras


def apply_ready_repair_reopen(
    task: dict[str, Any],
    *,
    target_stage_ids: list[str],
    candidate_digest: str,
) -> dict[str, Any]:
    """READY→IN_PROGRESS and target COMPLETE→IN_PROGRESS with UNKNOWN authority."""
    updated = deepcopy(task)
    updated["status"] = "IN_PROGRESS"
    targets = set(target_stage_ids)
    stages = []
    for stage in updated.get("stages") or []:
        if not isinstance(stage, dict):
            stages.append(stage)
            continue
        row = dict(stage)
        stage_id = str(row.get("stage_id") or "")
        if stage_id in targets:
            prior = row.get("completion_decision")
            row["status"] = "IN_PROGRESS"
            row["completion_decision"] = repair_unknown_stage_decision(
                stage_id=stage_id,
                candidate_digest=candidate_digest,
                prior=prior if isinstance(prior, dict) else None,
            )
        stages.append(row)
    updated["stages"] = stages
    prior_task = updated.get("task_completion_decision")
    updated["task_completion_decision"] = repair_unknown_task_decision(
        candidate_digest=candidate_digest,
        prior=prior_task if isinstance(prior_task, dict) else None,
    )
    return updated


def lifecycle_progressed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before.get("status") != after.get("status"):
        return True
    if before.get("task_completion_decision") != after.get("task_completion_decision"):
        return True
    return (before.get("stages") or []) != (after.get("stages") or [])


def _candidate_digest_current(
    root: Path,
    stored_digest: str,
    live_digest: str,
    *,
    stored_generation: str | None = None,
) -> bool:
    from scaffold_p6.projection import digest_is_current

    return digest_is_current(
        root,
        stored_digest,
        live_digest,
        stored_generation=stored_generation,
    )


def decision_is_satisfied_current(
    decision: Any,
    candidate_digest: str,
    *,
    root: Path | None = None,
) -> bool:
    if not isinstance(decision, dict):
        return False
    if decision.get("outcome") != "SATISFIED":
        return False
    digest = decision.get("candidate_digest")
    if not isinstance(digest, str) or not digest:
        return False
    generation = decision.get("projection_generation")
    stored_generation = generation if isinstance(generation, str) else None
    if root is None:
        return digest == candidate_digest
    from scaffold_p6.projection import digest_is_current

    return digest_is_current(
        root,
        digest,
        candidate_digest,
        stored_generation=stored_generation,
    )


def stage_completion_decision_binding(
    decision: Any,
    *,
    stage_id: str,
    stages: Any = None,
) -> tuple[bool, str]:
    """Usable Stage Completion Decision must bind exactly one existing Stage."""
    if not isinstance(decision, dict):
        return False, "Stage Completion Decision is malformed"
    target = decision.get("stage_id")
    if not isinstance(target, str) or not target.strip():
        return False, (
            "Stage Completion Decision is unscoped; "
            "it must bind exactly one stage_id"
        )
    target = target.strip()
    if not isinstance(stage_id, str) or not stage_id.strip() or target != stage_id.strip():
        return False, (
            "Stage Completion Decision does not bind the Stage being evaluated"
        )
    if stages is not None:
        matches = [
            str(row.get("stage_id") or "")
            for row in (stages or [])
            if isinstance(row, dict) and str(row.get("stage_id") or "") == target
        ]
        if not matches:
            return False, (
                f"Stage Completion Decision targets nonexistent Stage {target!r}"
            )
        if len(matches) != 1:
            return False, (
                "Stage Completion Decision stage_id is ambiguous; "
                "duplicate Stage identities exist"
            )
    return True, ""


def evaluate_required_tests(
    refs: Any,
    *,
    root: Path,
    candidate_digest: str,
) -> dict[str, Any]:
    if refs is None:
        refs = []
    if not isinstance(refs, list):
        return {"ok": False, "reason": "required test references are malformed", "failed": True}
    if not refs:
        return {"ok": True, "reason": "", "failed": False}
    engine = _p6_engine(root)
    for item in refs:
        if not isinstance(item, dict) or not str(item.get("requirement_id") or "").strip():
            return {
                "ok": False,
                "reason": "required test reference is malformed",
                "failed": False,
            }
        judged = _judge_requirement(engine, item, candidate_digest=candidate_digest)
        if judged["state"] == "fail":
            return {
                "ok": False,
                "reason": (
                    "required Stage or Task Test FAIL cannot support completion"
                ),
                "failed": True,
            }
        if judged["state"] != "pass":
            return {
                "ok": False,
                "reason": judged["reason"],
                "failed": False,
            }
    return {"ok": True, "reason": "", "failed": False}


def bind_published_evidence(
    task: dict[str, Any],
    *,
    root: Path,
    test_result: Any,
) -> dict[str, Any]:
    extras = getattr(test_result, "extras", None)
    if not isinstance(extras, dict):
        return task
    report_id = extras.get("report_id")
    if not isinstance(report_id, str) or not report_id.strip():
        return task
    engine = _p6_engine(root)
    locators = [
        str(ref.get("locator"))
        for ref in engine.build_evidence_refs(report_id)
        if isinstance(ref, dict) and ref.get("locator")
    ]
    if not locators:
        return task
    by_profile: dict[str, dict[str, Any]] = {}
    for locator in locators:
        if not _portable_locator(locator):
            continue
        resolved, _issues = engine.resolve_evidence(locator)
        if not isinstance(resolved, dict):
            continue
        if not engine.report_usable_for_current(resolved.get("report") or {}):
            continue
        profile_id = resolved_producer_profile_id(resolved)
        if not profile_id:
            continue
        by_profile[profile_id] = {
            "locator": locator,
            "observed": P6_RESULT_TO_OBSERVED.get(str(resolved.get("result") or "")),
        }
    if not by_profile:
        return task
    updated = deepcopy(task)
    updated["stages"] = [
        _bind_refs_on_stage(stage, by_profile)
        if isinstance(stage, dict)
        else stage
        for stage in (updated.get("stages") or [])
    ]
    updated["final_tests"] = _bind_refs(updated.get("final_tests") or [], by_profile)
    return updated


def apply_stage_decision(
    stage: dict[str, Any],
    *,
    spec: Any,
    candidate_digest: str,
    root: Path,
) -> dict[str, Any]:
    row = dict(stage)
    stage_id = str(row.get("stage_id") or "")
    prior = row.get("completion_decision") if isinstance(row.get("completion_decision"), dict) else None
    if spec is None:
        if not isinstance(prior, dict):
            row["completion_decision"] = unknown_stage_decision(
                stage_id=stage_id,
                candidate_digest=candidate_digest,
                rationale="Stage acceptance cannot be established from current authoritative facts.",
                prior=None,
            )
        return row
    row["completion_decision"] = normalize_stage_decision(
        spec,
        stage_id=stage_id,
        candidate_digest=candidate_digest,
        prior=prior,
        root=root,
        required_tests=row.get("required_tests") or [],
    )
    return row


def maybe_complete_stage(
    stage: dict[str, Any],
    *,
    root: Path,
    candidate_digest: str,
) -> dict[str, Any]:
    row = dict(stage)
    if row.get("status") != "IN_PROGRESS":
        return row
    tests = evaluate_required_tests(
        row.get("required_tests") or [],
        root=root,
        candidate_digest=candidate_digest,
    )
    decision = row.get("completion_decision")
    bound, _reason = stage_completion_decision_binding(
        decision,
        stage_id=str(row.get("stage_id") or ""),
    )
    if (
        bound
        and decision_is_satisfied_current(decision, candidate_digest, root=root)
        and tests["ok"]
        and not cited_decision_evidence_stale(decision, root=root, candidate_digest=candidate_digest)
    ):
        row["status"] = "COMPLETE"
    return row


def revalidate_complete_stage(
    stage: dict[str, Any],
    *,
    spec: Any,
    candidate_digest: str,
    root: Path,
) -> dict[str, Any]:
    row = dict(stage)
    stage_id = str(row.get("stage_id") or "")
    prior = row.get("completion_decision") if isinstance(row.get("completion_decision"), dict) else None
    tests = evaluate_required_tests(
        row.get("required_tests") or [],
        root=root,
        candidate_digest=candidate_digest,
    )
    if spec is not None:
        decision = normalize_stage_decision(
            spec,
            stage_id=stage_id,
            candidate_digest=candidate_digest,
            prior=prior,
            root=root,
            required_tests=row.get("required_tests") or [],
        )
    elif decision_is_satisfied_current(prior, candidate_digest, root=root) and tests["ok"]:
        decision = prior
    else:
        decision = unknown_stage_decision(
            stage_id=stage_id,
            candidate_digest=candidate_digest,
            rationale=(
                "Complete-Stage revalidation could not re-establish SATISFIED "
                "for the actual candidate."
            ),
            prior=prior,
        )
    row["completion_decision"] = decision
    bound, _reason = stage_completion_decision_binding(
        decision,
        stage_id=stage_id,
    )
    if (
        bound
        and decision_is_satisfied_current(decision, candidate_digest, root=root)
        and tests["ok"]
        and not cited_decision_evidence_stale(decision, root=root, candidate_digest=candidate_digest)
    ):
        row["status"] = "COMPLETE"
        return row
    row["status"] = "IN_PROGRESS"
    return row


def normalize_stage_decision(
    spec: Any,
    *,
    stage_id: str,
    candidate_digest: str,
    prior: dict[str, Any] | None,
    root: Path,
    required_tests: Any,
) -> dict[str, Any]:
    base = _copy_spec(spec)
    requested = str(base.get("outcome") or "UNKNOWN")
    if requested not in DECISION_OUTCOMES:
        requested = "UNKNOWN"
    supplied_digest = base.get("candidate_digest")
    stamp = candidate_digest
    keep_stale = (
        isinstance(supplied_digest, str)
        and supplied_digest.strip()
        and supplied_digest != candidate_digest
    )
    if keep_stale:
        stamp = supplied_digest
    basis = _normalized_basis(
        base.get("basis"),
        required_tests=required_tests,
        root=root,
        candidate_digest=candidate_digest,
    )
    rationale = str(base.get("rationale") or "").strip()
    if not rationale:
        rationale = "Stage Completion Decision recorded from current authoritative facts."
    outcome = requested
    if outcome == "SATISFIED" and not keep_stale:
        outcome = _satisfied_or_unknown(
            basis,
            rationale=rationale,
            root=root,
            candidate_digest=stamp,
        )
    if outcome != "SATISFIED":
        basis = [
            item
            for item in basis
            if str(item.get("kind") or "") not in FORBIDDEN_BASIS_KINDS
        ]
    if not basis:
        basis = [
            {
                "kind": "task_fact",
                "summary": "No reconstructable authoritative basis was supplied.",
            }
        ]
        if outcome == "SATISFIED" and not keep_stale:
            outcome = "UNKNOWN"
    decision = {
        "stage_id": stage_id,
        "candidate_digest": stamp,
        "outcome": outcome,
        "basis": basis,
        "rationale": rationale,
    }
    if prior and isinstance(prior, dict) and prior.get("candidate_digest") != stamp:
        decision["supersedes"] = _supersedes_summary(prior)
    elif isinstance(base.get("supersedes"), dict):
        decision["supersedes"] = _supersedes_summary(base["supersedes"])
    return decision


def normalize_task_decision(
    spec: Any,
    *,
    candidate_digest: str,
    prior: Any,
    root: Path,
    required_tests: Any = None,
) -> dict[str, Any]:
    base = _copy_spec(spec)
    requested = str(base.get("outcome") or "UNKNOWN")
    if requested not in DECISION_OUTCOMES:
        requested = "UNKNOWN"
    supplied_digest = base.get("candidate_digest")
    stamp = candidate_digest
    outcome = requested
    if isinstance(supplied_digest, str) and supplied_digest.strip():
        if supplied_digest != candidate_digest:
            decision = {
                "candidate_digest": supplied_digest,
                "outcome": requested,
                "basis": _normalized_basis(
                    base.get("basis"),
                    required_tests=required_tests,
                    root=root,
                    candidate_digest=candidate_digest,
                ),
                "rationale": str(base.get("rationale") or "").strip()
                or "Task Completion Decision recorded from supplied facts.",
            }
            if prior and isinstance(prior, dict):
                decision["supersedes"] = _supersedes_summary(prior)
            return decision
        stamp = supplied_digest
    basis = _normalized_basis(
        base.get("basis"),
        required_tests=required_tests,
        root=root,
        candidate_digest=candidate_digest,
    )
    rationale = str(base.get("rationale") or "").strip() or (
        "Task Completion Decision recorded from current authoritative facts."
    )
    if outcome == "SATISFIED":
        outcome = _satisfied_or_unknown(
            basis,
            rationale=rationale,
            root=root,
            candidate_digest=stamp,
        )
    if not basis:
        basis = [
            {
                "kind": "task_fact",
                "summary": "No reconstructable authoritative basis was supplied.",
            }
        ]
        if outcome == "SATISFIED":
            outcome = "UNKNOWN"
    decision = {
        "candidate_digest": stamp,
        "outcome": outcome,
        "basis": basis,
        "rationale": rationale,
    }
    if prior and isinstance(prior, dict) and prior.get("candidate_digest") != stamp:
        decision["supersedes"] = _supersedes_summary(prior)
    elif isinstance(base.get("supersedes"), dict):
        decision["supersedes"] = _supersedes_summary(base["supersedes"])
    return decision


def unknown_stage_decision(
    *,
    stage_id: str,
    candidate_digest: str,
    rationale: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = {
        "stage_id": stage_id,
        "candidate_digest": candidate_digest,
        "outcome": "UNKNOWN",
        "basis": [
            {
                "kind": "task_fact",
                "summary": "Authoritative facts do not currently establish Stage acceptance.",
            }
        ],
        "rationale": rationale,
    }
    if prior:
        decision["supersedes"] = _supersedes_summary(prior)
    return decision


def repair_unknown_stage_decision(
    *,
    stage_id: str,
    candidate_digest: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = {
        "stage_id": stage_id,
        "candidate_digest": candidate_digest,
        "outcome": "UNKNOWN",
        "basis": [
            {
                "kind": "task_fact",
                "summary": (
                    "Stage-targeted submit_to_develop repair reopened this Stage; "
                    "prior completion authority is no longer current."
                ),
            }
        ],
        "rationale": (
            "Repair reopen invalidates current Stage completion authority until "
            "the Stage is re-evaluated on the repair candidate."
        ),
    }
    if prior:
        decision["supersedes"] = _supersedes_summary(prior)
    return decision


def repair_unknown_task_decision(
    *,
    candidate_digest: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = {
        "candidate_digest": candidate_digest,
        "outcome": "UNKNOWN",
        "basis": [
            {
                "kind": "task_fact",
                "summary": (
                    "Stage-targeted submit_to_develop repair reopened the Task; "
                    "prior Task acceptance cannot immediately restore READY."
                ),
            }
        ],
        "rationale": (
            "Repair reopen invalidates current Task Completion Decision until "
            "acceptance is re-established for the repair candidate."
        ),
    }
    if prior:
        decision["supersedes"] = _supersedes_summary(prior)
    return decision


def cited_evidence_stale(
    task: dict[str, Any],
    *,
    root: Path,
    candidate_digest: str,
) -> bool:
    if cited_decision_evidence_stale(
        task.get("task_completion_decision"),
        root=root,
        candidate_digest=candidate_digest,
    ):
        return True
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        if cited_decision_evidence_stale(
            stage.get("completion_decision"),
            root=root,
            candidate_digest=candidate_digest,
        ):
            return True
    return False


def cited_decision_evidence_stale(
    decision: Any,
    *,
    root: Path,
    candidate_digest: str,
) -> bool:
    if not isinstance(decision, dict):
        return False
    engine = _p6_engine(root)
    for item in decision.get("basis") or []:
        if not isinstance(item, dict):
            continue
        ref = item.get("evidence_ref")
        if not isinstance(ref, dict):
            continue
        locator = ref.get("locator")
        if not isinstance(locator, str) or not locator:
            return True
        if not _portable_locator(locator):
            return True
        resolved, _issues = engine.resolve_evidence(locator)
        if resolved is None:
            return True
        report = resolved.get("report")
        if not isinstance(report, dict) or not engine.report_usable_for_current(report):
            return True
        bound = resolved.get("candidate_digest")
        if isinstance(bound, str) and bound and not _candidate_digest_current(
            root, bound, candidate_digest
        ):
            return True
    return False


def persist_ready_if_legal(
    task: dict[str, Any],
    *,
    candidate_digest: str,
    root: Path,
) -> tuple[dict[str, Any], bool, str]:
    ok, reason = evaluate_ready_for_review(
        task, candidate_digest=candidate_digest, root=root
    )
    if not ok:
        return task, False, reason
    updated = dict(task)
    updated["status"] = "READY_FOR_REVIEW"
    return updated, True, reason


def decision_is_satisfied_candidate_stale(decision: Any, candidate_digest: str) -> bool:
    if not isinstance(decision, dict):
        return False
    if decision.get("outcome") != "SATISFIED":
        return False
    digest = decision.get("candidate_digest")
    return (
        isinstance(digest, str)
        and bool(digest.strip())
        and digest != candidate_digest
    )


def apply_ready_authority_refresh(
    task: dict[str, Any],
    *,
    root: Path,
    candidate_digest: str,
    test_result: Any = None,
) -> tuple[dict[str, Any], list[str]]:
    """Replace candidate-stale SATISFIED decisions. Does not reopen READY/COMPLETE."""
    if not isinstance(candidate_digest, str) or not candidate_digest.strip():
        return task, ["READY authority refresh requires the actual current candidate"]
    if task.get("status") != "READY_FOR_REVIEW":
        return task, ["READY authority refresh requires Task status READY_FOR_REVIEW"]
    stages = task.get("stages") or []
    if not stages:
        return task, ["READY authority refresh requires COMPLETE Stages"]
    updated = bind_published_evidence(
        deepcopy(task), root=root, test_result=test_result
    )
    blockers: list[str] = []
    stale_found = False
    refreshed_stages: list[Any] = []
    for stage in updated.get("stages") or []:
        if not isinstance(stage, dict):
            blockers.append("Stage authority is malformed")
            continue
        if stage.get("status") != "COMPLETE":
            blockers.append(
                "READY authority refresh requires every Stage to remain COMPLETE"
            )
            refreshed_stages.append(stage)
            continue
        stage_id = str(stage.get("stage_id") or "")
        prior = stage.get("completion_decision")
        bound, bound_reason = stage_completion_decision_binding(
            prior, stage_id=stage_id, stages=updated.get("stages") or []
        )
        if not bound:
            blockers.append(bound_reason)
            refreshed_stages.append(stage)
            continue
        if not isinstance(prior, dict) or prior.get("outcome") != "SATISFIED":
            blockers.append(
                "READY authority refresh requires prior Stage Completion "
                "Decisions to be structurally valid SATISFIED decisions"
            )
            refreshed_stages.append(stage)
            continue
        prior_digest = prior.get("candidate_digest")
        if not isinstance(prior_digest, str) or not prior_digest.strip():
            blockers.append(
                "prior Stage Completion Decision candidate binding is missing"
            )
            refreshed_stages.append(stage)
            continue
        if not _candidate_digest_current(root, prior_digest, candidate_digest):
            stale_found = True
        tests = evaluate_required_tests(
            stage.get("required_tests") or [],
            root=root,
            candidate_digest=candidate_digest,
        )
        if not tests["ok"]:
            blockers.append(tests["reason"] or "required Stage tests are not current")
            refreshed_stages.append(stage)
            continue
        row = dict(stage)
        row["status"] = "COMPLETE"
        locators = _unique_locators(row.get("required_tests"))
        if locators:
            stage_basis = [
                {
                    "kind": "test_evidence",
                    "summary": "Required verification Evidence is cited by portable P6 locator.",
                    "evidence_ref": {"locator": locators[0]},
                }
            ]
        else:
            stage_basis = [
                {
                    "kind": "task_fact",
                    "summary": (
                        "Stage acceptance remains reconstructable and SATISFIED "
                        "for the current candidate."
                    ),
                }
            ]
        row["completion_decision"] = normalize_stage_decision(
            {
                "outcome": "SATISFIED",
                "stage_id": stage_id,
                "rationale": (
                    "Stage acceptance remains SATISFIED; completion authority "
                    "was refreshed to the current candidate from published P6 Evidence."
                ),
                "basis": stage_basis,
            },
            stage_id=stage_id,
            candidate_digest=candidate_digest,
            prior=prior,
            root=root,
            required_tests=row.get("required_tests") or [],
        )
        if not decision_is_satisfied_current(
            row["completion_decision"], candidate_digest, root=root
        ):
            blockers.append(
                "READY authority refresh could not establish a current SATISFIED "
                f"Stage Completion Decision for {stage_id}"
            )
        refreshed_stages.append(row)
    updated["stages"] = refreshed_stages
    prior_task = updated.get("task_completion_decision")
    if not isinstance(prior_task, dict):
        blockers.append("Task Completion Decision is malformed")
    elif prior_task.get("outcome") != "SATISFIED":
        blockers.append(
            "READY authority refresh requires a structurally valid SATISFIED "
            "Task Completion Decision stale only by candidate binding"
        )
    else:
        prior_digest = prior_task.get("candidate_digest")
        if not isinstance(prior_digest, str) or not prior_digest.strip():
            blockers.append("prior Task Completion Decision candidate binding is missing")
        else:
            if not _candidate_digest_current(root, prior_digest, candidate_digest):
                stale_found = True
            locators = _unique_locators(updated.get("final_tests"))
            if locators:
                task_basis = [
                    {
                        "kind": "test_evidence",
                        "summary": "Required verification Evidence is cited by portable P6 locator.",
                        "evidence_ref": {"locator": locators[0]},
                    }
                ]
            else:
                task_basis = [
                    {
                        "kind": "task_fact",
                        "summary": (
                            "Required Stages remain COMPLETE with current SATISFIED "
                            "decisions and Task-level acceptance is satisfied."
                        ),
                    }
                ]
            updated["task_completion_decision"] = normalize_task_decision(
                {
                    "outcome": "SATISFIED",
                    "rationale": (
                        "Task acceptance remains SATISFIED; completion authority "
                        "was refreshed to the current candidate from published P6 Evidence."
                    ),
                    "basis": task_basis,
                },
                candidate_digest=candidate_digest,
                prior=prior_task,
                root=root,
                required_tests=updated.get("final_tests"),
            )
            if not decision_is_satisfied_current(
                updated["task_completion_decision"], candidate_digest, root=root
            ):
                blockers.append(
                    "READY authority refresh could not establish a current "
                    "SATISFIED Task Completion Decision"
                )
    finals = evaluate_required_tests(
        updated.get("final_tests") or [],
        root=root,
        candidate_digest=candidate_digest,
    )
    if not finals["ok"]:
        blockers.append(
            finals["reason"]
            or "task-level final required tests do not satisfy defined acceptance"
        )
    if not stale_found and not blockers:
        blockers.append(
            "READY authority refresh requires candidate-stale SATISFIED "
            "completion decisions"
        )
    updated["status"] = "READY_FOR_REVIEW"
    if cited_evidence_stale(updated, root=root, candidate_digest=candidate_digest):
        blockers.append(
            "refreshed completion decision Evidence is not current for the actual candidate"
        )
    return updated, blockers


def _satisfied_or_unknown(
    basis: list[dict[str, Any]],
    *,
    rationale: str,
    root: Path,
    candidate_digest: str,
) -> str:
    if not basis:
        return "UNKNOWN"
    lowered = f"{rationale} " + " ".join(
        str(item.get("summary") or "") for item in basis
    )
    if "user said" in lowered.lower() or "in chat" in lowered.lower():
        return "UNKNOWN"
    engine = _p6_engine(root)
    for item in basis:
        kind = str(item.get("kind") or "")
        if kind in FORBIDDEN_BASIS_KINDS:
            return "UNKNOWN"
        if kind in EVIDENCE_BASIS_KINDS or kind in UNCITED_HUMAN_KINDS:
            ref = item.get("evidence_ref")
            locator = ""
            if isinstance(ref, dict):
                locator = str(ref.get("locator") or "")
            if not locator or not _portable_locator(locator):
                return "UNKNOWN"
            resolved, _issues = engine.resolve_evidence(locator)
            if resolved is None:
                return "UNKNOWN"
            report = resolved.get("report")
            if not isinstance(report, dict) or not engine.report_usable_for_current(report):
                return "UNKNOWN"
            if item.get("report") is not None:
                return "UNKNOWN"
    return "SATISFIED"


def _normalized_basis(
    value: Any,
    *,
    required_tests: Any,
    root: Path,
    candidate_digest: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        locators = _unique_locators(required_tests)
        if locators:
            return [
                {
                    "kind": "test_evidence",
                    "summary": "Required verification Evidence is cited by portable P6 locator.",
                    "evidence_ref": {"locator": locators[0]},
                }
            ]
        return []
    out: list[dict[str, Any]] = []
    locators = _unique_locators(required_tests)
    for item in value:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "task_fact").strip() or "task_fact"
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        row: dict[str, Any] = {"kind": kind, "summary": summary}
        if isinstance(item.get("evidence_ref"), dict) and item["evidence_ref"].get("locator"):
            locator = str(item["evidence_ref"]["locator"])
            if _portable_locator(locator) and "report" not in item:
                row["evidence_ref"] = {"locator": locator}
        elif kind in EVIDENCE_BASIS_KINDS and locators:
            row["evidence_ref"] = {"locator": locators[0]}
        if "report" in item or any(
            key in item for key in ("report_body", "raw_report", "test_report")
        ):
            continue
        out.append(row)
    return out


def _unique_locators(refs: Any) -> list[str]:
    if not isinstance(refs, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in refs:
        if not isinstance(item, dict):
            continue
        ref = item.get("evidence_ref")
        if not isinstance(ref, dict):
            continue
        locator = str(ref.get("locator") or "")
        if locator and _portable_locator(locator) and locator not in seen:
            seen.add(locator)
            out.append(locator)
    return out


def _bind_refs_on_stage(stage: dict[str, Any], by_profile: dict[str, dict[str, Any]]) -> dict[str, Any]:
    row = dict(stage)
    row["required_tests"] = _bind_refs(row.get("required_tests") or [], by_profile)
    return row


def _bind_refs(refs: Any, by_profile: dict[str, dict[str, Any]]) -> list[Any]:
    if not isinstance(refs, list):
        return []
    out = []
    for item in refs:
        if not isinstance(item, dict):
            out.append(item)
            continue
        row = dict(item)
        profile_id = automated_execution_profile_id(row)
        if not profile_id:
            out.append(row)
            continue
        bound = by_profile.get(profile_id)
        if bound:
            row["evidence_ref"] = {"locator": bound["locator"]}
            if bound.get("observed"):
                row["observed_outcome"] = bound["observed"]
        out.append(row)
    return out


def _judge_requirement(
    engine: TestEngine,
    item: dict[str, Any],
    *,
    candidate_digest: str,
) -> dict[str, str]:
    ref = item.get("evidence_ref")
    locator = ""
    if isinstance(ref, dict):
        locator = str(ref.get("locator") or "")
    if not locator:
        return {
            "state": "unresolved",
            "reason": "required test has no P6 Evidence locator",
        }
    if not _portable_locator(locator):
        return {
            "state": "unresolved",
            "reason": "required test Evidence locator is not a portable P6 locator",
        }
    resolved, issues = engine.resolve_evidence(locator)
    if resolved is None:
        return {
            "state": "unresolved",
            "reason": issues[0] if issues else "required test Evidence is unresolved",
        }
    report = resolved.get("report")
    if not isinstance(report, dict) or not engine.report_usable_for_current(report):
        bound_digest = ""
        stored = report.get("candidate") if isinstance(report, dict) else None
        if isinstance(stored, dict):
            bound_digest = str(stored.get("candidate_digest") or "")
        current = observe_candidate_digest(engine)
        diagnostic = (
            f"current_candidate_digest={current or 'unavailable'} "
            f"evidence_candidate_digest={bound_digest or 'unavailable'} "
            f"evidence_locator={locator} remediation=re-run Test against "
            "the current candidate and rebind; do not rewrite historical "
            "decisions or delete historical evidence"
        )
        return {
            "state": "unresolved",
            "reason": (
                "required test Evidence is stale for the actual candidate; "
                + diagnostic
            ),
        }
    bound_profile = automated_execution_profile_id(item)
    producer = resolved_producer_profile_id(resolved)
    if bound_profile and producer != bound_profile:
        return {
            "state": "unresolved",
            "reason": "required test Evidence producer does not match execution_binding.profile_id",
        }
    result = str(resolved.get("result") or "")
    observed = item.get("observed_outcome")
    if observed is not None:
        expected = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "NOT_EXECUTED": "NOT_RUN",
            "UNKNOWN": "BLOCKED",
        }.get(str(observed))
        if expected != result:
            return {
                "state": "unresolved",
                "reason": "required test observed_outcome does not match resolved P6 Evidence",
            }
    if result == "FAIL":
        return {"state": "fail", "reason": "required test FAIL"}
    if result in {"BLOCKED", "NOT_RUN"}:
        return {
            "state": "unresolved",
            "reason": "required test is BLOCKED, NOT_RUN, or otherwise unresolved",
        }
    if result == "PASS" and resolved.get("evidence_complete") is True:
        return {"state": "pass", "reason": ""}
    return {
        "state": "unresolved",
        "reason": "required test is not satisfactorily complete",
    }


def _supersedes_summary(prior: dict[str, Any]) -> dict[str, str]:
    return {
        "candidate_digest": str(prior.get("candidate_digest") or ""),
        "outcome": str(prior.get("outcome") or "UNKNOWN"),
        "rationale": str(prior.get("rationale") or "prior completion authority is no longer current"),
    }


def _spec_targets_stage(spec: Any, stage: dict[str, Any]) -> bool:
    if not isinstance(spec, dict):
        return False
    target = spec.get("stage_id")
    if not isinstance(target, str) or not target.strip():
        return False
    return target.strip() == str(stage.get("stage_id") or "")


def _normalized_batch_decisions(value: Any) -> list[dict[str, Any]] | None:
    """Batch decisions are opt-in: absent/None means single-decision mode."""
    if value is None:
        return None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _batch_stage_decisions_error(
    batch: list[dict[str, Any]],
    *,
    task: dict[str, Any],
    existing_stage_completion_decision: Any = None,
) -> str | None:
    """Atomic validation: any illegal decision rejects the entire batch.

    Checks (in order): empty batch, duplicate stage_id, batch/single-decision
    conflict, and per-decision existing Stage binding authority. No Task
    mutation has happened when any of these fail.
    """
    if not batch:
        return (
            "stage_decisions must be a non-empty list of Stage Completion "
            "Decision objects"
        )
    seen: set[str] = set()
    for index, spec in enumerate(batch):
        target = str(spec.get("stage_id") or "").strip()
        if not target:
            return (
                f"stage_decisions[{index}] is unscoped; each decision must "
                "bind exactly one stage_id"
            )
        if target in seen:
            return (
                f"stage_decisions contains duplicate stage_id {target!r}; "
                "each Stage must be bound at most once per envelope"
            )
        seen.add(target)
    if existing_stage_completion_decision is not None and isinstance(
        existing_stage_completion_decision, dict
    ):
        single_target = str(
            existing_stage_completion_decision.get("stage_id") or ""
        ).strip()
        if single_target and single_target in seen:
            return (
                "envelope contains conflicting Stage Completion Decisions: "
                f"stage_id {single_target!r} is bound by both stage_decision "
                "and stage_decisions"
            )
    for index, spec in enumerate(batch):
        authority_error = _stage_completion_authority_error(spec, task)
        if authority_error:
            return f"stage_decisions[{index}]: {authority_error}"
    return None


def _stage_spec_for_stage(
    single_spec: Any,
    batch: list[dict[str, Any]] | None,
    stage: dict[str, Any],
) -> Any:
    """Resolve the decision spec applying to one Stage, batch first."""
    if batch:
        for spec in batch:
            if _spec_targets_stage(spec, stage):
                return spec
        return None
    return single_spec if _spec_targets_stage(single_spec, stage) else None


def _stage_completion_authority_error(spec: Any, task: dict[str, Any]) -> str | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        return "Stage Completion Decision is malformed"
    target = spec.get("stage_id")
    if target in (None, ""):
        return (
            "Stage Completion Decision is unscoped; "
            "it must bind exactly one stage_id"
        )
    if not isinstance(target, str) or not target.strip():
        return "Stage Completion Decision stage_id is malformed"
    target = target.strip()
    matches = [
        str(stage.get("stage_id") or "")
        for stage in (task.get("stages") or [])
        if isinstance(stage, dict) and str(stage.get("stage_id") or "") == target
    ]
    if not matches:
        return (
            f"Stage Completion Decision targets nonexistent Stage {target!r}"
        )
    if len(matches) != 1:
        return (
            "Stage Completion Decision stage_id is ambiguous; "
            "duplicate Stage identities exist"
        )
    return None


def _copy_spec(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {}
    return dict(spec)


def automated_execution_profile_id(item: dict[str, Any]) -> str:
    binding = item.get("execution_binding")
    if not isinstance(binding, dict):
        return ""
    if binding.get("kind") != "test_profile":
        return ""
    profile_id = binding.get("profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    return ""


def resolved_producer_profile_id(resolved: dict[str, Any]) -> str:
    profile_id = resolved.get("profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    profile = resolved.get("profile")
    if isinstance(profile, dict) and profile.get("id"):
        return str(profile["id"])
    return ""


def _portable_locator(locator: str) -> bool:
    if not locator or not isinstance(locator, str):
        return False
    if Path(locator).is_absolute() or "\\" in locator:
        return False
    if locator.startswith("test-runs/"):
        return True
    return False


def _p6_engine(root: Path) -> TestEngine:
    from scaffold_p6.engine import TestEngine
    from scaffold_p5.packages import resolve_skill_package

    return TestEngine(
        root,
        resolve_skill_package("test", host=root, runtime_file=Path(__file__)),
    )


def observe_candidate_digest(engine: TestEngine) -> str:
    """Current candidate digest via the engine's root; empty when unusable."""
    from scaffold_p6.candidate import observe_candidate

    return observe_candidate(engine.root).digest


def open_session_drift_warning(
    root: Path,
    *,
    session: dict[str, Any],
    task: dict[str, Any],
    current_candidate_digest: str,
) -> dict[str, Any]:
    """Session-OPEN early diagnostic between Candidate and recent SEALED evidence.

    Read-only and advisory. Never rewrites or deletes historical Evidence and
    never duplicates the P2 Published-Evidence-Staleness gates (those run at
    decision/evidence consumption time). Distinguishes authorized in-session
    development from unattributed worktree drift and reports UNKNOWN when
    reliable attribution is not possible.
    """
    from scaffold_p5.scm import observe_scm

    warning: dict[str, Any] = {
        "status": "NONE",
        "checks": [],
    }
    checks = warning["checks"]

    observed = observe_scm(root)
    if not observed.ok or observed.kind != "git":
        warning["status"] = "UNKNOWN"
        checks.append(
            {
                "kind": "candidate_observation",
                "state": "UNKNOWN",
                "detail": (
                    "SCM observation is unresolved; open-Session drift "
                    "attribution cannot be performed"
                ),
            }
        )
        return warning

    # Check 1: Candidate drift since the Session recorded its digest.
    bound_digest = str(session.get("observed_candidate_digest") or "")
    candidate_unattributable = False
    if not bound_digest:
        candidate_unattributable = True
        warning["status"] = "UNKNOWN"
        checks.append(
            {
                "kind": "candidate_binding",
                "state": "UNKNOWN",
                "detail": (
                    "the OPEN Session has no recorded candidate digest; "
                    "Candidate identity cannot be reliably attributed"
                ),
            }
        )
    elif bound_digest != current_candidate_digest:
        checks.append(
            {
                "kind": "candidate_binding",
                "state": "DIVERGED",
                "detail": (
                    "workspace Candidate changed since this Session opened; "
                    "determine whether the change came from authorized "
                    "development inside this Session or from unattributed "
                    "worktree activity"
                ),
                "session_candidate_digest": bound_digest,
                "current_candidate_digest": current_candidate_digest,
            }
        )
        warning["status"] = "DIVERGED"
    else:
        checks.append(
            {
                "kind": "candidate_binding",
                "state": "CURRENT",
                "detail": "Session candidate digest matches the live Candidate",
            }
        )

    # Check 2: unattributed working-tree drift outside the Task scope.
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    scope_paths = {
        str(item).replace("\\", "/").strip("/")
        for item in (scope.get("paths") or [])
        if str(item or "").strip()
    }
    overlay_paths = {
        str(entry.get("path") or "")
        for entry in (session.get("workspace_overlay_s0") or {}).get("paths", [])
        if isinstance(entry, dict) and entry.get("path")
    }
    unattributed: list[str] = []
    unknown_paths = 0
    attributed_paths = _previously_attributed_paths(root)
    for entry in observed.entries:
        rel = str(entry.get("path") or "")
        if not rel:
            unknown_paths += 1
            continue
        if entry.get("untracked") or entry.get("code") in {"??", " A", "AM"}:
            in_scope = any(
                rel == item or rel.startswith(item.rstrip("/") + "/")
                for item in scope_paths
            )
            if in_scope:
                # Authorized in-Session development: Task-scope files the
                # implementation legitimately created. Not a warning.
                continue
            if rel == "AGENTS.md" or rel == ".gitattributes" or rel.startswith(
                ".scaffold/"
            ):
                # Scaffold governance/install-managed surfaces: their drift
                # classification is owned by the existing reconcile authority
                # (P2-F3), not by this advisory check.
                continue
            if rel in attributed_paths:
                # Existing drift-authority attribution (accepted anchor,
                # install-managed, or previously classified unexplained):
                # pre-existing historical difference, not new unattributed
                # worktree drift.
                continue
            unattributed.append(rel)
    if unattributed:
        warning["status"] = (
            "DIVERGED" if warning["status"] != "DIVERGED" else warning["status"]
        )
        checks.append(
            {
                "kind": "unattributed_drift",
                "state": "DIVERGED",
                "detail": (
                    "working-tree files changed outside the Task scope and "
                    "outside prior recorded authority; verify whether these "
                    "belong to pre-existing historical differences or to "
                    "unattributed worktree drift"
                ),
                "paths": sorted(unattributed)[:20],
            }
        )
    if unknown_paths:
        warning["status"] = "UNKNOWN" if warning["status"] == "NONE" else warning["status"]
        checks.append(
            {
                "kind": "unattributed_drift",
                "state": "UNKNOWN",
                "detail": (
                    f"{unknown_paths} SCM entries have no usable path; drift "
                    "attribution is incomplete"
                ),
            }
        )

    # Check 3: relationship to the most recent applicable SEALED evidence.
    latest_sealed = _latest_sealed_session_for_task(
        root, task_id=str(task.get("record_id") or "")
    )
    if latest_sealed is not None:
        sealed_digest = str(
            latest_sealed.get("observed_candidate_digest") or ""
        )
        if sealed_digest and current_candidate_digest and sealed_digest != current_candidate_digest:
            checks.append(
                {
                    "kind": "sealed_evidence_relationship",
                    "state": "DIVERGED",
                    "detail": (
                        "the most recent SEALED Session recorded a different "
                        "Candidate than the current workspace; any Evidence "
                        "bound by that Session may be stale for the current "
                        "Candidate (authoritative staleness is still decided "
                        "by the existing Evidence gates at consumption time)"
                    ),
                    "sealed_candidate_digest": sealed_digest,
                    "current_candidate_digest": current_candidate_digest,
                    "sealed_session_id": latest_sealed.get("record_id"),
                }
            )
            warning["status"] = "DIVERGED"
    else:
        checks.append(
            {
                "kind": "sealed_evidence_relationship",
                "state": "NONE",
                "detail": "no applicable SEALED Session exists for this Task",
            }
        )
    # Final status: a reliable-attribution failure (UNKNOWN) outranks a
    # divergence report, per the UNKNOWN-reporting requirement.
    if candidate_unattributable:
        warning["status"] = "UNKNOWN"
    return warning


def _latest_sealed_session_for_task(
    root: Path,
    *,
    task_id: str,
) -> dict[str, Any] | None:
    """Latest SEALED Session record for a Task from canonical Session files."""
    folder = root / SESSIONS_DIR
    wanted = str(task_id or "").strip()
    if not folder.is_dir() or not wanted:
        return None
    latest: dict[str, Any] | None = None
    for directory in sorted(folder.iterdir()):
        if not directory.is_dir():
            continue
        path = directory / "session.yaml"
        if not path.is_file():
            continue
        try:
            data = read_yaml(path)
        except (OSError, ValueError, TypeError, UnicodeError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("task_id") or "").strip() != wanted:
            continue
        if data.get("status") != "SEALED":
            continue
        if latest is None or str(data.get("updated_at") or "") > str(
            latest.get("updated_at") or ""
        ):
            latest = data
    return latest


def _previously_attributed_paths(root: Path) -> set[str]:
    """Paths that already carry an attribution from the existing drift authority.

    Includes accepted-anchor and install-managed/unexplained classifications.
    Read-only best-effort: any failure returns an empty set and the advisory
    check falls back to its UNKNOWN/reporting behavior.
    """
    try:
        from scaffold_p7.unexplained import unexplained_path_map

        return {str(key) for key in unexplained_path_map(root)}
    except Exception:
        return set()

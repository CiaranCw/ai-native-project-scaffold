"""Proof-obligation Evidence sufficiency and engine-derived adequacy.

Association (po_id / covers) is not coverage. Caller adequacy claims are not
authority. No TEST_ADEQUATE Foundation state. No parallel Test authority.
"""

from __future__ import annotations

from typing import Any

from scaffold_p6.evidence import SUPPLIED_PROVENANCE
from scaffold_p6.models import EVIDENCE_KINDS
from scaffold_p6.trace import (
    assertions_from_trace,
    effective_role,
    envelope_candidate_digest,
    envelope_from_evidence,
    role_can_directly_satisfy,
    validate_trace_envelope,
)


SUITE_STRATEGIES = frozenset({"suite", "profile", "regression", "bound_profile"})
SUPPORTING_ONLY_KINDS = frozenset({"log_text", "file_artifact"})
DECLARED_PROOF_KINDS = frozenset(EVIDENCE_KINDS) - SUPPORTING_ONLY_KINDS
STRUCTURAL_STRATEGIES = frozenset(
    {
        "structured_assertion",
        "structured_state",
        "state_transition",
        "event_trace",
        "suite",
        "profile",
        "regression",
        "bound_profile",
        "command_result",
    }
)
STRUCTURAL_EVIDENCE_KINDS = frozenset(
    {
        "structured_assertion",
        "structured_state",
        "event_trace",
        "command_result",
    }
)
ADEQUACY_SATISFIED = "SATISFIED"
ADEQUACY_UNSATISFIED = "UNSATISFIED"
ADEQUACY_UNKNOWN = "UNKNOWN"


def suite_strategy(item: dict[str, Any]) -> bool:
    strategy = str(item.get("execution_strategy") or "").strip().lower()
    return strategy in SUITE_STRATEGIES


def evaluate_sav_coverage(
    plan: dict[str, Any],
    *,
    evidence: list[dict[str, Any]],
    profile_results: dict[str, str],
    candidate_digest: str | None = None,
    caller_adequacy: Any = None,
) -> dict[str, Any]:
    """Map proof obligations to sufficient current Evidence. Names are not coverage."""
    del caller_adequacy  # never authority
    binding = plan.get("binding") if isinstance(plan.get("binding"), dict) else {}
    profile_id = str(binding.get("profile_id") or "")
    profile_pass = str(profile_results.get(profile_id) or "") == "PASS"
    obligations = [
        item for item in (plan.get("proof_obligations") or []) if isinstance(item, dict)
    ]
    rows: list[dict[str, Any]] = []
    insufficient = False
    failed = False
    unknown = False
    for item in obligations:
        po_id = str(item.get("po_id") or "")
        required = item.get("required") is True
        observability = str(item.get("observability_status") or "UNKNOWN")
        status = "UNKNOWN"
        reason = ""
        if observability == "INSUFFICIENT_OBSERVABILITY" and required:
            status = "INSUFFICIENT_OBSERVABILITY"
            reason = "required proof obligation is not observable"
            insufficient = True
        elif observability == "UNKNOWN" and required:
            status = "UNKNOWN"
            reason = "required proof obligation observability is UNKNOWN"
            unknown = True
        elif _po_candidate_conflict(item, candidate_digest):
            status = "UNKNOWN"
            reason = "proof obligation candidate_digest is not current"
            unknown = True
        elif suite_strategy(item):
            if not profile_pass:
                status = "UNSATISFIED"
                reason = "bound profile did not PASS; suite PO is not satisfied"
                if required:
                    failed = True
            else:
                status, reason = _suite_status(
                    item, po_id, evidence, candidate_digest=candidate_digest
                )
                if status != "SATISFIED" and required:
                    if status == "UNKNOWN":
                        unknown = True
                    else:
                        failed = True
        else:
            status, reason = _non_suite_status(
                item, po_id, evidence, candidate_digest=candidate_digest
            )
            if status != "SATISFIED" and required:
                if status == "UNKNOWN":
                    unknown = True
                else:
                    failed = True
        rows.append(
            {
                "po_id": po_id,
                "required": required,
                "observability_status": observability,
                "status": status,
                "reason": reason,
            }
        )
    required_rows = [row for row in rows if row.get("required")]
    requirement_pass = bool(required_rows) and all(
        row.get("status") == "SATISFIED" for row in required_rows
    )
    adequacy = derive_adequacy(
        plan,
        rows,
        evidence,
        profile_pass=profile_pass,
        candidate_digest=candidate_digest,
    )
    return {
        "ok": True,
        "requirement_pass": requirement_pass,
        "profile_pass": profile_pass,
        "insufficient_observability": insufficient,
        "failed": failed,
        "unknown": unknown,
        "proof_obligations": rows,
        "adequacy": adequacy,
        "handoff": {
            "kind": "test_to_develop",
            "reason": "INSUFFICIENT_OBSERVABILITY",
            "task_id": plan.get("task_id"),
            "requirement_id": plan.get("requirement_id"),
            "po_ids": [
                row["po_id"]
                for row in rows
                if row.get("status") == "INSUFFICIENT_OBSERVABILITY"
            ],
        }
        if insufficient
        else None,
    }


def derive_adequacy(
    plan: dict[str, Any],
    obligation_rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    profile_pass: bool,
    candidate_digest: str | None = None,
    caller_adequacy: Any = None,
) -> dict[str, Any]:
    """Engine-derived adequacy. Caller SATISFIED claims are ignored."""
    del caller_adequacy
    obligations = {
        str(item.get("po_id") or ""): item
        for item in (plan.get("proof_obligations") or [])
        if isinstance(item, dict)
    }
    reasons: list[str] = []
    per_po: list[dict[str, Any]] = []
    gate = ADEQUACY_SATISFIED
    required_rows = [row for row in obligation_rows if row.get("required")]
    if not required_rows:
        return {
            "status": ADEQUACY_SATISFIED,
            "derived": True,
            "authority": "engine",
            "reasons": [],
            "proof_obligations": [],
        }
    for row in required_rows:
        po_id = str(row.get("po_id") or "")
        po = obligations.get(po_id) or {}
        po_status = str(row.get("status") or "UNKNOWN")
        po_gate = ADEQUACY_SATISFIED
        po_reasons: list[str] = []
        if po_status == "INSUFFICIENT_OBSERVABILITY":
            po_gate = ADEQUACY_UNSATISFIED
            po_reasons.append("required proof obligation lacks observability")
        elif po_status == "UNKNOWN":
            po_gate = ADEQUACY_UNKNOWN
            po_reasons.append("required proof obligation adequacy is UNKNOWN")
        elif po_status != "SATISFIED":
            po_gate = ADEQUACY_UNSATISFIED
            po_reasons.append(str(row.get("reason") or "required proof obligation is unsatisfied"))
        else:
            primary = _primary_sufficient_items(
                po, po_id, evidence, candidate_digest=candidate_digest, profile_pass=profile_pass
            )
            if not primary:
                po_gate = ADEQUACY_UNSATISFIED
                po_reasons.append("required PRIMARY evidence is absent")
            if po_requires_negative_control(po) and not _negative_control_proven(
                po, po_id, evidence, candidate_digest=candidate_digest
            ):
                po_gate = ADEQUACY_UNSATISFIED
                po_reasons.append("declared negative-control obligation lacks required proof")
        if po_gate == ADEQUACY_UNKNOWN:
            if gate == ADEQUACY_SATISFIED:
                gate = ADEQUACY_UNKNOWN
        elif po_gate == ADEQUACY_UNSATISFIED:
            gate = ADEQUACY_UNSATISFIED
        reasons.extend(po_reasons)
        per_po.append(
            {
                "po_id": po_id,
                "status": po_gate,
                "reasons": po_reasons,
            }
        )
    return {
        "status": gate,
        "derived": True,
        "authority": "engine",
        "reasons": reasons,
        "proof_obligations": per_po,
    }


def sav_blocks_test_complete(coverage: dict[str, Any]) -> bool:
    if coverage.get("requirement_pass") is not True:
        return True
    if coverage.get("failed") or coverage.get("unknown") or coverage.get("insufficient_observability"):
        return True
    adequacy = coverage.get("adequacy") if isinstance(coverage.get("adequacy"), dict) else {}
    status = str(adequacy.get("status") or "")
    if status in {ADEQUACY_UNSATISFIED, ADEQUACY_UNKNOWN, ""}:
        return True
    for row in coverage.get("proof_obligations") or []:
        if isinstance(row, dict) and row.get("required") and row.get("status") != "SATISFIED":
            return True
    return False


def structured_assertion_eligible(
    item: Any,
    *,
    candidate_digest: str | None = None,
) -> bool:
    if not isinstance(item, dict) or item.get("kind") != "structured_assertion":
        return False
    if item.get("usable") is False:
        return False
    provenance = item.get("provenance")
    if provenance == "LOCAL_EXECUTION":
        return False
    if provenance not in SUPPLIED_PROVENANCE:
        return False
    bound = str(item.get("candidate_digest") or "")
    if provenance in {"EXTERNAL_RESULT", "CI_RESULT"}:
        if not bound:
            return False
        if candidate_digest and bound != candidate_digest:
            return False
    elif provenance == "HUMAN_OBSERVATION" and bound and candidate_digest and bound != candidate_digest:
        return False
    return True


def evidence_eligible(
    item: Any,
    *,
    candidate_digest: str | None = None,
) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("usable") is False:
        return False
    kind = item.get("kind")
    if kind == "structured_assertion":
        return structured_assertion_eligible(item, candidate_digest=candidate_digest)
    provenance = item.get("provenance")
    bound = str(item.get("candidate_digest") or "")
    if provenance == "LOCAL_EXECUTION":
        if candidate_digest and bound and bound != candidate_digest:
            return False
        return True
    if provenance in {"EXTERNAL_RESULT", "CI_RESULT"}:
        if not bound:
            return False
        if candidate_digest and bound != candidate_digest:
            return False
        return True
    if provenance == "HUMAN_OBSERVATION":
        if bound and candidate_digest and bound != candidate_digest:
            return False
        return True
    return False


def associates_with_po(item: dict[str, Any], po_id: str) -> bool:
    if not po_id:
        return False
    if str(item.get("po_id") or "") == po_id:
        return True
    assertion = item.get("assertion") if isinstance(item.get("assertion"), dict) else {}
    if str(assertion.get("po_id") or "") == po_id:
        return True
    if po_id in _covers(item) or po_id in _covers(assertion):
        return True
    for row in assertions_from_trace(item):
        if str(row.get("po_id") or "") == po_id:
            return True
        if po_id in _covers(row):
            return True
    envelope = envelope_from_evidence(item)
    if isinstance(envelope, dict):
        ids = envelope.get("obligation_ids")
        if isinstance(ids, list) and po_id in {str(value) for value in ids}:
            return True
    return False


def explicit_verdicts_for_po(item: dict[str, Any], po_id: str) -> list[dict[str, Any]]:
    """Return verdict payloads that explicitly address this PO.

    A covers list without a PO-bound verdict is not a verdict.
    An item-level PASS applies only to item.po_id or a singleton covers list
    that is the only association.
    """
    found: list[dict[str, Any]] = []
    for row in assertions_from_trace(item):
        if _row_targets_po(row, po_id) and _has_verdict(row):
            found.append(row)
    assertion = item.get("assertion") if isinstance(item.get("assertion"), dict) else None
    if assertion and _row_targets_po(assertion, po_id) and _has_verdict(assertion):
        found.append(assertion)
    if str(item.get("po_id") or "") == po_id and _has_verdict(item):
        found.append(item)
    elif (
        not str(item.get("po_id") or "")
        and _covers(item) == {po_id}
        and _has_verdict(item)
        and not assertions_from_trace(item)
    ):
        found.append(item)
    return found


def kind_may_directly_satisfy(kind: str, po: dict[str, Any], item: dict[str, Any]) -> bool:
    kind = str(kind or "")
    if kind in SUPPORTING_ONLY_KINDS:
        return False
    if not _kind_allowed_by_requirements(kind, po):
        return False
    if kind == "command_result":
        return suite_strategy(po)
    if kind == "structured_assertion":
        return True
    if kind == "structured_state":
        return bool(explicit_verdicts_for_po(item, str(po.get("po_id") or "")))
    if kind == "event_trace":
        envelope = envelope_from_evidence(item)
        if envelope is not None:
            issues = validate_trace_envelope(envelope)
            if issues:
                return False
        return bool(explicit_verdicts_for_po(item, str(po.get("po_id") or "")))
    if kind == "human_observation":
        return human_observation_permitted(po)
    if kind == "visual_checkpoint":
        return (not po_is_structural(po)) and visual_kind_permitted(po)
    if kind == "external_ci":
        return bool(explicit_verdicts_for_po(item, str(po.get("po_id") or ""))) or _has_verdict(item)
    return False


def declared_proof_kinds(po: dict[str, Any]) -> set[str]:
    return {
        item
        for item in _lower_list(po.get("evidence_requirements"))
        if item in DECLARED_PROOF_KINDS
    }


def _kind_allowed_by_requirements(kind: str, po: dict[str, Any]) -> bool:
    required = declared_proof_kinds(po)
    if not required:
        return True
    return kind in required


def po_is_structural(po: dict[str, Any]) -> bool:
    strategy = str(po.get("execution_strategy") or "").strip().lower()
    if strategy in {"visual", "visual_checkpoint", "human_observation", "human"}:
        return False
    reqs = _lower_list(po.get("evidence_requirements"))
    if reqs and set(reqs) <= {"visual_checkpoint", "human_observation"}:
        return False
    if strategy in STRUCTURAL_STRATEGIES:
        return True
    if any(kind in STRUCTURAL_EVIDENCE_KINDS or kind in STRUCTURAL_STRATEGIES for kind in reqs):
        return True
    return True


def human_observation_permitted(po: dict[str, Any]) -> bool:
    reqs = _lower_list(po.get("evidence_requirements"))
    strategy = str(po.get("execution_strategy") or "").strip().lower()
    methods = _lower_list(po.get("methods") or po.get("observation_methods"))
    if "human_observation" in reqs or strategy in {"human_observation", "human"}:
        return True
    return "human_observation" in methods


def visual_kind_permitted(po: dict[str, Any]) -> bool:
    reqs = _lower_list(po.get("evidence_requirements"))
    strategy = str(po.get("execution_strategy") or "").strip().lower()
    return "visual_checkpoint" in reqs or strategy in {"visual", "visual_checkpoint"}


def po_requires_negative_control(po: dict[str, Any]) -> bool:
    if po.get("negative_control") is True:
        return True
    reqs = _lower_list(po.get("evidence_requirements"))
    if "negative_control" in reqs:
        return True
    strategy = str(po.get("execution_strategy") or "").strip().lower()
    return strategy == "negative_control"


def _non_suite_status(
    po: dict[str, Any],
    po_id: str,
    evidence: list[dict[str, Any]],
    *,
    candidate_digest: str | None,
) -> tuple[str, str]:
    associated = [
        item
        for item in evidence
        if isinstance(item, dict) and associates_with_po(item, po_id)
    ]
    if not associated:
        return "UNSATISFIED", "required structured assertion for this proof obligation is absent"
    sufficient: list[dict[str, Any]] = []
    failed = False
    unknown = False
    for item in associated:
        if not evidence_eligible(item, candidate_digest=candidate_digest):
            continue
        if _trace_candidate_conflict(item, candidate_digest):
            continue
        if not kind_may_directly_satisfy(str(item.get("kind") or ""), po, item):
            continue
        if not role_can_directly_satisfy(item):
            continue
        verdicts = explicit_verdicts_for_po(item, po_id)
        if not verdicts:
            continue
        if any(_verdict_failed(row) for row in verdicts):
            failed = True
            continue
        if any(_verdict_passed(row) for row in verdicts):
            sufficient.append(item)
        elif any(_verdict_unknown(row) for row in verdicts):
            unknown = True
    if failed:
        return "UNSATISFIED", "structured assertion for this proof obligation failed"
    if sufficient:
        acceptable = [
            item
            for item in sufficient
            if effective_role(item) == "PRIMARY"
            or (
                effective_role(item) == "ESCALATION"
                and _escalation_allowed(po, item)
            )
        ]
        acceptable.sort(key=lambda item: str(item.get("evidence_id") or item.get("kind") or ""))
        if acceptable:
            return "SATISFIED", "structured assertion evidence covers this proof obligation"
        if any(effective_role(item) == "ESCALATION" for item in sufficient):
            return "UNSATISFIED", "ESCALATION evidence is not justified for this proof obligation"
        return "SATISFIED", "structured assertion evidence covers this proof obligation"
    if unknown:
        return "UNKNOWN", "proof obligation verdict is UNKNOWN"
    if any(
        evidence_eligible(item, candidate_digest=candidate_digest)
        and _trace_candidate_conflict(item, candidate_digest)
        for item in associated
    ):
        return "UNKNOWN", "trace envelope candidate is not current"
    if any(
        evidence_eligible(item, candidate_digest=candidate_digest)
        and associates_with_po(item, po_id)
        and effective_role(item) == "SECONDARY"
        for item in associated
    ):
        return "UNSATISFIED", "required PRIMARY evidence is absent"
    return "UNSATISFIED", "structured assertion does not explicitly PASS this proof obligation"


def _primary_sufficient_items(
    po: dict[str, Any],
    po_id: str,
    evidence: list[dict[str, Any]],
    *,
    candidate_digest: str | None,
    profile_pass: bool,
) -> list[dict[str, Any]]:
    if suite_strategy(po):
        return _eligible_command_results(
            po, evidence, candidate_digest=candidate_digest
        ) if profile_pass else []
    found: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if not associates_with_po(item, po_id):
            continue
        if not evidence_eligible(item, candidate_digest=candidate_digest):
            continue
        if _trace_candidate_conflict(item, candidate_digest):
            continue
        if not kind_may_directly_satisfy(str(item.get("kind") or ""), po, item):
            continue
        role = effective_role(item)
        if role == "PRIMARY":
            pass
        elif role == "ESCALATION" and _escalation_allowed(po, item):
            pass
        else:
            continue
        if not any(_verdict_passed(row) for row in explicit_verdicts_for_po(item, po_id)):
            continue
        found.append(item)
    return found


def _negative_control_proven(
    po: dict[str, Any],
    po_id: str,
    evidence: list[dict[str, Any]],
    *,
    candidate_digest: str | None,
) -> bool:
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if not evidence_eligible(item, candidate_digest=candidate_digest):
            continue
        if _trace_candidate_conflict(item, candidate_digest):
            continue
        if not kind_may_directly_satisfy(str(item.get("kind") or ""), po, item):
            continue
        if not role_can_directly_satisfy(item):
            continue
        if effective_role(item) == "ESCALATION" and not _escalation_allowed(po, item):
            continue
        rows = explicit_verdicts_for_po(item, po_id) or (
            [item] if associates_with_po(item, po_id) else []
        )
        for row in rows:
            if row.get("negative_control") is True and _verdict_passed(row):
                return True
        if item.get("negative_control") is True and any(_verdict_passed(row) for row in rows):
            return True
    return False


def _escalation_allowed(po: dict[str, Any], item: dict[str, Any]) -> bool:
    if visual_kind_permitted(po) or human_observation_permitted(po):
        return True
    for field in (
        "retention_justification",
        "escalation_justification",
        "visual_justification",
    ):
        if str(item.get(field) or "").strip():
            return True
    return False


def _covers(item: Any) -> set[str]:
    if not isinstance(item, dict):
        return set()
    covers = item.get("covers")
    if not isinstance(covers, list):
        return set()
    return {str(value) for value in covers if str(value).strip()}


def _row_targets_po(row: dict[str, Any], po_id: str) -> bool:
    if str(row.get("po_id") or "") == po_id:
        return True
    covers = _covers(row)
    return covers == {po_id}


def _has_verdict(row: dict[str, Any]) -> bool:
    if "pass" in row and row.get("pass") is not None:
        return True
    if row.get("result") in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        return True
    if row.get("verdict") in {"PASS", "FAIL", True, False}:
        return True
    oracle = row.get("oracle")
    if isinstance(oracle, dict) and (
        oracle.get("pass") is not None or oracle.get("result") in {"PASS", "FAIL"}
    ):
        return True
    return False


def _verdict_passed(row: dict[str, Any]) -> bool:
    if row.get("pass") is True or row.get("result") == "PASS":
        return True
    if row.get("verdict") in {"PASS", True}:
        return True
    oracle = row.get("oracle")
    if isinstance(oracle, dict) and (oracle.get("pass") is True or oracle.get("result") == "PASS"):
        return True
    return False


def _verdict_failed(row: dict[str, Any]) -> bool:
    if row.get("pass") is False or row.get("result") == "FAIL":
        return True
    if row.get("verdict") in {"FAIL", False}:
        return True
    oracle = row.get("oracle")
    if isinstance(oracle, dict) and (oracle.get("pass") is False or oracle.get("result") == "FAIL"):
        return True
    return False


def _verdict_unknown(row: dict[str, Any]) -> bool:
    if row.get("result") in {"BLOCKED", "NOT_RUN"}:
        return True
    if str(row.get("verdict") or "").upper() == "UNKNOWN":
        return True
    return False


def _lower_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _po_candidate_conflict(po: dict[str, Any], candidate_digest: str | None) -> bool:
    declared = po.get("candidate_digest")
    if declared in (None, "") or not candidate_digest:
        return False
    return str(declared) != str(candidate_digest)


def _trace_candidate_conflict(item: dict[str, Any], candidate_digest: str | None) -> bool:
    if not candidate_digest:
        return False
    envelope = envelope_from_evidence(item)
    if envelope is None:
        return False
    declared = envelope_candidate_digest(envelope.get("candidate"))
    if not declared:
        return False
    return declared != str(candidate_digest)


def _result_bearing_command_result(item: dict[str, Any]) -> bool:
    if str(item.get("kind") or "") != "command_result":
        return False
    if item.get("result") in {"PASS", "FAIL"}:
        return True
    if item.get("pass") is True or item.get("pass") is False:
        return True
    if item.get("exit_code") not in (None, ""):
        return True
    command = item.get("command")
    return isinstance(command, list) and bool(command)


def _eligible_command_results(
    po: dict[str, Any],
    evidence: list[dict[str, Any]],
    *,
    candidate_digest: str | None,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        if not _result_bearing_command_result(item):
            continue
        if not evidence_eligible(item, candidate_digest=candidate_digest):
            continue
        if _trace_candidate_conflict(item, candidate_digest):
            continue
        if not kind_may_directly_satisfy("command_result", po, item):
            continue
        if not role_can_directly_satisfy(item):
            continue
        po_id = str(po.get("po_id") or "")
        if po_id and str(item.get("po_id") or "") and str(item.get("po_id")) != po_id:
            if not associates_with_po(item, po_id):
                continue
        found.append(item)
    return found


def _suite_status(
    po: dict[str, Any],
    po_id: str,
    evidence: list[dict[str, Any]],
    *,
    candidate_digest: str | None,
) -> tuple[str, str]:
    required = declared_proof_kinds(po)
    if required and "command_result" not in required:
        return _non_suite_status(
            po, po_id, evidence, candidate_digest=candidate_digest
        )
    eligible = _eligible_command_results(
        po, evidence, candidate_digest=candidate_digest
    )
    if eligible:
        return "SATISFIED", "bound profile produced a passing command_result"
    return (
        "UNSATISFIED",
        "declared command_result evidence is absent for this suite proof obligation",
    )

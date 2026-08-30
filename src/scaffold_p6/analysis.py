"""Deterministic completeness and routing. No Repair. No Submit authorization."""

from __future__ import annotations

from typing import Any

from scaffold_p6.models import TERMINAL_USABLE, ScenarioResult


def analyze(
    *,
    required_ids: list[str],
    optional_ids: list[str],
    results: list[ScenarioResult],
    candidate_match: bool,
    verified_no_required: bool,
    contract_blockers: list[str],
    selected_ids: list[str] | None = None,
    required_set_authoritative: bool = False,
) -> dict[str, Any]:
    required_pass = 0
    required_fail = 0
    required_blocked = 0
    required_not_run = 0
    required_terminal = 0
    missing_required: list[str] = []
    blocked_required: list[str] = []
    coverage_evidence_complete = True

    for profile_id in required_ids:
        rows = [row for row in results if row.profile_id == profile_id]
        row = _worst(rows)
        if row is None:
            required_not_run += 1
            missing_required.append(profile_id)
            coverage_evidence_complete = False
            continue
        if row.result == "PASS":
            required_pass += 1
        elif row.result == "FAIL":
            required_fail += 1
        elif row.result == "BLOCKED":
            required_blocked += 1
            blocked_required.append(profile_id)
        else:
            required_not_run += 1
            missing_required.append(profile_id)
        if row.result in TERMINAL_USABLE:
            required_terminal += 1
        if not row.evidence_complete:
            coverage_evidence_complete = False

    batch = [row for row in results if row.result != "NOT_RUN"]
    batch_evidence_complete = all(row.evidence_complete for row in batch)
    test_pass = (
        bool(batch)
        and all(row.result == "PASS" for row in batch)
        and candidate_match
        and batch_evidence_complete
        and not contract_blockers
    )
    test_complete = (
        required_set_authoritative
        and candidate_match
        and coverage_evidence_complete
        and not contract_blockers
        and required_blocked == 0
        and required_not_run == 0
        and required_terminal == len(required_ids)
    )
    if (
        required_set_authoritative
        and not required_ids
        and not contract_blockers
        and candidate_match
    ):
        test_complete = True
        if verified_no_required or not batch:
            test_pass = False
        coverage_evidence_complete = True
    if not required_set_authoritative and not required_ids:
        test_complete = False

    executed = [row.profile_id for row in results if row.result != "NOT_RUN"]
    terminal = [row.profile_id for row in results if row.result in TERMINAL_USABLE]
    selected = list(selected_ids) if selected_ids is not None else executed
    return {
        "required_total": len(required_ids),
        "required_terminal_usable": required_terminal,
        "required_pass": required_pass,
        "required_fail": required_fail,
        "required_blocked": required_blocked,
        "required_not_run": required_not_run,
        "optional_total": len(optional_ids),
        "candidate_match": candidate_match,
        "evidence_complete": coverage_evidence_complete,
        "batch_evidence_complete": batch_evidence_complete,
        "test_complete": test_complete,
        "test_pass": test_pass,
        "selected": selected,
        "required": list(required_ids),
        "executed": executed,
        "terminal_usable": terminal,
        "missing_required": missing_required,
        "blocked_required": blocked_required,
        "optional": list(optional_ids),
        "verified_no_required_tests": verified_no_required,
        "required_set_authoritative": required_set_authoritative,
    }


def route(
    *,
    completeness: dict[str, Any],
    contract_route: str,
    candidate_match: bool,
    human_required: bool,
    verification_failed: bool,
) -> str:
    if contract_route:
        return contract_route
    if not candidate_match:
        return "test.scoped_verification"
    if human_required:
        return "human"
    if verification_failed:
        return "develop_or_human"
    if completeness.get("test_complete"):
        return "caller"
    return "caller"


def failure_summary(results: list[ScenarioResult]) -> str:
    parts = []
    for row in results:
        if row.result in {"FAIL", "BLOCKED"}:
            extra = "; ".join(row.blockers) if row.blockers else row.result
            parts.append(f"{row.profile_id}: {extra}")
    return "; ".join(parts)


def _worst(rows: list[ScenarioResult]) -> ScenarioResult | None:
    if not rows:
        return None
    order = {"BLOCKED": 0, "FAIL": 1, "NOT_RUN": 2, "PASS": 3}
    return min(rows, key=lambda row: order.get(row.result, 0))

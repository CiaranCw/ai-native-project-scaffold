"""S4 Knowledge Consistency. Consumes Understand Knowledge Assessment; not lexical."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.knowledge_assessment import (
    IMPACT_SURFACES,
    impact_id_for,
    knowledge_impact_digest,
    knowledge_relevant_impacts,
    mapped_surface_paths,
    resolve_current_knowledge_assessment,
)
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.structural import STATUS_UNKNOWN


def evaluate_knowledge(
    *,
    root: Path,
    project: dict[str, Any] | None,
    maintenance: list[str],
    structural: dict[str, Any] | None = None,
    real_diff: dict[str, Any] | None = None,
    real_paths: list[str] | None = None,
    caller_flags: dict[str, Any] | None = None,
) -> dict[str, Any]:
    flags = dict(caller_flags or {})
    flags.pop("knowledge_assessment", None)
    del real_diff, real_paths
    needs_refresh = "NEEDS_REFRESH" in maintenance
    needs_migration = "NEEDS_MIGRATION" in maintenance
    raw_impacts = [
        row
        for row in (structural or {}).get("impacts") or []
        if isinstance(row, dict) and row.get("status") != STATUS_UNKNOWN
    ]
    relevant = knowledge_relevant_impacts(raw_impacts)
    required: list[str] = []
    checked: list[str] = []
    for row in relevant:
        kind = row["class"]
        if kind not in checked:
            checked.append(kind)
        for surface in mapped_surface_paths(row) or IMPACT_SURFACES.get(kind) or ():
            if surface not in required:
                required.append(surface)

    impact_digest = knowledge_impact_digest(relevant)
    candidate = observe_candidate(root)
    assessment_state = _resolve_assessment(
        root,
        locator=flags.get("knowledge_assessment_ref"),
        candidate_digest=candidate.digest if candidate.usable else "",
        impact_digest=impact_digest,
        required=relevant,
    )

    missing: list[str] = []
    updated: list[str] = []
    unknown_relevance: list[str] = []
    needs_human_impacts: list[str] = []
    needs_refresh_impacts: list[str] = []
    coverage_blockers: list[str] = list(assessment_state.get("blockers") or [])
    if relevant:
        if not assessment_state.get("ok"):
            for row in relevant:
                for surface in mapped_surface_paths(row):
                    if surface not in missing:
                        missing.append(surface)
                    if surface not in unknown_relevance:
                        unknown_relevance.append(surface)
        else:
            by_id = {
                str(item.get("impact_id")): item
                for item in (
                    (assessment_state.get("assessment") or {}).get("assessments")
                    or []
                )
                if isinstance(item, dict)
            }
            for row in relevant:
                iid = impact_id_for(row)
                assessed = by_id.get(iid)
                label = f"{row['class']}:{row['path']}"
                if assessed is None:
                    missing.extend(
                        surface
                        for surface in mapped_surface_paths(row)
                        if surface not in missing
                    )
                    coverage_blockers.append(
                        "Knowledge Assessment does not cover required impact "
                        + label
                    )
                    continue
                outcome = assessed.get("outcome")
                surfaces = [
                    str(item)
                    for item in (assessed.get("surfaces") or mapped_surface_paths(row))
                    if item
                ]
                if outcome == "SATISFIED":
                    for surface in surfaces:
                        if surface not in updated:
                            updated.append(surface)
                elif outcome == "NEEDS_HUMAN":
                    needs_human_impacts.append(label)
                    missing.extend(
                        surface for surface in surfaces if surface not in missing
                    )
                elif outcome == "NEEDS_REFRESH":
                    needs_refresh_impacts.append(label)
                    missing.extend(
                        surface for surface in surfaces if surface not in missing
                    )
                else:
                    unknown_relevance.extend(
                        surface for surface in surfaces if surface not in unknown_relevance
                    )
                    missing.extend(
                        surface for surface in surfaces if surface not in missing
                    )

    impact_stale = bool(relevant) and (
        not assessment_state.get("ok")
        or bool(missing)
        or bool(unknown_relevance)
        or bool(needs_human_impacts)
        or bool(needs_refresh_impacts)
        or bool(coverage_blockers)
    )
    stale = needs_refresh or needs_migration or impact_stale
    needs_human = bool(needs_human_impacts) or assessment_state.get("needs_human")
    route = ""
    if needs_migration:
        route = "understand.compatibility"
    elif needs_human:
        route = "human"
    elif stale:
        route = "understand.refresh"

    blockers: list[str] = []
    if needs_migration:
        blockers.append("knowledge/compatibility is stale or conflicting")
    elif needs_refresh:
        blockers.append("stale project knowledge requires Understand refresh")
    elif needs_human:
        blockers.append(
            "Knowledge Assessment requires human action: "
            + ", ".join(needs_human_impacts or ["HUMAN_OWNED knowledge"])
        )
    elif not candidate.usable:
        blockers.append(
            "Knowledge Assessment cannot be validated without a usable current candidate"
        )
    elif relevant and not assessment_state.get("ok"):
        blockers.extend(
            coverage_blockers
            or [
                "structural impact knowledge authority is UNKNOWN; "
                "Understand Knowledge Assessment is required"
            ]
        )
    elif needs_refresh_impacts:
        blockers.append(
            "Knowledge Assessment requires Understand refresh: "
            + ", ".join(needs_refresh_impacts)
        )
    elif unknown_relevance:
        blockers.append(
            "structural impact knowledge-update relevance is UNKNOWN: "
            + ", ".join(unknown_relevance)
        )
    elif impact_stale:
        blockers.append(
            "structural impact requires current knowledge authority: "
            + ", ".join(missing)
        )

    consistent = (
        not stale
        and not needs_migration
        and not needs_human
        and (not relevant or assessment_state.get("satisfied"))
    )
    return {
        "stale": stale,
        "needs_refresh": needs_refresh or impact_stale,
        "needs_migration": needs_migration,
        "needs_human": bool(needs_human),
        "route": route,
        "knowledge_consistent": consistent,
        "project_name": (project or {}).get("name"),
        "impact_classes": sorted(set(checked)),
        "required_surfaces": required,
        "updated_surfaces": updated,
        "missing_surfaces": missing,
        "unknown_relevance_surfaces": unknown_relevance,
        "impact_digest": impact_digest,
        "knowledge_assessment_ref": assessment_state.get("locator") or "",
        "assessment_state": assessment_state.get("reason") or "",
        "blockers": blockers,
    }


def _resolve_assessment(
    root: Path,
    *,
    locator: Any,
    candidate_digest: str,
    impact_digest: str,
    required: list[dict[str, str]],
) -> dict[str, Any]:
    if not required:
        return {"ok": True, "satisfied": True, "reason": "no_knowledge_impact"}
    if not candidate_digest:
        return {
            "ok": False,
            "satisfied": False,
            "blockers": [
                "Knowledge Assessment cannot be validated without a usable "
                "current candidate"
            ],
            "reason": "candidate_unavailable",
        }
    loaded = resolve_current_knowledge_assessment(
        root,
        candidate_digest=candidate_digest,
        impact_digest=impact_digest,
        locator=locator,
    )
    if not loaded.get("ok"):
        return {
            "ok": False,
            "satisfied": False,
            "blockers": list(
                loaded.get("blockers")
                or [
                    "structural impact knowledge authority is UNKNOWN; "
                    "Understand Knowledge Assessment is required"
                ]
            ),
            "reason": loaded.get("reason") or "missing",
            "locator": loaded.get("locator") or "",
        }
    assessment = loaded.get("assessment") or {}
    bound = ((assessment.get("candidate") or {}).get("candidate_digest") or "")
    if bound != candidate_digest:
        return {
            "ok": False,
            "satisfied": False,
            "assessment": assessment,
            "locator": loaded.get("locator"),
            "blockers": [
                "Knowledge Assessment candidate binding is stale for the "
                "current P6 candidate"
            ],
            "reason": "candidate_mismatch",
        }
    if str(assessment.get("impact_digest") or "") != impact_digest:
        return {
            "ok": False,
            "satisfied": False,
            "assessment": assessment,
            "locator": loaded.get("locator"),
            "blockers": [
                "Knowledge Assessment impact binding is stale for the current S3 "
                "knowledge-relevant impact set"
            ],
            "reason": "impact_mismatch",
        }
    outcomes = [
        str(item.get("outcome"))
        for item in assessment.get("assessments") or []
        if isinstance(item, dict)
    ]
    if any(item == "NEEDS_HUMAN" for item in outcomes):
        return {
            "ok": True,
            "satisfied": False,
            "needs_human": True,
            "assessment": assessment,
            "locator": loaded.get("locator"),
            "reason": "needs_human",
        }
    if not outcomes or any(item != "SATISFIED" for item in outcomes):
        return {
            "ok": True,
            "satisfied": False,
            "assessment": assessment,
            "locator": loaded.get("locator"),
            "reason": "not_satisfied",
        }
    required_ids = {impact_id_for(row) for row in required}
    present = {
        str(item.get("impact_id"))
        for item in assessment.get("assessments") or []
        if isinstance(item, dict)
    }
    if required_ids - present:
        return {
            "ok": False,
            "satisfied": False,
            "assessment": assessment,
            "locator": loaded.get("locator"),
            "blockers": [
                "Knowledge Assessment covers only a subset of required impacts"
            ],
            "reason": "partial",
        }
    return {
        "ok": True,
        "satisfied": True,
        "assessment": assessment,
        "locator": loaded.get("locator"),
        "reason": "satisfied",
    }

from __future__ import annotations

from typing import Any

from scaffold_p5.models import SkillResult


def skill_result(
    *,
    skill_id: str,
    skill_version: str,
    mode: str,
    outcome: str,
    baseline: dict[str, Any] | None = None,
    mutations: str = "none",
    artifacts: list[str] | None = None,
    evidence: list[str] | None = None,
    blockers: list[str] | None = None,
    next_route: str = "",
    compatibility: str | None = None,
    extras: dict[str, Any] | None = None,
) -> SkillResult:
    return SkillResult(
        skill_id=skill_id,
        skill_version=skill_version,
        mode=mode,
        outcome=outcome,
        baseline=baseline,
        mutations=mutations,
        artifacts=artifacts or [],
        evidence=evidence or [],
        blockers=blockers or [],
        next_route=next_route,
        compatibility=compatibility,
        extras=extras or {},
    )


def result_dict(result: SkillResult) -> dict[str, Any]:
    return {
        "skill_id": result.skill_id,
        "skill_version": result.skill_version,
        "mode": result.mode,
        "outcome": result.outcome,
        "baseline": result.baseline,
        "mutations": result.mutations,
        "artifacts": list(result.artifacts),
        "evidence": list(result.evidence),
        "blockers": list(result.blockers),
        "next_route": result.next_route,
        "compatibility": result.compatibility,
        "extras": dict(result.extras),
    }

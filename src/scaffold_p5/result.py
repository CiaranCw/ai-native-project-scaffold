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


def adoption_approval_human_gate(plan: Any) -> dict[str, str]:
    """Presentation-only gate. Canonical blockers may still name B4 internally."""
    extra = ""
    actions = getattr(plan, "actions", None) or []
    agents = next((action for action in actions if action.target == "AGENTS.md"), None)
    if agents is not None and agents.action_class == "MANAGED_UPDATE":
        extra = (
            " Existing AGENTS.md human text stays; a bounded Scaffold router "
            "region is proposed."
        )
    elif agents is not None and agents.client_strategy == "DEFER":
        extra = (
            " Existing AGENTS.md cannot be integrated automatically; the Agent "
            "router must be resolved before this host can become Active."
        )
    actions = list(getattr(plan, "actions", None) or [])
    envelope = [str(item) for item in (getattr(plan, "mutation_envelope", None) or [])]
    ownership = []
    managed = []
    preserved = []
    for action in actions:
        target = str(getattr(action, "target", "") or "")
        mode = str(getattr(action, "ownership", "") or "")
        if target and mode:
            ownership.append(f"{target}={mode}")
        region = getattr(action, "managed_region", None)
        if target and region:
            managed.append(f"{target}:{region}")
        if getattr(action, "action_class", "") == "PRESERVE" and target:
            preserved.append(target)
    return {
        "observed": "An Adoption Plan is ready. No project files have been changed.",
        "why_stopped": (
            "Preview is not apply. The Agent continues with an exact-plan "
            "apply request when machine preconditions still hold."
        ),
        "human_action_required": (
            "No human approval is required for Adoption. Continue bootstrap "
            "with this exact plan_id/plan_digest to apply. Git Commit and "
            "Push remain separately forbidden until an explicit user instruction."
            + extra
        ),
        "if_approved": (
            "The exact previewed plan is applied. If the proposal or host "
            "changes materially, preview again before apply."
        ),
        "remains_unchanged": (
            "Applying this plan is not Git Commit, Git Push, or permission to "
            "edit HUMAN_OWNED business source."
        ),
        "plan_id": str(getattr(plan, "plan_id", "") or ""),
        "plan_digest": str(getattr(plan, "digest", "") or ""),
        "mutation_envelope": ", ".join(envelope) if envelope else "none",
        "ownership_changes": ", ".join(ownership) if ownership else "none",
        "managed_regions": ", ".join(managed) if managed else "none",
        "preserved_surfaces": ", ".join(preserved) if preserved else "none",
        "generic_intent_is_not_approval": "true",
        "preview_is_not_apply": "true",
    }

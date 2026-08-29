from __future__ import annotations

from dataclasses import dataclass, field

from scaffold_p5.distribution import Distribution
from scaffold_p5.host_state import HostSnapshot, compare_adoption_state
from scaffold_p5.models import PackageRef
from scaffold_p5.packages import exact_match


@dataclass
class PreflightDecision:
    context: str
    host_class: str
    allowed: bool
    blockers: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    pinned_understand: PackageRef | None = None
    authority: str | None = None
    recovery_plan_path: str | None = None
    recovery_session_path: str | None = None
    intended_lock: dict | None = None
    extras: dict = field(default_factory=dict)


def run_preflight(snapshot: HostSnapshot, distribution: Distribution) -> PreflightDecision:
    context = snapshot.preflight_context
    if context == "PRE_ADOPTION_BOOTSTRAP":
        return _bootstrap_preflight(snapshot, distribution)
    return _host_preflight(snapshot, distribution)


def _bootstrap_preflight(snapshot: HostSnapshot, distribution: Distribution) -> PreflightDecision:
    blockers = list(snapshot.blockers)
    evidence = list(snapshot.evidence)
    evidence.append("preflight context=PRE_ADOPTION_BOOTSTRAP")
    if snapshot.project_view.status != "ABSENT":
        blockers.append(
            "fresh Bootstrap requires project.yaml evidence to be absent"
        )
    if snapshot.adoption_recovery.get("classification") != "NONE":
        blockers.append(
            "fresh Bootstrap requires Adoption recovery evidence=NONE"
        )
        blockers.extend(snapshot.adoption_recovery.get("blockers") or [])
    if snapshot.migration_recovery.get("classification") != "NONE":
        blockers.append(
            "fresh Bootstrap requires Migration recovery evidence=NONE"
        )
        blockers.extend(snapshot.migration_recovery.get("blockers") or [])
    release = distribution.selected_release
    actual = distribution.actual_understand
    if release is None:
        blockers.append("Selected Distribution Release is not uniquely determined")
        return PreflightDecision(
            context="PRE_ADOPTION_BOOTSTRAP",
            host_class=snapshot.host_class,
            allowed=False,
            blockers=blockers,
            evidence=evidence,
        )
    release_issues = distribution.release_issues(release)
    if release_issues:
        blockers.extend(release_issues)
        return PreflightDecision(
            context="PRE_ADOPTION_BOOTSTRAP",
            host_class=snapshot.host_class,
            allowed=False,
            blockers=blockers,
            evidence=evidence,
            authority=None,
        )
    selected_packages = distribution.selected_packages()
    for skill_id, package in sorted(selected_packages.items()):
        environment_result, environment_reasons = distribution.environment_issues(
            package,
            selected_packages,
        )
        if environment_result:
            blockers.extend(
                f"{skill_id} release dependency/environment: {reason}"
                for reason in environment_reasons
            )
    if actual.validity != "VALID":
        blockers.append("actual Understand package is INVALID: " + "; ".join(actual.validity_reasons))
        return PreflightDecision(
            context="PRE_ADOPTION_BOOTSTRAP",
            host_class=snapshot.host_class,
            allowed=False,
            blockers=blockers,
            evidence=evidence,
            pinned_understand=release.pinned("understand"),
            authority=None,
        )
    pinned = release.pinned("understand")
    ok, reasons = exact_match(pinned, actual)
    if not ok:
        blockers.append(
            "bootstrap identity mismatch: release-pinned Understand != actual resolved Understand ("
            + "; ".join(reasons)
            + ")"
        )
        blockers.append("BLOCK before bootstrap; no pre-lock COMPATIBLE substitution")
        return PreflightDecision(
            context="PRE_ADOPTION_BOOTSTRAP",
            host_class=snapshot.host_class,
            allowed=False,
            blockers=blockers,
            evidence=evidence,
            pinned_understand=pinned,
            authority=None,
        )
    modes = actual.manifest.get("modes") or []
    if "bootstrap" not in modes:
        blockers.append("Understand package does not declare bootstrap")
    for req in actual.manifest.get("requires") or []:
        if not distribution.satisfies(str(req), selected_packages):
            blockers.append(f"unsatisfied bootstrap requires: {req}")
    environment_result, environment_reasons = distribution.environment_issues(
        actual,
        selected_packages,
    )
    if environment_result:
        blockers.extend(environment_reasons)
    contracts = actual.manifest.get("contracts") or {}
    project_generations = [
        str(value) for value in contracts.get("project_contract_generations") or []
    ]
    if "1" not in project_generations:
        blockers.append("Understand does not establish target Project Contract generation 1")
    record_capabilities = contracts.get("record_schema_capabilities") or {}
    adoption_versions = [
        str(value) for value in record_capabilities.get("adoption_session") or []
    ]
    if "1" not in adoption_versions:
        blockers.append("Understand does not support Adoption Session schema 1")
    provides = actual.manifest.get("provides") or []
    if "understand.bootstrap" not in provides:
        blockers.append("Understand lacks required bootstrap capability declaration")
    allowed = not blockers
    intended = {
        skill: {
            "skill_version": release.pinned(skill).skill_version,
            "package_digest": release.pinned(skill).package_digest,
            "package_format_version": release.pinned(skill).package_format_version,
        }
        for skill in ("understand", "develop", "test", "submit")
    }
    return PreflightDecision(
        context="PRE_ADOPTION_BOOTSTRAP",
        host_class=snapshot.host_class,
        allowed=allowed,
        blockers=blockers,
        evidence=evidence,
        pinned_understand=pinned,
        authority="selected_distribution_release",
        intended_lock=intended,
        extras={"release_id": release.release_id, "package_validity": actual.validity},
    )


def _host_preflight(snapshot: HostSnapshot, distribution: Distribution) -> PreflightDecision:
    evidence = list(snapshot.evidence)
    blockers = list(snapshot.blockers)
    evidence.append("preflight context=HOST_COMPATIBILITY")
    if snapshot.host_class == "INTERRUPTED_INITIAL_ADOPTION":
        return _interrupted_recovery(snapshot, distribution, evidence, blockers)
    if snapshot.host_class == "ESTABLISHED_HOST":
        from scaffold_p5.compatibility import evaluate_host

        evaluation = evaluate_host(snapshot, distribution)
        overall = evaluation.get("overall")
        allowed = bool(
            evaluation.get("ok") and overall in {"EXACT", "COMPATIBLE"}
        )
        if not allowed:
            blockers.extend(evaluation.get("blockers") or [])
            if overall:
                blockers.append(f"host compatibility preflight result={overall}")
        return PreflightDecision(
            context="HOST_COMPATIBILITY",
            host_class=snapshot.host_class,
            allowed=allowed,
            blockers=blockers,
            evidence=evidence,
            authority="skills.lock",
            extras={
                "lock_status": snapshot.lock.status,
                "compatibility": overall,
                "evaluation": evaluation,
            },
        )
    if snapshot.host_class == "ESTABLISHED_HOST_CONSISTENCY":
        blockers.append("historical Adoption Plan is not reusable lock authority")
        return PreflightDecision(
            context="HOST_COMPATIBILITY",
            host_class=snapshot.host_class,
            allowed=False,
            blockers=blockers,
            evidence=evidence,
            authority=None,
        )
    return PreflightDecision(
        context="HOST_COMPATIBILITY",
        host_class=snapshot.host_class,
        allowed=False,
        blockers=blockers or ["host/recovery evidence without safe authority"],
        evidence=evidence,
    )


def _interrupted_recovery(
    snapshot: HostSnapshot,
    distribution: Distribution,
    evidence: list[str],
    blockers: list[str],
) -> PreflightDecision:
    usable = _usable_sessions(snapshot)
    if not usable:
        blockers.append("no recoverable current Adoption Session")
        return _recovery_block(snapshot, evidence, blockers)
    if len(usable) != 1:
        blockers.append(
            f"ambiguous interrupted Adoption: {len(usable)} recoverable current Sessions"
        )
        return _recovery_block(snapshot, evidence, blockers)
    session = usable[0]
    from pathlib import Path
    from scaffold_p5.io_util import read_yaml
    from scaffold_p5.adoption import validate_plan_content

    plan_file = Path(session["_dir"]) / "plan.yaml"
    if not plan_file.exists():
        blockers.append("Plan identity/content is not recoverable")
        return _recovery_block(snapshot, evidence, blockers, session.get("_path"))
    try:
        plan = read_yaml(plan_file)
    except (OSError, ValueError, TypeError):
        blockers.append("Plan identity/content is malformed or unreadable")
        return _recovery_block(snapshot, evidence, blockers, session.get("_path"))
    if not isinstance(plan, dict):
        blockers.append("Plan identity/content is not a mapping")
        return _recovery_block(snapshot, evidence, blockers, session.get("_path"))
    blockers.extend(validate_plan_content(plan))
    plan_binding = session.get("plan") or {}
    if plan_binding.get("digest") != plan.get("digest"):
        blockers.append("Session/Plan digest binding failed")
    if plan_binding.get("identity") != plan.get("plan_id"):
        blockers.append("Session does not identify the applicable Plan")
    observed = bool(plan_binding.get("observed_approved"))
    if not observed:
        blockers.append("P1 Human Plan Approval is not observed as applicable")
    evidence.append("observed_approved is revalidation input, not permission")
    if session.get("baseline") != plan.get("baseline"):
        blockers.append("Session Adoption Baseline does not match Plan")
    if session.get("intended_lock") != plan.get("intended_lock"):
        blockers.append("Session intended lock does not match Plan")
    if session.get("mutation_envelope") != plan.get("mutation_envelope"):
        blockers.append("Session mutation envelope does not match Plan")
    if session.get("release_id") != plan.get("release_id"):
        blockers.append("Session Selected Distribution Release does not match Plan")

    state_issues = compare_adoption_state(
        snapshot.root,
        plan.get("baseline") or {},
        list(plan.get("mutation_envelope") or []),
        session,
    )
    blockers.extend(state_issues)

    release_id = plan.get("release_id")
    release = distribution.release(str(release_id)) if release_id else None
    if snapshot.lock.complete_authoritative:
        return _authoritative_lock_activation_recovery(
            snapshot,
            distribution,
            session,
            plan,
            plan_file,
            evidence,
            blockers,
            observed,
        )

    if release is None:
        blockers.append("exact Selected Distribution Release is not resolvable")
        return _recovery_block(snapshot, evidence, blockers, session.get("_path"), str(plan_file))
    blockers.extend(distribution.release_issues(release))
    pinned = release.pinned("understand")
    plan_u = plan.get("pinned_understand") or {}
    if plan_u.get("package_digest") != pinned.package_digest or plan_u.get("skill_version") != pinned.skill_version:
        blockers.append("Plan Understand identity does not match resolvable release pin")
    actual = distribution.actual_understand
    ok, reasons = exact_match(pinned, actual)
    if not ok:
        blockers.append(
            "recovery Understand is not the exact release-pinned identity (" + "; ".join(reasons) + ")"
        )
        blockers.append("no pre-lock COMPATIBLE substitution")
    intended = plan.get("intended_lock")
    if not isinstance(intended, dict) or set(intended) != {"understand", "develop", "test", "submit"}:
        blockers.append("Plan does not bind a coherent exact four-Skill initial lock")
    else:
        for skill, entry in intended.items():
            pinned_skill = release.pinned(skill)
            if entry.get("skill_version") != pinned_skill.skill_version:
                blockers.append(f"intended lock {skill} is not the selected release pin")
            if entry.get("package_digest") != pinned_skill.package_digest:
                blockers.append(f"intended lock {skill} digest is not the selected release pin")
    if snapshot.lock.status in {
        "partial",
        "incomplete",
        "malformed",
        "unpublished",
        "complete_candidate",
    }:
        evidence.append(f"lock status={snapshot.lock.status} is recovery evidence, not authority")
    if snapshot.lock.data and snapshot.lock.status == "complete_candidate":
        if snapshot.lock.data.get("skills") != intended:
            blockers.append("complete candidate lock differs from approved intended lock")
    allowed = not blockers
    return PreflightDecision(
        context="HOST_COMPATIBILITY",
        host_class=snapshot.host_class,
        allowed=allowed,
        blockers=blockers,
        evidence=evidence,
        pinned_understand=pinned,
        authority="approved_plan_selected_release" if allowed else None,
        recovery_plan_path=str(plan_file),
        recovery_session_path=session.get("_path"),
        intended_lock=intended if isinstance(intended, dict) else None,
        extras={
            "release_id": release.release_id,
            "plan_digest": plan.get("digest"),
            "observed_approved": observed,
            "package_validity": actual.validity,
            "state_comparison": "expected approved prefix" if allowed else "diverged",
        },
    )


def _recovery_block(
    snapshot: HostSnapshot,
    evidence: list[str],
    blockers: list[str],
    session_path: str | None = None,
    plan_path: str | None = None,
) -> PreflightDecision:
    return PreflightDecision(
        context="HOST_COMPATIBILITY",
        host_class=snapshot.host_class,
        allowed=False,
        blockers=blockers,
        evidence=evidence,
        recovery_session_path=session_path,
        recovery_plan_path=plan_path,
    )


def _usable_sessions(snapshot: HostSnapshot) -> list[dict]:
    return [
        session
        for session in snapshot.sessions
        if session.get("status") in {"OPEN", "INTERRUPTED", "BLOCKED"}
    ]


def _authoritative_lock_activation_recovery(
    snapshot: HostSnapshot,
    distribution: Distribution,
    session: dict,
    plan: dict,
    plan_file,
    evidence: list[str],
    blockers: list[str],
    observed: bool,
) -> PreflightDecision:
    checkpoints = set(session.get("checkpoints") or [])
    if "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints:
        if "B7_PASSED" in checkpoints:
            evidence.append(
                "authoritative lock matches B7-passed candidate; interrupted checkpoint publication is recoverable"
            )
        else:
            blockers.append(
                "authoritative initial lock exists without B7/lock-authority Adoption checkpoint"
            )
    intended = plan.get("intended_lock")
    if (snapshot.lock.data or {}).get("skills") != intended:
        blockers.append("authoritative initial lock differs from approved intended lock")
    entry = ((snapshot.lock.data or {}).get("skills") or {}).get("understand") or {}
    pinned = PackageRef(
        skill_id="understand",
        skill_version=str(entry.get("skill_version") or ""),
        package_digest=str(entry.get("package_digest") or ""),
        package_format_version=str(entry.get("package_format_version") or ""),
    )
    ok, reasons = exact_match(pinned, distribution.actual_understand)
    if not ok:
        blockers.append(
            "actual recovery Understand does not match authoritative lock: "
            + "; ".join(reasons)
        )
    evidence.append(
        "authoritative skills.lock drives activation recovery; Plan release authority expired"
    )
    allowed = not blockers
    return PreflightDecision(
        context="HOST_COMPATIBILITY",
        host_class=snapshot.host_class,
        allowed=allowed,
        blockers=blockers,
        evidence=evidence,
        pinned_understand=pinned,
        authority="skills.lock" if allowed else None,
        recovery_plan_path=str(plan_file),
        recovery_session_path=session.get("_path"),
        intended_lock=intended if isinstance(intended, dict) else None,
        extras={
            "plan_digest": plan.get("digest"),
            "observed_approved": observed,
            "lock_status": snapshot.lock.status,
            "state_comparison": "expected approved prefix" if allowed else "diverged",
        },
    )

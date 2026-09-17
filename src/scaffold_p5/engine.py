from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.adoption import (
    SKILLS_LOCK,
    approval_matches,
    build_adoption_plan,
    delete_session,
    persist_session,
    plan_from_dict,
    plan_to_dict,
    ownership_presentation,
    preservation_presentation,
    publish_lock_authority,
    rebuild_adoption_plan,
    replace_session_plan,
    update_session,
)
from scaffold_p5.compatibility import evaluate_host, lock_update_plan
from scaffold_p5.ownership_update import (
    apply_ownership_update,
    build_ownership_update_plan,
)
from scaffold_p5.discovery import critical_unresolved, discover
from scaffold_p5.distribution import Distribution
from scaffold_p5.full import (
    active_project_digest,
    activate_project,
    expected_normalization_mutations,
    normalize,
)
from scaffold_p5.currentness import evaluate_understanding_currentness
from scaffold_p5.host_state import (
    PROJECT_YAML,
    compare_adoption_state,
    inspect_lock,
    inspect_project,
    snapshot_host,
)
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.migration import (
    CONTRACT_GENERATION_UPDATED,
    VALIDATION_PASSED,
    apply_contract_generation,
    approval_matches as migration_approval_matches,
    bindings_still_hold,
    build_migration_plan,
    complete_migration,
    consume_compatibility_boundary,
    delete_execution,
    derive_migration_target,
    load_execution,
    mark_needs_migration,
    mark_recovery_required,
    reconcile_execution_checkpoint,
    save_execution,
    validate_applied_state,
    validate_recovery_state,
)
from scaffold_p5.models import AdoptionPlan, DiscoveryFact, UNDERSTAND_MODES
from scaffold_p5.packages import exact_match
from scaffold_p5.preflight import PreflightDecision, run_preflight
from scaffold_p5.knowledge_assessment import publish_knowledge_assessment
from scaffold_p5.refresh import refresh_host, refreshable_ownership_contract_host
from scaffold_p5.refresh_completion import produce_refresh_completion
from scaffold_p5.result import adoption_approval_human_gate, skill_result
from scaffold_p5.resume import resume_project
from scaffold_p5.schemas import whole_file_mutation_allowed
from scaffold_p5.understanding import persist_project_understanding


class UnderstandEngine:
    def __init__(
        self,
        host_root: str | Path,
        distribution: Distribution,
    ):
        self.root = Path(host_root)
        self.distribution = distribution

    def run(self, mode: str, **opts: Any):
        opts.pop("authorization_provider", None)
        opts.pop("approval_origin", None)
        opts.pop("adoption_authorization_ref", None)
        opts.pop("adoption_authorization_attempt_id", None)
        actual = self.distribution.actual_understand
        if mode not in UNDERSTAND_MODES:
            return skill_result(
                skill_id="understand",
                skill_version=actual.ref.skill_version,
                mode=mode,
                outcome="FAILED",
                blockers=[f"unsupported Understand mode: {mode}"],
                next_route="stop",
            )
        snapshot = snapshot_host(self.root)
        preflight = run_preflight(snapshot, self.distribution)
        recovery_isolation = (
            snapshot.lifecycle == "RECOVERY_REQUIRED"
            or bool(snapshot.migration_recovery.get("requires_isolation"))
        )
        resume_ok = (
            mode == "refresh" and str(opts.get("action") or "").strip() == "resume"
        )
        if recovery_isolation and mode in {"full", "refresh"} and not resume_ok:
            return self._base(
                mode,
                "BLOCKED",
                mutations="none",
                blockers=[
                    "migration recovery evidence or RECOVERY_REQUIRED lifecycle isolates persistent host maintenance"
                ]
                + list(snapshot.migration_recovery.get("blockers") or []),
                next_route="understand/compatibility migrate recovery",
                extras={
                    "preflight_context": preflight.context,
                    "host_class": snapshot.host_class,
                    "migration_recovery_isolation": True,
                    "migration_recovery": snapshot.migration_recovery,
                },
            )
        if mode == "bootstrap":
            return self._bootstrap(snapshot, preflight, opts)
        if mode == "full":
            return self._full(snapshot, preflight, opts)
        if mode == "refresh":
            return self._refresh(snapshot, preflight, opts)
        return self._compatibility(snapshot, preflight, opts)

    def _base(self, mode: str, outcome: str, **kwargs):
        actual = self.distribution.actual_understand
        kwargs.setdefault("skill_id", "understand")
        kwargs.setdefault("skill_version", actual.ref.skill_version)
        kwargs.setdefault("mode", mode)
        kwargs.setdefault("outcome", outcome)
        extras = kwargs.get("extras") or {}
        extras.setdefault("package_validity", actual.validity)
        kwargs["extras"] = extras
        return skill_result(**kwargs)

    def _bootstrap(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        extras = {
            "preflight_context": preflight.context,
            "host_class": preflight.host_class,
            "authority": preflight.authority,
            "preflight_evidence": preflight.evidence,
        }
        if snapshot.host_class not in {"NOT_ADOPTED", "INTERRUPTED_INITIAL_ADOPTION"}:
            return self._base(
                "bootstrap",
                "BLOCKED",
                baseline=_baseline(snapshot),
                blockers=preflight.blockers or ["bootstrap is not available for this host class"],
                next_route="understand/compatibility or recovery",
                extras=extras,
            )
        if snapshot.host_class == "NOT_ADOPTED" and preflight.context != "PRE_ADOPTION_BOOTSTRAP":
            return self._base(
                "bootstrap",
                "BLOCKED",
                blockers=["fresh bootstrap requires Pre-Adoption Bootstrap Preflight"],
                extras=extras,
            )
        if not preflight.allowed:
            if (
                snapshot.host_class == "INTERRUPTED_INITIAL_ADOPTION"
                and opts.get("replan")
            ):
                return self._replan_adoption(snapshot, preflight, opts, extras)
            return self._base(
                "bootstrap",
                "BLOCKED",
                baseline=_baseline(snapshot),
                blockers=preflight.blockers,
                next_route=(
                    "re-discover / re-plan / exact-plan apply"
                    if snapshot.host_class == "INTERRUPTED_INITIAL_ADOPTION"
                    else "resolve release/package identity"
                ),
                extras=extras,
            )
        extra_facts = list(opts.get("extra_facts") or [])
        if snapshot.host_class == "INTERRUPTED_INITIAL_ADOPTION":
            return self._resume_adoption(snapshot, preflight, extra_facts, opts, extras)
        facts = discover(self.root, extra_facts)
        extras["facts"] = [
            {"name": f.name, "value": f.value, "confidence": f.confidence, "critical": f.critical}
            for f in facts
        ]
        plan = build_adoption_plan(
            self.root,
            facts=facts,
            distribution=self.distribution,
            preflight=preflight,
            derived_copy=bool(opts.get("derived_copy")),
        )
        extras["plan"] = plan_to_dict(plan)
        extras["preservation_presentation"] = preservation_presentation(plan)
        extras["ownership_presentation"] = ownership_presentation(plan)
        extras["authority"] = "selected_distribution_release"
        extras["human_gate"] = adoption_approval_human_gate(plan)
        extras["preview_is_not_approval"] = True
        extras["generic_adoption_intent_is_not_plan_approval"] = True
        extras["exact_plan_apply_required"] = True
        extras["exact_plan_approval_required"] = True
        authority = self._adoption_apply_requested(plan, opts, extras)
        if not authority["ok"]:
            return self._base(
                "bootstrap",
                "NEEDS_HUMAN",
                baseline=plan.baseline,
                mutations="none",
                blockers=[authority["reason"]],
                next_route="understand.bootstrap apply of this exact plan",
                evidence=["B1/B2 read-only; no persistent host mutation"],
                extras=extras,
            )
        if _plan_stale_vs_host(self.root, plan):
            return self._base(
                "bootstrap",
                "NEEDS_HUMAN",
                baseline=plan.baseline,
                mutations="none",
                blockers=["apply request Plan is materially stale versus current host"],
                next_route="re-discover / re-plan / exact-plan apply",
                extras=extras,
            )
        return self._apply_adoption(plan, extra_facts, opts, extras, resume_dir=None)

    def _resume_adoption(self, snapshot, preflight: PreflightDecision, extra_facts, opts, extras):
        from pathlib import Path as P

        if not preflight.recovery_plan_path or not preflight.recovery_session_path:
            return self._base("bootstrap", "BLOCKED", blockers=preflight.blockers, extras=extras)
        plan = plan_from_dict(read_yaml(preflight.recovery_plan_path))
        if opts.get("replan"):
            return self._replan_adoption(snapshot, preflight, opts, extras, plan=plan)
        extras["plan"] = plan_to_dict(plan)
        extras["preservation_presentation"] = preservation_presentation(plan)
        extras["ownership_presentation"] = ownership_presentation(plan)
        extras["authority"] = "approved_plan_selected_release"
        extras["zero_context_recovery"] = True
        extras["human_gate"] = adoption_approval_human_gate(plan)
        extras["preview_is_not_approval"] = True
        extras["generic_adoption_intent_is_not_plan_approval"] = True
        extras["exact_plan_apply_required"] = True
        extras["exact_plan_approval_required"] = True
        authority = self._adoption_apply_requested(plan, opts, extras)
        if not authority["ok"]:
            return self._base(
                "bootstrap",
                "NEEDS_HUMAN",
                baseline=plan.baseline,
                mutations="none",
                blockers=[
                    "persisted observed_approved is not standing permission; "
                    + authority["reason"]
                ],
                next_route="understand.bootstrap apply of this exact plan",
                extras=extras,
            )
        session_data = read_yaml(preflight.recovery_session_path)
        divergence = compare_adoption_state(
            self.root,
            plan.baseline,
            plan.mutation_envelope,
            session_data,
        )
        if divergence:
            return self._base(
                "bootstrap",
                "NEEDS_HUMAN",
                blockers=["host diverged from apply envelope; re-plan required"]
                + divergence,
                next_route="re-discover / re-plan / exact-plan apply",
                extras=extras,
            )
        session_dir = P(preflight.recovery_session_path).parent
        return self._apply_adoption(plan, extra_facts, opts, extras, resume_dir=session_dir)

    def _replan_adoption(
        self,
        snapshot,
        preflight: PreflightDecision,
        opts: dict[str, Any],
        extras: dict[str, Any],
        *,
        plan: AdoptionPlan | None = None,
    ):
        if not preflight.recovery_plan_path or not preflight.recovery_session_path:
            return self._base(
                "bootstrap",
                "BLOCKED",
                blockers=preflight.blockers
                or ["re-plan requires one unambiguous current Adoption Session/Plan"],
                next_route="human resolution of ambiguous Adoption Sessions",
                extras=extras,
            )
        old = plan or plan_from_dict(read_yaml(preflight.recovery_plan_path))
        if snapshot.lock.complete_authoritative:
            return self._base(
                "bootstrap",
                "BLOCKED",
                blockers=[
                    "replacement Plan cannot revive release authority after authoritative lock handoff"
                ],
                next_route="authoritative-lock activation recovery",
                extras=extras,
            )
        release = self.distribution.release(old.release_id)
        release_issues = (
            ["replacement Plan Selected Distribution Release is unavailable"]
            if release is None
            else self.distribution.release_issues(release)
        )
        exact, identity_issues = exact_match(
            old.pinned_understand,
            self.distribution.actual_understand,
        )
        if release_issues or not exact:
            return self._base(
                "bootstrap",
                "BLOCKED",
                blockers=release_issues
                + ([] if exact else ["replacement Plan bootstrap identity mismatch"] + identity_issues),
                next_route="resolve exact Distribution release/package identity before re-planning",
                extras=extras,
            )
        facts = discover(self.root, list(opts.get("extra_facts") or []))
        session_data = read_yaml(preflight.recovery_session_path)
        replacement = rebuild_adoption_plan(
            self.root,
            old,
            facts,
            session_data,
        )
        extras["plan"] = plan_to_dict(replacement)
        extras["preservation_presentation"] = preservation_presentation(replacement)
        extras["ownership_presentation"] = ownership_presentation(replacement)
        extras["human_gate"] = adoption_approval_human_gate(replacement)
        extras["preview_is_not_approval"] = True
        extras["generic_adoption_intent_is_not_plan_approval"] = True
        extras["exact_plan_apply_required"] = True
        extras["exact_plan_approval_required"] = True
        extras["replaces_plan"] = old.plan_id
        extras["authority"] = None
        if not self._adoption_apply_requested(replacement, opts, extras)["ok"]:
            return self._base(
                "bootstrap",
                "NEEDS_HUMAN",
                baseline=replacement.baseline,
                mutations="none",
                blockers=[
                    "replacement Adoption Plan requires a new exact-plan apply request"
                ],
                next_route="understand.bootstrap apply of the replacement plan",
                extras=extras,
            )
        session_dir = Path(preflight.recovery_session_path).parent
        replace_session_plan(session_dir, replacement)
        return self._apply_adoption(
            replacement,
            list(opts.get("extra_facts") or []),
            opts,
            extras,
            resume_dir=session_dir,
        )

    def _adoption_apply_requested(
        self, plan: AdoptionPlan, opts: dict[str, Any], extras: dict[str, Any]
    ) -> dict[str, Any]:
        """Exact-plan apply request. Not human approval and not a grant.

        `--approved --plan-digest` selects which previewed Plan to apply. It
        has no Commit/Push meaning.
        """
        extras["apply_request"] = {
            "plan_id": plan.plan_id,
            "plan_digest": plan.digest,
            "is_not_human_approval": True,
            "is_not_commit_or_push": True,
        }
        if not approval_matches(plan, opts.get("approval")):
            return {
                "ok": False,
                "reason": (
                    "exact Adoption Plan apply request is required; "
                    "preview is not apply and generated Plan is not permission"
                ),
            }
        return {"ok": True, "reason": ""}

    def _apply_adoption(self, plan: AdoptionPlan, extra_facts, opts, extras, resume_dir):
        preserve_truncation = [
            item
            for item in plan.activation_blockers
            if item.startswith("human_owned_preservation:")
        ]
        if preserve_truncation:
            return self._base(
                "bootstrap",
                "BLOCKED",
                blockers=list(preserve_truncation)
                + ["human-owned preservation discovery is incomplete; Apply is unsafe"],
                next_route="understand.bootstrap",
                extras=extras,
            )
        existing_agents = (self.root / "AGENTS.md").exists() and any(
            a.target == "AGENTS.md" and a.action_class == "PRESERVE" for a in plan.actions
        )
        preserve_bytes = {
            a.target: (self.root / a.target).read_bytes()
            for a in plan.actions
            if a.action_class == "PRESERVE" and (self.root / a.target).is_file()
        }
        derived = bool(opts.get("derived_copy")) or any(
            a.target == ".scaffold/derived/understand.md" for a in plan.actions
        )
        interrupt_after = opts.get("interrupt_after")
        if resume_dir is None:
            session_dir = persist_session(
                self.root,
                plan,
                status="OPEN",
                steps=["B1", "B2", "B3", "B4"],
                checkpoints=[],
                mutations=[],
                observed_approved=True,
            )
        else:
            session_dir = resume_dir
            update_session(session_dir, status="OPEN")
        session_data = read_yaml(session_dir / "session.yaml")
        if session_data.get("expected_mutations_plan_id") != plan.plan_id:
            expected_mutations = expected_normalization_mutations(
                self.root,
                plan,
                extra_facts=extra_facts,
                existing_agents_human=existing_agents,
                derived_copy=derived,
            )
            update_session(
                session_dir,
                expected_mutations_plan_id=plan.plan_id,
                expected_mutations=expected_mutations,
            )
            session_data = read_yaml(session_dir / "session.yaml")
        checkpoints = set(session_data.get("checkpoints") or [])
        current_lock = snapshot_host(self.root).lock
        if (
            current_lock.complete_authoritative
            and "B7_PASSED" in checkpoints
            and "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints
        ):
            checkpoints.add("LOCK_AUTHORITY_ESTABLISHED")
            update_session(
                session_dir,
                checkpoints=["B7_PASSED", "LOCK_AUTHORITY_ESTABLISHED"],
                pending_validation=["B8"],
            )
        artifacts = [
            mutation.get("target")
            for mutation in session_data.get("applied_mutation_summary") or []
            if isinstance(mutation, dict) and mutation.get("target")
        ]

        if "B8_ACTIVE" in checkpoints:
            current = snapshot_host(self.root)
            if current.lifecycle != "ACTIVE" or not current.lock.complete_authoritative:
                return self._base(
                    "bootstrap",
                    "BLOCKED",
                    blockers=["B8 checkpoint does not match actual ACTIVE/lock state"],
                    next_route="re-discover / re-plan / human approval",
                    extras=extras,
                )
            delete_session(session_dir)
            extras["authority"] = "skills.lock"
            return self._base(
                "bootstrap",
                "COMPLETED",
                baseline=plan.baseline,
                mutations="bounded",
                artifacts=[PROJECT_YAML, SKILLS_LOCK],
                evidence=["B8 ACTIVE revalidated", "B9 session cleaned"],
                next_route="understand/refresh or develop",
                extras=extras,
            )

        if "B7_PASSED" not in checkpoints and "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints:
            normalized_artifacts = normalize(
                self.root,
                plan,
                lifecycle="ADOPTING",
                extra_facts=extra_facts,
                interrupt_after=interrupt_after,
                existing_agents_human=existing_agents,
                derived_copy=derived,
                preserve_bytes=preserve_bytes,
            )
            artifacts = sorted(set(artifacts + normalized_artifacts))
        mutations = _mutation_observations(self.root, plan, artifacts)
        if interrupt_after in {
            "project_yaml",
            "before_lock",
            "partial_lock",
            "after_b6",
        }:
            update_session(
                session_dir,
                status="INTERRUPTED",
                completed_steps=["B1", "B2", "B3", "B4", "B5", "B6"],
                checkpoints=["B6_COMPLETE", interrupt_after],
                applied_mutation_summary=mutations,
            )
            extras["session"] = str(session_dir)
            extras["authority"] = (
                "skills.lock"
                if snapshot_host(self.root).lock.complete_authoritative
                else "approved_plan_selected_release"
            )
            return self._base(
                "bootstrap",
                "BLOCKED",
                baseline=plan.baseline,
                mutations="partial",
                artifacts=artifacts,
                blockers=[f"interrupted after {interrupt_after}"],
                next_route="resume Understand/bootstrap from Session/Plan",
                extras=extras,
            )
        if "B7_PASSED" not in checkpoints and "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints:
            critical = critical_unresolved(discover(self.root, extra_facts))
        else:
            critical = []
        if critical:
            update_session(
                session_dir,
                status="BLOCKED",
                completed_steps=["B1", "B2", "B3", "B4", "B5", "B6"],
                checkpoints=["B6_COMPLETE"],
                applied_mutation_summary=mutations,
                pending_validation=["B7"],
            )
            extras["critical_facts"] = [f.name for f in critical]
            blockers = ["B7 FAIL: unresolved critical UNKNOWN/CONFLICTING"] + [
                f"{f.name}:{f.confidence}" for f in critical
            ]
            agents_action = next(
                (action for action in plan.actions if action.target == "AGENTS.md"),
                None,
            )
            if agents_action and agents_action.action_class == "MANAGED_UPDATE":
                blockers.append("approved AGENTS integration did not materialize")
            return self._base(
                "bootstrap",
                "FAILED",
                baseline=plan.baseline,
                mutations="bounded",
                artifacts=artifacts,
                blockers=blockers,
                next_route="re-run bootstrap with replan=true; review replacement Plan; no activation waiver",
                extras=extras,
            )
        leaked = _envelope_breach(self.root, plan, artifacts)
        if leaked:
            update_session(session_dir, status="BLOCKED")
            return self._base(
                "bootstrap",
                "FAILED",
                mutations="bounded",
                artifacts=artifacts,
                blockers=["B7 FAIL: mutation outside approved envelope"] + leaked,
                extras=extras,
            )
        state_issues = compare_adoption_state(
            self.root,
            plan.baseline,
            plan.mutation_envelope,
            {
                "applied_mutation_summary": mutations,
            },
        )
        if state_issues:
            update_session(
                session_dir,
                status="BLOCKED",
                checkpoints=["B6_COMPLETE"],
                applied_mutation_summary=mutations,
            )
            return self._base(
                "bootstrap",
                "FAILED",
                mutations="bounded",
                artifacts=artifacts,
                blockers=["B7 FAIL: actual durable state diverged"] + state_issues,
                next_route="re-discover / re-plan / exact-plan apply",
                extras=extras,
            )

        if "B7_PASSED" not in checkpoints and "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints:
            update_session(
                session_dir,
                status="OPEN",
                completed_steps=["B1", "B2", "B3", "B4", "B5", "B6", "B7"],
                checkpoints=["B7_PASSED"],
                applied_mutation_summary=mutations,
                pending_validation=["B8"],
            )
            checkpoints.add("B7_PASSED")
        if interrupt_after == "after_b7":
            update_session(session_dir, status="INTERRUPTED")
            extras["authority"] = "approved_plan_selected_release"
            return self._base(
                "bootstrap",
                "BLOCKED",
                baseline=plan.baseline,
                mutations="partial",
                artifacts=artifacts,
                blockers=["interrupted after B7 validation"],
                next_route="resume activation from B7_PASSED checkpoint",
                extras=extras,
            )

        if "LOCK_AUTHORITY_ESTABLISHED" not in checkpoints:
            lock_issues = publish_lock_authority(
                self.root,
                plan.intended_lock,
                plan.release_id,
            )
            if lock_issues:
                update_session(session_dir, status="BLOCKED")
                return self._base(
                    "bootstrap",
                    "FAILED",
                    mutations="bounded",
                    artifacts=artifacts,
                    blockers=["initial-lock authority handoff failed"] + lock_issues,
                    next_route="Adoption recovery",
                    extras=extras,
                )
            if interrupt_after == "lock_written_before_checkpoint":
                update_session(session_dir, status="INTERRUPTED")
                extras["authority"] = "skills.lock"
                return self._base(
                    "bootstrap",
                    "BLOCKED",
                    mutations="partial",
                    artifacts=artifacts,
                    blockers=["interrupted after lock publication before Session checkpoint"],
                    next_route="reconcile authoritative lock with B7_PASSED checkpoint",
                    extras=extras,
                )
            update_session(
                session_dir,
                status="OPEN",
                checkpoints=["B7_PASSED", "LOCK_AUTHORITY_ESTABLISHED"],
                applied_mutation_summary=_mutation_observations(
                    self.root,
                    plan,
                    artifacts,
                ),
                pending_validation=["B8"],
            )
            checkpoints.add("LOCK_AUTHORITY_ESTABLISHED")
        if interrupt_after == "lock_authority":
            update_session(session_dir, status="INTERRUPTED")
            extras["authority"] = "skills.lock"
            return self._base(
                "bootstrap",
                "BLOCKED",
                baseline=plan.baseline,
                mutations="partial",
                artifacts=artifacts,
                blockers=["interrupted after initial-lock authority handoff"],
                next_route="resume B8 using authoritative skills.lock",
                extras=extras,
            )

        expected_active_digest = active_project_digest(
            self.root,
            plan,
            extra_facts,
            derived,
            existing_agents,
        )
        update_session(
            session_dir,
            expected_active_project_digest=expected_active_digest,
        )
        activate_project(self.root, plan, extra_facts, derived, existing_agents)
        # The host is now ACTIVE at the adopted generation, so it is already
        # post-boundary and opens an empty drift register. A freshly adopted
        # host never receives legacy compatibility amnesty (FND5-E12).
        extras["compatibility_boundary"] = consume_compatibility_boundary(
            self.root,
            classify_inherited=False,
        )
        mutations = _mutation_observations(self.root, plan, artifacts)
        update_session(
            session_dir,
            status="OPEN",
            completed_steps=["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"],
            checkpoints=["B7_PASSED", "LOCK_AUTHORITY_ESTABLISHED", "B8_ACTIVE"],
            applied_mutation_summary=mutations,
            pending_validation=[],
        )
        if interrupt_after == "active_before_cleanup":
            update_session(session_dir, status="INTERRUPTED")
            extras["authority"] = "skills.lock"
            return self._base(
                "bootstrap",
                "BLOCKED",
                mutations="bounded",
                artifacts=artifacts,
                blockers=["interrupted after B8 before B9 cleanup"],
                next_route="revalidate ACTIVE state and clean current Adoption Session",
                extras=extras,
            )
        delete_session(session_dir)
        extras["authority"] = "skills.lock"
        extras["authority_handoff"] = "complete four-Skill lock is durable expected-version SSOT"
        return self._base(
            "bootstrap",
            "COMPLETED",
            baseline=plan.baseline,
            mutations="bounded",
            artifacts=sorted(set(artifacts + [PROJECT_YAML, SKILLS_LOCK])),
            evidence=["B7 passed", "B8 ACTIVE", "B9 session cleaned"],
            next_route="understand/refresh or develop",
            extras=extras,
        )

    def _full(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        if snapshot.host_class == "NOT_ADOPTED":
            return self._base(
                "full",
                "BLOCKED",
                blockers=["ordinary first attachment must use Understand/bootstrap"],
                extras={"preflight_context": preflight.context, "host_class": snapshot.host_class},
            )
        if snapshot.host_class == "INTERRUPTED_INITIAL_ADOPTION":
            return self._bootstrap(snapshot, preflight, opts)
        if snapshot.lifecycle == "ACTIVE":
            if not preflight.allowed:
                return self._base(
                    "full",
                    "BLOCKED",
                    blockers=preflight.blockers,
                    next_route="understand/compatibility",
                    extras={
                        "preflight_context": preflight.context,
                        "host_class": snapshot.host_class,
                    },
                )
            result = refresh_host(self.root)
            extras = {
                "preflight_context": preflight.context,
                "note": "ACTIVE full stays inside Refresh rules",
            }
            self._maybe_publish_knowledge_assessment("full", opts, extras)
            if result.get("ok") and not result.get("conflicts"):
                extras["understanding"] = self._persist_understanding(
                    producer_mode="full",
                    incremental=False,
                    expected_head_digest=opts.get("expected_head_digest"),
                )
            return self._base(
                "full",
                result.get("outcome")
                or ("COMPLETED" if result["ok"] else "BLOCKED"),
                baseline=result.get("baseline"),
                mutations="bounded" if result.get("changed") else "none",
                artifacts=result.get("changed") or [],
                blockers=result.get("blockers") or [],
                next_route=(
                    "human knowledge/ownership resolution → understand/refresh"
                    if result.get("conflicts")
                    else "understand/refresh"
                ),
                extras=extras,
            )
        return self._base("full", "BLOCKED", blockers=preflight.blockers or ["full cannot run"], extras={"host_class": snapshot.host_class})

    def _refresh(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        extras = {"preflight_context": preflight.context, "host_class": snapshot.host_class, "authority": preflight.authority}
        action = str(opts.get("action") or "").strip()
        if action == "resume":
            return self._resume(snapshot, preflight, opts)
        if (
            snapshot.host_class != "ESTABLISHED_HOST" or not preflight.allowed
        ) and not refreshable_ownership_contract_host(snapshot):
            return self._base("refresh", "BLOCKED", blockers=preflight.blockers or ["refresh requires established host"], extras=extras)
        if action == "understand":
            return self._understand_currentness(snapshot, preflight, opts)
        result = refresh_host(self.root)
        extras["conflicts"] = result.get("conflicts") or []
        extras["untouched_business"] = result.get("untouched_business") or []
        self._maybe_publish_knowledge_assessment("refresh", opts, extras)
        return self._base(
            "refresh",
            result.get("outcome")
            or ("COMPLETED" if result["ok"] else "BLOCKED"),
            baseline=result.get("baseline") or _baseline(snapshot),
            mutations="bounded" if result.get("changed") else "none",
            artifacts=result.get("changed") or [],
            blockers=result.get("blockers") or [],
            evidence=["HUMAN_OWNED preserved", "business source not edited"],
            next_route=(
                "human knowledge/ownership resolution → understand/refresh"
                if result.get("conflicts")
                else "continue"
            ),
            extras=extras,
        )

    def _resume(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        view = resume_project(
            self.root,
            distribution=self.distribution,
            task_id=opts.get("task_id"),
        )
        extras = {
            "preflight_context": preflight.context,
            "host_class": snapshot.host_class,
            "authority": view.get("authority"),
            "summary": view.get("summary"),
            "understanding": view.get("understanding"),
            "project": view.get("project"),
            "work": view.get("work"),
            "test": view.get("test"),
            "submit": view.get("submit"),
            "next_route_reason": view.get("next_route_reason"),
            "ambiguous_task_ids": list(view.get("ambiguous_task_ids") or []),
            "observational": True,
            "chat_memory": False,
        }
        return self._base(
            "refresh",
            "COMPLETED" if view.get("ok") else "FAILED",
            baseline=_baseline(snapshot),
            mutations="none",
            artifacts=[],
            blockers=[],
            evidence=["zero-context resume reconstructed from project-local truth"],
            next_route=str(view.get("next_route") or "human"),
            extras=extras,
        )

    def _understand_currentness(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        incremental = bool(opts.get("incremental")) or str(opts.get("request") or "") == "incremental"
        published = self._persist_understanding(
            producer_mode="refresh",
            incremental=incremental,
            expected_head_digest=opts.get("expected_head_digest"),
            produce_completion=opts.get("produce_completion", True),
            knowledge_payloads=opts.get("knowledge_payloads"),
        )
        extras = {
            "preflight_context": preflight.context,
            "host_class": snapshot.host_class,
            "understanding": published,
            "incremental_requested": incremental,
        }
        if published.get("rejected_incremental") or (
            not published.get("ok") and published.get("needs_human")
        ):
            return self._base(
                "refresh",
                "NEEDS_HUMAN",
                baseline=_baseline(snapshot),
                mutations="none",
                blockers=list(published.get("blockers") or []),
                next_route="understand.refresh",
                extras=extras,
            )
        if not published.get("ok"):
            return self._base(
                "refresh",
                "BLOCKED",
                baseline=_baseline(snapshot),
                mutations="none",
                blockers=list(published.get("blockers") or ["understanding persist failed"]),
                next_route="understand.refresh",
                extras=extras,
            )
        resume = resume_project(self.root, distribution=self.distribution, task_id=opts.get("task_id"))
        extras["authority"] = resume.get("authority")
        extras["summary"] = resume.get("summary")
        extras["next_route_reason"] = resume.get("next_route_reason")
        artifacts = []
        if published.get("locator"):
            artifacts.append(".scaffold/runtime/" + str(published["locator"]))
        artifacts.extend(
            ".scaffold/runtime/" + str(item)
            for item in (published.get("completion_locators") or [])
            if item
        )
        return self._base(
            "refresh",
            "COMPLETED",
            baseline=_baseline(snapshot),
            mutations="bounded" if published.get("mutations") else "none",
            artifacts=artifacts,
            blockers=[],
            evidence=[
                "understanding currentness bound to physical module/structural authority "
                "and Understand refresh-completion receipts"
            ],
            next_route=str(resume.get("next_route") or "none"),
            extras=extras,
        )

    def _persist_understanding(
        self,
        *,
        producer_mode: str,
        incremental: bool,
        expected_head_digest: Any,
        produce_completion: bool = True,
        knowledge_payloads: Any = None,
    ) -> dict[str, Any]:
        evaluation = evaluate_understanding_currentness(self.root)
        currentness = str(evaluation.get("currentness") or "UNKNOWN")
        if produce_completion and currentness != "CURRENT":
            if not (incremental and currentness in {"FULL_REFRESH_REQUIRED", "UNKNOWN"}):
                if incremental and currentness == "PARTIAL_REFRESH_REQUIRED":
                    module_ids = list(evaluation.get("affected_module_ids") or [])
                else:
                    observed = evaluation.get("observed") or {}
                    module_ids = [
                        str(item.get("id"))
                        for item in observed.get("modules") or []
                        if isinstance(item, dict) and item.get("id")
                    ]
                if module_ids:
                    produced = produce_refresh_completion(
                        self.root,
                        module_ids=module_ids,
                        producer_mode=producer_mode,
                        knowledge_payloads=knowledge_payloads
                        if isinstance(knowledge_payloads, dict)
                        else None,
                    )
                    if not produced.get("ok"):
                        return {
                            "ok": False,
                            "needs_human": bool(produced.get("needs_human")),
                            "currentness": currentness,
                            "blockers": list(
                                produced.get("blockers")
                                or ["refresh completion production failed"]
                            ),
                            "evaluation": evaluation,
                            "mutations": False,
                        }
        return persist_project_understanding(
            self.root,
            mode="incremental" if incremental else "full",
            incremental=incremental,
            expected_head_digest=expected_head_digest if isinstance(expected_head_digest, str) else None,
            producer_mode=producer_mode,
        )

    def _maybe_publish_knowledge_assessment(
        self,
        mode: str,
        opts: dict[str, Any],
        extras: dict[str, Any],
    ) -> None:
        handoff = opts.get("structural_impacts")
        if handoff is None:
            handoff = opts.get("structural")
        if isinstance(handoff, dict):
            impacts = handoff.get("impacts")
        elif isinstance(handoff, list):
            impacts = handoff
        else:
            return
        if not isinstance(impacts, list) or not impacts:
            return
        published = publish_knowledge_assessment(
            self.root,
            mode=mode,
            impacts=list(impacts),
            outcomes=list(opts.get("knowledge_outcomes") or []),
        )
        extras["knowledge_assessment"] = {
            "ok": published.get("ok"),
            "locator": published.get("locator"),
            "impact_digest": published.get("impact_digest"),
            "candidate_digest": published.get("candidate_digest"),
            "assessment_digest": published.get("assessment_digest"),
            "current_head_locator": published.get("current_head_locator"),
            "blockers": list(published.get("blockers") or []),
        }
        if published.get("locator"):
            extras["knowledge_assessment_ref"] = published["locator"]

    def _compatibility(self, snapshot, preflight: PreflightDecision, opts: dict[str, Any]):
        extras = {
            "preflight_context": preflight.context,
            "host_class": snapshot.host_class,
            "authority": preflight.authority,
        }
        action = opts.get("action") or "evaluate"
        recovery = snapshot.migration_recovery
        recovery_isolation = (
            snapshot.lifecycle == "RECOVERY_REQUIRED"
            or bool(recovery.get("requires_isolation"))
        )
        extras["migration_recovery"] = recovery
        extras["project_observation"] = snapshot.project_view.status
        if not snapshot.project_view.valid:
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                blockers=[
                    "project.yaml concrete schema is not executable"
                ]
                + list(snapshot.project_view.reasons),
                next_route="resolve project host schema/authority",
                extras=extras,
            )
        if (
            action == "migrate"
            and recovery.get("classification") == "ONE_VALID_UNRESOLVED"
        ):
            return self._resume_or_abort_migration(snapshot, opts, extras)
        if recovery_isolation and action != "evaluate":
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                blockers=[
                    "migration recovery evidence or RECOVERY_REQUIRED lifecycle blocks independent persistent compatibility mutations"
                ]
                + list(recovery.get("blockers") or []),
                next_route="resume or safely abort the current Migration Execution",
                extras={**extras, "migration_recovery_isolation": True},
            )
        if snapshot.host_class != "ESTABLISHED_HOST":
            if snapshot.lock.status in {"partial", "incomplete", "malformed", "unpublished", "absent"}:
                extras["lock_status"] = snapshot.lock.status
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    blockers=["lock is recovery/consistency evidence, not ordinary compatibility authority"]
                    + snapshot.lock.reasons
                    + preflight.blockers,
                    extras=extras,
                )
            return self._base("compatibility", "BLOCKED", blockers=preflight.blockers, extras=extras)
        evaluation = evaluate_host(snapshot, self.distribution)
        extras["evaluation"] = evaluation
        overall = evaluation.get("overall")
        maintenance_changed = False
        if (
            overall == "MIGRATION_REQUIRED"
            and action == "evaluate"
            and evaluation.get("ok")
            and not recovery_isolation
        ):
            project = snapshot.project or {}
            already = "NEEDS_MIGRATION" in (project.get("maintenance") or [])
            if already:
                maintenance_changed = False
            else:
                allowed, reason = whole_file_mutation_allowed(
                    project.get("ownership"),
                    PROJECT_YAML,
                )
                if not allowed:
                    return self._base(
                        "compatibility",
                        "NEEDS_HUMAN",
                        baseline=_baseline(snapshot),
                        mutations="none",
                        compatibility=overall,
                        blockers=[reason],
                        next_route=(
                            "resolve project.yaml ownership before persisting "
                            "NEEDS_MIGRATION"
                        ),
                        extras=extras,
                    )
                maintenance_changed = mark_needs_migration(self.root)
        if action == "evaluate":
            if recovery_isolation:
                extras["migration_recovery_isolation"] = True
                extras["read_only_during_recovery"] = True
            return self._base(
                "compatibility",
                "COMPLETED" if evaluation.get("ok") else "BLOCKED",
                baseline=_baseline(snapshot),
                mutations="bounded" if maintenance_changed else "none",
                artifacts=[PROJECT_YAML] if maintenance_changed else [],
                compatibility=overall,
                blockers=evaluation.get("blockers") or [],
                next_route=_compat_route(overall),
                extras=extras,
            )
        if action == "lock_update":
            new_expected = opts.get("new_expected")
            if not new_expected:
                return self._base("compatibility", "FAILED", blockers=["lock update requires new_expected"], extras=extras)
            plan = lock_update_plan(snapshot, self.distribution, new_expected, evaluation)
            extras["lock_update_plan"] = plan
            extras["lock_update_is_not_migration"] = not plan["migration_required"]
            if not plan.get("valid"):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=plan.get("blockers") or ["invalid lock-update candidate"],
                    next_route="provide exact resolvable VALID core package identities",
                    extras=extras,
                )
            approval = opts.get("approval")
            if not approval or not approval.get("approved") or (approval.get("plan_digest") or approval.get("digest")) != plan["digest"]:
                return self._base(
                    "compatibility",
                    "NEEDS_HUMAN",
                    mutations="none",
                    compatibility=overall,
                    blockers=["explicit lock-update approval is required"],
                    next_route="review lock update plan",
                    extras=extras,
                )
            if plan["migration_required"]:
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    compatibility=overall,
                    blockers=["this change is project migration, not a lock update"],
                    extras=extras,
                )
            current_project = inspect_project(self.root / PROJECT_YAML)
            if not current_project.valid:
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=[
                        "project.yaml became non-executable before lock update"
                    ]
                    + list(current_project.reasons),
                    next_route="resolve project host schema/authority",
                    extras=extras,
                )
            allowed, reason = whole_file_mutation_allowed(
                (current_project.data or {}).get("ownership"),
                SKILLS_LOCK,
            )
            if not allowed:
                return self._base(
                    "compatibility",
                    "NEEDS_HUMAN",
                    mutations="none",
                    compatibility=overall,
                    blockers=[reason],
                    next_route="resolve skills.lock ownership before lock update",
                    extras=extras,
                )
            merged = dict((snapshot.lock.data or {}))
            merged["skills"] = plan["final_skills"]
            merged.pop("release_provenance", None)
            write_yaml_atomic(self.root / SKILLS_LOCK, merged)
            validated = inspect_lock(self.root / SKILLS_LOCK)
            if not validated.complete_authoritative:
                return self._base(
                    "compatibility",
                    "FAILED",
                    mutations="partial",
                    artifacts=[SKILLS_LOCK],
                    blockers=["written lock failed final validation"] + validated.reasons,
                    next_route="lock consistency recovery",
                    extras=extras,
                )
            return self._base(
                "compatibility",
                "COMPLETED",
                mutations="bounded",
                artifacts=[SKILLS_LOCK],
                compatibility=overall,
                evidence=["lock update is an explicit expected-version mutation"],
                next_route="submit later if durable publication is required",
                extras=extras,
            )
        if action == "ownership_update":
            plan = build_ownership_update_plan(self.root)
            extras["ownership_update_plan"] = plan
            extras["plan_digest"] = plan.get("digest")
            if not plan.get("valid"):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=plan.get("blockers") or [
                        "P6 durable Evidence ownership update is not eligible"
                    ],
                    next_route="human review of ownership",
                    extras=extras,
                )
            approval = opts.get("approval")
            if (
                not approval
                or not approval.get("approved")
                or (approval.get("plan_digest") or approval.get("digest"))
                != plan["digest"]
            ):
                return self._base(
                    "compatibility",
                    "NEEDS_HUMAN",
                    mutations="none",
                    compatibility=overall,
                    blockers=["explicit P6 durable Evidence ownership-update approval is required"],
                    next_route="review ownership update plan",
                    extras=extras,
                )
            applied = apply_ownership_update(self.root, plan)
            extras["ownership_update"] = {
                "ok": applied.get("ok"),
                "applied": applied.get("applied"),
                "plan_digest": (applied.get("plan") or {}).get("digest"),
            }
            if not applied.get("ok"):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="partial" if applied.get("applied") else "none",
                    artifacts=list(applied.get("artifacts") or []),
                    blockers=applied.get("blockers") or [
                        "ownership update could not be applied"
                    ],
                    next_route="review ownership update plan",
                    extras=extras,
                )
            return self._base(
                "compatibility",
                "COMPLETED",
                mutations="bounded",
                artifacts=[PROJECT_YAML],
                compatibility=overall,
                evidence=[
                    "P6 durable Evidence area registered as GENERATED after exact approval"
                ],
                next_route="understand.refresh",
                extras=extras,
            )
        if action == "migrate":
            return self._migrate(snapshot, evaluation, opts, extras)
        return self._base("compatibility", "FAILED", blockers=[f"unknown compatibility action: {action}"], extras=extras)

    def _migrate(self, snapshot, evaluation, opts, extras):
        if snapshot.migrations:
            return self._resume_or_abort_migration(snapshot, opts, extras)
        if evaluation.get("overall") != "MIGRATION_REQUIRED" or not evaluation.get("ok"):
            return self._base(
                "compatibility",
                "BLOCKED",
                compatibility=evaluation.get("overall"),
                blockers=["migration requires evaluated MIGRATION_REQUIRED"],
                extras=extras,
            )
        requested_target = (
            str(opts["target_generation"])
            if opts.get("target_generation") is not None
            else None
        )
        target, compatibility_binding, target_issues = derive_migration_target(
            evaluation,
            requested_target,
        )
        if target_issues or target is None or compatibility_binding is None:
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                compatibility="MIGRATION_REQUIRED",
                blockers=[
                    "migration target is not uniquely established by compatibility evidence"
                ]
                + target_issues,
                next_route="resolve compatibility target and re-evaluate",
                extras=extras,
            )
        plan = build_migration_plan(
            self.root,
            snapshot,
            target_generation=target,
            compatibility_binding=compatibility_binding,
        )
        extras["migration_plan"] = plan
        extras["fresh_application_owner"] = "develop"
        extras["plan_approval_is_not_application_authority"] = True
        extras["pre_compatibility"] = evaluation.get("overall") or "MIGRATION_REQUIRED"
        extras["plan_reviewed"] = migration_approval_matches(
            plan, opts.get("approval")
        )
        issues = bindings_still_hold(
            self.root,
            plan,
            snapshot,
            evaluation,
        )
        if issues:
            extras["human_action"] = {
                "observed": "The current Migration Plan is not bound to this host state.",
                "why_stopped": "Plan bindings changed before Task-bound application.",
                "human_action_required": (
                    "Re-evaluate compatibility, then apply the current Plan "
                    "through Task-bound Develop. Human approval is not a "
                    "Migration predicate."
                ),
            }
            return self._base(
                "compatibility",
                "NEEDS_HUMAN",
                mutations="none",
                compatibility="MIGRATION_REQUIRED",
                blockers=["migration bindings changed; re-evaluate before Develop apply"]
                + issues,
                next_route="develop",
                extras=extras,
            )
        allowed, reason = whole_file_mutation_allowed(
            (snapshot.project or {}).get("ownership"),
            PROJECT_YAML,
        )
        if not allowed:
            extras["human_action"] = {
                "observed": "A bounded Migration Plan exists.",
                "why_stopped": reason,
                "human_action_required": (
                    "Resolve project.yaml ownership before any whole-file "
                    "migration mutation. HUMAN_OWNED content is not silently overwritten."
                ),
            }
            return self._base(
                "compatibility",
                "NEEDS_HUMAN",
                mutations="none",
                compatibility="MIGRATION_REQUIRED",
                blockers=[reason],
                next_route="resolve project.yaml ownership before Migration",
                extras=extras,
            )
        extras["human_action"] = {
            "observed": (
                "A bounded Migration Plan is ready. No durable project-local "
                "state has been changed."
            ),
            "why_stopped": (
                "Fresh Migration application is Task-bound Develop work. "
                "Understand does not start a fresh persistent apply."
            ),
            "human_action_required": (
                "Continue in Develop with the current Task identity, Task "
                "revision, and candidate bound to this exact Plan. Human "
                "approval is not required. Git Commit and Push remain separate."
            ),
        }
        return self._base(
            "compatibility",
            "NEEDS_HUMAN",
            mutations="none",
            compatibility="MIGRATION_REQUIRED",
            blockers=[
                "fresh Migration application requires Task-bound Develop authority"
            ],
            next_route="develop",
            extras=extras,
        )

    def _resume_or_abort_migration(self, snapshot, opts, extras):
        if len(snapshot.migrations) != 1:
            return self._base(
                "compatibility",
                "BLOCKED",
                blockers=["migration recovery requires one unambiguous execution"],
                next_route="human recovery resolution",
                extras=extras,
            )
        current = snapshot.migrations[0]
        directory = Path(current["_dir"])
        try:
            data = load_execution(directory)
            plan = read_yaml(directory / "plan.yaml")
        except (OSError, ValueError, TypeError):
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                blockers=[
                    "Migration Execution/Plan recovery artifacts are missing or malformed"
                ],
                next_route="human recovery resolution; preserve execution evidence",
                extras=extras,
            )
        extras["migration"] = data
        if opts.get("abort"):
            if data.get("status") == "PREPARED" and not data.get("checkpoints_completed"):
                data["status"] = "ABORTED"
                save_execution(directory, data)
                extras["migration"] = data
                return self._base(
                    "compatibility",
                    "COMPLETED",
                    mutations="none",
                    evidence=["ABORTED with no persistent mutation"],
                    extras=extras,
                )
            return self._base(
                "compatibility",
                "BLOCKED",
                blockers=["ABORTED is invalid after uncertain/partial mutation; use RECOVERY_REQUIRED"],
                extras=extras,
            )
        if data.get("status") not in {
            "PREPARED",
            "RECOVERY_REQUIRED",
            "APPLYING",
            "VALIDATING",
        }:
            return self._base("compatibility", "BLOCKED", blockers=[f"cannot resume from {data.get('status')}"], extras=extras)
        if reconcile_execution_checkpoint(
            directory,
            data,
            plan,
            snapshot,
        ):
            data = load_execution(directory)
            extras["migration"] = data
        current_evaluation = evaluate_host(snapshot, self.distribution)
        recovery_issues = validate_recovery_state(
            self.root,
            data,
            plan,
            snapshot,
            current_evaluation,
        )
        if recovery_issues:
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                blockers=["unexpected migration divergence"] + recovery_issues,
                next_route="re-evaluate compatibility → regenerate plan → Develop apply",
                extras=extras,
            )
        completed = list(data.get("checkpoints_completed") or [])
        if not completed and (
            not current_evaluation.get("ok")
            or current_evaluation.get("overall") != "MIGRATION_REQUIRED"
        ):
            return self._base(
                "compatibility",
                "BLOCKED",
                mutations="none",
                compatibility=current_evaluation.get("overall"),
                blockers=[
                    "pre-mutation resume no longer has executable MIGRATION_REQUIRED compatibility evidence"
                ]
                + list(current_evaluation.get("blockers") or []),
                next_route="re-evaluate compatibility → regenerate plan → Develop apply",
                extras=extras,
            )
        if not completed:
            allowed, reason = whole_file_mutation_allowed(
                (snapshot.project or {}).get("ownership"),
                PROJECT_YAML,
            )
            if not allowed:
                return self._base(
                    "compatibility",
                    "NEEDS_HUMAN",
                    mutations="none",
                    blockers=[reason],
                    next_route="resolve project.yaml ownership before Migration resume",
                    extras=extras,
                )
            applied = apply_contract_generation(
                self.root,
                plan["target_contract_generation"],
            )
            if not applied:
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=[
                        "project.yaml became non-executable before migration resume mutation"
                    ],
                    next_route="resolve project host schema/authority",
                    extras=extras,
                )
            data["status"] = (
                "RECOVERY_REQUIRED"
                if snapshot.lifecycle == "RECOVERY_REQUIRED"
                else "VALIDATING"
            )
            data["checkpoints_completed"] = [CONTRACT_GENERATION_UPDATED]
            data["checkpoints_remaining"] = [VALIDATION_PASSED]
            data["observed_expected_state"] = "VALIDATING"
            save_execution(directory, data)
            completed = list(data["checkpoints_completed"])

        if completed == [CONTRACT_GENERATION_UPDATED]:
            checkpoint_snapshot = snapshot_host(self.root)
            checkpoint_evaluation = evaluate_host(
                checkpoint_snapshot,
                self.distribution,
            )
            checkpoint_issues = validate_recovery_state(
                self.root,
                data,
                plan,
                checkpoint_snapshot,
                checkpoint_evaluation,
            )
            if checkpoint_issues:
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=["unexpected migration divergence"]
                    + checkpoint_issues,
                    next_route="re-evaluate compatibility → regenerate plan → Develop apply",
                    extras=extras,
                )
            if checkpoint_evaluation.get("overall") not in {
                "EXACT",
                "COMPATIBLE",
            }:
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    compatibility=checkpoint_evaluation.get("overall"),
                    blockers=[
                        "migration validation did not resolve the approved compatibility cause"
                    ]
                    + list(checkpoint_evaluation.get("blockers") or []),
                    next_route="retain RECOVERY_REQUIRED and resolve compatibility evidence",
                    extras=extras,
                )
            data["checkpoints_completed"] = [
                CONTRACT_GENERATION_UPDATED,
                VALIDATION_PASSED,
            ]
            data["checkpoints_remaining"] = []
            data["observed_expected_state"] = "VALIDATION_PASSED"
            save_execution(directory, data)
            completed = list(data["checkpoints_completed"])

        if completed == [CONTRACT_GENERATION_UPDATED, VALIDATION_PASSED]:
            final_snapshot = snapshot_host(self.root)
            final_evaluation = evaluate_host(
                final_snapshot,
                self.distribution,
            )
            final_issues = validate_recovery_state(
                self.root,
                data,
                plan,
                final_snapshot,
                final_evaluation,
            )
            if (
                final_issues
                or not final_evaluation.get("ok")
                or final_evaluation.get("overall")
                not in {"EXACT", "COMPATIBLE"}
            ):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    compatibility=final_evaluation.get("overall"),
                    blockers=[
                        "final migration checkpoint no longer proves compatible target state"
                    ]
                    + final_issues
                    + list(final_evaluation.get("blockers") or []),
                    next_route="retain RECOVERY_REQUIRED and resolve compatibility evidence",
                    extras=extras,
                )
            if not complete_migration(
                self.root,
                plan["target_contract_generation"],
            ):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="none",
                    blockers=[
                        "project.yaml became non-executable before migration completion"
                    ],
                    next_route="resolve project host schema/authority",
                    extras=extras,
                )
            consumed = consume_compatibility_boundary(
                self.root,
                classify_inherited=True,
            )
            extras["compatibility_boundary"] = consumed
            if not consumed.get("ok"):
                return self._base(
                    "compatibility",
                    "BLOCKED",
                    mutations="partial",
                    artifacts=[PROJECT_YAML],
                    blockers=list(consumed.get("blockers") or [
                        "compatibility boundary could not be established after migration"
                    ]),
                    next_route="resolve durable drift authority before resuming Develop",
                    extras=extras,
                )
            data["status"] = "COMPLETED"
            save_execution(directory, data)
            delete_execution(directory)
            extras["migration"] = {
                "status": "COMPLETED",
                "plan_id": plan["plan_id"],
            }
            extras["pre_compatibility"] = plan.get("compatibility") or "MIGRATION_REQUIRED"
            extras["post_compatibility"] = final_evaluation.get("overall")
            extras["current_compatibility"] = final_evaluation.get("overall")
            return self._base(
                "compatibility",
                "COMPLETED",
                mutations="bounded",
                artifacts=[PROJECT_YAML],
                compatibility=final_evaluation.get("overall"),
                evidence=["resumed from exact approved checkpoint"],
                extras=extras,
            )
        return self._base(
            "compatibility",
            "BLOCKED",
            blockers=["cannot determine safe resume"],
            extras=extras,
        )


def _baseline(snapshot) -> dict[str, Any] | None:
    if snapshot.project:
        return snapshot.project.get("baseline")
    return None


def _plan_stale_vs_host(root: Path, plan: AdoptionPlan, allow_expected_progress: bool = False) -> bool:
    issues = compare_adoption_state(
        root,
        plan.baseline,
        plan.mutation_envelope if allow_expected_progress else [],
    )
    return bool(issues)


def _envelope_breach(root: Path, plan: AdoptionPlan, artifacts: list[str]) -> list[str]:
    allowed = set(plan.mutation_envelope)
    return [path for path in artifacts if path not in allowed]


def _compat_route(overall: str | None) -> str:
    if overall == "MIGRATION_REQUIRED":
        return "understand/compatibility migrate"
    if overall in {"INCOMPATIBLE", "UNKNOWN"}:
        return "resolve compatibility"
    if overall == "COMPATIBLE":
        return "optional explicit lock update"
    return "continue"


def _mutation_observations(
    root: Path,
    plan: AdoptionPlan,
    artifacts: list[str],
) -> list[dict[str, str]]:
    action_by_target = {action.target: action.action_class for action in plan.actions}
    observations: list[dict[str, str]] = []
    for target in artifacts:
        path = root / target
        if not path.is_file():
            continue
        observations.append(
            {
                "action_class": action_by_target.get(target, "CREATE"),
                "target": target,
                "type": "file",
                "digest": file_digest(path),
            }
        )
    return observations

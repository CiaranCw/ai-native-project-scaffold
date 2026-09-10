"""Task-bound Develop orchestration around canonical P5 Migration authority.

Not Adoption. Not a fourth canonical record. Not a second Migration state
machine. Understand/P5 owns evaluation, Plan construction, Execution
lifecycle, checkpoints, recovery, and post-migration validation. Develop
may apply an already-approved Plan only when the human approval binds that
exact Plan to the current Task identity/revision/candidate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.compatibility import evaluate_host, migration_need
from scaffold_p5.host_state import PROJECT_YAML, snapshot_host
from scaffold_p5.migration import (
    application_approval_matches,
    apply_fresh_migration_execution,
    build_migration_plan,
    derive_migration_target,
    normalize_develop_binding,
    plan_application_issues,
    task_application_binding_issues,
)
from scaffold_p5.schemas import whole_file_mutation_allowed


class MigrationRun:
    def __init__(
        self,
        *,
        ok: bool,
        outcome: str,
        blockers: list[str] | None = None,
        writes: list[str] | None = None,
        extras: dict[str, Any] | None = None,
        route: str = "understand.compatibility",
        applied: bool = False,
        plan: dict[str, Any] | None = None,
    ):
        self.ok = ok
        self.outcome = outcome
        self.blockers = blockers or []
        self.writes = writes or []
        self.extras = extras or {}
        self.route = route
        self.applied = applied
        self.plan = plan

    @property
    def ready(self) -> bool:
        return self.ok and isinstance(self.plan, dict)


def prepare_task_bound_migration_application(
    root: Path,
    *,
    distribution,
    approval: dict[str, Any] | None = None,
    task_id: str | None = None,
    task_revision: int | None = None,
    candidate_digest: str | None = None,
) -> MigrationRun:
    """Prove full Plan+Task application authority. No durable mutation."""
    extras: dict[str, Any] = {
        "adoption": False,
        "application_binding": {
            "task_id": task_id,
            "task_revision": task_revision,
            "candidate_digest": candidate_digest,
            "required_approval_fields": [
                "approved",
                "plan_id",
                "plan_digest",
                "task_id",
                "task_revision",
                "candidate_digest",
            ],
        },
    }
    if distribution is None:
        return MigrationRun(
            ok=False,
            outcome="BLOCKED",
            blockers=["migration requires current Distribution/compatibility authority"],
            extras=extras,
            route="understand.compatibility",
        )
    snapshot = snapshot_host(root)
    takeover = _foreign_or_unbound_execution_issues(
        snapshot,
        task_id=str(task_id or ""),
    )
    if takeover:
        extras["migration_recovery"] = dict(snapshot.migration_recovery or {})
        extras["develop_binding"] = _execution_develop_binding(snapshot)
        return MigrationRun(
            ok=False,
            outcome="BLOCKED",
            blockers=takeover,
            extras=extras,
            route="understand.compatibility",
        )
    plan, extras, blockers, route, outcome = _current_plan_context(
        root,
        snapshot,
        distribution,
        extras,
    )
    if plan is None:
        return MigrationRun(
            ok=False,
            outcome=outcome,
            blockers=blockers,
            extras=extras,
            route=route,
        )
    if task_id is None or task_revision is None or candidate_digest is None:
        return MigrationRun(
            ok=False,
            outcome="BLOCKED",
            blockers=[
                "approved migration apply requires current Task identity, "
                "Task revision, and candidate digest"
            ],
            extras=extras,
            route="human",
            plan=plan,
        )
    if not approval or not approval.get("approved"):
        extras["human_action"] = {
            "observed": (
                "A bounded Migration Plan is ready. No durable project-local "
                "state has been changed."
            ),
            "why_stopped": "Migration waits for current digest-bound human approval.",
            "human_action_required": (
                "Review and approve this exact Migration Plan for this exact "
                "Task identity, Task revision, and candidate before Develop "
                "may mutate Task Book, Session, or project.yaml. Task "
                "title/goal keywords are not authority."
            ),
        }
        return MigrationRun(
            ok=False,
            outcome="NEEDS_HUMAN",
            blockers=["Migration Plan Approval is required and is not SUBMIT_AUTHORIZED"],
            extras=extras,
            route="human",
            plan=plan,
        )
    binding_issues = task_application_binding_issues(
        approval,
        task_id=str(task_id),
        task_revision=int(task_revision),
        candidate_digest=str(candidate_digest),
    )
    plan_issues = plan_application_issues(plan, approval)
    if binding_issues or plan_issues or not application_approval_matches(
        plan,
        approval,
        task_id=str(task_id),
        task_revision=int(task_revision),
        candidate_digest=str(candidate_digest),
    ):
        stale = (
            str(approval.get("task_id") or "") == str(task_id)
            and not plan_issues
            and any("stale" in item for item in binding_issues)
        )
        issues = binding_issues + plan_issues
        extras["human_action"] = {
            "observed": (
                "A bounded Migration Plan exists. No durable project-local "
                "state has been changed."
            ),
            "why_stopped": (
                "Migration application approval is not bound to this Task, "
                "revision, candidate, and Plan digest."
            ),
            "human_action_required": (
                "Re-review and re-approve the current Plan for the current "
                "Task identity/revision. An unrelated Task cannot carry this "
                "approval. Title/goal text does not create authority."
            ),
        }
        return MigrationRun(
            ok=False,
            outcome="NEEDS_HUMAN" if stale else "BLOCKED",
            blockers=issues
            or [
                "Migration application approval does not match the current "
                "Plan and Task binding"
            ],
            extras=extras,
            route="human",
            plan=plan,
        )
    extras["approved_plan_id"] = plan.get("plan_id")
    extras["approved_plan_digest"] = plan.get("digest")
    extras["pre_compatibility"] = extras.get("pre_evaluation_overall")
    extras["human_action"] = None
    return MigrationRun(
        ok=True,
        outcome="PREPARED",
        extras=extras,
        route="caller",
        plan=plan,
    )


def execute_task_bound_migration(
    root: Path,
    *,
    distribution,
    approval: dict[str, Any] | None = None,
    revalidation_distribution=None,
    interrupt_after: str | None = None,
    task_id: str | None = None,
    task_revision: int | None = None,
    session_id: str | None = None,
    candidate_digest: str | None = None,
    prepared_plan: dict[str, Any] | None = None,
) -> MigrationRun:
    """Apply an already-prepared approved Plan via canonical P5 authority."""
    if prepared_plan is None:
        prepared = prepare_task_bound_migration_application(
            root,
            distribution=distribution,
            approval=approval,
            task_id=task_id,
            task_revision=task_revision,
            candidate_digest=candidate_digest,
        )
        if not prepared.ready:
            return prepared
        prepared_plan = prepared.plan
        extras = dict(prepared.extras)
    else:
        extras = {
            "adoption": False,
            "migration_plan": prepared_plan,
            "approved_plan_id": prepared_plan.get("plan_id"),
            "approved_plan_digest": prepared_plan.get("digest"),
            "pre_compatibility": prepared_plan.get("compatibility"),
        }
    current, current_extras, blockers, route, outcome = _current_plan_context(
        root,
        snapshot_host(root),
        distribution,
        dict(extras),
    )
    extras.update(current_extras)
    if current is None:
        return MigrationRun(
            ok=False,
            outcome=outcome,
            blockers=blockers,
            extras=extras,
            route=route,
        )
    if (
        current.get("plan_id") != prepared_plan.get("plan_id")
        or current.get("digest") != prepared_plan.get("digest")
    ):
        return MigrationRun(
            ok=False,
            outcome="BLOCKED",
            blockers=[
                "current Migration Plan identity differs from the approved Plan; "
                "silent plan substitution is not permitted"
            ],
            extras=extras,
            route="human",
            plan=prepared_plan,
        )
    extras["applied_plan_id"] = current.get("plan_id")
    extras["applied_plan_digest"] = current.get("digest")
    extras["plan_identity_held"] = True
    develop_binding = normalize_develop_binding(
        {
            "task_id": task_id,
            "task_revision": task_revision,
            "session_id": session_id or "",
            "candidate_digest": candidate_digest,
        }
    )
    applied = apply_fresh_migration_execution(
        root,
        prepared_plan,
        distribution=distribution,
        validation_distribution=revalidation_distribution or distribution,
        interrupt_after=interrupt_after,
        develop_binding=develop_binding,
    )
    extras.update(applied.get("extras") or {})
    extras["lock_unchanged"] = True
    extras["develop_binding"] = develop_binding
    extras.setdefault(
        "pre_compatibility",
        prepared_plan.get("compatibility") or "MIGRATION_REQUIRED",
    )
    writes = list(applied.get("artifacts") or [])
    completed = bool(applied.get("completed"))
    post = extras.get("post_compatibility")
    if completed and post not in {"EXACT", "COMPATIBLE"}:
        completed = False
    outcome = str(applied.get("outcome") or "BLOCKED")
    if not completed and outcome == "COMPLETED":
        outcome = "BLOCKED"
    extras["current_compatibility"] = post if completed else post
    return MigrationRun(
        ok=completed,
        outcome=outcome if completed else (
            outcome if outcome != "COMPLETED" else "BLOCKED"
        ),
        blockers=list(applied.get("blockers") or []),
        writes=writes if applied.get("applied") else [],
        extras=extras,
        route=str(
            applied.get("next_route")
            or ("caller" if completed else "understand.compatibility")
        ),
        applied=bool(applied.get("applied")),
        plan=prepared_plan,
    )


def reconstruct_migration_view(root: Path) -> dict[str, Any]:
    """Fresh-process reconstruction of pending/in-progress Migration Execution."""
    snapshot = snapshot_host(root)
    executions = list(snapshot.migrations or [])
    recovery = dict(snapshot.migration_recovery or {})
    bindings = [
        dict(row.get("develop_binding") or {})
        for row in executions
        if isinstance(row, dict)
    ]
    return {
        "pending": bool(executions) or recovery.get("classification") not in {None, "NONE"},
        "executions": executions,
        "migration_recovery": recovery,
        "develop_bindings": bindings,
        "task_binding": bindings[0] if len(bindings) == 1 else None,
        "host_lifecycle": snapshot.lifecycle if hasattr(snapshot, "lifecycle") else (
            (snapshot.project or {}).get("lifecycle") if snapshot.project else None
        ),
        "project_contract_generation": (
            (snapshot.project or {}).get("project_contract_generation")
            if snapshot.project
            else None
        ),
    }


def _current_plan_context(
    root: Path,
    snapshot,
    distribution,
    extras: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str], str, str]:
    evaluation = evaluate_host(snapshot, distribution)
    need = migration_need(evaluation)
    extras["migration_need"] = need
    extras["pre_evaluation_overall"] = evaluation.get("overall")
    extras["pre_compatibility"] = evaluation.get("overall")
    if need.get("validity") != "VALID":
        return (
            None,
            extras,
            [
                "INVALID is not a compatibility/migration state"
            ]
            + list(need.get("reasons") or evaluation.get("blockers") or []),
            "understand.compatibility",
            "BLOCKED",
        )
    if not need.get("needed"):
        overall = need.get("compatibility") or evaluation.get("overall")
        return (
            None,
            extras,
            [f"no migration: host compatibility is {overall}"],
            "caller",
            "BLOCKED",
        )
    target, binding, target_issues = derive_migration_target(evaluation)
    if target_issues or target is None or binding is None:
        return (
            None,
            extras,
            [
                "migration target is not uniquely established by compatibility evidence"
            ]
            + list(target_issues),
            "resolve compatibility target and re-evaluate",
            "BLOCKED",
        )
    plan = build_migration_plan(
        root,
        snapshot,
        target_generation=target,
        compatibility_binding=binding,
    )
    extras["migration_plan"] = plan
    extras["source_contract_generation"] = plan.get("source_contract_generation")
    extras["target_contract_generation"] = plan.get("target_contract_generation")
    extras["mutation_envelope"] = list(plan.get("mutation_envelope") or [])
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
        return None, extras, [reason], "human", "NEEDS_HUMAN"
    return plan, extras, [], "caller", "PREPARED"


def _execution_develop_binding(snapshot) -> dict[str, Any] | None:
    rows = list(snapshot.migrations or [])
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    return normalize_develop_binding(rows[0].get("develop_binding"))


def _foreign_or_unbound_execution_issues(
    snapshot,
    *,
    task_id: str,
) -> list[str]:
    rows = list(snapshot.migrations or [])
    if not rows:
        return []
    if len(rows) != 1:
        return ["unresolved Migration Execution requires Understand recovery"]
    bound = normalize_develop_binding(
        rows[0].get("develop_binding") if isinstance(rows[0], dict) else None
    )
    if bound is None:
        return [
            "unresolved Migration Execution is not bound to this Task; "
            "Understand recovery owns resume"
        ]
    if bound.get("task_id") != str(task_id):
        return [
            "Migration Execution is bound to another Task and cannot be "
            "taken over"
        ]
    return [
        "unresolved Migration Execution requires Understand recovery; "
        "Develop does not fork the P5 resume state machine"
    ]

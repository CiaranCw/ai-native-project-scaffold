"""Thin client-neutral entry, routing, status, and human-gate projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.host_state import snapshot_host
from scaffold_p5.models import SkillResult
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.engine import DevelopEngine
from scaffold_p7.tasks import resolve_task, valid_tasks


STRUCTURED_INTENTS = frozenset({"understand", "develop", "test", "submit", "status"})


def enter_project(
    root: str | Path,
    *,
    structured_intent: Any,
    proposal: Any = None,
    grounding: Any = None,
    develop_package: str | Path | None = None,
) -> SkillResult | dict[str, Any]:
    """Route Agent-interpreted intent; never classify raw prose by keywords."""
    host = Path(root)
    if not isinstance(structured_intent, dict):
        return _entry_decision(
            outcome="NEEDS_HUMAN",
            route="human",
            blockers=["Agent interpretation must provide structured intent"],
            gate=_gate(
                "Natural-language input is present without a structured Agent interpretation.",
                "Raw keyword matching is not workflow authority.",
                "Ask the Agent to identify understand/develop/test/submit/status intent.",
                "The structured intent can then be routed against current host authority.",
            ),
        )
    kind = structured_intent.get("kind")
    if kind not in STRUCTURED_INTENTS:
        return _entry_decision(
            outcome="NEEDS_HUMAN",
            route="human",
            blockers=["structured intent kind is missing or unsupported"],
            gate=_gate(
                "The Agent did not establish one supported intent kind.",
                "The entry layer cannot guess from request wording.",
                "Clarify the desired understand/develop/test/submit/status outcome.",
                "The Agent will route to exactly one top-level Skill.",
            ),
        )
    if kind == "status":
        return project_status(host)

    snapshot = snapshot_host(host)
    host_route = _host_work_route(snapshot)
    if host_route is not None:
        return _entry_from_host_route(host_route)

    if kind == "develop":
        explicit_task = structured_intent.get("task_id")
        if explicit_task and proposal is None:
            resolved = resolve_task(host, task_id=explicit_task)
            if not resolved.ok or resolved.task is None:
                return _entry_decision(
                    outcome="BLOCKED",
                    route=resolved.route,
                    blockers=list(resolved.blockers),
                    gate=_gate(
                        "An explicit Task identity was requested but is not usable.",
                        "Develop requires canonical Task authority.",
                        "Resolve the reported Task identity problem.",
                        "No duplicate Task or source mutation will be created.",
                    ),
                )
            status = resolved.task.get("status")
            route = "develop.normal_task" if status == "IN_PROGRESS" else "human"
            outcome = "ROUTED" if status == "IN_PROGRESS" else "NEEDS_HUMAN"
            blockers = [] if status == "IN_PROGRESS" else [
                f"explicit Task status {status} cannot enter normal Develop"
            ]
            return _entry_decision(
                outcome=outcome,
                route=route,
                blockers=blockers,
                observed={
                    "task_id": explicit_task,
                    "task_status": status,
                },
                gate=_gate(
                    f"Canonical Task {explicit_task} has status {status}.",
                    "No stop is required." if not blockers else blockers[0],
                    "Continue with normal Develop." if not blockers else "Resolve or define the intended Task state.",
                    "The existing Task is reused; no duplicate is created.",
                ),
            )
        return DevelopEngine(host, develop_package).intake(
            structured_intent=structured_intent,
            proposal=proposal,
            grounding=grounding,
        )

    routes = {
        "understand": "understand",
        "test": "test.scoped_verification",
        "submit": "submit",
    }
    return _entry_decision(
        outcome="ROUTED",
        route=routes[str(kind)],
        observed={
            "host_class": snapshot.host_class,
            "lifecycle": snapshot.lifecycle,
            "intent": kind,
        },
        gate=_gate(
            f"Structured intent routes to {kind}.",
            "No human decision is currently required by the entry layer.",
            "Continue through the selected canonical Skill.",
            "That Skill retains all of its existing gates and permissions.",
        ),
    )


def project_status(root: str | Path) -> dict[str, Any]:
    """Project “where am I?” projection. Persists nothing."""
    host = Path(root)
    snapshot = snapshot_host(host)
    tasks, task_blockers = valid_tasks(host)
    in_progress = [
        task for task in tasks if task.get("status") == "IN_PROGRESS"
    ]
    candidate = observe_candidate(host)
    host_route = _host_work_route(snapshot)
    blockers = list(snapshot.blockers) + list(task_blockers)
    if host_route is not None:
        blockers = list(host_route["blockers"]) + [
            item for item in blockers if item not in host_route["blockers"]
        ]
    if len(in_progress) > 1:
        blockers.append("multiple IN_PROGRESS Tasks require explicit selection")
    if not candidate.usable:
        blockers.extend(candidate.data.get("blockers") or [
            "candidate observation is unresolved"
        ])
    authority_coherent = not task_blockers
    current_task = (
        in_progress[0]
        if len(in_progress) == 1 and authority_coherent
        else None
    )
    next_route = _status_next_route(
        host_route=host_route,
        candidate_usable=candidate.usable,
        task_blockers=task_blockers,
        in_progress_count=len(in_progress),
        blockers=blockers,
    )
    maintenance = list((snapshot.project or {}).get("maintenance") or [])
    changes = host / ".scaffold/changes"
    return {
        "kind": "status_projection",
        "project": {
            "name": (snapshot.project or {}).get("name"),
            "lifecycle": snapshot.lifecycle,
            "host_class": snapshot.host_class,
            "maintenance": maintenance,
        },
        "lock_status": snapshot.lock.status,
        "executable_compatibility_evaluated": False,
        "executable_compatibility_authority": (
            "Skill execution preflight remains authoritative. "
            "lock_status is lock observation only and is not executable "
            "package compatibility."
        ),
        "scm": {
            "kind": candidate.kind,
            "observation_state": candidate.data.get("observation_state"),
            "observation_ok": candidate.data.get("observation_ok"),
            "candidate_digest": candidate.digest,
        },
        "tasks": [
            {
                "record_id": task.get("record_id"),
                "status": task.get("status"),
                "title": task.get("title"),
            }
            for task in tasks
        ],
        "current_task": (
            {
                "record_id": current_task.get("record_id"),
                "status": current_task.get("status"),
                "title": current_task.get("title"),
            }
            if current_task
            else None
        ),
        "change_record_count": (
            len(list(changes.glob("*.yaml"))) if changes.is_dir() else 0
        ),
        "blockers": sorted(set(str(item) for item in blockers if item)),
        "next_route": next_route,
        "source": (
            "projection from project.yaml, Task Books, Change Records, "
            "skills.lock observation, and current workspace/SCM; "
            "lock observation is not executable package compatibility"
        ),
    }


def _host_work_route(snapshot) -> dict[str, Any] | None:
    """Shared first-contact/status host route from P5 classification.

    This is not a second host-state machine. Ordinary Skill work is only
    considered after this returns None.
    """
    maintenance = list((snapshot.project or {}).get("maintenance") or [])
    if snapshot.host_class == "NOT_ADOPTED":
        return {
            "reason": "not_adopted",
            "route": "understand.bootstrap",
            "outcome": "ROUTED",
            "blockers": [],
            "observed": {"host_class": snapshot.host_class},
        }
    if snapshot.host_class != "ESTABLISHED_HOST":
        return {
            "reason": "host_recovery",
            "route": "understand.compatibility",
            "outcome": "BLOCKED",
            "blockers": list(snapshot.blockers) or [
                "host identity/recovery authority is unresolved"
            ],
            "observed": {
                "host_class": snapshot.host_class,
                "lifecycle": snapshot.lifecycle,
            },
        }
    if snapshot.lifecycle == "RECOVERY_REQUIRED":
        return {
            "reason": "recovery_required",
            "route": "understand.compatibility",
            "outcome": "BLOCKED",
            "blockers": ["RECOVERY_REQUIRED host cannot enter normal Skill work"],
            "observed": {
                "lifecycle": snapshot.lifecycle,
                "maintenance": maintenance,
            },
        }
    if "NEEDS_MIGRATION" in maintenance:
        return {
            "reason": "needs_migration",
            "route": "understand.compatibility",
            "outcome": "ROUTED",
            "blockers": [],
            "observed": {
                "lifecycle": snapshot.lifecycle,
                "maintenance": maintenance,
            },
        }
    if "NEEDS_REFRESH" in maintenance:
        return {
            "reason": "needs_refresh",
            "route": "understand.refresh",
            "outcome": "ROUTED",
            "blockers": [],
            "observed": {
                "lifecycle": snapshot.lifecycle,
                "maintenance": maintenance,
            },
        }
    return None


def _status_next_route(
    *,
    host_route: dict[str, Any] | None,
    candidate_usable: bool,
    task_blockers: list[str],
    in_progress_count: int,
    blockers: list[str],
) -> str:
    """Fail-closed next-route ordering. An IN_PROGRESS Task never outranks A–G."""
    if host_route is not None:
        return str(host_route["route"])
    if not candidate_usable or task_blockers or in_progress_count > 1:
        return "human"
    if in_progress_count == 1:
        return "human" if blockers else "develop.normal_task"
    if blockers:
        return "human"
    return "caller"


def _entry_from_host_route(host_route: dict[str, Any]) -> dict[str, Any]:
    gates = {
        "not_adopted": (
            "This appears to be an ordinary project without completed Scaffold adoption.",
            "Persistent Task or development work cannot start before adoption authority.",
            "Review the read-only Adoption Plan when Understand presents it.",
            "Only the approved Adoption mutation envelope will be applied.",
        ),
        "host_recovery": (
            "Existing Scaffold state is incomplete, conflicting, or requires recovery.",
            "Normal Skill routing cannot safely guess through host authority.",
            "Use the reported Understand compatibility/recovery route.",
            "Project source and canonical Tasks remain unchanged.",
        ),
        "recovery_required": (
            "The established host requires recovery.",
            "Normal Task, Test, and Submit work cannot guess through recovery state.",
            "Use Understand Compatibility/recovery with current durable evidence.",
            "No Task, source, Commit, or Push authority is changed.",
        ),
        "needs_migration": (
            "The ACTIVE host requires compatibility/migration handling.",
            "Normal work cannot use unresolved persistent representation.",
            "Run Understand Compatibility and review any required plan.",
            "No Task, source, Commit, or Push authority is changed.",
        ),
        "needs_refresh": (
            "The ACTIVE host records stale project knowledge.",
            "Task planning or execution cannot rely on stale authority.",
            "Run Understand Refresh before continuing.",
            "No Task or source mutation occurs during this routing decision.",
        ),
    }
    observed, stopped, action, approved = gates[str(host_route["reason"])]
    return _entry_decision(
        outcome=str(host_route["outcome"]),
        route=str(host_route["route"]),
        blockers=list(host_route["blockers"]),
        observed=dict(host_route["observed"]),
        gate=_gate(observed, stopped, action, approved),
    )


def present_result(result: SkillResult) -> dict[str, Any]:
    """Plain-language gate projection over a canonical Skill result."""
    existing = result.extras.get("human_gate")
    if isinstance(existing, dict):
        return dict(existing)
    stopped = result.outcome in {"BLOCKED", "FAILED", "NEEDS_HUMAN"}
    return _gate(
        f"{result.skill_id} reported {result.outcome}.",
        "; ".join(result.blockers) if stopped and result.blockers else "Work has not stopped.",
        (
            f"Follow route: {result.next_route or 'human clarification'}."
            if stopped
            else "No additional entry-layer action is required."
        ),
        "The canonical Skill will re-evaluate all gates before any further mutation.",
    )


def _entry_decision(
    *,
    outcome: str,
    route: str,
    gate: dict[str, str],
    blockers: list[str] | None = None,
    observed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "entry_projection",
        "outcome": outcome,
        "route": route,
        "observed": observed or {},
        "blockers": blockers or [],
        "human_gate": gate,
        "authoritative": False,
        "mutations": "none",
    }


def _gate(
    observed: str,
    stopped: str,
    action: str,
    approved: str,
) -> dict[str, str]:
    return {
        "observed": observed,
        "why_stopped": stopped,
        "human_action_required": action,
        "if_approved": approved,
        "remains_unchanged": (
            "This projection grants no source write, Commit, Push, adoption "
            "approval, Task approval, or Submit authorization."
        ),
    }

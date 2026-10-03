"""Bounded Submit → Develop repair handoff. Not silent source editing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.ownership import ordinary_business_source
from scaffold_p7.mutation import (
    hard_mutation_boundary_reason,
    is_protected_governance_path,
)
from scaffold_p7.repair_targets import (
    EXECUTION_BINDING_MAPPING,
    map_repair_target_stage_ids,
    SINGLE_STAGE_MAPPING,
)


UNRESOLVED_REPAIR_ROUTE = "human"
UNRESOLVED_REPAIR_REASON = "repair target Stage mapping unresolved"


def build_repair_handoff(
    *,
    task_id: str,
    candidate_digest: str,
    blockers: list[str],
    evidence_refs: list[str] | None = None,
    target_stage_ids: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": "submit_to_develop",
        "task_id": task_id,
        "candidate_digest": candidate_digest,
        "test_pass": False,
        "blockers": list(blockers),
        "evidence_refs": list(evidence_refs or []),
        "submit_authorized": False,
        "capabilities": {
            "commit": False,
            "push": False,
            "submit_authorized": False,
        },
    }
    targets = _explicit_targets(target_stage_ids)
    if targets:
        payload["target_stage_ids"] = targets
    return payload


def executable_repair_route(
    task: dict[str, Any],
    *,
    candidate_digest: str,
    blockers: list[str],
    fail_ids: list[str] | None = None,
    missing_source: list[str] | None = None,
    undeclared: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Emit develop.repair only when target_stage_ids are explicit and nonempty."""
    targets = map_repair_target_stage_ids(
        task, fail_ids=fail_ids, missing_source=missing_source, undeclared=undeclared
    )
    if not targets:
        return (
            UNRESOLVED_REPAIR_ROUTE,
            None,
            list(blockers) + [UNRESOLVED_REPAIR_REASON],
        )
    handoff = build_repair_handoff(
        task_id=str(task.get("record_id") or ""),
        candidate_digest=candidate_digest,
        blockers=list(blockers),
        evidence_refs=evidence_refs,
        target_stage_ids=targets,
    )
    if fail_ids:
        handoff["target_mapping"] = EXECUTION_BINDING_MAPPING
    else:
        handoff["target_mapping"] = SINGLE_STAGE_MAPPING
    return "develop.repair", handoff, list(blockers)


def nonrepairable_scope_paths(
    root: str | Path,
    project: dict[str, Any] | None,
    paths: list[str],
) -> list[str]:
    """Escaped paths a Develop repair handoff must not absorb.

    A path is repairable only when it is ordinary product source inside the
    project's source areas and the Task is not blocked by a governance hard
    boundary. Protected governance and paths the Task cannot legally claim,
    such as a root ``CODEOWNERS`` file outside those source areas, stay here.
    """
    host = Path(root)
    source_areas: list[Any] = []
    if isinstance(project, dict) and isinstance(project.get("source_areas"), list):
        source_areas = list(project.get("source_areas") or [])
    blocked: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path:
            continue
        if is_protected_governance_path(path, host):
            blocked.append(path)
            continue
        if hard_mutation_boundary_reason(host, path):
            blocked.append(path)
            continue
        if not ordinary_business_source(path, source_areas):
            blocked.append(path)
    return blocked


def _explicit_targets(value: list[str] | None) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip() or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out

"""Bounded Submit → Develop repair handoff. Not silent source editing."""

from __future__ import annotations

from typing import Any

from scaffold_p7.repair_targets import map_repair_target_stage_ids


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
    evidence_refs: list[str] | None = None,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Emit develop.repair only when target_stage_ids are explicit and nonempty."""
    targets = map_repair_target_stage_ids(
        task, fail_ids=fail_ids, missing_source=missing_source
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
    return "develop.repair", handoff, list(blockers)


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

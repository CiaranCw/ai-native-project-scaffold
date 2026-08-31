"""Bounded Submit → Develop repair handoff. Not silent source editing."""

from __future__ import annotations

from typing import Any


def build_repair_handoff(
    *,
    task_id: str,
    candidate_digest: str,
    blockers: list[str],
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    return {
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

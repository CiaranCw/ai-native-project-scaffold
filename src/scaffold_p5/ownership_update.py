"""Plan-first P6 durable Evidence ownership recovery. Understand-owned."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.host_state import PROJECT_YAML, inspect_project
from scaffold_p5.io_util import sha256_text, write_yaml_atomic
from scaffold_p5.ownership import (
    P6_DURABLE_EVIDENCE_AREA,
    P6_DURABLE_EVIDENCE_PROBE,
    path_covered,
    resolve_ownership,
)
from scaffold_p5.schemas import validate_project_data, whole_file_mutation_allowed
from scaffold_p5 import yaml_lite
from scaffold_p6.candidate import observe_candidate


def build_ownership_update_plan(root: Path) -> dict[str, Any]:
    """Plan adding only `.scaffold/ext/test/evidence/: GENERATED` when UNKNOWN."""
    host = Path(root)
    view = inspect_project(host / PROJECT_YAML)
    blockers: list[str] = []
    ownership: dict[str, Any] = {}
    lifecycle = None
    if not view.valid:
        blockers.extend(
            ["project.yaml is not current and executable"] + list(view.reasons)
        )
    else:
        data = view.data or {}
        lifecycle = data.get("lifecycle")
        ownership = dict(data.get("ownership") or {})
        if lifecycle != "ACTIVE":
            blockers.append("host lifecycle is not ACTIVE")
        allowed, reason = whole_file_mutation_allowed(ownership, PROJECT_YAML)
        if not allowed:
            blockers.append(reason)
        status, schema_issues = validate_project_data(data)
        if status != "VALID":
            blockers.extend(
                ["current project contract is not otherwise valid"] + list(schema_issues)
            )
        blockers.extend(_ownership_update_blockers(ownership))

    candidate = observe_candidate(host)
    if not candidate.usable:
        blockers.extend(
            list(candidate.data.get("blockers") or [
                "current candidate cannot be reconstructed"
            ])
        )

    after = dict(ownership)
    if not blockers:
        after[P6_DURABLE_EVIDENCE_AREA] = "GENERATED"

    body: dict[str, Any] = {
        "kind": "ownership_update",
        "skill": "understand",
        "target": P6_DURABLE_EVIDENCE_AREA,
        "mode": "GENERATED",
        "current_candidate_digest": candidate.digest if candidate.usable else "",
        "before_ownership": dict(ownership),
        "after_ownership": after,
        "mutation_envelope": [PROJECT_YAML],
        "lifecycle": lifecycle,
        "valid": not blockers,
        "blockers": sorted(set(blockers)),
        "reason": (
            "register the proven P6 durable Evidence root as GENERATED; "
            "do not create the directory"
        ),
    }
    body["digest"] = sha256_text(
        yaml_lite.dump({key: value for key, value in body.items() if key != "digest"})
    )
    body["plan_digest"] = body["digest"]
    return body


def apply_ownership_update(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Apply an exact approved ownership-update Plan. Writes project.yaml only."""
    host = Path(root)
    expected = str(plan.get("digest") or plan.get("plan_digest") or "")
    current = build_ownership_update_plan(host)
    if not current.get("valid"):
        return {
            "ok": False,
            "applied": False,
            "blockers": list(current.get("blockers") or ["ownership-update Plan is not valid"]),
            "plan": current,
        }
    if expected != current.get("digest"):
        return {
            "ok": False,
            "applied": False,
            "blockers": ["approved ownership-update Plan does not match the current host"],
            "plan": current,
        }
    view = inspect_project(host / PROJECT_YAML)
    project = dict(view.data or {})
    project["ownership"] = dict(current["after_ownership"])
    write_yaml_atomic(host / PROJECT_YAML, project)
    after = inspect_project(host / PROJECT_YAML)
    if not after.valid:
        return {
            "ok": False,
            "applied": True,
            "blockers": ["written project.yaml failed validation"] + list(after.reasons),
            "plan": current,
        }
    return {
        "ok": True,
        "applied": True,
        "blockers": [],
        "plan": current,
        "artifacts": [PROJECT_YAML],
    }


def _ownership_update_blockers(ownership: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if P6_DURABLE_EVIDENCE_AREA in ownership:
        blockers.append(
            "P6 durable Evidence area already has an exact ownership declaration"
        )
    more_specific = _more_specific_declarations(ownership)
    if more_specific:
        blockers.append(
            "more-specific ownership already covers the P6 durable Evidence area: "
            + ", ".join(f"{path}={mode}" for path, mode in more_specific)
        )
    probe = resolve_ownership(ownership, P6_DURABLE_EVIDENCE_PROBE)
    if probe.status == "CONFLICTING":
        blockers.append(
            f"CONFLICTING ownership covers the P6 durable Evidence area: {probe.reason}"
        )
        return blockers
    if probe.status == "RESOLVED":
        if probe.mode in {"HUMAN_OWNED", "MANAGED"}:
            blockers.append(
                f"{probe.mode} covering declaration {probe.matched_key!r} "
                "blocks P6 durable Evidence ownership update"
            )
        elif probe.mode == "GENERATED":
            blockers.append(
                "P6 durable Evidence path is already covered; ownership is not UNKNOWN"
            )
        else:
            blockers.append(
                f"covering ownership {probe.mode!r} blocks P6 durable Evidence update"
            )
        return blockers
    if probe.status != "UNKNOWN":
        blockers.append(
            f"P6 durable Evidence ownership cannot be reconstructed: {probe.reason}"
        )
    covering = _covering_declarations(ownership)
    for path, mode in covering:
        if mode in {"HUMAN_OWNED", "MANAGED"}:
            blockers.append(
                f"{mode} covering declaration {path!r} blocks P6 durable Evidence "
                "ownership update"
            )
    return blockers


def _more_specific_declarations(ownership: dict[str, Any]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for raw, mode in ownership.items():
        key = str(raw or "").replace("\\", "/")
        if not key or key == P6_DURABLE_EVIDENCE_AREA:
            continue
        if path_covered(key, P6_DURABLE_EVIDENCE_AREA):
            hits.append((key, str(mode)))
    return sorted(hits)


def _covering_declarations(ownership: dict[str, Any]) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for raw, mode in ownership.items():
        key = str(raw or "").replace("\\", "/")
        if not key.endswith("/"):
            continue
        if path_covered(P6_DURABLE_EVIDENCE_PROBE, key):
            hits.append((key, str(mode)))
    return hits

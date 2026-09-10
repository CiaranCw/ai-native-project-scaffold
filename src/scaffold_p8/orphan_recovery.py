"""Plan-first recovery of a stranded pre-durable S9 Change Record."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.host_state import inspect_project
from scaffold_p5.io_util import file_digest, sha256_text
from scaffold_p5.scm import observe_scm
from scaffold_p5 import yaml_lite
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.storage import list_prepared_materializations
from scaffold_p8.models import CHANGES_DIR
from scaffold_p8.records import (
    change_path,
    durability_state,
    list_change_record_ids,
    load_change_record,
    remove_non_durable_change_record,
)
from scaffold_p8.schemas import CHANGE_ID_RE, validate_change_record


def change_record_rel(record_id: str) -> str:
    return f"{CHANGES_DIR}/{record_id}.yaml"


def build_abandon_pre_durable_plan(
    root: Path,
    *,
    change_id: str,
) -> dict[str, Any]:
    host = Path(root)
    blockers: list[str] = []
    record_id = str(change_id or "")
    rel = change_record_rel(record_id) if CHANGE_ID_RE.fullmatch(record_id) else ""
    record = None
    record_digest = ""
    durability: dict[str, Any] = {}
    materialization: dict[str, Any] = {}
    current = observe_candidate(host)
    projected = current
    project_view = inspect_project(host / ".scaffold/project.yaml")
    if not CHANGE_ID_RE.fullmatch(record_id):
        blockers.append("change_id is missing or malformed")
    if not project_view.valid:
        blockers.extend(
            ["project ownership/currentness cannot be reconstructed"]
            + list(project_view.reasons)
        )
    if not current.usable:
        blockers.extend(
            list(current.data.get("blockers") or [
                "current candidate cannot be reconstructed"
            ])
        )
    if CHANGE_ID_RE.fullmatch(record_id):
        path = change_path(host, record_id)
        if not path.is_file():
            blockers.append("Change Record is missing")
        else:
            record = load_change_record(host, record_id)
            if not isinstance(record, dict):
                blockers.append("Change Record is malformed")
            else:
                issues = validate_change_record(record, expected_id=record_id)
                if issues:
                    blockers.extend(["Change Record is malformed"] + issues)
                if str(record.get("record_id") or "") != record_id:
                    blockers.append("change_id does not match the Change Record")
                record_digest = file_digest(path)
            durability = durability_state(host, record_id)
            state = str(durability.get("state") or "")
            if state == "durable":
                blockers.append("Change Record is S10 durable and cannot be abandoned")
            elif state != "absent":
                blockers.extend(
                    list(durability.get("blockers") or [
                        "S10 durability is ambiguous"
                    ])
                )
            materialization = _materialization_state(host, record_id)
            if materialization.get("ambiguous"):
                blockers.extend(
                    list(materialization.get("blockers") or [
                        "P6 materialization coordination state is ambiguous"
                    ])
                )
            scm = observe_scm(host)
            if isinstance(record, dict):
                blockers.extend(_parent_blockers(record, scm))
        others = [
            item
            for item in list_change_record_ids(host)
            if item != record_id and _non_durable_conflict(host, item)
        ]
        if others:
            blockers.append(
                "multiple conflicting candidate-finalization records: "
                + ",".join(others)
            )
        if rel and current.usable:
            projected = observe_candidate(host, omit_paths=[rel])
            if not projected.usable:
                blockers.extend(
                    list(projected.data.get("blockers") or [
                        "projected post-removal candidate cannot be determined exactly"
                    ])
                )
            elif not projected.digest:
                blockers.append(
                    "projected post-removal candidate cannot be determined exactly"
                )

    body: dict[str, Any] = {
        "kind": "abandon_pre_durable_change",
        "skill": "submit",
        "change_id": record_id,
        "change_record_digest": record_digest,
        "change_record_path": rel,
        "current_candidate_digest": current.digest if current.usable else "",
        "projected_candidate_digest": projected.digest if projected.usable else "",
        "head": current.data.get("revision") if current.usable else None,
        "durability": {
            "state": durability.get("state"),
            "non_durable": durability.get("state") == "absent",
            "s10_durable": durability.get("state") == "durable",
        },
        "materialization": materialization,
        "mutation_envelope": [rel] if rel else [],
        "valid": not blockers,
        "blockers": sorted(set(blockers)),
        "reason": (
            "remove only this non-durable pre-S10 Change Record after exact approval"
        ),
    }
    body["digest"] = sha256_text(
        yaml_lite.dump({key: value for key, value in body.items() if key != "digest"})
    )
    body["plan_digest"] = body["digest"]
    return body


def apply_abandon_pre_durable_change(
    root: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    host = Path(root)
    change_id = str(plan.get("change_id") or "")
    expected = str(plan.get("digest") or plan.get("plan_digest") or "")
    current = build_abandon_pre_durable_plan(host, change_id=change_id)
    if not current.get("valid"):
        return {
            "ok": False,
            "applied": False,
            "blockers": list(current.get("blockers") or ["orphan recovery Plan is not valid"]),
            "plan": current,
        }
    if expected != current.get("digest"):
        return {
            "ok": False,
            "applied": False,
            "blockers": ["approved orphan recovery Plan does not match the current host"],
            "plan": current,
        }
    removed = remove_non_durable_change_record(
        host,
        change_id,
        expected_digest=str(current.get("change_record_digest") or ""),
    )
    if not removed.get("ok"):
        return {
            "ok": False,
            "applied": False,
            "blockers": list(removed.get("blockers") or ["Change Record could not be removed"]),
            "plan": current,
        }
    after = observe_candidate(host)
    if not after.usable or after.digest != current.get("projected_candidate_digest"):
        return {
            "ok": False,
            "applied": True,
            "blockers": [
                "post-removal candidate does not match the projected predecessor"
            ],
            "plan": current,
            "artifacts": list(current.get("mutation_envelope") or []),
        }
    return {
        "ok": True,
        "applied": True,
        "blockers": [],
        "plan": current,
        "artifacts": list(current.get("mutation_envelope") or []),
        "current_candidate_digest": after.digest,
    }


def _materialization_state(root: Path, record_id: str) -> dict[str, Any]:
    prepared = list_prepared_materializations(root)
    malformed = [item for item in prepared if item.get("malformed")]
    held = [
        item
        for item in prepared
        if not item.get("malformed")
        and str(item.get("coordination_id") or "") == record_id
    ]
    created: list[str] = []
    for item in held:
        for row in item.get("artifacts") or []:
            if not isinstance(row, dict):
                continue
            rel = str(row.get("path") or "")
            if rel and (root / rel).is_file() and row.get("created"):
                created.append(rel)
    ambiguous = bool(malformed or created)
    blockers: list[str] = []
    if malformed:
        blockers.append("P6 PREPARED materialization is malformed")
    if created:
        blockers.append(
            "P6 materialization created candidate-significant artifacts; "
            "orphan recovery cannot remove only the Change Record"
        )
    return {
        "coordination_id": record_id,
        "prepared_count": len(held),
        "created_artifacts": created,
        "ambiguous": ambiguous,
        "blockers": blockers,
        "state": (
            "ambiguous"
            if ambiguous
            else ("prepared" if held else "absent")
        ),
    }


def _parent_blockers(record: dict[str, Any], scm: Any) -> list[str]:
    base = record.get("base") if isinstance(record.get("base"), dict) else {}
    kind = str(base.get("kind") or "")
    value = base.get("value")
    if kind == "git":
        if getattr(scm, "kind", None) != "git" or not getattr(scm, "ok", False):
            return ["Git parent cannot be reconstructed"]
        if getattr(scm, "revision", None) != value:
            return ["Git parent advanced; orphan recovery is blocked"]
        return []
    if kind == "none":
        if getattr(scm, "kind", None) == "git":
            return ["SCM kind changed; orphan recovery is blocked"]
        return []
    return ["Change Record base kind is not reconstructable"]


def _non_durable_conflict(root: Path, record_id: str) -> bool:
    state = durability_state(root, record_id)
    if state.get("state") == "durable":
        return False
    return change_path(root, record_id).is_file()

"""P8-owned Change Record validation. Not a Foundation schema file."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from scaffold_p8.models import CHANGE_RECORD_TYPE, PROVENANCE_CLASSES, RECORD_SCHEMA_VERSION


CHANGE_ID_RE = re.compile(r"^change-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
TASK_ID_RE = re.compile(r"^task-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
SESSION_ID_RE = re.compile(r"^dev-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{40,64}$")
RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
PATH_CHANGE_KINDS = {
    "added",
    "modified",
    "deleted",
    "renamed",
    "copied",
    "untracked",
    "type_changed",
}

_CHANGE_REQUIRED = (
    "record_type",
    "schema_version",
    "record_id",
    "created_at",
    "summary",
    "base",
    "affected",
    "path_summary",
    "structural_summary",
    "knowledge_updates",
    "verification",
    "understand_involvement",
    "task_book_ids",
    "provenance",
    "limitations",
)

_FORBIDDEN_GRANT_FIELDS = (
    "submit_authorized",
    "submitted",
    "status",
    "commit_sha",
    "can_commit",
    "can_push",
    "grant_ref",
    "attempt_id",
    "authorization_attempt_id",
    "submit_authorization_ref",
    "push_authorization_ref",
)


def validate_change_record(data: Any, *, expected_id: str | None = None) -> list[str]:
    issues: list[str] = []
    if not isinstance(data, dict):
        return ["Change Record is not a mapping"]
    if data.get("record_type") != CHANGE_RECORD_TYPE:
        issues.append("record_type must be change_record")
    if data.get("schema_version") != RECORD_SCHEMA_VERSION:
        issues.append("schema_version must be 1")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not CHANGE_ID_RE.fullmatch(record_id):
        issues.append("record_id is missing or malformed")
    elif expected_id is not None and record_id != expected_id:
        issues.append("record_id does not match filename")
    for field in _CHANGE_REQUIRED:
        if field not in data:
            issues.append(f"Change Record missing {field}")
    if not _timezone_aware_rfc3339(data.get("created_at")):
        issues.append("created_at must be a timezone-aware RFC3339 timestamp")
    if not isinstance(data.get("summary"), str) or not str(data.get("summary") or "").strip():
        issues.append("summary is missing")
    base = data.get("base")
    if not isinstance(base, dict):
        issues.append("base must be a mapping")
    else:
        if base.get("kind") not in {
            "git",
            "perforce",
            "project",
            "none",
            "unavailable",
        }:
            issues.append("base.kind is missing or UNKNOWN")
        if "value" not in base:
            issues.append("base.value is required")
        elif base.get("value") is not None and not _nonempty_text(base.get("value")):
            issues.append("base.value must be a nonempty string or null")
        if base.get("kind") == "git" and not _nonempty_text(base.get("value")):
            issues.append("Git base.value must identify the pre-S10 parent")
        elif (
            base.get("kind") == "git"
            and isinstance(base.get("value"), str)
            and not GIT_OBJECT_RE.fullmatch(base["value"])
        ):
            issues.append("Git base.value must be a valid object identity")
    affected = data.get("affected")
    if not isinstance(affected, dict):
        issues.append("affected must be a mapping")
    else:
        issues.extend(_string_list_issues(affected.get("modules"), "affected.modules"))
        issues.extend(_string_list_issues(affected.get("areas"), "affected.areas"))
    path_summary = data.get("path_summary")
    if not isinstance(path_summary, dict):
        issues.append("path_summary must be a mapping")
    else:
        representation = path_summary.get("representation")
        if representation not in {"exact", "grouped"}:
            issues.append("path_summary.representation must be exact or grouped")
        total = path_summary.get("total_changed_paths")
        if not _strict_nonnegative_int(total):
            issues.append("path_summary.total_changed_paths must be a nonnegative integer")
        paths = path_summary.get("paths")
        if not isinstance(paths, list):
            issues.append("path_summary.paths must be a list")
        else:
            seen: set[str] = set()
            for index, item in enumerate(paths):
                if not isinstance(item, dict):
                    issues.append(f"path_summary.paths[{index}] must be a mapping")
                    continue
                path = item.get("path")
                if not _nonempty_text(path):
                    issues.append(f"path_summary.paths[{index}].path is required")
                    continue
                if path in seen:
                    issues.append(f"path_summary contains duplicate path {path}")
                seen.add(path)
                if str(path).startswith(".scaffold/changes/"):
                    issues.append("path_summary must not list the Change Record file")
                change = item.get("change")
                if change not in PATH_CHANGE_KINDS:
                    issues.append(
                        f"path_summary.paths[{index}].change is missing or unknown"
                    )
                old_path = item.get("old_path")
                if change in {"renamed", "copied"}:
                    if not _nonempty_text(old_path) or old_path == path:
                        issues.append(
                            f"path_summary.paths[{index}].old_path is required"
                        )
                elif old_path is not None:
                    issues.append(
                        f"path_summary.paths[{index}].old_path is only valid for rename/copy"
                    )
            if (
                representation == "exact"
                and _strict_nonnegative_int(total)
                and total != len(paths)
            ):
                issues.append("path_summary total_changed_paths does not match paths")
        if representation == "grouped":
            groups = path_summary.get("groups")
            if not isinstance(groups, list) or not groups:
                issues.append("grouped path_summary requires nonempty groups")
            else:
                for index, item in enumerate(groups):
                    if not isinstance(item, dict):
                        issues.append(
                            f"path_summary.groups[{index}] must be a mapping"
                        )
                        continue
                    if not _nonempty_text(item.get("prefix")):
                        issues.append(
                            f"path_summary.groups[{index}].prefix is required"
                        )
                    if not _strict_nonnegative_int(item.get("count")):
                        issues.append(
                            f"path_summary.groups[{index}].count is malformed"
                        )
                    if "note" in item and not _nonempty_text(item.get("note")):
                        issues.append(
                            f"path_summary.groups[{index}].note must be nonempty"
                        )
    if not _nonempty_text(data.get("structural_summary")):
        issues.append("structural_summary must be a nonempty string")
    if not _nonempty_text(data.get("knowledge_updates")):
        issues.append("knowledge_updates must be a nonempty string")
    task_ids = data.get("task_book_ids")
    if not isinstance(task_ids, list):
        issues.append("task_book_ids must be a list")
    elif any(not isinstance(item, str) or not TASK_ID_RE.fullmatch(item) for item in task_ids):
        issues.append("task_book_ids contains a malformed Task Book identity")
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        issues.append("provenance must be a mapping")
    else:
        session_count = provenance.get("relevant_develop_session_count")
        if not _strict_nonnegative_int(session_count):
            issues.append(
                "provenance.relevant_develop_session_count must be a nonnegative integer"
            )
        session_ids = provenance.get("relevant_develop_session_ids")
        if not isinstance(session_ids, list):
            issues.append("provenance.relevant_develop_session_ids must be a list")
        else:
            seen_ids: set[str] = set()
            for index, item in enumerate(session_ids):
                if not isinstance(item, str) or not SESSION_ID_RE.fullmatch(item):
                    issues.append(
                        f"provenance.relevant_develop_session_ids[{index}] is malformed"
                    )
                    continue
                if item in seen_ids:
                    issues.append(
                        f"provenance.relevant_develop_session_ids contains duplicate {item}"
                    )
                seen_ids.add(item)
        for field in (
            "submit_authorized",
            "grant_ref",
            "grant",
            "attempt_id",
            "authorization_attempt_id",
        ):
            if field in provenance:
                issues.append(f"Change Record must not persist {field}")
        classes = provenance.get("classes")
        if not isinstance(classes, dict):
            issues.append("provenance.classes must be a mapping")
        else:
            if set(classes) != set(PROVENANCE_CLASSES):
                issues.append("provenance.classes must contain the exact P3 class set")
            class_total = 0
            for key, value in classes.items():
                if key not in PROVENANCE_CLASSES:
                    issues.append(f"unknown provenance class {key}")
                    continue
                if not isinstance(value, dict) or set(value) != {"path_count"}:
                    issues.append(f"provenance class {key} must contain only path_count")
                    continue
                count = value.get("path_count")
                if not _strict_nonnegative_int(count):
                    issues.append(f"provenance class {key} path_count is malformed")
                    continue
                class_total += count
            total = (
                path_summary.get("total_changed_paths")
                if isinstance(path_summary, dict)
                else None
            )
            if _strict_nonnegative_int(total) and class_total != total:
                issues.append("provenance path counts do not match path_summary total")
    verification = data.get("verification")
    if not isinstance(verification, dict):
        issues.append("verification must be a mapping")
    else:
        if not _nonempty_text(verification.get("summary")):
            issues.append("verification.summary must be a nonempty string")
        refs = verification.get("evidence_refs")
        if not isinstance(refs, list):
            issues.append("verification.evidence_refs must be a list")
        else:
            for index, item in enumerate(refs):
                if (
                    not isinstance(item, dict)
                    or set(item) != {"locator"}
                    or not _nonempty_text(item.get("locator"))
                ):
                    issues.append(
                        f"verification.evidence_refs[{index}] must contain an opaque locator"
                    )
    understand = data.get("understand_involvement")
    if not isinstance(understand, dict):
        issues.append("understand_involvement must be a mapping")
    else:
        if set(understand) != {"refresh", "compatibility"}:
            issues.append(
                "understand_involvement must contain refresh and compatibility"
            )
        for field in ("refresh", "compatibility"):
            if type(understand.get(field)) is not bool:
                issues.append(f"understand_involvement.{field} must be boolean")
    limitations = data.get("limitations")
    if not isinstance(limitations, list):
        issues.append("limitations must be a list")
    elif any(not _nonempty_text(item) for item in limitations):
        issues.append("limitations entries must be nonempty strings")
    for field in _FORBIDDEN_GRANT_FIELDS:
        if field in data:
            issues.append(f"Change Record must not persist {field}")
    return issues


def validate_finalization_marker(
    data: Any, *, expected_id: str | None = None
) -> list[str]:
    if not isinstance(data, dict):
        return ["finalization support artifact is not a mapping"]
    issues: list[str] = []
    required = {
        "kind",
        "record_class",
        "change_id",
        "ok",
        "scm_kind",
        "candidate_digest",
        "change_record_digest",
        "finalization_digest",
    }
    lineage_fields = {
        "baseline_generation",
        "parent_generation",
        "parent_representation_digest",
        "parent_change_id",
    }
    allowed = required | {
        "commit",
        "tree",
        "support_artifacts",
        "representation_digest",
    } | lineage_fields
    if set(data) - allowed:
        issues.append("finalization support artifact has unknown fields")
    for field in required:
        if field not in data:
            issues.append(f"finalization support artifact missing {field}")
    if data.get("kind") != "submit_finalization":
        issues.append("finalization kind must be submit_finalization")
    if data.get("record_class") != "support_artifact":
        issues.append("finalization record_class must be support_artifact")
    change_id = data.get("change_id")
    if not isinstance(change_id, str) or not CHANGE_ID_RE.fullmatch(change_id):
        issues.append("finalization change_id is malformed")
    elif expected_id is not None and change_id != expected_id:
        issues.append("finalization change_id does not match filename")
    if data.get("ok") is not True:
        issues.append("finalization ok must be true")
    if data.get("scm_kind") not in {"none", "git"}:
        issues.append("finalization scm_kind is unknown")
    for field in ("candidate_digest", "change_record_digest", "finalization_digest"):
        value = data.get(field)
        if not isinstance(value, str) or not HEX_DIGEST_RE.fullmatch(value):
            issues.append(f"finalization {field} is malformed")
    representation = data.get("representation_digest")
    if representation is not None and (
        not isinstance(representation, str) or not HEX_DIGEST_RE.fullmatch(representation)
    ):
        issues.append("finalization representation_digest is malformed")
    lineage_present = lineage_fields & set(data)
    if data.get("scm_kind") == "none":
        if lineage_present != lineage_fields:
            issues.append("no-SCM finalization lineage fields are missing")
        else:
            issues.extend(noscms_lineage_shape_issues(data))
    elif lineage_present and lineage_present != lineage_fields:
        issues.append("finalization lineage fields are incomplete")
    elif lineage_present == lineage_fields:
        issues.extend(noscms_lineage_shape_issues(data))
    if data.get("scm_kind") == "git":
        for field in ("commit", "tree"):
            value = data.get(field)
            if not isinstance(value, str) or not GIT_OBJECT_RE.fullmatch(value):
                issues.append(f"Git finalization {field} is malformed")
    elif "commit" in data or "tree" in data:
        issues.append("no-SCM finalization must not contain Git identity")
    support = data.get("support_artifacts", [])
    if not isinstance(support, list):
        issues.append("finalization support_artifacts must be a list")
    else:
        seen: set[str] = set()
        for item in support:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "digest"}
                or not isinstance(item.get("path"), str)
                or not item["path"].startswith(".scaffold/ext/")
                or any(
                    part in {"", ".", ".."}
                    for part in PurePosixPath(item["path"]).parts
                )
                or item["path"] in seen
                or not isinstance(item.get("digest"), str)
                or not HEX_DIGEST_RE.fullmatch(item["digest"])
            ):
                issues.append("finalization support_artifact is malformed")
                continue
            seen.add(item["path"])
    return issues


def noscms_lineage_shape_issues(data: Any) -> list[str]:
    """Shared no-SCM lineage shape. Genesis parent_change_id is empty, not absent."""
    if not isinstance(data, dict):
        return ["no-SCM publication lineage is malformed"]
    issues: list[str] = []
    generation = data.get("baseline_generation")
    parent_generation = data.get("parent_generation")
    if type(generation) is not int or generation < 1:
        issues.append("finalization baseline_generation is malformed")
    if type(parent_generation) is not int or parent_generation < 0:
        issues.append("finalization parent_generation is malformed")
    elif type(generation) is int and parent_generation != generation - 1:
        issues.append(
            "finalization lineage parent_generation does not precede "
            "baseline_generation"
        )
    parent_digest = data.get("parent_representation_digest")
    if not isinstance(parent_digest, str) or not HEX_DIGEST_RE.fullmatch(
        parent_digest
    ):
        issues.append("finalization parent_representation_digest is malformed")
    parent_id = data.get("parent_change_id")
    if not isinstance(parent_id, str):
        issues.append("finalization parent_change_id is malformed")
    elif type(parent_generation) is int and parent_generation == 0:
        if parent_id != "":
            issues.append("finalization lineage root parent_change_id must be empty")
    elif not CHANGE_ID_RE.fullmatch(str(parent_id or "")):
        issues.append("finalization parent_change_id is malformed")
    return issues


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strict_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _string_list_issues(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{field} must be a list"]
    if any(not _nonempty_text(item) for item in value):
        return [f"{field} entries must be nonempty strings"]
    return []


def _timezone_aware_rfc3339(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not RFC3339_RE.fullmatch(value)
    ):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None

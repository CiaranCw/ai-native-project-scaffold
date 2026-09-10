"""Project-understanding currentness. Supporting authority, not a canonical record."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import (
    COMMANDS_YAML,
    MODULES_YAML,
    PROJECT_YAML,
    SKILLS_LOCK,
    TESTS_YAML,
)
from scaffold_p5.inventory import EXCLUDED_DIR_NAMES
from scaffold_p5.io_util import file_digest, read_yaml, sha256_text
from scaffold_p5.models import UNDERSTANDING_CURRENTNESS
from scaffold_p5 import yaml_lite


CURRENTNESS_ROOT = ".scaffold/runtime/understand-currentness"
HEADS_ROOT = ".scaffold/runtime/understand-currentness/heads"
SCOPE_PROJECT = "project"
RECORD_TYPE = "understand_currentness"
HEAD_RECORD_TYPE = "understand_currentness_head"
SCHEMA_VERSION = "1"
PRODUCER_SKILL = "understand"
SNAPSHOT_ID_RE = re.compile(r"^uc-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LOCATOR_RE = re.compile(
    r"^understand-currentness/uc-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}/snapshot\.yaml$"
)
HEAD_LOCATOR = "understand-currentness/heads/project/head.yaml"

SKIP_DIR_NAMES = EXCLUDED_DIR_NAMES
SKIP_FILE_SUFFIXES = (".pyc", ".pyo")
RUNTIME_PREFIX = ".scaffold/runtime/"


def snapshot_locator(record_id: str) -> str:
    return f"understand-currentness/{record_id}/snapshot.yaml"


def snapshot_path(root: Path, locator: str) -> Path | None:
    if not isinstance(locator, str) or not LOCATOR_RE.fullmatch(locator):
        return None
    if ".." in locator.replace("\\", "/"):
        return None
    return Path(root) / ".scaffold/runtime" / locator


def head_path(root: Path) -> Path:
    return Path(root) / ".scaffold/runtime" / HEAD_LOCATOR


def observe_physical_understanding(root: str | Path) -> dict[str, Any]:
    """Observe declared modules and structural indexes. Not a timestamp claim."""
    host = Path(root)
    modules_path = host / MODULES_YAML
    if not modules_path.is_file():
        return {
            "ok": False,
            "reasons": ["declared module index is missing"],
            "structural_digest": "",
            "physical_digest": "",
            "modules": [],
            "unmapped": [],
        }
    try:
        index = read_yaml(modules_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "reasons": ["declared module index is malformed or unreadable"],
            "structural_digest": "",
            "physical_digest": "",
            "modules": [],
            "unmapped": [],
        }
    if not isinstance(index, dict) or not isinstance(index.get("modules"), list):
        return {
            "ok": False,
            "reasons": ["declared module index is not a mapping with modules"],
            "structural_digest": "",
            "physical_digest": "",
            "modules": [],
            "unmapped": [],
        }
    modules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    reasons: list[str] = []
    for row in index.get("modules") or []:
        if not isinstance(row, dict):
            reasons.append("module index contains a non-mapping entry")
            continue
        module_id = str(row.get("id") or "").strip()
        path = str(row.get("path") or "").replace("\\", "/").strip().strip("/")
        if not module_id or not path:
            reasons.append("module index entry is missing id or path")
            continue
        if module_id in seen_ids:
            reasons.append(f"duplicate declared module id: {module_id}")
            continue
        seen_ids.add(module_id)
        target = host / path
        missing = not target.exists()
        digest = _tree_digest(host, path) if not missing else ""
        modules.append(
            {
                "id": module_id,
                "path": path,
                "digest": digest,
                "knowledge_entry": str(row.get("knowledge_entry") or ""),
                "kind": str(row.get("kind") or "source"),
                "missing": missing,
            }
        )
    structural = structural_digest(host)
    unmapped = _unmapped_paths(host, modules)
    physical = physical_digest_for(structural, modules, unmapped)
    return {
        "ok": not reasons,
        "reasons": reasons,
        "structural_digest": structural,
        "physical_digest": physical,
        "modules": modules,
        "unmapped": unmapped,
    }


def structural_digest(root: str | Path) -> str:
    host = Path(root)
    parts: dict[str, str] = {}
    for rel in (MODULES_YAML, COMMANDS_YAML, TESTS_YAML, SKILLS_LOCK):
        path = host / rel
        parts[rel] = file_digest(path) if path.is_file() else ""
    project_path = host / PROJECT_YAML
    identity: dict[str, Any] = {}
    if project_path.is_file():
        try:
            data = read_yaml(project_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            data = None
        if isinstance(data, dict):
            identity = {
                "schema_version": data.get("schema_version"),
                "project_contract_generation": data.get("project_contract_generation"),
                "ownership": data.get("ownership") or {},
                "source_areas": data.get("source_areas") or [],
                "capabilities": data.get("capabilities") or {},
            }
    parts["project_identity"] = sha256_text(yaml_lite.dump(identity)) if identity else ""
    return sha256_text(yaml_lite.dump(parts))


def physical_digest_for(
    structural: str,
    modules: list[dict[str, Any]],
    unmapped: list[dict[str, str]],
) -> str:
    body = {
        "structural_digest": structural,
        "modules": [
            {
                "id": item.get("id"),
                "path": item.get("path"),
                "digest": item.get("digest"),
            }
            for item in sorted(modules, key=lambda row: str(row.get("id") or ""))
        ],
        "unmapped": [
            {"path": item.get("path"), "digest": item.get("digest")}
            for item in sorted(unmapped, key=lambda row: str(row.get("path") or ""))
        ],
    }
    return sha256_text(yaml_lite.dump(body))


def evaluate_understanding_currentness(root: str | Path) -> dict[str, Any]:
    """Compare the current-head snapshot to physical module/structural authority."""
    host = Path(root)
    observed = observe_physical_understanding(host)
    loaded = load_current_snapshot(host)
    result: dict[str, Any] = {
        "currentness": "UNKNOWN",
        "reasons": [],
        "affected_module_ids": [],
        "reusable_module_ids": [],
        "structural_changed": False,
        "module_set_changed": False,
        "unmapped_changed": False,
        "ambiguous": False,
        "observed": observed,
        "snapshot": loaded.get("snapshot"),
        "head": loaded.get("head"),
        "locator": loaded.get("locator") or "",
        "snapshot_digest": loaded.get("snapshot_digest") or "",
        "physical_digest": observed.get("physical_digest") or "",
        "head_digest": loaded.get("head_digest") or "",
    }
    if not observed.get("ok"):
        result["currentness"] = "UNKNOWN"
        result["reasons"] = list(observed.get("reasons") or ["physical understanding observation failed"])
        return result
    if not loaded.get("ok"):
        reason = str(loaded.get("reason") or "missing")
        if reason in {"missing"}:
            result["currentness"] = "FULL_REFRESH_REQUIRED"
            result["reasons"] = ["no durable project understanding current-head"]
            return result
        result["currentness"] = "UNKNOWN"
        result["reasons"] = list(loaded.get("blockers") or ["understanding current-head is not reconstructable"])
        return result
    snapshot = loaded.get("snapshot") or {}
    bound_structural = str(snapshot.get("structural_digest") or "")
    bound_physical = str(snapshot.get("physical_digest") or "")
    if bound_physical and bound_physical == observed.get("physical_digest"):
        result["currentness"] = "CURRENT"
        result["reusable_module_ids"] = [str(item.get("id")) for item in observed.get("modules") or []]
        result["reasons"] = ["physical module and structural authority match the current-head snapshot"]
        return _with_knowledge_currentness(host, result)
    if bound_structural != observed.get("structural_digest"):
        previous_ids = {
            str(item.get("id"))
            for item in (snapshot.get("modules") or [])
            if isinstance(item, dict) and item.get("id")
        }
        current_ids = {
            str(item.get("id"))
            for item in (observed.get("modules") or [])
            if isinstance(item, dict) and item.get("id")
        }
        result["currentness"] = "FULL_REFRESH_REQUIRED"
        result["structural_changed"] = True
        result["module_set_changed"] = previous_ids != current_ids
        result["ambiguous"] = True
        result["reasons"] = [
            "structural project/module/command/test/lock authority changed; incremental reuse is not bounded"
        ]
        return _with_knowledge_currentness(host, result)
    previous_modules = {
        str(item.get("id")): item
        for item in (snapshot.get("modules") or [])
        if isinstance(item, dict) and item.get("id")
    }
    current_modules = {
        str(item.get("id")): item
        for item in (observed.get("modules") or [])
        if isinstance(item, dict) and item.get("id")
    }
    if set(previous_modules) != set(current_modules):
        result["currentness"] = "FULL_REFRESH_REQUIRED"
        result["module_set_changed"] = True
        result["ambiguous"] = True
        result["reasons"] = ["declared module set changed; incremental reuse is not bounded"]
        return _with_knowledge_currentness(host, result)
    for module_id, current in current_modules.items():
        previous = previous_modules.get(module_id) or {}
        if str(previous.get("path") or "") != str(current.get("path") or ""):
            result["currentness"] = "FULL_REFRESH_REQUIRED"
            result["module_set_changed"] = True
            result["ambiguous"] = True
            result["reasons"] = [
                f"module boundary changed for {module_id}; incremental reuse is not bounded"
            ]
            return _with_knowledge_currentness(host, result)
        if current.get("missing") or previous.get("missing"):
            result["currentness"] = "FULL_REFRESH_REQUIRED"
            result["ambiguous"] = True
            result["reasons"] = [
                f"module path is missing for {module_id}; incremental reuse is not bounded"
            ]
            return result
    previous_unmapped = _unmapped_key(snapshot.get("unmapped") or [])
    current_unmapped = _unmapped_key(observed.get("unmapped") or [])
    if previous_unmapped != current_unmapped:
        result["currentness"] = "FULL_REFRESH_REQUIRED"
        result["unmapped_changed"] = True
        result["ambiguous"] = True
        result["reasons"] = [
            "unmapped source paths changed; module mapping is ambiguous"
        ]
        return result
    affected: list[str] = []
    reusable: list[str] = []
    for module_id, current in sorted(current_modules.items()):
        previous = previous_modules.get(module_id) or {}
        if str(previous.get("digest") or "") == str(current.get("digest") or ""):
            reusable.append(module_id)
        else:
            affected.append(module_id)
    if not affected:
        result["currentness"] = "CURRENT"
        result["reusable_module_ids"] = reusable
        result["reasons"] = ["physical module and structural authority match the current-head snapshot"]
        return _with_knowledge_currentness(host, result)
    result["currentness"] = "PARTIAL_REFRESH_REQUIRED"
    result["affected_module_ids"] = affected
    result["reusable_module_ids"] = reusable
    result["reasons"] = [
        "physical change is bounded to declared modules: " + ", ".join(affected)
    ]
    return _with_knowledge_currentness(host, result)


def load_current_snapshot(root: str | Path) -> dict[str, Any]:
    host = Path(root)
    path = head_path(host)
    if not path.is_file():
        return {"ok": False, "reason": "missing", "blockers": ["understanding current-head is missing"]}
    try:
        head = read_yaml(path)
        head_digest = file_digest(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "reason": "malformed",
            "blockers": ["understanding current-head is malformed or unreadable"],
        }
    issues = validate_currentness_head(head)
    if issues:
        return {"ok": False, "reason": "malformed", "blockers": issues, "head": head}
    assert isinstance(head, dict)
    locator = str(head.get("locator") or "")
    snap_path = snapshot_path(host, locator)
    if snap_path is None or not snap_path.is_file():
        return {
            "ok": False,
            "reason": "unresolvable",
            "blockers": ["understanding snapshot locator is missing or illegal"],
            "head": head,
        }
    try:
        snapshot = read_yaml(snap_path)
        actual_digest = file_digest(snap_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "reason": "malformed",
            "blockers": ["understanding snapshot is malformed or unreadable"],
            "head": head,
        }
    snap_issues = validate_currentness_snapshot(snapshot)
    if snap_issues:
        return {
            "ok": False,
            "reason": "malformed",
            "blockers": snap_issues,
            "head": head,
            "snapshot": snapshot,
        }
    assert isinstance(snapshot, dict)
    expected = str(head.get("snapshot_digest") or "")
    if actual_digest != expected:
        return {
            "ok": False,
            "reason": "integrity_mismatch",
            "blockers": [
                "understanding snapshot bytes do not match the current-head integrity binding"
            ],
            "head": head,
            "snapshot": snapshot,
        }
    if str(snapshot.get("record_id") or "") != str(head.get("record_id") or ""):
        return {
            "ok": False,
            "reason": "identity_mismatch",
            "blockers": ["understanding current-head record_id does not match the snapshot"],
            "head": head,
            "snapshot": snapshot,
        }
    if locator != snapshot_locator(str(head.get("record_id") or "")):
        return {
            "ok": False,
            "reason": "identity_mismatch",
            "blockers": ["understanding current-head locator does not match record_id"],
            "head": head,
            "snapshot": snapshot,
        }
    return {
        "ok": True,
        "locator": locator,
        "snapshot": snapshot,
        "head": head,
        "snapshot_digest": actual_digest,
        "head_digest": head_digest,
        "blockers": [],
    }


def validate_currentness_head(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["understanding current-head is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != HEAD_RECORD_TYPE:
        issues.append("record_type must be understand_currentness_head")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("understanding current-head schema_version must be 1")
    if data.get("canonical") is True:
        issues.append("understanding current-head must not claim canonical record authority")
    if str(data.get("scope") or "") != SCOPE_PROJECT:
        issues.append("understanding current-head scope must be project")
    locator = data.get("locator")
    if not isinstance(locator, str) or not LOCATOR_RE.fullmatch(locator):
        issues.append("understanding current-head locator is missing or illegal")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not SNAPSHOT_ID_RE.fullmatch(record_id):
        issues.append("understanding current-head record_id is missing or malformed")
    digest = data.get("snapshot_digest")
    if not isinstance(digest, str) or not HEX64_RE.fullmatch(digest):
        issues.append("understanding current-head snapshot_digest must be the published snapshot digest")
    physical = data.get("physical_digest")
    if not isinstance(physical, str) or not HEX64_RE.fullmatch(physical):
        issues.append("understanding current-head physical_digest must be a SHA-256 hex digest")
    if (
        isinstance(record_id, str)
        and SNAPSHOT_ID_RE.fullmatch(record_id)
        and isinstance(locator, str)
        and LOCATOR_RE.fullmatch(locator)
        and locator != snapshot_locator(record_id)
    ):
        issues.append(
            "understanding current-head locator does not identify the same snapshot as record_id"
        )
    return issues


def validate_currentness_snapshot(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["understanding snapshot is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != RECORD_TYPE:
        issues.append("record_type must be understand_currentness")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("understanding snapshot schema_version must be 1")
    if data.get("canonical") is True:
        issues.append("understanding snapshot must not claim canonical record authority")
    if data.get("supporting") is not True:
        issues.append("understanding snapshot must be marked supporting")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not SNAPSHOT_ID_RE.fullmatch(record_id):
        issues.append("understanding snapshot record_id is missing or malformed")
    if str(data.get("scope") or "") != SCOPE_PROJECT:
        issues.append("understanding snapshot scope must be project")
    if not isinstance(data.get("structural_digest"), str) or not HEX64_RE.fullmatch(
        str(data.get("structural_digest") or "")
    ):
        issues.append("understanding snapshot structural_digest must be a SHA-256 hex digest")
    if not isinstance(data.get("physical_digest"), str) or not HEX64_RE.fullmatch(
        str(data.get("physical_digest") or "")
    ):
        issues.append("understanding snapshot physical_digest must be a SHA-256 hex digest")
    modules = data.get("modules")
    if not isinstance(modules, list):
        issues.append("understanding snapshot modules must be a list")
    producer = data.get("producer")
    if not isinstance(producer, dict) or producer.get("skill_id") != PRODUCER_SKILL:
        issues.append("understanding snapshot producer.skill_id must be understand")
    return issues


def currentness_values() -> tuple[str, ...]:
    return UNDERSTANDING_CURRENTNESS


def _with_knowledge_currentness(host: Path, result: dict[str, Any]) -> dict[str, Any]:
    from scaffold_p5.refresh_completion import apply_knowledge_currentness

    return apply_knowledge_currentness(host, result)


def _tree_digest(host: Path, rel: str) -> str:
    files = _files_under(host, rel)
    rows = []
    for item in files:
        path = host / item
        try:
            digest = file_digest(path)
        except OSError:
            continue
        rows.append({"path": item, "digest": digest})
    return sha256_text(yaml_lite.dump(rows))


def _files_under(host: Path, rel: str) -> list[str]:
    base = host / rel
    if base.is_file():
        normalized = rel.replace("\\", "/")
        if _skipped_rel(normalized):
            return []
        return [normalized]
    if not base.is_dir():
        return []
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [name for name in dirnames if name.lower() not in SKIP_DIR_NAMES]
        for name in filenames:
            full = Path(dirpath) / name
            item = str(full.relative_to(host)).replace("\\", "/")
            if _skipped_rel(item):
                continue
            out.append(item)
    return sorted(out)


def _unmapped_paths(host: Path, modules: list[dict[str, Any]]) -> list[dict[str, str]]:
    prefixes = [
        str(item.get("path") or "").replace("\\", "/").strip("/")
        for item in modules
        if item.get("path")
    ]
    roots = _coverage_roots(host, prefixes)
    mapped: list[str] = []
    for prefix in prefixes:
        mapped.extend(_files_under(host, prefix))
    mapped_set = set(mapped)
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for root_rel in roots:
        for item in _files_under(host, root_rel):
            if item in mapped_set or item in seen:
                continue
            if any(item == prefix or item.startswith(prefix + "/") for prefix in prefixes):
                continue
            seen.add(item)
            path = host / item
            try:
                digest = file_digest(path)
            except OSError:
                continue
            found.append({"path": item, "digest": digest})
    return sorted(found, key=lambda row: row["path"])


def _coverage_roots(host: Path, module_paths: list[str]) -> list[str]:
    project_path = host / PROJECT_YAML
    areas: list[str] = []
    if project_path.is_file():
        try:
            data = read_yaml(project_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("source_areas"), list):
            areas = [
                str(item).replace("\\", "/").strip().strip("/")
                for item in data.get("source_areas") or []
                if item
            ]
    if not areas:
        for rel in module_paths:
            head = rel.split("/", 1)[0]
            if head and head not in areas:
                areas.append(head)
    return [item for item in areas if item]


def _unmapped_key(rows: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        out.append((str(item.get("path") or ""), str(item.get("digest") or "")))
    return sorted(out)


def _skipped_rel(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if normalized.endswith(SKIP_FILE_SUFFIXES):
        return True
    parts = [part.lower() for part in normalized.split("/")]
    if any(part in SKIP_DIR_NAMES for part in parts):
        return True
    return False

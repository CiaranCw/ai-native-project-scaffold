"""Understand-owned supporting refresh-completion receipts. Not a canonical record."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.agents import (
    parse_managed_regions,
    registered_region_ids,
    registry_marker_issues,
    replace_managed_region,
)
from scaffold_p5.currentness import (
    HEX64_RE,
    observe_physical_understanding,
)
from scaffold_p5.full import MODULE_ENTRY
from scaffold_p5.host_state import PROJECT_YAML
from scaffold_p5.io_util import file_digest, read_text, read_yaml, write_text_atomic, write_yaml_atomic
from scaffold_p5.refresh import register_generated_ownership
from scaffold_p5.schemas import plan_owned_text_mutation


COMPLETIONS_ROOT = ".scaffold/runtime/understand-currentness/completions"
RECORD_TYPE = "understand_refresh_completion"
OUTPUT_RECORD_TYPE = "understand_refresh_result"
SCHEMA_VERSION = "1"
PRODUCER_SKILL = "understand"
COMPLETION_ID_RE = re.compile(r"^rc-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


def completion_locator(record_id: str) -> str:
    return f"understand-currentness/completions/{record_id}/completion.yaml"


def result_locator(record_id: str) -> str:
    return f"understand-currentness/completions/{record_id}/result.yaml"


def produce_refresh_completion(
    root: str | Path,
    *,
    module_ids: list[str] | None = None,
    producer_mode: str = "refresh",
    knowledge_payloads: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Publish final Understand knowledge then bind a supporting completion receipt."""
    host = Path(root)
    observed = observe_physical_understanding(host)
    if not observed.get("ok"):
        return {
            "ok": False,
            "needs_human": True,
            "blockers": list(observed.get("reasons") or ["physical understanding observation failed"]),
        }
    by_id = {
        str(item.get("id")): item
        for item in observed.get("modules") or []
        if isinstance(item, dict) and item.get("id")
    }
    requested = [str(item) for item in (module_ids or list(by_id)) if item]
    missing = [item for item in requested if item not in by_id]
    if missing:
        return {
            "ok": False,
            "blockers": [
                "refresh completion requested modules that are not in the declared index: "
                + ", ".join(missing)
            ],
        }
    if not requested:
        return {"ok": False, "blockers": ["refresh completion requires a non-empty module scope"]}
    project = _load_project(host)
    if not project.get("ok"):
        return {
            "ok": False,
            "needs_human": True,
            "blockers": list(project.get("blockers") or ["project.yaml is not reconstructable"]),
        }
    ownership = dict((project.get("data") or {}).get("ownership") or {})
    payloads = {
        str(key): value
        for key, value in (knowledge_payloads or {}).items()
        if isinstance(key, str) and isinstance(value, str)
    }
    planned: list[dict[str, Any]] = []
    register: list[str] = []
    blockers: list[str] = []
    needs_human = False
    for module_id in requested:
        row = by_id[module_id]
        item = _plan_module_knowledge(
            host,
            row,
            ownership=ownership,
            project=project.get("data") or {},
            payload=payloads.get(module_id),
        )
        planned.append(item)
        if item.get("blockers"):
            blockers.extend(item["blockers"])
            needs_human = needs_human or bool(item.get("needs_human"))
            continue
        if item.get("register_generated"):
            register.append(str(item.get("knowledge_entry") or ""))
    if blockers:
        return {
            "ok": False,
            "needs_human": True if needs_human else False,
            "blockers": blockers,
            "mutations": False,
        }
    if register:
        registered = register_generated_ownership(host, register)
        if not registered.get("ok"):
            return {
                "ok": False,
                "needs_human": bool(registered.get("needs_human")),
                "blockers": list(
                    registered.get("blockers") or ["ownership registration failed"]
                ),
                "mutations": False,
            }
        ownership = dict(registered.get("ownership") or ownership)
        observed = observe_physical_understanding(host)
        if not observed.get("ok"):
            return {
                "ok": False,
                "needs_human": True,
                "blockers": list(
                    observed.get("reasons") or ["physical understanding observation failed"]
                ),
                "mutations": True,
            }
        by_id = {
            str(item.get("id")): item
            for item in observed.get("modules") or []
            if isinstance(item, dict) and item.get("id")
        }
    for item in planned:
        row = by_id[item["module_id"]]
        applied = _apply_module_knowledge(
            host,
            row,
            item,
            ownership=ownership,
            payload=payloads.get(str(item.get("module_id") or "")),
        )
        if applied.get("blockers"):
            return {
                "ok": False,
                "needs_human": bool(applied.get("needs_human")),
                "blockers": list(applied["blockers"]),
                "mutations": True,
            }
        item["knowledge_digest"] = applied.get("knowledge_digest") or ""
        item["source_digest"] = str(row.get("digest") or "")
    record_id = _allocate_id(host)
    modules: list[dict[str, Any]] = []
    for item in planned:
        row = by_id[item["module_id"]]
        modules.append(
            {
                "id": item["module_id"],
                "path": str(row.get("path") or ""),
                "source_digest": str(row.get("digest") or ""),
                "knowledge_entry": str(item.get("knowledge_entry") or ""),
                "knowledge_digest": str(item.get("knowledge_digest") or ""),
            }
        )
    result_payload = {
        "record_type": OUTPUT_RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "record_id": record_id,
        "producer": {"skill_id": PRODUCER_SKILL, "mode": producer_mode},
        "structural_digest": observed.get("structural_digest"),
        "modules": modules,
    }
    result_path = host / ".scaffold/runtime" / result_locator(record_id)
    write_yaml_atomic(result_path, result_payload)
    output_digest = file_digest(result_path)
    completion = {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "record_id": record_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": {"skill_id": PRODUCER_SKILL, "mode": producer_mode},
        "structural_digest": observed.get("structural_digest"),
        "module_ids": requested,
        "modules": modules,
        "output_locator": result_locator(record_id),
        "output_digest": output_digest,
    }
    issues = validate_refresh_completion(completion)
    if issues:
        return {"ok": False, "blockers": issues, "completion": completion}
    write_yaml_atomic(host / ".scaffold/runtime" / completion_locator(record_id), completion)
    return {
        "ok": True,
        "locator": completion_locator(record_id),
        "output_locator": result_locator(record_id),
        "output_digest": output_digest,
        "record_id": record_id,
        "module_ids": requested,
        "structural_digest": observed.get("structural_digest"),
        "completion": completion,
        "blockers": [],
        "registered_ownership": register,
    }


def load_refresh_completions(root: str | Path) -> list[dict[str, Any]]:
    host = Path(root)
    folder = host / COMPLETIONS_ROOT
    if not folder.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for child in sorted(folder.iterdir(), key=lambda path: path.name):
        path = child / "completion.yaml"
        if not child.is_dir() or not path.is_file():
            continue
        loaded = resolve_refresh_completion(host, completion_locator(child.name))
        if loaded.get("ok"):
            rows.append(loaded)
    return rows


def resolve_refresh_completion(root: str | Path, locator: str) -> dict[str, Any]:
    host = Path(root)
    if not isinstance(locator, str) or ".." in locator.replace("\\", "/"):
        return {"ok": False, "blockers": ["refresh completion locator is illegal"]}
    if not locator.startswith("understand-currentness/completions/") or not locator.endswith(
        "/completion.yaml"
    ):
        return {"ok": False, "blockers": ["refresh completion locator is illegal"]}
    path = host / ".scaffold/runtime" / locator
    if not path.is_file():
        return {"ok": False, "blockers": ["refresh completion is missing"]}
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ok": False, "blockers": ["refresh completion is malformed or unreadable"]}
    issues = validate_refresh_completion(data)
    if issues:
        return {"ok": False, "blockers": issues, "completion": data}
    assert isinstance(data, dict)
    record_id = str(data.get("record_id") or "")
    if completion_locator(record_id) != locator:
        return {
            "ok": False,
            "blockers": ["refresh completion locator does not match record identity"],
            "completion": data,
        }
    output_locator = str(data.get("output_locator") or "")
    output_path = host / ".scaffold/runtime" / output_locator
    if not output_path.is_file():
        return {"ok": False, "blockers": ["refresh completion output artifact is missing"]}
    actual = file_digest(output_path)
    if actual != str(data.get("output_digest") or ""):
        return {
            "ok": False,
            "blockers": [
                "refresh completion output bytes do not match the bound output digest"
            ],
            "completion": data,
        }
    try:
        output = read_yaml(output_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "blockers": ["refresh completion output artifact is malformed or unreadable"],
            "completion": data,
        }
    if not isinstance(output, dict):
        return {
            "ok": False,
            "blockers": ["refresh completion output artifact is not a mapping"],
            "completion": data,
        }
    if str(output.get("record_id") or "") != record_id:
        return {
            "ok": False,
            "blockers": ["refresh completion output record identity does not match"],
            "completion": data,
        }
    if output.get("record_type") != OUTPUT_RECORD_TYPE:
        return {
            "ok": False,
            "blockers": ["refresh completion output record_type is not coherent"],
            "completion": data,
        }
    if str(output.get("structural_digest") or "") != str(data.get("structural_digest") or ""):
        return {
            "ok": False,
            "blockers": ["refresh completion output structural digest is not coherent"],
            "completion": data,
        }
    if not _module_bindings_match(output.get("modules"), data.get("modules")):
        return {
            "ok": False,
            "blockers": ["refresh completion output module bindings do not match the receipt"],
            "completion": data,
        }
    return {
        "ok": True,
        "locator": locator,
        "completion": data,
        "output_digest": actual,
        "blockers": [],
    }


def completions_covering(
    root: str | Path,
    *,
    observed: dict[str, Any],
    locators: list[str] | None = None,
) -> dict[str, Any]:
    """Return per-module valid completions whose source/structural bindings still hold."""
    covered: dict[str, dict[str, Any]] = {}
    mismatched: list[str] = []
    structural = str(observed.get("structural_digest") or "")
    by_id = {
        str(item.get("id")): item
        for item in observed.get("modules") or []
        if isinstance(item, dict) and item.get("id")
    }
    loaded_rows: list[dict[str, Any]]
    if locators is None:
        loaded_rows = load_refresh_completions(root)
    else:
        loaded_rows = []
        for locator in locators:
            loaded = resolve_refresh_completion(root, str(locator))
            if loaded.get("ok"):
                loaded_rows.append(loaded)
            else:
                mismatched.extend(
                    loaded.get("blockers")
                    or [f"refresh completion locator is not valid current authority: {locator}"]
                )
    for loaded in loaded_rows:
        completion = loaded.get("completion") or {}
        if str(completion.get("structural_digest") or "") != structural:
            mismatched.append(
                "refresh completion structural digest does not match current structural authority: "
                + str(loaded.get("locator") or "")
            )
            continue
        for row in completion.get("modules") or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            module_id = str(row.get("id"))
            current = by_id.get(module_id) or {}
            claimed = str(row.get("source_digest") or "")
            actual = str(current.get("digest") or "")
            if not actual or claimed != actual:
                mismatched.append(
                    f"refresh completion source digest does not match current module {module_id}"
                )
                continue
            claimed_path = _normalize_entry(row.get("path"))
            observed_path = _normalize_entry(current.get("path"))
            if claimed_path and observed_path and claimed_path != observed_path:
                mismatched.append(
                    f"refresh completion path does not match current module {module_id}"
                )
                continue
            knowledge_rel = _normalize_entry(row.get("knowledge_entry"))
            observed_entry = _normalize_entry(current.get("knowledge_entry"))
            if knowledge_rel and observed_entry and knowledge_rel != observed_entry:
                mismatched.append(
                    f"refresh completion knowledge_entry does not match module {module_id}"
                )
                continue
            required_entry = knowledge_rel or observed_entry
            if required_entry:
                knowledge_path = Path(root) / required_entry.replace("\\", "/")
                if not knowledge_path.is_file():
                    mismatched.append(
                        f"refresh completion knowledge_entry is missing: {required_entry}"
                    )
                    continue
                actual_knowledge = file_digest(knowledge_path)
                claimed_knowledge = str(row.get("knowledge_digest") or "")
                if not claimed_knowledge or actual_knowledge != claimed_knowledge:
                    mismatched.append(
                        f"refresh completion knowledge digest does not match {required_entry}"
                    )
                    continue
                knowledge_rel = required_entry
            covered[module_id] = {
                "locator": loaded.get("locator"),
                "output_locator": completion.get("output_locator"),
                "output_digest": loaded.get("output_digest"),
                "source_digest": claimed,
                "knowledge_entry": knowledge_rel,
                "knowledge_digest": row.get("knowledge_digest"),
            }
    return {"covered": covered, "mismatched": mismatched}


def referenced_completion_targets(completion: dict[str, Any]) -> list[str]:
    """Transitive supporting locators required to verify a completion receipt."""
    targets: list[str] = []
    locator = completion.get("output_locator")
    if isinstance(locator, str) and locator:
        targets.append(locator)
    return targets


def review_package_missing_targets(
    packaged_paths: list[str],
    completions: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Return referenced completion targets omitted from a claimed review package."""
    packaged = {_normalize_packaged(path) for path in packaged_paths}
    missing: list[str] = []
    for path in packaged_paths:
        norm = _normalize_packaged(path)
        if not norm.endswith("completion.yaml"):
            continue
        sibling = norm[: -len("completion.yaml")] + "result.yaml"
        if not packaged.intersection(_packaged_aliases(sibling)) and sibling not in missing:
            missing.append(sibling)
    for completion in completions or []:
        if not isinstance(completion, dict):
            continue
        record_id = str(completion.get("record_id") or "")
        completion_rel = completion_locator(record_id) if record_id else ""
        if not packaged.intersection(_packaged_aliases(completion_rel)):
            continue
        for target in referenced_completion_targets(completion):
            if not packaged.intersection(_packaged_aliases(target)) and target not in missing:
                missing.append(target)
    return missing


def _normalize_entry(rel: Any) -> str:
    value = str(rel or "").replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.strip().strip("/")


def _module_binding_key(row: Any) -> tuple[str, str, str, str, str] | None:
    if not isinstance(row, dict):
        return None
    return (
        str(row.get("id") or ""),
        _normalize_entry(row.get("path")),
        str(row.get("source_digest") or ""),
        _normalize_entry(row.get("knowledge_entry")),
        str(row.get("knowledge_digest") or ""),
    )


def _module_bindings_match(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return False
    left_keys = [_module_binding_key(row) for row in left]
    right_keys = [_module_binding_key(row) for row in right]
    return left_keys == right_keys and all(item is not None for item in left_keys)


def _normalize_packaged(path: str) -> str:
    rel = str(path or "").replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    prefix = ".scaffold/runtime/"
    if rel.startswith(prefix):
        rel = rel[len(prefix) :]
    return rel


def _packaged_aliases(locator: str) -> set[str]:
    loc = str(locator or "").replace("\\", "/")
    return {loc, ".scaffold/runtime/" + loc, _normalize_packaged(loc)}


def apply_knowledge_currentness(host: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Physical currentness is not CURRENT unless completion knowledge bytes still match."""
    currentness = str(result.get("currentness") or "UNKNOWN")
    observed = result.get("observed") or {}
    if not observed.get("ok"):
        return result
    if currentness in {"UNKNOWN", "FULL_REFRESH_REQUIRED"} and not result.get("snapshot"):
        return result
    snapshot = result.get("snapshot") or {}
    locator_issues: list[str] = []
    for locator in snapshot.get("completion_locators") or []:
        loaded = resolve_refresh_completion(host, str(locator))
        if not loaded.get("ok"):
            locator_issues.extend(
                loaded.get("blockers")
                or ["refresh completion locator is not valid current authority"]
            )
    coverage = completions_covering(
        host,
        observed=observed,
        locators=list(snapshot.get("completion_locators") or []),
    )
    covered = coverage.get("covered") or {}
    mismatched = list(coverage.get("mismatched") or [])
    knowledge_stale: list[str] = []
    reusable = list(result.get("reusable_module_ids") or [])
    for item in observed.get("modules") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        module_id = str(item.get("id"))
        entry = str(item.get("knowledge_entry") or "").replace("\\", "/")
        if not entry:
            continue
        if module_id not in covered:
            knowledge_stale.append(module_id)
    result["knowledge_mismatched"] = mismatched
    result["knowledge_stale_module_ids"] = knowledge_stale
    if locator_issues:
        result["currentness"] = "UNKNOWN"
        result["reasons"] = locator_issues + mismatched
        result["affected_module_ids"] = knowledge_stale or list(result.get("affected_module_ids") or [])
        result["reusable_module_ids"] = [
            item for item in reusable if item not in set(knowledge_stale)
        ]
        return result
    if not knowledge_stale:
        return result
    stale_set = set(knowledge_stale)
    module_ids = [
        str(item.get("id"))
        for item in observed.get("modules") or []
        if isinstance(item, dict) and item.get("id")
    ]
    result["reusable_module_ids"] = [item for item in reusable if item not in stale_set]
    result["affected_module_ids"] = list(
        dict.fromkeys(list(result.get("affected_module_ids") or []) + knowledge_stale)
    )
    reasons = [
        "bound module knowledge bytes do not match refresh-completion knowledge_digest: "
        + ", ".join(knowledge_stale)
    ] + mismatched
    if currentness == "FULL_REFRESH_REQUIRED":
        result["reasons"] = list(result.get("reasons") or []) + reasons
        return result
    if currentness == "UNKNOWN":
        result["reasons"] = list(result.get("reasons") or []) + reasons
        return result
    if stale_set.issuperset(set(module_ids)):
        result["currentness"] = "FULL_REFRESH_REQUIRED"
        result["reasons"] = reasons
        return result
    result["currentness"] = "PARTIAL_REFRESH_REQUIRED"
    result["reasons"] = reasons
    return result


def validate_refresh_completion(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["refresh completion is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != RECORD_TYPE:
        issues.append("record_type must be understand_refresh_completion")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        issues.append("refresh completion schema_version must be 1")
    if data.get("canonical") is True:
        issues.append("refresh completion must not claim canonical record authority")
    if data.get("supporting") is not True:
        issues.append("refresh completion must be marked supporting")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not COMPLETION_ID_RE.fullmatch(record_id):
        issues.append("refresh completion record_id is missing or malformed")
    producer = data.get("producer")
    if not isinstance(producer, dict) or producer.get("skill_id") != PRODUCER_SKILL:
        issues.append("refresh completion producer.skill_id must be understand")
    if not isinstance(data.get("structural_digest"), str) or not HEX64_RE.fullmatch(
        str(data.get("structural_digest") or "")
    ):
        issues.append("refresh completion structural_digest must be a SHA-256 hex digest")
    modules = data.get("modules")
    if not isinstance(modules, list) or not modules:
        issues.append("refresh completion modules must be a non-empty list")
        return issues
    seen: set[str] = set()
    for index, row in enumerate(modules):
        if not isinstance(row, dict):
            issues.append(f"refresh completion modules[{index}] must be a mapping")
            continue
        module_id = str(row.get("id") or "")
        if not module_id or module_id in seen:
            issues.append(f"refresh completion modules[{index}].id is missing or duplicated")
        seen.add(module_id)
        if not HEX64_RE.fullmatch(str(row.get("source_digest") or "")):
            issues.append(
                f"refresh completion modules[{index}].source_digest must be a SHA-256 hex digest"
            )
        knowledge_digest = str(row.get("knowledge_digest") or "")
        if knowledge_digest and not HEX64_RE.fullmatch(knowledge_digest):
            issues.append(
                f"refresh completion modules[{index}].knowledge_digest must be a SHA-256 hex digest"
            )
    output_digest = data.get("output_digest")
    if not isinstance(output_digest, str) or not HEX64_RE.fullmatch(output_digest):
        issues.append("refresh completion output_digest must be a SHA-256 hex digest")
    output_locator = data.get("output_locator")
    if (
        not isinstance(output_locator, str)
        or (
            isinstance(record_id, str)
            and COMPLETION_ID_RE.fullmatch(record_id)
            and output_locator != result_locator(record_id)
        )
        or not str(output_locator or "").startswith("understand-currentness/completions/")
    ):
        issues.append("refresh completion output_locator is missing or illegal")
    return issues


def _load_project(host: Path) -> dict[str, Any]:
    path = host / PROJECT_YAML
    if not path.is_file():
        return {"ok": False, "blockers": ["project.yaml is missing"]}
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"ok": False, "blockers": ["project.yaml is malformed or unreadable"]}
    if not isinstance(data, dict):
        return {"ok": False, "blockers": ["project.yaml is not a mapping"]}
    return {"ok": True, "data": data, "blockers": []}


def _plan_module_knowledge(
    host: Path,
    row: dict[str, Any],
    *,
    ownership: dict[str, Any],
    project: dict[str, Any],
    payload: str | None = None,
) -> dict[str, Any]:
    module_id = str(row.get("id") or "")
    rel = str(row.get("knowledge_entry") or "").replace("\\", "/")
    result: dict[str, Any] = {
        "module_id": module_id,
        "knowledge_entry": rel,
        "register_generated": False,
        "write": False,
        "bind_existing": False,
        "bounded_region": False,
        "region_id": "",
        "blockers": [],
        "needs_human": False,
        "payload": payload,
    }
    if not rel:
        return result
    if ".." in rel.split("/"):
        result["blockers"] = [f"knowledge_entry is illegal: {rel}"]
        result["needs_human"] = True
        return result
    path = host / rel
    exists = path.exists()
    managed = _managed_region_plan(host, rel, path, project) if exists and path.is_file() else {}
    bounded = bool(managed.get("ok"))
    plan = plan_owned_text_mutation(
        ownership,
        rel,
        exists=exists,
        is_file=path.is_file() if exists else True,
        bounded_region=bounded,
    )
    if (
        exists
        and path.is_file()
        and payload is None
        and plan.get("status") == "RESOLVED"
        and plan.get("mode") == "GENERATED"
    ):
        result["bind_existing"] = True
        result["mode"] = plan.get("mode")
        result["status"] = plan.get("status")
        return result
    if plan.get("blockers") or (plan.get("preserve") and plan.get("needs_human")):
        result["blockers"] = list(plan.get("blockers") or [plan.get("reason") or f"{rel} cannot be refreshed"])
        result["needs_human"] = True
        result["mode"] = plan.get("mode")
        result["status"] = plan.get("status")
        return result
    if plan.get("register_generated"):
        result["register_generated"] = True
        result["write"] = True
        return result
    if plan.get("write") and bounded:
        result["write"] = True
        result["bounded_region"] = True
        result["region_id"] = str(managed.get("region_id") or "")
        result["prepared_text"] = managed.get("text")
        return result
    if plan.get("write"):
        result["write"] = True
        return result
    result["blockers"] = list(plan.get("blockers") or [f"{rel} cannot be refreshed"])
    result["needs_human"] = True
    return result


def _managed_region_plan(
    host: Path,
    rel: str,
    path: Path,
    project: dict[str, Any],
) -> dict[str, Any]:
    registered = registered_region_ids(project, rel)
    if len(registered) != 1:
        return {"ok": False}
    try:
        text = read_text(path)
    except (OSError, UnicodeError):
        return {"ok": False}
    spans, issues = parse_managed_regions(text)
    if issues:
        return {"ok": False}
    agreement = registry_marker_issues(spans, registered, surface=rel)
    if agreement:
        return {"ok": False}
    region_id = registered[0]
    return {"ok": True, "region_id": region_id, "text": text}


def _apply_module_knowledge(
    host: Path,
    row: dict[str, Any],
    plan: dict[str, Any],
    *,
    ownership: dict[str, Any],
    payload: str | None = None,
) -> dict[str, Any]:
    rel = str(plan.get("knowledge_entry") or "")
    if not rel:
        return {"ok": True, "knowledge_digest": ""}
    path = host / rel
    source_digest = str(row.get("digest") or "")
    supplied = payload if isinstance(payload, str) else plan.get("payload")
    inner = (
        supplied
        if isinstance(supplied, str)
        else _generated_knowledge_text(str(row.get("path") or ""), source_digest)
    )
    if plan.get("bind_existing"):
        if not path.is_file():
            return {
                "ok": False,
                "needs_human": True,
                "blockers": [f"{rel} cannot be bound because it is missing"],
            }
        return {"ok": True, "knowledge_digest": file_digest(path)}
    if plan.get("bounded_region"):
        current = str(plan.get("prepared_text") or "")
        replaced = replace_managed_region(current, str(plan.get("region_id") or ""), inner)
        if replaced is None:
            return {
                "ok": False,
                "needs_human": True,
                "blockers": [
                    f"{rel} MANAGED region cannot be updated without guessing"
                ],
            }
        allowed = plan_owned_text_mutation(
            ownership,
            rel,
            exists=path.exists(),
            is_file=path.is_file() if path.exists() else True,
            bounded_region=True,
        )
        if not allowed.get("write"):
            return {
                "ok": False,
                "needs_human": True,
                "blockers": list(
                    allowed.get("blockers") or [f"{rel} is MANAGED without a lawful region"]
                ),
            }
        write_text_atomic(path, replaced)
        return {"ok": True, "knowledge_digest": file_digest(path)}
    if plan.get("write"):
        write_text_atomic(path, inner)
        return {"ok": True, "knowledge_digest": file_digest(path)}
    return {
        "ok": False,
        "needs_human": True,
        "blockers": [f"{rel} cannot be refreshed under current ownership"],
    }


def _generated_knowledge_text(module_path: str, source_digest: str) -> str:
    text = MODULE_ENTRY.format(module=module_path)
    text += f"\n<!-- scaffold:understand-refresh-binding:{source_digest} -->\n"
    return text


def _allocate_id(root: Path) -> str:
    used = set()
    folder = root / COMPLETIONS_ROOT
    if folder.is_dir():
        used = {path.name for path in folder.iterdir() if path.is_dir()}
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(32):
        candidate = f"rc-{utc}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
        utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raise RuntimeError("unable to allocate unique refresh completion identity")

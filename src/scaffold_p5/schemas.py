from __future__ import annotations

from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import sha256_text
from scaffold_p5.models import (
    ACTION_CLASSES,
    CORE_SKILLS,
    FACT_CLASSES,
    OWNERSHIP_MODES,
    SESSION_STATES,
)
from scaffold_p5.agents import AGENTS_ROUTER_REGION
from scaffold_p5.ownership import ownership_registry_issues, resolve_ownership
from scaffold_p5.rules import rule_ref_issues


PROJECT_SCHEMA_VERSION = "1"
ADOPTION_SESSION_SCHEMA_VERSION = "1"
ADOPTION_PLAN_SCHEMA_VERSION = "1"
PERSISTED_LIFECYCLES = {"ADOPTING", "ACTIVE", "RECOVERY_REQUIRED"}
MAINTENANCE_STATES = {"NEEDS_REFRESH", "NEEDS_MIGRATION"}
CORE_MACHINE_ARTIFACTS = (
    ".scaffold/project.yaml",
    ".scaffold/modules.yaml",
    ".scaffold/commands.yaml",
    ".scaffold/tests.yaml",
    ".scaffold/skills.lock",
)
CORE_MACHINE_OWNERSHIP_MODES = frozenset({"GENERATED", "MANAGED"})
ADOPTION_PLAN_BODY_FIELDS = (
    "schema_version",
    "release_id",
    "pinned_understand",
    "intended_lock",
    "target_contract_generation",
    "mutation_envelope",
    "actions",
    "facts",
    "baseline",
    "activation_blockers",
)


def validate_project_data(data: Any) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "MALFORMED", ["project.yaml is not a mapping"]

    issues: list[str] = []
    schema = data.get("schema_version")
    if schema is None:
        issues.append("project.yaml schema_version is missing")
    elif str(schema) != PROJECT_SCHEMA_VERSION:
        return "UNSUPPORTED", ["project.yaml schema_version is unsupported"]

    generation = data.get("project_contract_generation")
    if not _textual_scalar(generation):
        issues.append("project.yaml project_contract_generation is missing or malformed")

    lifecycle = data.get("lifecycle")
    if lifecycle is None:
        issues.append("project.yaml lifecycle is missing")
    elif (
        not isinstance(lifecycle, str)
        or lifecycle not in PERSISTED_LIFECYCLES
    ):
        return "UNSUPPORTED", ["project.yaml lifecycle is unsupported"]

    maintenance = data.get("maintenance")
    if not _string_list(maintenance):
        issues.append("project.yaml maintenance must be a list of states")
    elif any(
        not isinstance(value, str)
        or value not in MAINTENANCE_STATES
        for value in maintenance
    ):
        return "UNSUPPORTED", ["project.yaml maintenance contains an unsupported state"]

    baseline = data.get("baseline")
    if not _valid_baseline(baseline):
        issues.append("project.yaml baseline is missing or structurally invalid")

    ownership = data.get("ownership")
    if not isinstance(ownership, dict) or not ownership:
        issues.append("project.yaml ownership must be a non-empty mapping")
    elif any(
        not isinstance(path, str)
        or not path
        or mode not in OWNERSHIP_MODES
        for path, mode in ownership.items()
    ):
        return "UNSUPPORTED", ["project.yaml ownership contains an unsupported entry"]
    else:
        issues.extend(ownership_registry_issues(ownership))
        issues.extend(_core_machine_ownership_issues(ownership))

        issues.extend(_managed_region_index_issues(data.get("managed_regions"), ownership))

    issues.extend(rule_ref_issues(data.get("rule_refs"), "project.yaml rule_refs"))

    if not isinstance(data.get("knowledge"), dict):
        issues.append("project.yaml knowledge must be a mapping")
    if not isinstance(data.get("capabilities"), dict):
        issues.append("project.yaml capabilities must be a mapping")
    facts = data.get("facts")
    if not isinstance(facts, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("name"), str)
        or not row.get("name")
        or row.get("confidence") not in FACT_CLASSES
        or not isinstance(row.get("critical"), bool)
        for row in facts
    ):
        issues.append("project.yaml facts must be a list of mappings")
    clients = data.get("clients")
    if not isinstance(clients, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("path"), str)
        or not row.get("path")
        or (
            row.get("ownership") is not None
            and row.get("ownership") not in OWNERSHIP_MODES
        )
        for row in clients
    ):
        issues.append("project.yaml clients must be a list of mappings")

    source_areas = data.get("source_areas")
    if source_areas is not None and not _string_list(source_areas):
        issues.append("project.yaml source_areas must be a list of paths")

    requirements = data.get("record_schema_requirements")
    if requirements is not None and (
        not isinstance(requirements, dict)
        or any(
            not isinstance(kind, str)
            or not kind
            or not _textual_scalar(version)
            for kind, version in requirements.items()
        )
    ):
        issues.append("project.yaml record_schema_requirements is malformed")

    refresh_conflicts = data.get("refresh_conflicts")
    if refresh_conflicts is not None and not _string_list(refresh_conflicts):
        issues.append("project.yaml refresh_conflicts must be a list")

    if issues:
        return "INCOMPLETE", issues
    return "VALID", []


def validate_adoption_session_data(data: Any) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "MALFORMED", ["Adoption Session is not a mapping"]

    required = {
        "record_type",
        "schema_version",
        "record_id",
        "status",
        "baseline",
        "plan",
        "release_id",
        "intended_lock",
        "mutation_envelope",
        "checkpoints",
        "applied_mutation_summary",
        "expected_mutations",
        "expected_mutations_plan_id",
    }
    issues: list[str] = []
    if not required.issubset(data):
        issues.append("Adoption Session is missing required structure")
    if data.get("record_type") != "adoption_session":
        return "UNSUPPORTED", ["Adoption Session record_type is unsupported"]
    schema = data.get("schema_version")
    if schema is None:
        issues.append("Adoption Session schema_version is missing")
    elif str(schema) != ADOPTION_SESSION_SCHEMA_VERSION:
        return "UNSUPPORTED", ["Adoption Session schema_version is unsupported"]
    if data.get("status") not in SESSION_STATES:
        return "UNSUPPORTED", ["Adoption Session status is unsupported"]
    if not _textual_scalar(data.get("record_id")):
        issues.append("Adoption Session record_id is missing")
    if not isinstance(data.get("baseline"), dict):
        issues.append("Adoption Session baseline must be a mapping")

    binding = data.get("plan")
    if not isinstance(binding, dict):
        issues.append("Adoption Session Plan binding must be a mapping")
    elif (
        not _textual_scalar(binding.get("identity"))
        or not _textual_scalar(binding.get("digest"))
        or not isinstance(binding.get("observed_approved"), bool)
    ):
        issues.append("Adoption Session Plan binding is incomplete")

    if not _textual_scalar(data.get("release_id")):
        issues.append("Adoption Session release_id is missing")
    if not _valid_intended_lock(data.get("intended_lock")):
        issues.append("Adoption Session intended_lock is malformed")
    if not _string_list(data.get("mutation_envelope")):
        issues.append("Adoption Session mutation_envelope must be a list of paths")
    if not _string_list(data.get("checkpoints")):
        issues.append("Adoption Session checkpoints must be a list")
    if not _mutation_summary(data.get("applied_mutation_summary")):
        issues.append("Adoption Session applied_mutation_summary is malformed")

    expected = data.get("expected_mutations")
    if not isinstance(expected, dict) or any(
        not isinstance(path, str)
        or not path
        or not isinstance(row, dict)
        or row.get("target") != path
        or not _textual_scalar(row.get("digest"))
        for path, row in expected.items()
    ):
        issues.append("Adoption Session expected_mutations is malformed")
    expected_plan = data.get("expected_mutations_plan_id")
    if expected_plan is not None and not _textual_scalar(expected_plan):
        issues.append("Adoption Session expected_mutations_plan_id is malformed")

    if issues:
        return "INCOMPLETE", issues
    return "VALID", []


def whole_file_mutation_allowed(
    ownership: Any,
    path: str,
    *,
    bounded_region: bool = False,
) -> tuple[bool, str]:
    """Internal whole-file mutation eligibility. Not a Foundation outcome."""
    normalized = str(path).replace("\\", "/")
    resolved = resolve_ownership(ownership, normalized)
    if resolved.status != "RESOLVED":
        return False, resolved.reason
    mode = resolved.mode
    if mode == "GENERATED":
        return True, "GENERATED whole-file mutation is allowed"
    if mode == "HUMAN_OWNED":
        return False, (
            f"HUMAN_OWNED {normalized} cannot be whole-file overwritten"
        )
    if mode == "MANAGED":
        if bounded_region:
            return True, "MANAGED bounded-region mutation is allowed"
        return False, (
            f"{normalized} is MANAGED but no bounded managed region is defined"
        )
    return False, f"unknown/invalid ownership {mode!r} for {normalized}"


def plan_owned_text_mutation(
    ownership: Any,
    path: str,
    *,
    exists: bool,
    is_file: bool = True,
    bounded_region: bool = False,
) -> dict[str, Any]:
    """Canonical text-mutation plan. Does not write and does not invent ownership."""
    normalized = str(path).replace("\\", "/")
    resolved = resolve_ownership(ownership, normalized)
    allowed, reason = whole_file_mutation_allowed(
        ownership, normalized, bounded_region=bounded_region
    )
    result: dict[str, Any] = {
        "status": resolved.status,
        "mode": resolved.mode,
        "matched_key": resolved.matched_key,
        "reason": resolved.reason or reason,
        "write": False,
        "register_generated": False,
        "preserve": False,
        "blockers": [],
        "needs_human": False,
    }
    if exists and not is_file:
        result["blockers"] = [f"{normalized} exists but is not a regular file"]
        result["needs_human"] = True
        return result
    if resolved.status == "CONFLICTING":
        result["blockers"] = [resolved.reason]
        result["needs_human"] = True
        return result
    if exists:
        if allowed:
            result["write"] = True
            return result
        if resolved.mode == "HUMAN_OWNED":
            result["preserve"] = True
            result["needs_human"] = True
            result["reason"] = reason
            return result
        if resolved.mode == "MANAGED":
            result["preserve"] = True
            result["needs_human"] = True
            result["blockers"] = [reason]
            result["reason"] = reason
            return result
        result["preserve"] = True
        result["needs_human"] = True
        result["blockers"] = [f"{normalized} exists without truthful ownership"]
        result["reason"] = result["blockers"][0]
        return result
    if resolved.status == "UNKNOWN":
        result["register_generated"] = True
        result["write"] = True
        result["mode"] = "GENERATED"
        result["reason"] = "absent UNKNOWN knowledge may be registered GENERATED"
        return result
    if allowed:
        result["write"] = True
        return result
    result["needs_human"] = True
    result["blockers"] = [
        f"{normalized} is absent but ownership is {resolved.mode}"
    ]
    result["reason"] = result["blockers"][0]
    return result


def _managed_region_index_issues(value: Any, ownership: Any) -> list[str]:
    issues: list[str] = []
    index = value
    if index is None:
        index = {}
    elif not isinstance(index, dict):
        return ["project.yaml managed_regions must be a mapping"]
    for path, regions in index.items():
        if not isinstance(path, str) or not path:
            issues.append("project.yaml managed_regions path is invalid")
            continue
        if not isinstance(regions, list) or not regions or any(
            not isinstance(item, str) or not item.strip() for item in regions
        ):
            issues.append(
                f"project.yaml managed_regions for {path} must be a list of region ids"
            )
            continue
        if len(set(regions)) != len(regions):
            issues.append(
                f"project.yaml managed_regions for {path} has duplicate region ids"
            )
        if isinstance(ownership, dict) and ownership.get(path) != "MANAGED":
            issues.append(
                f"project.yaml managed_regions lists {path} but ownership is not MANAGED"
            )
    if isinstance(ownership, dict) and ownership.get("AGENTS.md") == "MANAGED":
        agents_regions = index.get("AGENTS.md") if isinstance(index, dict) else None
        if not (
            isinstance(agents_regions, list)
            and AGENTS_ROUTER_REGION in agents_regions
        ):
            issues.append(
                "MANAGED AGENTS.md must register approved managed region agents-router"
            )
    return issues


def _core_machine_ownership_issues(ownership: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for path in CORE_MACHINE_ARTIFACTS:
        if path not in ownership:
            issues.append(f"project.yaml ownership must declare {path}")
            continue
        mode = ownership[path]
        if mode == "HUMAN_OWNED":
            issues.append(
                f"project.yaml ownership cannot mark {path} HUMAN_OWNED"
            )
        elif mode not in CORE_MACHINE_OWNERSHIP_MODES:
            issues.append(
                f"project.yaml ownership for {path} must be GENERATED or MANAGED"
            )
    return issues


def adoption_plan_body(data: dict[str, Any]) -> dict[str, Any]:
    return {field: data[field] for field in ADOPTION_PLAN_BODY_FIELDS}


def adoption_plan_digest(data: dict[str, Any]) -> str:
    return sha256_text(yaml_lite.dump(adoption_plan_body(data)))


def validate_adoption_plan_data(data: Any) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "MALFORMED", ["Adoption Plan is not a mapping"]

    required = set(ADOPTION_PLAN_BODY_FIELDS) | {"plan_id", "digest"}
    issues: list[str] = []
    if not required.issubset(data):
        return "INCOMPLETE", ["Adoption Plan is missing required structure"]

    schema = data.get("schema_version")
    if schema is None:
        issues.append("Adoption Plan schema_version is missing")
    elif str(schema) != ADOPTION_PLAN_SCHEMA_VERSION:
        issues.append("Adoption Plan schema_version is unsupported")

    if not _textual_scalar(data.get("release_id")):
        issues.append("Adoption Plan release_id is missing")
    pinned = data.get("pinned_understand")
    if not isinstance(pinned, dict) or not {
        "skill_id",
        "skill_version",
        "package_digest",
        "package_format_version",
    }.issubset(pinned):
        issues.append("Adoption Plan pinned_understand is incomplete")
    if not _valid_intended_lock(data.get("intended_lock")):
        issues.append("Adoption Plan intended_lock is malformed")
    if not _textual_scalar(data.get("target_contract_generation")):
        issues.append("Adoption Plan target_contract_generation is malformed")
    if not _string_list(data.get("mutation_envelope")):
        issues.append("Adoption Plan mutation_envelope must be a list of paths")

    actions = data.get("actions")
    if not isinstance(actions, list) or any(
        not isinstance(action, dict)
        or not {"action_class", "target", "ownership", "rationale", "expected"}.issubset(action)
        or action.get("action_class") not in ACTION_CLASSES
        or action.get("ownership") not in OWNERSHIP_MODES
        or not _textual_scalar(action.get("target"))
        for action in actions
    ):
        issues.append("Adoption Plan actions are malformed")
    facts = data.get("facts")
    if not isinstance(facts, list) or any(
        not isinstance(fact, dict)
        or not {"name", "value", "confidence", "critical"}.issubset(fact)
        or fact.get("confidence") not in FACT_CLASSES
        or not isinstance(fact.get("critical"), bool)
        for fact in facts
    ):
        issues.append("Adoption Plan facts are malformed")
    if not isinstance(data.get("baseline"), dict):
        issues.append("Adoption Plan baseline must be a mapping")
    if not _string_list(data.get("activation_blockers")):
        issues.append("Adoption Plan activation_blockers must be a list")

    actual = adoption_plan_digest(data)
    if data.get("digest") != actual:
        issues.append("Adoption Plan content digest does not match declared digest")
    if data.get("plan_id") != f"plan-{actual[:16]}":
        issues.append("Adoption Plan identity/content binding is invalid")

    if issues:
        status = (
            "UNSUPPORTED"
            if str(data.get("schema_version") or "") not in {"", ADOPTION_PLAN_SCHEMA_VERSION}
            else "INCOMPLETE"
        )
        return status, issues
    return "VALID", []


def _valid_baseline(value: Any) -> bool:
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("kind"), str)
        or value.get("kind") not in ("git", "none")
    ):
        return False
    filesystem = value.get("filesystem")
    return bool(
        isinstance(filesystem, dict)
        and isinstance(filesystem.get("project_state"), str)
        and filesystem.get("project_state") in ("empty", "existing")
        and _textual_scalar(filesystem.get("fingerprint"))
        and isinstance(filesystem.get("file_count"), int)
        and filesystem.get("file_count") >= 0
    )


def _valid_intended_lock(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(CORE_SKILLS):
        return False
    return all(
        isinstance(entry, dict)
        and {
            "skill_version",
            "package_digest",
            "package_format_version",
        }.issubset(entry)
        and all(_textual_scalar(entry.get(field)) for field in (
            "skill_version",
            "package_digest",
            "package_format_version",
        ))
        for entry in value.values()
    )


def _mutation_summary(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    return all(
        isinstance(row, dict)
        and _textual_scalar(row.get("target"))
        and _textual_scalar(row.get("digest"))
        for row in value
    )


def _mapping_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(row, dict) for row in value)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _textual_scalar(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (str, int))
        and bool(str(value).strip())
    )

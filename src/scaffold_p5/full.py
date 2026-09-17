from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.adoption import default_ownership, lock_data, write_lock, write_text
from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    CONSUMER_INSTALL_REGION,
    GENERATED_AGENTS,
    integrated_agents_text,
    managed_regions_from_actions,
    parse_managed_regions,
)
from scaffold_p5.discovery import discover, project_display_name
from scaffold_p5.host_state import (
    AGENTS_MD,
    ARCHITECTURE_MD,
    COMMANDS_YAML,
    DEVELOPMENT_MD,
    MODULES_YAML,
    MODULE_DOCS,
    OVERVIEW_MD,
    PROJECT_YAML,
    SKILLS_LOCK,
    TESTING_MD,
    TESTS_YAML,
    scm_baseline,
)
from scaffold_p5.client_support import client_support_row
from scaffold_p5.io_util import sha256_text, write_yaml_atomic
from scaffold_p5.models import AdoptionPlan, DiscoveryFact
from scaffold_p5.ownership import source_area_ownership


GENERATED_OVERVIEW = """# Overview

This is the canonical high-level project map generated during Understand Full.

Human-owned documents outside this file remain in place and are indexed, not moved.
"""

DERIVED_COPY = """# Derived Understand copy

authoritative: false
source_skill_id: understand
source_skill_version: {version}
generation: p5-derived-1

This file is a one-way regenerable derived copy. It is not Skill authority.
"""

ARCHITECTURE_POINTER = """# Architecture

Canonical architecture authority: `{source}`

This generated entry is a pointer. The referenced HUMAN_OWNED document remains
authoritative and is not copied or made Scaffold-owned.
"""

DEVELOPMENT_ENTRY = """# Development

Observed workflow surfaces: {surfaces}

These are discovered declarations only. Understand did not execute them during
read-only Discovery.
"""

DEVELOPMENT_UNKNOWN_ENTRY = """# Development

Current development workflow declarations are UNKNOWN.

Understand did not infer or execute a command.
"""

TESTING_ENTRY = """# Testing

Observed test paths: {paths}

This entry records observed test availability. It is not an authoritative
REQUIRED test policy. Understand did not execute tests.
"""

TESTING_UNKNOWN_ENTRY = """# Testing

Current test-system applicability is UNKNOWN.

Understand did not convert missing evidence into NOT_APPLICABLE. P6 Test
execution is not implemented.
"""

MODULE_ENTRY = """# Module: {module}

- Verified path: `{module}`
- Purpose: UNKNOWN

Understand does not invent architecture or responsibility from a directory name.
"""

MODULE_MISSING_ENTRY = """# Module: {module}

- Indexed path: `{module}`
- Current observation: CONFLICTING (path is missing)
- Purpose: UNKNOWN

Resolve through Understand Refresh or human project-knowledge correction.
"""


def _planned_agents_text(
    root: Path,
    plan: AdoptionPlan,
    existing_agents_human: bool,
) -> str | None:
    if AGENTS_MD not in plan.mutation_envelope:
        return None
    action = next((row for row in plan.actions if row.target == AGENTS_MD), None)
    if action and action.action_class == "MANAGED_UPDATE":
        if action.managed_region != AGENTS_ROUTER_REGION:
            return None
        current = ""
        if (root / AGENTS_MD).is_file():
            current = (root / AGENTS_MD).read_text(encoding="utf-8")
        return integrated_agents_text(
            current,
            insert_if_absent=True,
            region_id=action.managed_region or AGENTS_ROUTER_REGION,
        )
    if existing_agents_human:
        return None
    return GENERATED_AGENTS


def expected_normalization_mutations(
    root: Path,
    plan: AdoptionPlan,
    *,
    extra_facts: list[DiscoveryFact],
    existing_agents_human: bool,
    derived_copy: bool,
) -> dict[str, dict[str, str]]:
    ownership = default_ownership(
        existing_agents_human,
        derived_copy,
        [action.target for action in plan.actions if action.action_class == "PRESERVE"],
    )
    action_classes = {
        action.target: action.action_class for action in plan.actions
    }
    for action in plan.actions:
        if action.action_class in {"CREATE", "MANAGED_UPDATE", "PRESERVE"}:
            ownership[action.target] = action.ownership
    facts = _fact_maps(plan.facts + extra_facts)
    rendered: dict[str, str] = {
        PROJECT_YAML: yaml_lite.dump(
            _project_data(
                root,
                plan,
                lifecycle="ADOPTING",
                ownership=ownership,
                facts=facts,
                maintenance=[],
            )
        ),
        MODULES_YAML: yaml_lite.dump(_modules_data(facts)),
        COMMANDS_YAML: yaml_lite.dump(_commands_data(facts)),
        TESTS_YAML: yaml_lite.dump(_tests_data(facts)),
        SKILLS_LOCK: yaml_lite.dump(
            lock_data(plan.intended_lock, plan.release_id, authoritative=False)
        ),
    }
    planned_agents = _planned_agents_text(root, plan, existing_agents_human)
    if planned_agents is not None:
        rendered[AGENTS_MD] = planned_agents
    if OVERVIEW_MD in plan.mutation_envelope:
        rendered[OVERVIEW_MD] = GENERATED_OVERVIEW
    architecture = _fact(facts, "architecture")
    if (
        ARCHITECTURE_MD in plan.mutation_envelope
        and architecture
        and architecture["confidence"] == "VERIFIED"
        and architecture["value"]
    ):
        rendered[ARCHITECTURE_MD] = ARCHITECTURE_POINTER.format(
            source=architecture["value"]
        )
    build = _fact(facts, "declared_build_surface")
    if DEVELOPMENT_MD in plan.mutation_envelope and build and build["value"]:
        surfaces = ", ".join(f"`{value}`" for value in build["value"])
        rendered[DEVELOPMENT_MD] = DEVELOPMENT_ENTRY.format(surfaces=surfaces)
    tests = _fact(facts, "test_tree")
    if TESTING_MD in plan.mutation_envelope:
        paths = list(tests["value"] or []) if tests and tests.get("value") else []
        if not paths:
            commands = _fact(facts, "declared_commands")
            paths = [
                str(row.get("invocation"))
                for row in (commands.get("value") or [])
                if isinstance(row, dict) and row.get("kind") == "test" and row.get("invocation")
            ]
        rendered[TESTING_MD] = TESTING_ENTRY.format(
            paths=", ".join(f"`{value}`" for value in paths) or "`declared test surface`"
        )
    for module in _module_names(facts):
        target = f"{MODULE_DOCS}/{module}.md"
        if target in plan.mutation_envelope:
            rendered[target] = MODULE_ENTRY.format(module=module)
    derived_target = ".scaffold/derived/understand.md"
    if derived_copy and derived_target in plan.mutation_envelope:
        rendered[derived_target] = DERIVED_COPY.format(
            version=plan.pinned_understand.skill_version
        )
    return {
        target: {
            "target": target,
            "action_class": action_classes.get(target, "CREATE"),
            "digest": sha256_text(text),
        }
        for target, text in sorted(rendered.items())
        if target in plan.mutation_envelope
    }


def normalize(
    root: Path,
    plan: AdoptionPlan,
    *,
    lifecycle: str,
    extra_facts: list[DiscoveryFact],
    interrupt_after: str | None = None,
    existing_agents_human: bool,
    derived_copy: bool,
    preserve_bytes: dict[str, bytes],
) -> list[str]:
    created: list[str] = []
    ownership = default_ownership(
        existing_agents_human,
        derived_copy,
        [a.target for a in plan.actions if a.action_class == "PRESERVE"],
    )
    for action in plan.actions:
        if action.action_class in {"CREATE", "MANAGED_UPDATE", "PRESERVE"}:
            ownership[action.target] = action.ownership
    facts = _fact_maps(plan.facts + extra_facts)
    if interrupt_after == "project_yaml":
        if PROJECT_YAML in plan.mutation_envelope:
            _write_project(root, plan, lifecycle="ADOPTING", ownership=ownership, facts=facts, maintenance=[])
            created.append(PROJECT_YAML)
        return created

    if PROJECT_YAML in plan.mutation_envelope:
        _write_project(root, plan, lifecycle=lifecycle, ownership=ownership, facts=facts, maintenance=[])
        created.append(PROJECT_YAML)
    if MODULES_YAML in plan.mutation_envelope:
        _write_modules(root, facts)
        created.append(MODULES_YAML)
    if COMMANDS_YAML in plan.mutation_envelope:
        _write_commands(root, facts)
        created.append(COMMANDS_YAML)
    if TESTS_YAML in plan.mutation_envelope:
        _write_tests(root, facts)
        created.append(TESTS_YAML)

    planned_agents = _planned_agents_text(root, plan, existing_agents_human)
    if planned_agents is not None and AGENTS_MD in plan.mutation_envelope:
        write_text(root, AGENTS_MD, planned_agents)
        created.append(AGENTS_MD)
    if OVERVIEW_MD in plan.mutation_envelope and not (root / OVERVIEW_MD).exists():
        write_text(root, OVERVIEW_MD, GENERATED_OVERVIEW)
        created.append(OVERVIEW_MD)
    architecture = _fact(facts, "architecture")
    if (
        ARCHITECTURE_MD in plan.mutation_envelope
        and architecture
        and architecture["confidence"] == "VERIFIED"
        and architecture["value"]
    ):
        write_text(
            root,
            ARCHITECTURE_MD,
            ARCHITECTURE_POINTER.format(source=architecture["value"]),
        )
        created.append(ARCHITECTURE_MD)
    build = _fact(facts, "declared_build_surface")
    if DEVELOPMENT_MD in plan.mutation_envelope and build and build["value"]:
        surfaces = ", ".join(f"`{value}`" for value in build["value"])
        write_text(root, DEVELOPMENT_MD, DEVELOPMENT_ENTRY.format(surfaces=surfaces))
        created.append(DEVELOPMENT_MD)
    tests = _fact(facts, "test_tree")
    if TESTING_MD in plan.mutation_envelope:
        paths = list(tests["value"] or []) if tests and tests.get("value") else []
        if not paths:
            commands = _fact(facts, "declared_commands")
            paths = [
                str(row.get("invocation"))
                for row in (commands.get("value") or [])
                if isinstance(row, dict) and row.get("kind") == "test" and row.get("invocation")
            ]
        write_text(
            root,
            TESTING_MD,
            TESTING_ENTRY.format(
                paths=", ".join(f"`{value}`" for value in paths) or "`declared test surface`"
            ),
        )
        created.append(TESTING_MD)
    for module in _module_names(facts):
        target = f"{MODULE_DOCS}/{module}.md"
        if target in plan.mutation_envelope:
            write_text(root, target, MODULE_ENTRY.format(module=module))
            created.append(target)
    if derived_copy and ".scaffold/derived/understand.md" in plan.mutation_envelope:
        write_text(
            root,
            ".scaffold/derived/understand.md",
            DERIVED_COPY.format(version=plan.pinned_understand.skill_version),
        )
        created.append(".scaffold/derived/understand.md")

    if interrupt_after == "before_lock":
        return created
    if interrupt_after == "partial_lock":
        from scaffold_p5.adoption import write_partial_lock

        if SKILLS_LOCK in plan.mutation_envelope:
            write_partial_lock(root, plan.intended_lock, plan.release_id)
            created.append(SKILLS_LOCK)
        return created

    if SKILLS_LOCK in plan.mutation_envelope:
        write_lock(root, plan.intended_lock, plan.release_id, authoritative=False)
        created.append(SKILLS_LOCK)
    _assert_preserved(root, preserve_bytes)
    return created


def activate_project(root: Path, plan: AdoptionPlan, extra_facts: list[DiscoveryFact], derived_copy: bool, existing_agents_human: bool) -> None:
    write_yaml_atomic(
        root / PROJECT_YAML,
        active_project_data(
            root,
            plan,
            extra_facts,
            derived_copy,
            existing_agents_human,
        ),
    )


def active_project_data(
    root: Path,
    plan: AdoptionPlan,
    extra_facts: list[DiscoveryFact],
    derived_copy: bool,
    existing_agents_human: bool,
) -> dict[str, Any]:
    ownership = default_ownership(
        existing_agents_human,
        derived_copy,
        [a.target for a in plan.actions if a.action_class == "PRESERVE"],
    )
    for action in plan.actions:
        if action.action_class in {"CREATE", "MANAGED_UPDATE", "PRESERVE"}:
            ownership[action.target] = action.ownership
    return _project_data(
        root,
        plan,
        lifecycle="ACTIVE",
        ownership=ownership,
        facts=_fact_maps(discover(root, extra_facts)),
        maintenance=[],
    )


def active_project_digest(
    root: Path,
    plan: AdoptionPlan,
    extra_facts: list[DiscoveryFact],
    derived_copy: bool,
    existing_agents_human: bool,
) -> str:
    return sha256_text(
        yaml_lite.dump(
            active_project_data(
                root,
                plan,
                extra_facts,
                derived_copy,
                existing_agents_human,
            )
        )
    )


def _write_project(
    root: Path,
    plan: AdoptionPlan,
    *,
    lifecycle: str,
    ownership: dict[str, str],
    facts: list[dict[str, Any]],
    maintenance: list[str],
) -> None:
    write_yaml_atomic(
        root / PROJECT_YAML,
        _project_data(
            root,
            plan,
            lifecycle=lifecycle,
            ownership=ownership,
            facts=facts,
            maintenance=maintenance,
        ),
    )


def _project_data(
    root: Path,
    plan: AdoptionPlan,
    *,
    lifecycle: str,
    ownership: dict[str, str],
    facts: list[dict[str, Any]],
    maintenance: list[str],
) -> dict[str, Any]:
    source = next((f["value"] for f in facts if f["name"] == "source_tree"), [])
    ownership = source_area_ownership(ownership, list(source or []))
    tests = next((f for f in facts if f["name"] == "test_tree"), None)
    arch = next((f for f in facts if f["name"] == "architecture"), None)
    data = {
        "schema_version": "1",
        "project_contract_generation": plan.target_contract_generation,
        "name": project_display_name(facts),
        "lifecycle": lifecycle,
        "maintenance": maintenance,
        "baseline": scm_baseline(root),
        "knowledge": {
            "overview": "present",
            "architecture": _knowledge_state(arch),
            "development": _knowledge_state(
                next((f for f in facts if f["name"] == "declared_build_surface"), None)
            ),
            "testing": _knowledge_state(tests),
        },
        "capabilities": {
            "scm": plan.baseline.get("kind") or "none",
        },
        "ownership": ownership,
        "facts": facts,
        "source_areas": source or [],
        "clients": _client_index(plan, root),
    }
    regions = managed_regions_from_actions(plan.actions)
    if ownership.get(AGENTS_MD) == "MANAGED":
        agents_path = root / AGENTS_MD
        if agents_path.is_file():
            try:
                text = agents_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                text = ""
            spans, issues = parse_managed_regions(text)
            if not issues and CONSUMER_INSTALL_REGION in spans:
                current = list(regions.get(AGENTS_MD) or [])
                if CONSUMER_INSTALL_REGION not in current:
                    current.append(CONSUMER_INSTALL_REGION)
                regions[AGENTS_MD] = current
    if regions:
        data["managed_regions"] = regions
    return data


def _write_modules(root: Path, facts: list[dict[str, Any]]) -> None:
    write_yaml_atomic(root / MODULES_YAML, _modules_data(facts))


def _modules_data(facts: list[dict[str, Any]]) -> dict[str, Any]:
    modules_fact = next((f for f in facts if f["name"] == "modules"), None)
    areas = list(modules_fact["value"] or []) if modules_fact and modules_fact.get("value") else []
    if not areas:
        areas = next((f["value"] for f in facts if f["name"] == "source_tree"), []) or []
    modules = []
    for area in areas:
        modules.append(
            {
                "id": str(area).replace("/", "-"),
                "path": area,
                "knowledge_entry": f"{MODULE_DOCS}/{area}.md",
                "kind": "source",
                "confidence": "VERIFIED",
            }
        )
    return {"schema_version": "1", "modules": modules}


def _write_commands(root: Path, facts: list[dict[str, Any]]) -> None:
    write_yaml_atomic(root / COMMANDS_YAML, _commands_data(facts))


def _commands_data(facts: list[dict[str, Any]]) -> dict[str, Any]:
    declared = next((f for f in facts if f["name"] == "declared_commands"), None)
    commands = []
    rows = declared.get("value") if declared and isinstance(declared.get("value"), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("id"):
            commands.append(dict(row))
    if not commands:
        surface = next((f for f in facts if f["name"] == "declared_build_surface"), None)
        if surface and surface.get("value"):
            commands.append(
                {
                    "id": "declared-build-surface",
                    "surface": surface["value"],
                    "availability": "declared",
                    "execution": "not_validated",
                    "confidence": "INFERRED",
                }
            )
    return {"schema_version": "1", "commands": commands}


def _write_tests(root: Path, facts: list[dict[str, Any]]) -> None:
    write_yaml_atomic(root / TESTS_YAML, _tests_data(facts))


def _tests_data(facts: list[dict[str, Any]]) -> dict[str, Any]:
    tests = next((f for f in facts if f["name"] == "test_tree"), None)
    profiles = []
    confidence = tests["confidence"] if tests else "UNKNOWN"
    applicability: bool | None = None
    required_authority = "UNKNOWN"
    if tests and tests["value"]:
        profiles.append(
            {
                "id": "observed-tests",
                "paths": tests["value"],
                "policy": "observed",
                "required_authority": "UNKNOWN",
            }
        )
        confidence = tests["confidence"]
        applicability = True
        required_authority = "UNKNOWN"
    elif tests and tests["confidence"] == "VERIFIED":
        applicability = False
    return {
        "schema_version": "1",
        "applicable": applicability,
        "applicability": "UNKNOWN"
        if applicability is None
        else ("APPLICABLE" if applicability else "NOT_APPLICABLE"),
        "confidence": confidence,
        "required_authority": required_authority,
        "profiles": profiles,
    }


def _fact_maps(facts: list[DiscoveryFact]) -> list[dict[str, Any]]:
    return [
        {"name": f.name, "value": f.value, "confidence": f.confidence, "critical": f.critical}
        for f in facts
    ]


def _client_index(plan: AdoptionPlan, root: Path) -> list[dict[str, Any]]:
    out = []
    for action in plan.actions:
        if action.client_strategy:
            out.append(
                {
                    "path": action.target,
                    "strategy": action.client_strategy,
                    "authoritative": False,
                    "ownership": action.ownership,
                }
            )
    out.extend(_proposed_client_support(root, {row["path"] for row in out}))
    return out


def _proposed_client_support(root: Path, declared: set[str]) -> list[dict[str, Any]]:
    """Client-support areas proposed by the installation's declared adapters.

    Core consumes the resulting generic declaration; the per-client detail
    stays in the adapter profile.
    """
    from scaffold_p5.adapter_profiles import client_support_areas, declared_profiles
    from scaffold_p5.consumer_install import current_manifest

    rows = []
    for area in client_support_areas(declared_profiles(current_manifest(root))):
        if area not in declared:
            rows.append(client_support_row(area.rstrip("/"), area=True))
    return [row for row in rows if row]


def _knowledge_state(fact: dict[str, Any] | None) -> str:
    if not fact or fact.get("confidence") == "UNKNOWN":
        return "unknown"
    if fact.get("confidence") == "CONFLICTING":
        return "conflicting"
    if fact.get("value"):
        return "referenced" if fact.get("name") == "architecture" else "present"
    return "not_applicable" if fact.get("confidence") == "VERIFIED" else "unknown"


def _module_names(facts: list[dict[str, Any]]) -> list[str]:
    modules = next((row for row in facts if row.get("name") == "modules"), None)
    if modules and isinstance(modules.get("value"), list) and modules["value"]:
        return [str(item) for item in modules["value"] if item]
    source = next((row for row in facts if row.get("name") == "source_tree"), None)
    return list(source["value"] or []) if source and source.get("value") else []


def _fact(facts: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((fact for fact in facts if fact.get("name") == name), None)


def _assert_preserved(root: Path, preserve_bytes: dict[str, bytes]) -> None:
    for rel, original in preserve_bytes.items():
        current = (root / rel).read_bytes()
        if current != original:
            raise RuntimeError(f"HUMAN_OWNED preservation failed: {rel}")

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.discovery import discover, facts_as_dicts, module_paths, observed_testing_surface
from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    human_forbids_agents_integration,
    integrated_agents_text,
    parse_managed_regions,
    registered_region_ids,
    registry_marker_issues,
)
from scaffold_p5.full import (
    ARCHITECTURE_POINTER,
    DEVELOPMENT_ENTRY,
    DEVELOPMENT_UNKNOWN_ENTRY,
    GENERATED_AGENTS,
    GENERATED_OVERVIEW,
    MODULE_ENTRY,
    MODULE_MISSING_ENTRY,
    TESTING_ENTRY,
    TESTING_UNKNOWN_ENTRY,
    _commands_data,
    _tests_data,
)
from scaffold_p5.host_state import (
    AGENTS_MD,
    ARCHITECTURE_MD,
    COMMANDS_YAML,
    DEVELOPMENT_MD,
    MODULES_YAML,
    MODULE_DOCS,
    OVERVIEW_MD,
    PROJECT_YAML,
    TESTING_MD,
    TESTS_YAML,
    snapshot_host,
)
from scaffold_p5.io_util import read_text, read_yaml, write_text_atomic, write_yaml_atomic
from scaffold_p5.models import DiscoveryFact
from scaffold_p5.ownership import source_area_ownership
from scaffold_p5.schemas import plan_owned_text_mutation, whole_file_mutation_allowed


BUSINESS_HINTS = ("src/", "lib/", "app/", "pkg/")


def refreshable_ownership_contract_host(snap) -> bool:
    view = snap.project_view
    if view.status != "INCOMPLETE" or view.data is None or not view.reasons:
        return False
    if not all(
        reason.startswith("project.yaml ownership cannot mark ")
        for reason in view.reasons
    ):
        return False
    return (
        view.data.get("lifecycle") == "ACTIVE"
        and snap.lock.complete_authoritative
    )


def refresh_host(root: Path) -> dict[str, Any]:
    snap = snapshot_host(root)
    ownership_contract_refresh = refreshable_ownership_contract_host(snap)
    if not snap.project_view.valid and not ownership_contract_refresh:
        return {
            "ok": False,
            "outcome": "BLOCKED",
            "blockers": [
                "refresh requires a valid supported project.yaml schema"
            ]
            + list(snap.project_view.reasons),
            "changed": [],
            "conflicts": [],
        }
    if not ownership_contract_refresh and (
        snap.lifecycle != "ACTIVE" or not snap.lock.complete_authoritative
    ):
        return {
            "ok": False,
            "outcome": "BLOCKED",
            "blockers": ["refresh requires an ACTIVE host with authoritative skills.lock"],
            "changed": [],
            "conflicts": [],
        }
    ownership = dict((snap.project or {}).get("ownership") or {})
    allowed, _reason = whole_file_mutation_allowed(ownership, PROJECT_YAML)
    if not allowed:
        blocker = "project.yaml ownership does not permit whole-file Refresh"
        return {
            "ok": False,
            "outcome": "NEEDS_HUMAN",
            "blockers": [blocker],
            "changed": [],
            "conflicts": [blocker],
            "baseline": (snap.project or {}).get("baseline"),
            "untouched_business": _business_files(root),
        }
    previous_conflicts = list(
        (snap.project or {}).get("refresh_conflicts") or []
    )
    facts = discover(root)
    observed_source_facts = [fact.value for fact in facts if fact.name == "source_tree"]
    observed_source_areas = (
        list(observed_source_facts[0] or []) if observed_source_facts else []
    )
    ownership = source_area_ownership(ownership, observed_source_areas)
    previous_facts = {
        row.get("name"): row
        for row in (snap.project or {}).get("facts") or []
        if isinstance(row, dict) and row.get("name")
    }
    changed: list[str] = []
    conflicts: list[str] = []
    text_writes: dict[str, str] = {}
    yaml_writes: dict[str, Any] = {}

    agents_fact = _fact(facts, "agents_scaffold_bridge")
    agents_mode = ownership.get(AGENTS_MD)
    agents_path = root / AGENTS_MD
    agents_text = read_text(agents_path) if agents_path.is_file() else ""
    if agents_mode == "MANAGED":
        registered = registered_region_ids(snap.project or {}, AGENTS_MD)
        spans, parse_issues = parse_managed_regions(agents_text)
        agreement = list(parse_issues) + registry_marker_issues(spans, registered)
        if AGENTS_ROUTER_REGION not in registered:
            agreement.append("MANAGED AGENTS.md has no registered agents-router region")
        if not parse_issues and human_forbids_agents_integration(agents_text):
            agreement.append(
                "human AGENTS.md text conflicts with Scaffold integration"
            )
        if agreement:
            conflicts.extend(agreement)
        else:
            integrated = integrated_agents_text(
                agents_text,
                insert_if_absent=False,
                region_id=AGENTS_ROUTER_REGION,
            )
            if integrated is None:
                conflicts.append(
                    "AGENTS.md MANAGED region cannot be repaired without guessing"
                )
            else:
                _queue_text(
                    root,
                    ownership,
                    AGENTS_MD,
                    integrated,
                    stale=bool(
                        not agents_fact
                        or agents_fact.confidence != "VERIFIED"
                        or agents_fact.value is not True
                        or integrated != agents_text
                    ),
                    conflict="AGENTS.md MANAGED router region is missing or incoherent",
                    writes=text_writes,
                    conflicts=conflicts,
                    bounded_region=True,
                )
    else:
        _queue_text(
            root,
            ownership,
            AGENTS_MD,
            GENERATED_AGENTS,
            stale=bool(
                agents_mode == "HUMAN_OWNED"
                and (
                    not agents_fact
                    or agents_fact.confidence != "VERIFIED"
                    or agents_fact.value is not True
                )
            ),
            conflict="AGENTS.md HUMAN_OWNED router is missing or incoherent",
            writes=text_writes,
            conflicts=conflicts,
        )
    overview_path = root / OVERVIEW_MD
    overview_mode = ownership.get(OVERVIEW_MD)
    overview_human_stale = bool(
        overview_mode == "HUMAN_OWNED"
        and (
            not overview_path.is_file()
            or not read_text(overview_path).strip()
        )
    )
    _queue_text(
        root,
        ownership,
        OVERVIEW_MD,
        GENERATED_OVERVIEW,
        stale=overview_human_stale,
        conflict=f"{OVERVIEW_MD} HUMAN_OWNED authority is missing or incoherent",
        writes=text_writes,
        conflicts=conflicts,
    )

    modules_path = root / MODULES_YAML
    modules_status, modules_value, modules_issues = _inspect_machine_index(
        modules_path,
        "modules",
    )
    modules = (
        dict(modules_value)
        if modules_status == "VALID" and modules_value is not None
        else {"schema_version": "1", "modules": []}
    )
    indexed = {m.get("path"): m for m in modules.get("modules") or []}
    observed = module_paths(facts)
    for path in observed:
        if path not in indexed:
            entry = {
                "id": str(path).replace("/", "-"),
                "path": path,
                "knowledge_entry": f"{MODULE_DOCS}/{path}.md",
                "kind": "source",
                "confidence": "VERIFIED",
            }
            modules.setdefault("modules", []).append(entry)
            target = f"{MODULE_DOCS}/{path}.md"
            _queue_text(
                root,
                ownership,
                target,
                MODULE_ENTRY.format(module=path),
                stale=True,
                conflict=f"module knowledge authority requires resolution: {target}",
                writes=text_writes,
                conflicts=conflicts,
            )
        else:
            indexed[path]["confidence"] = "VERIFIED"
    for path, entry in list(indexed.items()):
        if path and not (root / str(path)).exists():
            entry["confidence"] = "CONFLICTING"
            conflicts.append(f"indexed module missing: {path}")
            target = entry.get("knowledge_entry")
            if target:
                _queue_text(
                    root,
                    ownership,
                    str(target),
                    MODULE_MISSING_ENTRY.format(module=path),
                    stale=True,
                    conflict=f"module knowledge authority requires resolution: {target}",
                    writes=text_writes,
                    conflicts=conflicts,
                )
    modules["modules"] = sorted(modules.get("modules") or [], key=lambda row: str(row.get("id")))
    if _yaml_changed(modules_path, modules):
        module_conflict = "modules index authority requires resolution"
        if modules_issues:
            module_conflict += ": " + "; ".join(modules_issues)
        _queue_yaml(
            root,
            ownership,
            MODULES_YAML,
            modules,
            module_conflict,
            yaml_writes,
            conflicts,
        )

    build = _fact(facts, "declared_build_surface")
    commands = _commands_data(facts_as_dicts(facts))
    if build and build.value:
        surfaces = ", ".join(f"`{value}`" for value in build.value)
        _queue_text(
            root,
            ownership,
            DEVELOPMENT_MD,
            DEVELOPMENT_ENTRY.format(surfaces=surfaces),
            stale=_fact_changed(previous_facts, build)
            or _was_unresolved(previous_conflicts, "development knowledge"),
            conflict="development knowledge entry is HUMAN_OWNED and stale",
            writes=text_writes,
            conflicts=conflicts,
        )
    elif (root / DEVELOPMENT_MD).exists():
        _queue_text(
            root,
            ownership,
            DEVELOPMENT_MD,
            DEVELOPMENT_UNKNOWN_ENTRY,
            stale=_fact_changed(previous_facts, build)
            or _was_unresolved(previous_conflicts, "development knowledge"),
            conflict="development knowledge entry is HUMAN_OWNED and stale",
            writes=text_writes,
            conflicts=conflicts,
        )
    if _yaml_changed(root / COMMANDS_YAML, commands):
        _queue_yaml(
            root,
            ownership,
            COMMANDS_YAML,
            commands,
            "commands index authority requires resolution",
            yaml_writes,
            conflicts,
        )

    tests_fact = _fact(facts, "test_tree")
    prior_tests_status, prior_tests, _prior_tests_issues = _inspect_machine_index(
        root / TESTS_YAML,
        "profiles",
    )
    tests_data = _tests_data(facts_as_dicts(facts))
    if observed_testing_surface(facts):
        paths = list(tests_fact.value or []) if tests_fact and tests_fact.value else []
        if not paths:
            commands_fact = _fact(facts, "declared_commands")
            paths = [
                str(row.get("invocation"))
                for row in (commands_fact.value or [])
                if isinstance(row, dict) and row.get("kind") == "test" and row.get("invocation")
            ]
        _queue_text(
            root,
            ownership,
            TESTING_MD,
            TESTING_ENTRY.format(
                paths=", ".join(f"`{value}`" for value in paths) or "`declared test surface`"
            ),
            stale=_fact_changed(previous_facts, tests_fact)
            or _was_unresolved(previous_conflicts, "testing knowledge"),
            conflict="testing knowledge entry is HUMAN_OWNED and stale",
            writes=text_writes,
            conflicts=conflicts,
        )
    elif tests_fact and tests_fact.confidence == "VERIFIED":
        pass
    elif (root / TESTING_MD).exists():
        _queue_text(
            root,
            ownership,
            TESTING_MD,
            TESTING_UNKNOWN_ENTRY,
            stale=_fact_changed(previous_facts, tests_fact)
            or _was_unresolved(previous_conflicts, "testing knowledge"),
            conflict="testing knowledge entry is HUMAN_OWNED and stale",
            writes=text_writes,
            conflicts=conflicts,
        )
    if prior_tests_status == "VALID" and isinstance(prior_tests, dict):
        if "rule_refs" in prior_tests:
            tests_data["rule_refs"] = prior_tests["rule_refs"]
        prior_profiles = {
            str(row.get("id") or ""): row
            for row in prior_tests.get("profiles") or []
            if isinstance(row, dict) and row.get("id")
        }
        for profile in tests_data["profiles"]:
            prior = prior_profiles.get(str(profile.get("id") or ""))
            if isinstance(prior, dict) and "rule_refs" in prior:
                profile["rule_refs"] = prior["rule_refs"]
        current_ids = {
            str(profile.get("id") or "")
            for profile in tests_data["profiles"]
            if isinstance(profile, dict)
        }
        for profile_id, prior in sorted(prior_profiles.items()):
            if profile_id not in current_ids and "rule_refs" in prior:
                tests_data["profiles"].append(dict(prior))
        tests_data["profiles"] = sorted(
            tests_data["profiles"], key=lambda row: str(row.get("id") or "")
        )
    if _yaml_changed(root / TESTS_YAML, tests_data):
        _queue_yaml(
            root,
            ownership,
            TESTS_YAML,
            tests_data,
            "tests index authority requires resolution",
            yaml_writes,
            conflicts,
        )

    architecture = _fact(facts, "architecture")
    if (
        architecture
        and architecture.confidence == "VERIFIED"
        and architecture.value
        and architecture.value != ARCHITECTURE_MD
    ):
        _queue_text(
            root,
            ownership,
            ARCHITECTURE_MD,
            ARCHITECTURE_POINTER.format(source=architecture.value),
            stale=_fact_changed(previous_facts, architecture)
            or _was_unresolved(previous_conflicts, "architecture"),
            conflict="architecture canonical entry is HUMAN_OWNED and stale",
            writes=text_writes,
            conflicts=conflicts,
        )
    elif architecture and architecture.confidence == "CONFLICTING":
        conflicts.append(
            "architecture knowledge authority is CONFLICTING"
        )

    for target, text in sorted(text_writes.items()):
        if _write_text_if_changed(root / target, text):
            changed.append(target)
    for target, value in sorted(yaml_writes.items()):
        path = root / target
        if _yaml_changed(path, value):
            write_yaml_atomic(path, value)
            changed.append(target)

    for target, collection in (
        (MODULES_YAML, "modules"),
        (COMMANDS_YAML, "commands"),
        (TESTS_YAML, "profiles"),
    ):
        if ownership.get(target) != "GENERATED":
            continue
        status, _, issues = _inspect_machine_index(root / target, collection)
        if status != "VALID":
            conflicts.append(
                f"GENERATED {target} did not validate after Refresh"
                + (": " + "; ".join(issues) if issues else "")
            )

    facts = discover(root)
    post_agents = _fact(facts, "agents_scaffold_bridge")
    agents_path = root / AGENTS_MD
    if ownership.get(AGENTS_MD) == "GENERATED":
        if (
            not agents_path.is_file()
            or read_text(agents_path) != GENERATED_AGENTS
            or not post_agents
            or post_agents.confidence != "VERIFIED"
            or post_agents.value is not True
        ):
            conflicts.append("GENERATED AGENTS.md router did not converge")
    elif ownership.get(AGENTS_MD) == "MANAGED":
        if (
            not post_agents
            or post_agents.confidence != "VERIFIED"
            or post_agents.value is not True
        ):
            conflicts.append("AGENTS.md MANAGED router region did not converge")
    elif ownership.get(AGENTS_MD) == "HUMAN_OWNED" and (
        not post_agents
        or post_agents.confidence != "VERIFIED"
        or post_agents.value is not True
    ):
        conflicts.append("AGENTS.md HUMAN_OWNED router is missing or incoherent")
    overview_path = root / OVERVIEW_MD
    if ownership.get(OVERVIEW_MD) == "GENERATED":
        if (
            not overview_path.is_file()
            or read_text(overview_path) != GENERATED_OVERVIEW
        ):
            conflicts.append("GENERATED overview did not converge")
    elif ownership.get(OVERVIEW_MD) == "HUMAN_OWNED" and (
        not overview_path.is_file() or not read_text(overview_path).strip()
    ):
        conflicts.append(
            f"{OVERVIEW_MD} HUMAN_OWNED authority is missing or incoherent"
        )

    project = dict(snap.project or {})
    project["facts"] = _merge_facts(project.get("facts") or [], facts)
    project["ownership"] = ownership
    project["source_areas"] = observed_source_areas
    knowledge = dict(project.get("knowledge") or {})
    knowledge["overview"] = (
        "conflicting"
        if any("overview" in value for value in conflicts)
        else "present"
    )
    knowledge["testing"] = _knowledge_state(tests_fact)
    knowledge["development"] = _knowledge_state(build)
    knowledge["architecture"] = _knowledge_state(architecture, referenced=True)
    if any("testing knowledge" in value for value in conflicts):
        knowledge["testing"] = "conflicting"
    if any("development knowledge" in value for value in conflicts):
        knowledge["development"] = "conflicting"
    if any("architecture" in value for value in conflicts):
        knowledge["architecture"] = "conflicting"
    project["knowledge"] = knowledge
    project["clients"] = _reconcile_clients(
        project.get("clients") or [],
        ownership,
        post_agents,
        facts,
    )
    maintenance = list(project.get("maintenance") or [])
    if conflicts and "NEEDS_REFRESH" not in maintenance:
        maintenance.append("NEEDS_REFRESH")
    if not conflicts:
        maintenance = [value for value in maintenance if value != "NEEDS_REFRESH"]
        project["baseline"] = snapshot_host(root).workspace_baseline
        project.pop("refresh_conflicts", None)
    else:
        project["refresh_conflicts"] = sorted(set(conflicts))
    project["maintenance"] = maintenance
    if _yaml_changed(root / PROJECT_YAML, project):
        allowed, reason = whole_file_mutation_allowed(ownership, PROJECT_YAML)
        if allowed:
            write_yaml_atomic(root / PROJECT_YAML, project)
            changed.append(PROJECT_YAML)
        else:
            conflicts.append(reason)
    conflicts = sorted(set(conflicts))
    outcome = "NEEDS_HUMAN" if conflicts else "COMPLETED"
    return {
        "ok": not conflicts,
        "outcome": outcome,
        "blockers": conflicts,
        "changed": changed,
        "conflicts": conflicts,
        "facts": facts,
        "baseline": project.get("baseline"),
        "untouched_business": _business_files(root),
    }


def _merge_facts(existing: list[dict[str, Any]], discovered: list[DiscoveryFact]) -> list[dict[str, Any]]:
    by_name = {row["name"]: row for row in existing if isinstance(row, dict) and "name" in row}
    for fact in discovered:
        by_name[fact.name] = {
            "name": fact.name,
            "value": fact.value,
            "confidence": fact.confidence,
            "critical": fact.critical,
        }
    return list(by_name.values())


def _reconcile_clients(
    clients: list[dict[str, Any]],
    ownership: dict[str, str],
    bridge: DiscoveryFact | None,
    facts: list[DiscoveryFact],
) -> list[dict[str, Any]]:
    observed_fact = _fact(facts, "existing_ai_clients")
    observed = {
        str(path)
        for path in (observed_fact.value if observed_fact and observed_fact.value else [])
    }
    result = [
        dict(client)
        for client in clients
        if (
            isinstance(client, dict)
            and client.get("path") != AGENTS_MD
            and (
                client.get("ownership") != "HUMAN_OWNED"
                or client.get("path") in observed
            )
        )
    ]
    existing_paths = {str(client.get("path") or "") for client in result}
    for path in sorted(observed - {AGENTS_MD}):
        if path not in existing_paths:
            ownership.setdefault(path, "HUMAN_OWNED")
            result.append(
                {
                    "path": path,
                    "strategy": "PRESERVE",
                    "authoritative": False,
                    "ownership": "HUMAN_OWNED",
                }
            )
    for path, mode in list(ownership.items()):
        if (
            mode == "HUMAN_OWNED"
            and path in {
                str(client.get("path") or "")
                for client in clients
                if isinstance(client, dict)
            }
            and path not in observed
            and path != AGENTS_MD
        ):
            ownership.pop(path, None)
    if ownership.get(AGENTS_MD) == "HUMAN_OWNED":
        verified = bool(
            bridge
            and bridge.confidence == "VERIFIED"
            and bridge.value is True
        )
        result.append(
            {
                "path": AGENTS_MD,
                "strategy": "THIN_BRIDGE" if verified else "DEFER",
                "authoritative": False,
                "ownership": "HUMAN_OWNED",
            }
        )
    return sorted(result, key=lambda row: str(row.get("path") or ""))


def _business_files(root: Path) -> list[str]:
    out = []
    for rel_root in ("src", "lib", "app", "pkg"):
        base = root / rel_root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                out.append(str(path.relative_to(root)).replace("\\", "/"))
    return out


def _fact(facts: list[DiscoveryFact], name: str) -> DiscoveryFact | None:
    return next((fact for fact in facts if fact.name == name), None)


def _knowledge_state(
    fact: DiscoveryFact | None,
    *,
    referenced: bool = False,
) -> str:
    if not fact or fact.confidence == "UNKNOWN":
        return "unknown"
    if fact.confidence == "CONFLICTING":
        return "conflicting"
    if fact.value:
        return "referenced" if referenced else "present"
    return "not_applicable" if fact.confidence == "VERIFIED" else "unknown"


def register_generated_ownership(root: Path, paths: list[str]) -> dict[str, Any]:
    """Register exact GENERATED ownership for absent UNKNOWN paths. Refresh authority."""
    unique = []
    seen: set[str] = set()
    for item in paths:
        rel = str(item or "").replace("\\", "/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        unique.append(rel)
    if not unique:
        return {"ok": True, "registered": [], "mutations": False, "blockers": []}
    project_path = root / PROJECT_YAML
    if not project_path.is_file():
        return {
            "ok": False,
            "needs_human": True,
            "registered": [],
            "mutations": False,
            "blockers": ["project.yaml is missing; ownership cannot be registered"],
        }
    try:
        project = read_yaml(project_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "needs_human": True,
            "registered": [],
            "mutations": False,
            "blockers": ["project.yaml is malformed or unreadable"],
        }
    if not isinstance(project, dict):
        return {
            "ok": False,
            "needs_human": True,
            "registered": [],
            "mutations": False,
            "blockers": ["project.yaml is not a mapping"],
        }
    ownership = dict(project.get("ownership") or {})
    allowed, reason = whole_file_mutation_allowed(ownership, PROJECT_YAML)
    if not allowed:
        return {
            "ok": False,
            "needs_human": True,
            "registered": [],
            "mutations": False,
            "blockers": [reason],
        }
    for rel in unique:
        ownership[rel] = "GENERATED"
    project["ownership"] = ownership
    write_yaml_atomic(project_path, project)
    return {
        "ok": True,
        "registered": unique,
        "mutations": True,
        "blockers": [],
        "ownership": ownership,
    }


def _queue_text(
    root: Path,
    ownership: dict[str, str],
    target: str,
    text: str,
    *,
    stale: bool,
    conflict: str,
    writes: dict[str, str],
    conflicts: list[str],
    bounded_region: bool = False,
) -> None:
    path = root / target
    exists = path.exists()
    plan = plan_owned_text_mutation(
        ownership,
        target,
        exists=exists,
        is_file=path.is_file() if exists else True,
        bounded_region=bounded_region,
    )
    if exists and not path.is_file():
        conflicts.append(f"{target} exists but is not a regular file")
        return
    if plan.get("write"):
        if plan.get("register_generated"):
            ownership[target] = "GENERATED"
        writes[target] = text
        return
    if plan.get("status") == "CONFLICTING":
        conflicts.extend(plan.get("blockers") or [plan.get("reason") or "ownership is CONFLICTING"])
        return
    if plan.get("preserve") and plan.get("mode") == "HUMAN_OWNED":
        if stale:
            conflicts.append(conflict)
        return
    if plan.get("mode") == "MANAGED":
        conflicts.append(
            plan.get("reason")
            or f"{target} is MANAGED but no bounded managed region is defined"
        )
        return
    if exists and plan.get("status") == "UNKNOWN":
        conflicts.append(f"{target} exists without truthful ownership")
        return
    if not exists:
        conflicts.append(
            f"{target} is absent but ownership is {plan.get('mode')}"
        )
        return
    conflicts.extend(
        plan.get("blockers") or [f"{target} exists without truthful ownership"]
    )


def _queue_yaml(
    root: Path,
    ownership: dict[str, str],
    target: str,
    value: Any,
    conflict: str,
    writes: dict[str, Any],
    conflicts: list[str],
) -> None:
    path = root / target
    mode = ownership.get(target)
    allowed, reason = whole_file_mutation_allowed(ownership, target)
    if path.exists():
        if not path.is_file():
            conflicts.append(
                f"{target} exists but is not a regular file"
            )
            return
        if allowed:
            writes[target] = value
            return
        if mode == "MANAGED":
            conflicts.append(reason)
            return
        conflicts.append(conflict)
        return
    if mode in {None, "GENERATED"}:
        ownership[target] = "GENERATED"
        writes[target] = value
        return
    conflicts.append(f"{target} is absent but ownership is {mode}")


def _fact_changed(
    previous: dict[str, dict[str, Any]],
    current: DiscoveryFact | None,
) -> bool:
    if current is None:
        return True
    before = previous.get(current.name)
    if before is None:
        return True
    return (
        before.get("value") != current.value
        or before.get("confidence") != current.confidence
    )


def _was_unresolved(conflicts: list[str], token: str) -> bool:
    return any(token in value for value in conflicts)


def _yaml_changed(path: Path, value: Any) -> bool:
    if not path.exists():
        return True
    try:
        return read_text(path) != yaml_lite.dump(value)
    except (OSError, ValueError, TypeError, UnicodeError):
        return True


def _write_text_if_changed(path: Path, text: str) -> bool:
    if path.exists() and read_text(path) == text:
        return False
    write_text_atomic(path, text)
    return True


def _inspect_machine_index(
    path: Path,
    collection: str,
) -> tuple[str, dict[str, Any] | None, list[str]]:
    if not path.exists():
        return "ABSENT", None, [f"{path.name} is absent"]
    try:
        value = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return "MALFORMED", None, [f"{path.name} is malformed or unreadable"]
    if not isinstance(value, dict):
        return "MALFORMED", None, [f"{path.name} is not a mapping"]
    if str(value.get("schema_version") or "") != "1":
        return "UNSUPPORTED", value, [f"{path.name} schema_version is unsupported"]
    rows = value.get(collection)
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) for row in rows
    ):
        return (
            "INCOMPLETE",
            value,
            [f"{path.name} {collection} must be a list of mappings"],
        )
    if collection == "modules" and any(
        not isinstance(row.get("path"), str)
        or not row.get("path")
        for row in rows
    ):
        return (
            "INCOMPLETE",
            value,
            [f"{path.name} module paths must be non-empty strings"],
        )
    return "VALID", value, []

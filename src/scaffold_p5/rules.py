"""Shared P4 Project Rule loading from existing P2 authority pointers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.io_util import file_digest, read_text, read_yaml
from scaffold_p5.ownership import normalize_project_path, path_covered


RULE_EFFECTS = frozenset({"PROHIBIT", "REQUIRE", "ADVISE"})
RULE_SKILLS = frozenset({"understand", "develop", "test", "submit"})
CANONICAL_RULE_INDEXES = (
    ".scaffold/project.yaml",
    ".scaffold/modules.yaml",
    ".scaffold/tests.yaml",
)
REQUIRED_AGENTS_ROUTES = (
    ".scaffold/project.yaml",
    "docs/project/overview.md",
    ".scaffold/skills.lock",
)
CORE_RULE_INDEXES = frozenset(CANONICAL_RULE_INDEXES)


def resolve_project_rules(
    root: Path,
    *,
    project: dict[str, Any] | None,
    skill_id: str,
    paths: list[str] | None = None,
    modules: list[str] | None = None,
    test_ids: list[str] | None = None,
    operation: str,
) -> dict[str, Any]:
    work_paths = sorted(
        {
            normalized
            for value in (paths or [])
            if (normalized := normalize_project_path(value, area=False))
        }
    )
    work_modules = sorted({str(value) for value in (modules or []) if str(value)})
    work_tests = sorted({str(value) for value in (test_ids or []) if str(value)})
    blockers: list[str] = []
    references: list[dict[str, Any]] = []

    agents = root / "AGENTS.md"
    agents_loaded = agents.is_file()
    agents_routes: list[str] = []
    if not agents_loaded:
        blockers.append("AGENTS.md router is missing; Project Rule authority is UNKNOWN")
    else:
        try:
            agents_text = read_text(agents)
        except (OSError, UnicodeError):
            blockers.append("AGENTS.md router is unreadable; Project Rule authority is UNKNOWN")
        else:
            if any(route not in agents_text for route in REQUIRED_AGENTS_ROUTES):
                blockers.append(
                    "AGENTS.md does not route to required project authority indexes"
                )
            agents_routes = _agents_index_routes(agents_text)

    if not isinstance(project, dict):
        blockers.append("project.yaml Rule authority is UNKNOWN")
    else:
        _append_refs(
            references,
            project.get("rule_refs"),
            "global",
            ".scaffold/project.yaml",
        )

    modules_data = _read_index(root / ".scaffold/modules.yaml", "modules", blockers)
    for row in modules_data:
        if not _module_relevant(row, work_paths, work_modules):
            continue
        ident = str(row.get("id") or "")
        source = f".scaffold/modules.yaml#{ident or row.get('path') or 'module'}"
        _append_refs(references, row.get("rule_refs"), "module", source, ident)

    tests_path = root / ".scaffold/tests.yaml"
    tests_data = None
    if operation == "test_execute" or work_tests:
        if tests_path.is_file():
            tests_data = _read_mapping(tests_path, blockers)
    if tests_data:
        _append_refs(
            references,
            tests_data.get("rule_refs"),
            "test",
            ".scaffold/tests.yaml",
        )
        for row in tests_data.get("profiles") or []:
            if not isinstance(row, dict):
                continue
            profile_id = str(row.get("id") or "")
            if profile_id not in work_tests:
                continue
            _append_refs(
                references,
                row.get("rule_refs"),
                "test",
                f".scaffold/tests.yaml#{profile_id}",
                profile_id,
            )

    loaded_sources: list[dict[str, str]] = []
    applicable: list[dict[str, Any]] = []
    by_id: dict[str, str] = {}
    for reference in references:
        rel = _rule_path(reference.get("path"))
        if not rel:
            blockers.append(
                f"Project Rule reference from {reference.get('source')} is malformed"
            )
            continue
        if rel in CORE_RULE_INDEXES:
            continue
        source_path = root / rel
        if not source_path.is_file():
            blockers.append(f"Project Rule source is not resolvable: {rel}")
            continue
        try:
            payload = read_yaml(source_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            blockers.append(f"Project Rule source is malformed or unreadable: {rel}")
            continue
        rows = payload.get("rules") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or str(payload.get("schema_version") or "") != "1"
            or not isinstance(rows, list)
        ):
            blockers.append(f"Project Rule source has unsupported structure: {rel}")
            continue
        loaded_sources.append({"path": rel, "digest": file_digest(source_path)})
        for row in rows:
            normalized, issues = _normalize_rule(
                row,
                source=rel,
                reference=reference,
            )
            if issues:
                blockers.extend(issues)
                continue
            assert normalized is not None
            if not _rule_applies(
                normalized,
                skill_id=skill_id,
                paths=work_paths,
                modules=work_modules,
                test_ids=work_tests,
            ):
                continue
            rule_id = str(normalized["rule_id"])
            identity = yaml_lite.dump(_identity_body(normalized))
            previous = by_id.get(rule_id)
            if previous is not None and previous != identity:
                blockers.append(
                    f"applicable Project Rules conflict for rule_id {rule_id}"
                )
                continue
            by_id[rule_id] = identity
            if not any(
                item.get("rule_id") == rule_id
                and _identity_body(item) == _identity_body(normalized)
                for item in applicable
            ):
                applicable.append(normalized)

    applicable.sort(key=lambda row: (str(row.get("rule_id")), str(row.get("source"))))
    prohibitions = [
        row
        for row in applicable
        if row.get("effect") == "PROHIBIT"
        and _operation_applies(row, operation)
    ]
    requirements = [
        row
        for row in applicable
        if row.get("effect") == "REQUIRE"
        and _operation_applies(row, operation)
    ]
    advisories = [row for row in applicable if row.get("effect") == "ADVISE"]
    for row in prohibitions:
        blockers.append(
            f"Project Rule {row['rule_id']} prohibits {operation}: {row['statement']}"
        )
    for row in requirements:
        blockers.append(
            f"Project Rule {row['rule_id']} requires unresolved {operation} "
            f"evidence: {row['statement']}"
        )

    blockers = sorted(set(blockers))
    return {
        "ok": not blockers,
        "status": "VALID" if not blockers else "CONFLICTING",
        "skill_id": skill_id,
        "operation": operation,
        "scope": {
            "paths": work_paths,
            "modules": work_modules,
            "tests": work_tests,
        },
        "agents_loaded": agents_loaded,
        "agents_rule_routes": agents_routes,
        "sources": sorted(
            {row["path"]: row for row in loaded_sources}.values(),
            key=lambda row: row["path"],
        ),
        "applicable": applicable,
        "prohibitions": prohibitions,
        "requirements": requirements,
        "advisories": advisories,
        "blockers": blockers,
        "route": "understand.refresh" if blockers else "",
        "grants": [],
    }


def rule_test_ids(
    *,
    task: dict[str, Any] | None = None,
    selected: Any = None,
) -> list[str]:
    """Collect explicit test identifiers for Project Rule applicability only.

    Unions caller-selected ids with Task `final_tests` and stage
    `required_tests` requirement_id values. Does not invent required tests,
    consult observed results, or change TEST_COMPLETE / coverage judgment.
    """
    ids: list[str] = []
    if isinstance(selected, list):
        for item in selected:
            if isinstance(item, str) and item.strip():
                ids.append(item.strip())
    if isinstance(task, dict):
        for item in task.get("final_tests") or []:
            if isinstance(item, dict) and item.get("requirement_id"):
                ids.append(str(item["requirement_id"]))
        for stage in task.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            for item in stage.get("required_tests") or []:
                if isinstance(item, dict) and item.get("requirement_id"):
                    ids.append(str(item["requirement_id"]))
    return sorted(set(ids))


def rule_ref_issues(value: Any, field: str = "rule_refs") -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"{field} must be a list of project-local Rule references"]
    issues: list[str] = []
    for index, item in enumerate(value):
        path = item.get("path") if isinstance(item, dict) else item
        if not _rule_path(path):
            issues.append(f"{field}[{index}] is not a valid project-local Rule reference")
    return issues


def _append_refs(
    target: list[dict[str, Any]],
    value: Any,
    kind: str,
    source: str,
    scope_id: str = "",
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        target.append({"path": None, "kind": kind, "source": source, "scope_id": scope_id})
        return
    for item in value:
        path = item.get("path") if isinstance(item, dict) else item
        target.append(
            {
                "path": path,
                "kind": kind,
                "source": source,
                "scope_id": scope_id,
            }
        )


def _agents_index_routes(text: str) -> list[str]:
    return [path for path in CANONICAL_RULE_INDEXES if path in text]


def _rule_path(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    normalized = normalize_project_path(raw, area=False)
    if not normalized or raw.endswith("/"):
        return ""
    return normalized


def _read_mapping(path: Path, blockers: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        blockers.append(f"required Project Rule index is missing: {path.name}")
        return None
    try:
        value = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        blockers.append(f"required Project Rule index is unreadable: {path.name}")
        return None
    if not isinstance(value, dict):
        blockers.append(f"required Project Rule index is malformed: {path.name}")
        return None
    return value


def _read_index(
    path: Path,
    collection: str,
    blockers: list[str],
) -> list[dict[str, Any]]:
    value = _read_mapping(path, blockers)
    if value is None:
        return []
    rows = value.get(collection)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        blockers.append(f"Project Rule index {path.name} has malformed {collection}")
        return []
    return list(rows)


def _module_relevant(
    row: dict[str, Any],
    paths: list[str],
    modules: list[str],
) -> bool:
    ident = str(row.get("id") or row.get("name") or "")
    declared = normalize_project_path(row.get("path") or row.get("root"), area=False)
    return bool(
        (ident and ident in modules)
        or (declared and any(path_covered(path, declared) for path in paths))
    )


def _normalize_rule(
    value: Any,
    *,
    source: str,
    reference: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"Project Rule entry in {source} is not a mapping"]
    rule_id = value.get("rule_id", value.get("id"))
    applies_to = value.get("applies_to")
    effect = str(value.get("effect") or "").upper()
    operations = value.get("operations")
    statement = value.get("statement")
    scope = value.get("scope")
    issues: list[str] = []
    if not isinstance(rule_id, str) or not rule_id.strip():
        issues.append(f"Project Rule in {source} is missing rule_id")
    if (
        not isinstance(applies_to, list)
        or not applies_to
        or any(item not in RULE_SKILLS for item in applies_to)
    ):
        issues.append(f"Project Rule {rule_id!r} in {source} has invalid applies_to")
    if effect not in RULE_EFFECTS:
        issues.append(f"Project Rule {rule_id!r} in {source} has invalid effect")
    if (
        not isinstance(operations, list)
        or not operations
        or any(not isinstance(item, str) or not item.strip() for item in operations)
    ):
        issues.append(f"Project Rule {rule_id!r} in {source} has invalid operations")
    if not isinstance(statement, str) or not statement.strip():
        issues.append(f"Project Rule {rule_id!r} in {source} has no normative statement")
    if scope is None:
        scope = _reference_scope(reference)
    if not isinstance(scope, dict):
        issues.append(f"Project Rule {rule_id!r} in {source} has invalid scope")
        scope = {}
    kind = str(scope.get("kind") or "")
    if kind not in {"global", "module", "path", "test"}:
        issues.append(f"Project Rule {rule_id!r} in {source} has invalid scope kind")
    normalized_scope = {
        "kind": kind,
        "paths": _string_list(scope.get("paths")),
        "modules": _string_list(scope.get("modules")),
        "tests": _string_list(scope.get("tests")),
    }
    if kind == "path" and not normalized_scope["paths"]:
        issues.append(f"Project Rule {rule_id!r} in {source} has no path scope")
    if kind == "module" and not normalized_scope["modules"]:
        issues.append(f"Project Rule {rule_id!r} in {source} has no module scope")
    if kind == "test" and not normalized_scope["tests"]:
        issues.append(f"Project Rule {rule_id!r} in {source} has no test scope")
    if issues:
        return None, issues
    return (
        {
            "rule_id": rule_id.strip(),
            "source": source,
            "applies_to": sorted(set(applies_to)),
            "effect": effect,
            "operations": sorted(set(item.strip() for item in operations)),
            "scope": normalized_scope,
            "statement": statement.strip(),
        },
        [],
    )


def _reference_scope(reference: dict[str, Any]) -> dict[str, Any]:
    kind = str(reference.get("kind") or "global")
    scope_id = str(reference.get("scope_id") or "")
    return {
        "kind": kind,
        "paths": [],
        "modules": [scope_id] if kind == "module" and scope_id else [],
        "tests": [scope_id] if kind == "test" and scope_id else [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if isinstance(item, str) and item})


def _rule_applies(
    rule: dict[str, Any],
    *,
    skill_id: str,
    paths: list[str],
    modules: list[str],
    test_ids: list[str],
) -> bool:
    if skill_id not in rule.get("applies_to", []):
        return False
    scope = rule.get("scope") or {}
    kind = scope.get("kind")
    if kind == "global":
        return True
    if kind == "path":
        return any(
            path_covered(path, declared)
            for path in paths
            for declared in scope.get("paths") or []
        )
    if kind == "module":
        return bool(set(modules).intersection(scope.get("modules") or []))
    if kind == "test":
        return bool(set(test_ids).intersection(scope.get("tests") or []))
    return False


def _operation_applies(rule: dict[str, Any], operation: str) -> bool:
    operations = set(rule.get("operations") or [])
    return "*" in operations or operation in operations


def _identity_body(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        key: rule.get(key)
        for key in ("rule_id", "applies_to", "effect", "operations", "scope", "statement")
    }

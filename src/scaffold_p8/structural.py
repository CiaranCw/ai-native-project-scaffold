"""S3 Structural Review. Judges the real S2 Diff. Does not edit source."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml
from scaffold_p5.ownership import (
    normalize_project_path,
    path_covered,
    resolve_ownership,
)
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p7.mutation import authorize_path_mutation
from scaffold_p8.task_authority import (
    path_in_task_candidate,
    resolve_task_scope,
)


IMPACT_MODULE_STRUCTURE = "MODULE_STRUCTURE"
IMPACT_PUBLIC_INTERFACE = "PUBLIC_INTERFACE"
IMPACT_DEPENDENCY = "DEPENDENCY"
IMPACT_COMMAND = "COMMAND"
IMPACT_TEST_CONFIGURATION = "TEST_CONFIGURATION"
IMPACT_PROJECT_CONFIGURATION = "PROJECT_CONFIGURATION"
IMPACT_SCAFFOLD_STRUCTURE = "SCAFFOLD_STRUCTURE"

IMPACT_CLASSES = (
    IMPACT_MODULE_STRUCTURE,
    IMPACT_PUBLIC_INTERFACE,
    IMPACT_DEPENDENCY,
    IMPACT_COMMAND,
    IMPACT_TEST_CONFIGURATION,
    IMPACT_PROJECT_CONFIGURATION,
    IMPACT_SCAFFOLD_STRUCTURE,
)

STATUS_DETERMINED = "DETERMINED"
STATUS_UNKNOWN = "UNKNOWN"

DEPENDENCY_BASENAMES = frozenset(
    {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "Pipfile.lock",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "poetry.lock",
    }
)
SKILLS_LOCK = ".scaffold/skills.lock"
PROJECT_YAML = ".scaffold/project.yaml"
MODULES_YAML = ".scaffold/modules.yaml"
COMMANDS_YAML = ".scaffold/commands.yaml"
TESTS_YAML = ".scaffold/tests.yaml"


def scope_covers_path(declared: str, path: str) -> bool:
    """Boundary-aware directory/area coverage. `src/` matches `src/app.py`, not `src2/`."""
    return path_covered(path, declared)


def review_structure(
    *,
    root: Path,
    task: dict[str, Any] | None,
    real_diff: dict[str, Any],
    project: dict[str, Any] | None,
    lock_review_authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    repair: list[str] = []
    real_paths = [
        str(item)
        for item in (real_diff.get("paths") or [])
        if isinstance(item, str) and item
    ]
    entries = [
        row
        for row in (real_diff.get("entries") or [])
        if isinstance(row, dict)
    ]
    ownership = (project or {}).get("ownership") or {}
    scope = resolve_task_scope(root, task) if task is not None else None

    unexpected_core = [
        path
        for path in real_paths
        if path in CORE_MACHINE_ARTIFACTS and path == SKILLS_LOCK
    ]
    authority = lock_review_authority if isinstance(lock_review_authority, dict) else {}
    if unexpected_core:
        if (
            authority.get("kind") == "initial_adoption_lock_creation"
            and authority.get("lawful") is True
        ):
            pass
        elif authority.get("blockers"):
            blockers.extend(str(item) for item in authority.get("blockers") or [] if item)
        else:
            blockers.append(
                "core skills.lock change requires Understand compatibility review: "
                + ", ".join(unexpected_core)
            )

    undeclared: list[str] = []
    if scope is not None:
        if scope.issues:
            blockers.extend(scope.issues)
        if scope.constrained:
            undeclared = [
                path
                for path in real_paths
                if _is_source_path(path)
                and not path_in_task_candidate(path, scope)
                and path not in CORE_MACHINE_ARTIFACTS
            ]
            if undeclared:
                blockers.append(
                    "real Diff contains undeclared Task Book paths: "
                    + ", ".join(undeclared)
                )

    missing_scoped = missing_scoped_source(root, task)
    unknown_ownership: list[str] = []
    conflicting_ownership: list[str] = []
    ownership_authority: list[dict[str, Any]] = []
    for path in real_paths:
        if not _is_source_path(path):
            continue
        if task is None:
            resolved = resolve_ownership(ownership, path)
            if resolved.status == "UNKNOWN":
                unknown_ownership.append(path)
            elif resolved.status != "RESOLVED":
                conflicting_ownership.append(
                    f"{path}: {resolved.reason or 'ownership is conflicting'}"
                )
            continue
        allowed, reason, role = authorize_path_mutation(
            root,
            path,
            task=task,
            project=project or {},
            require_in_progress=False,
        )
        resolved = resolve_ownership(ownership, path)
        if not allowed:
            if resolved.status == "UNKNOWN" and role != "supporting":
                unknown_ownership.append(path)
            else:
                conflicting_ownership.append(f"{path}: {reason}")
            continue
        ownership_mode = (
            "UNKNOWN"
            if resolved.status == "UNKNOWN"
            else (
                str(resolved.mode)
                if resolved.status == "RESOLVED"
                else "CONFLICTING"
            )
        )
        ownership_authority.append(
            {
                "path": path,
                "ownership": ownership_mode,
                "ownership_key": resolved.matched_key,
                "scope_role": role,
            }
        )
    if unknown_ownership:
        blockers.append(
            "changed source path has UNKNOWN ownership: " + ", ".join(unknown_ownership)
        )
    if conflicting_ownership:
        blockers.append(
            "changed source path has CONFLICTING ownership: "
            + ", ".join(conflicting_ownership)
        )

    impacts, impact_blockers = classify_structural_impacts(
        root, entries=entries, paths=real_paths
    )
    blockers.extend(impact_blockers)
    unknown_impacts = [
        row for row in impacts if row.get("status") == STATUS_UNKNOWN
    ]
    if unknown_impacts:
        blockers.append(
            "structural impact is UNKNOWN for: "
            + ", ".join(
                sorted(
                    {
                        f"{row.get('class')}:{row.get('path')}"
                        for row in unknown_impacts
                    }
                )
            )
        )

    structural_review_pass = not blockers and not repair
    return {
        "structural_review_pass": structural_review_pass,
        "blockers": blockers,
        "repair_required": repair,
        "unexpected_core": unexpected_core,
        "undeclared": undeclared,
        "missing_scoped": missing_scoped,
        "unknown_ownership": unknown_ownership,
        "conflicting_ownership": conflicting_ownership,
        "ownership_authority": ownership_authority,
        "impacts": impacts,
        "impact_classes": sorted({str(row.get("class")) for row in impacts}),
        "reviewed_paths": list(real_paths),
        "structural_unknown": bool(unknown_impacts),
        "skills_lock_review_authority": dict(authority) if authority else {},
    }


def missing_scoped_source(root: Path, task: dict[str, Any] | None) -> list[str]:
    if not task:
        return []
    scope = ((task.get("scope") or {}).get("paths") or []) if task else []
    missing = []
    for item in scope:
        path = str(item)
        if _is_source_path(path) and not scope_path_present(root, path):
            missing.append(path)
    return missing


def scope_path_present(root: Path, declared: str) -> bool:
    raw = str(declared or "").strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    rel = raw.strip("/")
    if not rel:
        return False
    target = root / rel
    return target.is_dir() or target.is_file()


def classify_structural_impacts(
    root: Path,
    *,
    entries: list[dict[str, Any]],
    paths: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    changed = _changed_identities(entries, paths)
    modules, modules_state = _load_modules(root)
    commands_state = _index_state(root / COMMANDS_YAML, "commands")
    tests_state = _index_state(root / TESTS_YAML, "profiles")
    project_state = _mapping_state(root / PROJECT_YAML)
    impacts: list[dict[str, Any]] = []
    blockers: list[str] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, path: str, status: str, *, detail: str = "") -> None:
        key = (kind, path)
        if key in seen:
            return
        seen.add(key)
        row = {"class": kind, "path": path, "status": status}
        if detail:
            row["detail"] = detail
        impacts.append(row)

    for path in changed:
        if _record_namespace(path):
            continue
        basename = path.rsplit("/", 1)[-1]
        if path == SKILLS_LOCK:
            add(
                IMPACT_SCAFFOLD_STRUCTURE,
                path,
                STATUS_DETERMINED,
                detail="skills.lock is a compatibility surface",
            )
            continue
        if path == TESTS_YAML:
            status = STATUS_UNKNOWN if tests_state[0] is None else STATUS_DETERMINED
            add(IMPACT_TEST_CONFIGURATION, path, status, detail=tests_state[1])
            continue
        if path == COMMANDS_YAML:
            status = STATUS_UNKNOWN if commands_state[0] is None else STATUS_DETERMINED
            add(IMPACT_COMMAND, path, status, detail=commands_state[1])
            continue
        if path == MODULES_YAML:
            status = STATUS_UNKNOWN if modules is None else STATUS_DETERMINED
            add(IMPACT_MODULE_STRUCTURE, path, status, detail=modules_state)
            continue
        if path == PROJECT_YAML:
            status = STATUS_UNKNOWN if project_state[0] is None else STATUS_DETERMINED
            add(IMPACT_PROJECT_CONFIGURATION, path, status, detail=project_state[1])
            continue
        if path in CORE_MACHINE_ARTIFACTS:
            add(IMPACT_SCAFFOLD_STRUCTURE, path, STATUS_DETERMINED)
            continue
        if basename in DEPENDENCY_BASENAMES or path in DEPENDENCY_BASENAMES:
            add(IMPACT_DEPENDENCY, path, STATUS_DETERMINED)
            continue
        interface = _public_interface_hit(path, modules)
        if interface is not None:
            add(
                IMPACT_PUBLIC_INTERFACE,
                path,
                interface["status"],
                detail=str(interface.get("detail") or ""),
            )
            if interface.get("module_structure"):
                add(IMPACT_MODULE_STRUCTURE, path, interface["status"])
            continue
        module_hit = _module_structure_hit(path, modules, modules_state)
        if module_hit is not None:
            add(
                IMPACT_MODULE_STRUCTURE,
                path,
                module_hit["status"],
                detail=str(module_hit.get("detail") or ""),
            )

    return impacts, blockers


def _changed_identities(
    entries: list[dict[str, Any]], paths: list[str]
) -> list[str]:
    found: set[str] = set()
    for path in paths:
        if path:
            found.add(path)
    for row in entries:
        for key in ("path", "orig_path"):
            value = str(row.get(key) or "")
            if value:
                found.add(value)
    return sorted(found)


def _load_modules(root: Path) -> tuple[list[dict[str, Any]] | None, str]:
    rows, reason = _index_state(root / MODULES_YAML, "modules")
    if rows is None:
        return None, reason
    return rows, reason


def _index_state(path: Path, field: str) -> tuple[list[dict[str, Any]] | None, str]:
    if not path.is_file():
        return None, f"{path.name} is missing"
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, f"{path.name} is unreadable"
    if not isinstance(data, dict):
        return None, f"{path.name} is malformed"
    rows = data.get(field)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None, f"{path.name}#{field} is malformed"
    return rows, "readable"


def _mapping_state(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, f"{path.name} is missing"
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, f"{path.name} is unreadable"
    if not isinstance(data, dict):
        return None, f"{path.name} is malformed"
    return data, "readable"


def _public_interface_hit(
    path: str, modules: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    if modules is None:
        return None
    for row in modules:
        declared = str(row.get("path") or row.get("root") or "")
        interfaces, unknown = _interface_paths(row)
        if unknown and declared and path_covered(path, declared) and _looks_public(path):
            return {
                "status": STATUS_UNKNOWN,
                "detail": (
                    f"module {row.get('id') or declared} public interface is UNKNOWN"
                ),
                "module_structure": False,
            }
        if path in interfaces:
            return {
                "status": STATUS_DETERMINED,
                "detail": f"module {row.get('id') or declared} public interface",
                "module_structure": False,
            }
    return None


def _module_structure_hit(
    path: str,
    modules: list[dict[str, Any]] | None,
    modules_state: str,
) -> dict[str, Any] | None:
    if modules is None:
        return None
    for row in modules:
        declared = str(row.get("path") or row.get("root") or "")
        if not declared:
            continue
        normalized = normalize_project_path(declared, area=declared.endswith("/"))
        file_form = normalized.rstrip("/")
        if path == file_form or path == (file_form + "/"):
            return {
                "status": STATUS_DETERMINED,
                "detail": f"module {row.get('id') or declared} root",
            }
    return None


def _interface_paths(row: dict[str, Any]) -> tuple[set[str], bool]:
    raw = None
    for key in ("interfaces", "public", "public_interface", "exports"):
        if key in row:
            raw = row.get(key)
            break
    if raw is None:
        return set(), False
    if isinstance(raw, list):
        out: set[str] = set()
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                return set(), True
            out.add(item.replace("\\", "/").strip())
        return out, False
    if isinstance(raw, str):
        text = raw.strip()
        if not text or text.upper() == "UNKNOWN":
            return set(), True
        return {text.replace("\\", "/")}, False
    return set(), True


def _looks_public(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return name in {"__init__.py", "api.py", "interface.py", "public.py"} or name.endswith(
        "_api.py"
    )


def _record_namespace(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith(".scaffold/runtime/")
        or normalized.startswith(".scaffold/tasks/")
        or normalized.startswith(".scaffold/changes/")
        or normalized.startswith(".scaffold/finalizations/")
        or normalized.startswith(".scaffold/derived/")
        or normalized.startswith(".scaffold/ext/")
    )


def _is_source_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith(".scaffold/"):
        return False
    if normalized.startswith("docs/"):
        return False
    if normalized in {"README.md", "AGENTS.md"}:
        return False
    return True

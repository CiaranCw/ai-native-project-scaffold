"""Ownership-bounded source mutation. No generic write-any-file escape hatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.io_util import write_text_atomic
from scaffold_p5.ownership import (
    path_covered,
    resolve_ownership,
)
from scaffold_p5.client_support import is_client_support_path
from scaffold_p5.scm import git_path_is_tracked
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS

from scaffold_p7.models import MODULES_YAML
from scaffold_p7.session import file_sha256, path_kind, record_touch


CORE_PROTECTED = frozenset(CORE_MACHINE_ARTIFACTS)
OWNERSHIP_MODES = frozenset({"GENERATED", "MANAGED", "HUMAN_OWNED"})
MAX_SUPPORTING_PATHS = 32
GOVERNANCE_NAMES = frozenset({".scaffold", ".git"})
GOVERNANCE_PREFIXES = (".scaffold/", ".git/")
GOVERNANCE_FILES = frozenset({"AGENTS.md", ".gitattributes"})
SUPPORTING_WILDCARD_CHARS = frozenset("*?[]")


class MutationPlan:
    def __init__(
        self,
        *,
        ok: bool,
        writes: list[dict[str, Any]] | None = None,
        blockers: list[str] | None = None,
        authority: list[dict[str, Any]] | None = None,
    ):
        self.ok = ok
        self.writes = writes or []
        self.blockers = blockers or []
        self.authority = authority or []


def authorize_writes(
    root: Path,
    *,
    writes: Any,
    task: dict[str, Any],
    project: dict[str, Any],
) -> MutationPlan:
    if writes in (None, [], ()):
        return MutationPlan(ok=True, writes=[])
    if not isinstance(writes, list):
        return MutationPlan(ok=False, blockers=["writes must be a list of path/content maps"])
    ownership = project.get("ownership")
    if not isinstance(ownership, dict):
        return MutationPlan(
            ok=False,
            blockers=["project ownership registry is UNKNOWN; mutation is blocked"],
        )
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    module_paths = _module_paths(root, scope)
    authorized: list[dict[str, Any]] = []
    authority: list[dict[str, Any]] = []
    for index, item in enumerate(writes):
        if not isinstance(item, dict):
            return MutationPlan(ok=False, blockers=[f"write {index} is not a mapping"])
        rel = _normalize(item.get("path"))
        if not rel:
            return MutationPlan(ok=False, blockers=[f"write {index} path is missing"])
        if rel.startswith("../") or rel.startswith("/") or ":" in rel.split("/", 1)[0]:
            return MutationPlan(
                ok=False,
                blockers=[f"{rel} is outside ordinary local fixture path form"],
            )
        allowed, reason, role = authorize_path_mutation(
            root,
            rel,
            task=task,
            project=project,
            module_paths=module_paths,
            require_in_progress=True,
        )
        if not allowed:
            return MutationPlan(ok=False, blockers=[reason])
        if "content" not in item or not isinstance(item.get("content"), str):
            return MutationPlan(
                ok=False,
                blockers=[f"write {rel} content must be a string"],
            )
        resolved = resolve_ownership(ownership, rel)
        ownership_mode = (
            "UNKNOWN"
            if resolved.status == "UNKNOWN"
            else (str(resolved.mode) if resolved.status == "RESOLVED" else "CONFLICTING")
        )
        authorized.append({"path": rel, "content": item["content"]})
        authority.append(
            {
                "path": rel,
                "ownership": ownership_mode,
                "ownership_key": resolved.matched_key,
                "task_scoped": role in {"product", "supporting"},
                "scope_role": role,
            }
        )
    return MutationPlan(ok=True, writes=authorized, authority=authority)


def hard_mutation_boundary_reason(
    root: Path,
    rel: str,
    *,
    deleting: bool = False,
) -> str | None:
    """Cheap hard-boundary denial. Not Task scope, ownership, or tool identity."""
    normalized = _normalize(rel)
    if not normalized:
        return "mutation target path is missing; fail closed"
    if (
        normalized.startswith("../")
        or normalized.startswith("/")
        or ":" in normalized.split("/", 1)[0]
    ):
        return f"{normalized} is outside ordinary local fixture path form"
    if is_client_support_path(root, normalized):
        return (
            f"mutation authority for {normalized} is CONFLICTING: "
            "declared CLIENT_SUPPORT path is not project product"
        )
    if is_protected_governance_path(normalized, root) or normalized in CORE_PROTECTED:
        return (
            f"mutation authority for {normalized} is CONFLICTING: "
            "protected Scaffold governance path"
        )
    if deleting:
        return irrecoverable_deletion_reason(root, normalized)
    return None


def irrecoverable_deletion_reason(root: Path, rel: str) -> str | None:
    """Deny untracked / no-SCM deletion when the client exposes the target."""
    normalized = _normalize(rel)
    dest = Path(root) / normalized
    if not dest.exists() and not dest.is_symlink():
        return None
    tracked = git_path_is_tracked(root, normalized)
    if tracked is True:
        return None
    if tracked is False:
        return (
            f"untracked deletion of {normalized} is potentially irrecoverable"
        )
    return (
        f"deletion of {normalized} on a no-SCM host is potentially irrecoverable"
    )


def authorize_path_mutation(
    root: Path,
    rel: str,
    *,
    task: dict[str, Any],
    project: dict[str, Any] | None,
    module_paths: list[str] | None = None,
    require_in_progress: bool = True,
    bounded_region: bool = False,
) -> tuple[bool, str, str]:
    """Classify Task affiliation and keep genuine governance protection.

    Task scope is semantic intent, not a pre-write allowlist. HUMAN_OWNED
    ordinary project content may be modified when the Task requires it.
    MANAGED/GENERATED direct edits are allowed and remain review-visible.
    ``bounded_region`` is retained for callers; it is not a write deny gate.
    """
    del bounded_region
    normalized = _normalize(rel)
    boundary = hard_mutation_boundary_reason(root, normalized)
    if boundary:
        return False, boundary, ""
    if require_in_progress and task.get("status") != "IN_PROGRESS":
        return (
            False,
            f"Task status {task.get('status')} does not authorize mutation",
            "",
        )
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    modules = (
        list(module_paths)
        if module_paths is not None
        else _module_paths(Path(root), scope)
    )
    in_product, product_reason = path_in_scope(normalized, scope, modules)
    in_supporting, supporting_reason = path_in_supporting_scope(normalized, scope)
    if in_product:
        role = "product"
        affiliation_reason = product_reason
    elif in_supporting:
        role = "supporting"
        affiliation_reason = supporting_reason
    else:
        role = "discovered"
        affiliation_reason = f"{normalized} is a discovered Task dependency"
    host_project = project if isinstance(project, dict) else {}
    ownership = host_project.get("ownership")
    if not isinstance(ownership, dict):
        return False, "project ownership registry is UNKNOWN; mutation is blocked", role
    resolved = resolve_ownership(ownership, normalized)
    if resolved.status == "UNKNOWN":
        if role in {"supporting", "discovered"}:
            return True, affiliation_reason, role
        return False, f"mutation authority for {normalized} is UNKNOWN", role
    if resolved.status != "RESOLVED" or resolved.mode not in OWNERSHIP_MODES:
        return (
            False,
            resolved.reason or f"mutation authority for {normalized} is CONFLICTING",
            role,
        )
    return True, affiliation_reason, role


def apply_writes(
    root: Path,
    writes: list[dict[str, Any]],
    *,
    directory: Path,
    files: list[dict[str, Any]],
    overlay_paths: set[str],
    stage_ids: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    applied: list[str] = []
    current = list(files)
    for item in writes:
        rel = item["path"]
        dest = root / rel
        before_kind = path_kind(dest)
        before_digest = file_sha256(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(dest, item["content"])
        after_kind = path_kind(dest)
        after_digest = file_sha256(dest)
        if before_kind == "missing":
            change_kind = "created"
        elif after_kind != before_kind:
            change_kind = "type_changed"
        else:
            change_kind = "modified"
        current = record_touch(
            directory,
            current,
            rel=rel,
            before_kind=before_kind,
            after_kind=after_kind,
            before_digest=before_digest,
            after_digest=after_digest,
            change_kind=change_kind,
            was_preexisting_dirty=rel in overlay_paths,
            stage_ids=stage_ids,
        )
        applied.append(rel)
    return applied, current


def path_in_scope(
    rel: str,
    scope: dict[str, Any],
    module_paths: list[str],
) -> tuple[bool, str]:
    if any(
        field in scope and not isinstance(scope.get(field), list)
        for field in ("paths", "modules", "exclude", "supporting_paths")
    ):
        return False, "Task Book scope containers are not schema-validated lists"
    declared_paths = [
        _normalize(item) for item in (scope.get("paths") or []) if _normalize(item)
    ]
    excludes = [
        _normalize(item) for item in (scope.get("exclude") or []) if _normalize(item)
    ]
    for excluded in excludes:
        if _covers(rel, excluded):
            return False, f"{rel} is excluded from Task Book scope"
    if not declared_paths and not module_paths:
        return False, "Task Book scope paths/modules are UNKNOWN; mutation is blocked"
    if any(_covers(rel, declared) for declared in declared_paths):
        return True, "path is inside declared Task Book scope"
    if any(_covers(rel, declared) for declared in module_paths):
        return True, "path is inside a declared Task Book module"
    return False, f"{rel} is outside authoritative Task Book scope"


def path_in_supporting_scope(
    rel: str,
    scope: dict[str, Any],
) -> tuple[bool, str]:
    if "supporting_paths" in scope and not isinstance(scope.get("supporting_paths"), list):
        return False, "Task Book supporting_paths is not a schema-validated list"
    declared = [
        _normalize(item)
        for item in (scope.get("supporting_paths") or [])
        if _normalize(item)
    ]
    excludes = [
        _normalize(item) for item in (scope.get("exclude") or []) if _normalize(item)
    ]
    for excluded in excludes:
        if _covers(rel, excluded):
            return False, f"{rel} is excluded from Task Book supporting scope"
    if any(_covers(rel, declared_path) for declared_path in declared):
        return True, "path is inside declared Task supporting scope"
    return False, f"{rel} is outside declared Task supporting scope"


def is_protected_governance_path(rel: str, root: Path | None = None) -> bool:
    """Scaffold authority paths, plus project-declared CLIENT_SUPPORT when root is known."""
    normalized = _normalize(rel)
    if not normalized:
        return True
    if normalized in CORE_PROTECTED or normalized in GOVERNANCE_FILES:
        return True
    if normalized in GOVERNANCE_NAMES:
        return True
    if any(normalized.startswith(prefix) for prefix in GOVERNANCE_PREFIXES):
        return True
    return root is not None and is_client_support_path(root, normalized)


def supporting_path_declaration_issues(
    supporting: list[str],
    product_paths: list[str] | None = None,
    root: Path | None = None,
) -> list[str]:
    issues: list[str] = []
    if len(supporting) > MAX_SUPPORTING_PATHS:
        issues.append(
            "Task proposal scope.supporting_paths exceeds "
            f"{MAX_SUPPORTING_PATHS} prefixes"
        )
    seen: set[str] = set()
    products = [_normalize(item) for item in (product_paths or []) if _normalize(item)]
    for raw in supporting:
        path = _normalize(raw)
        if not path:
            issues.append("Task supporting path is empty or invalid")
            continue
        if any(char in path for char in SUPPORTING_WILDCARD_CHARS):
            issues.append(f"Task supporting path must not use wildcards: {path}")
            continue
        if is_protected_governance_path(path, root):
            issues.append(
                f"Task supporting path cannot declare protected governance: {path}"
            )
            continue
        if path in seen:
            continue
        seen.add(path)
        for product in products:
            if _covers(path, product) or _covers(product, path):
                issues.append(
                    f"Task supporting path overlaps product scope: {path}"
                )
                break
    return issues


def supporting_path_grounding_issues(
    root: Path,
    supporting: list[str],
    *,
    tests_rows: list[dict[str, Any]] | None = None,
    commands_rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Reject arbitrary nonexistent prefixes. Ground in project facts."""
    issues: list[str] = []
    facts = discovered_supporting_fact_prefixes(
        root, tests_rows=tests_rows, commands_rows=commands_rows
    )
    for raw in supporting:
        path = _normalize(raw)
        if not path:
            continue
        if is_protected_governance_path(path, root):
            continue
        if not supporting_path_grounded(root, path, fact_prefixes=facts):
            issues.append(
                "Task supporting path is not grounded in current project "
                f"knowledge: {path}"
            )
    return issues


def supporting_path_grounded(
    root: Path,
    path: str,
    *,
    fact_prefixes: list[str] | None = None,
) -> bool:
    normalized = _normalize(path)
    if not normalized:
        return False
    physical = Path(root) / normalized
    if physical.exists():
        return True
    parent = physical.parent
    if parent != Path(root) and parent.exists():
        return True
    for prefix in fact_prefixes or []:
        declared = _normalize(prefix)
        if not declared:
            continue
        if normalized == declared or _covers(normalized, declared):
            return True
    return False


def discovered_supporting_fact_prefixes(
    root: Path,
    *,
    tests_rows: list[dict[str, Any]] | None = None,
    commands_rows: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Discovered test/tool/evidence locators. Not every top-level directory."""
    prefixes: list[str] = []
    del root
    for row in list(tests_rows or []) + list(commands_rows or []):
        if not isinstance(row, dict):
            continue
        for key in ("path", "root", "working_directory", "cwd", "locator"):
            declared = _normalize(row.get(key))
            if not declared or declared in {".", ".."}:
                continue
            if is_protected_governance_path(declared):
                continue
            prefixes.append(declared)
    unique: list[str] = []
    seen: set[str] = set()
    for item in prefixes:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def task_scope_prefixes(root: Path, task: dict[str, Any]) -> list[str]:
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    prefixes = [
        _normalize(item)
        for item in list(scope.get("paths") or []) + list(scope.get("supporting_paths") or [])
        if _normalize(item)
    ]
    prefixes.extend(_module_paths(Path(root), scope))
    unique: list[str] = []
    seen: set[str] = set()
    for item in prefixes:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def overlay_path_set(session: dict[str, Any]) -> set[str]:
    overlay = session.get("workspace_overlay_s0") or {}
    paths = overlay.get("paths") if isinstance(overlay, dict) else []
    out: set[str] = set()
    if not isinstance(paths, list):
        return out
    for item in paths:
        if isinstance(item, dict) and item.get("path"):
            out.add(_normalize(item.get("path")))
    return out


def task_module_paths(root: Path, scope: dict[str, Any]) -> list[str]:
    return _module_paths(root, scope)


def _module_paths(root: Path, scope: dict[str, Any]) -> list[str]:
    names = [str(item) for item in (scope.get("modules") or []) if item]
    if not names:
        return []
    modules_path = root / MODULES_YAML
    if not modules_path.is_file():
        return []
    try:
        from scaffold_p5.io_util import read_yaml

        raw = read_yaml(modules_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return []
    rows = (raw or {}).get("modules") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or row.get("name") or "")
        if ident not in names:
            continue
        declared = _normalize(row.get("path") or row.get("root"))
        if declared:
            out.append(declared)
    return out


def _covers(rel: str, declared: str) -> bool:
    return path_covered(rel, declared)


def _normalize(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.strip("/")

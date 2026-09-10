"""Ownership-bounded source mutation. No generic write-any-file escape hatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.io_util import write_text_atomic
from scaffold_p5.ownership import (
    ordinary_business_source,
    path_covered,
    resolve_ownership,
)
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS, whole_file_mutation_allowed

from scaffold_p7.models import MODULES_YAML
from scaffold_p7.session import file_sha256, path_kind, record_touch


CORE_PROTECTED = frozenset(CORE_MACHINE_ARTIFACTS)
OWNERSHIP_MODES = frozenset({"GENERATED", "MANAGED", "HUMAN_OWNED"})


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
        in_scope, scope_reason = path_in_scope(rel, scope, module_paths)
        if not in_scope:
            return MutationPlan(ok=False, blockers=[scope_reason])
        if rel in CORE_PROTECTED:
            return MutationPlan(
                ok=False,
                blockers=[
                    f"mutation authority for {rel} is CONFLICTING: "
                    "core Scaffold machine artifact"
                ],
            )
        resolved = resolve_ownership(ownership, rel)
        if resolved.status == "UNKNOWN":
            return MutationPlan(
                ok=False,
                blockers=[f"mutation authority for {rel} is UNKNOWN"],
            )
        if resolved.status != "RESOLVED" or resolved.mode not in OWNERSHIP_MODES:
            return MutationPlan(
                ok=False, blockers=[resolved.reason or f"mutation authority for {rel} is CONFLICTING"]
            )
        mode = str(resolved.mode)
        if mode == "HUMAN_OWNED":
            allowed = bool(
                task.get("status") == "IN_PROGRESS"
                and ordinary_business_source(
                    rel, list(project.get("source_areas") or [])
                )
            )
            reason = (
                "current Task-scoped instruction authorizes HUMAN_OWNED business source"
                if allowed
                else (
                    f"HUMAN_OWNED {rel} requires explicit current business-source "
                    "Task authority"
                )
            )
        else:
            allowed, reason = whole_file_mutation_allowed(ownership, rel)
        if not allowed:
            return MutationPlan(ok=False, blockers=[reason])
        if "content" not in item or not isinstance(item.get("content"), str):
            return MutationPlan(
                ok=False,
                blockers=[f"write {rel} content must be a string"],
            )
        authorized.append({"path": rel, "content": item["content"]})
        authority.append(
            {
                "path": rel,
                "ownership": mode,
                "ownership_key": resolved.matched_key,
                "task_scoped": True,
            }
        )
    return MutationPlan(ok=True, writes=authorized, authority=authority)


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
        for field in ("paths", "modules", "exclude")
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

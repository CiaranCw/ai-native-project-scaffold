"""Submit Task vs no-Task authority. Does not invent a Task Book."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml
from scaffold_p5.ownership import path_covered
from scaffold_p7.schemas import TASK_ID_RE
from scaffold_p7.tasks import resolve_task, valid_tasks


MODULES_YAML = ".scaffold/modules.yaml"

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"


@dataclass
class SubmitTaskAuthority:
    ok: bool
    task: dict[str, Any] | None = None
    no_task: bool = False
    blockers: list[str] = field(default_factory=list)
    route: str = "stop"


@dataclass
class TaskScopeResolution:
    allowed: list[str]
    excludes: list[str]
    issues: list[str]
    constrained: bool
    declared_paths: list[str]
    declared_modules: list[str]
    resolved_module_paths: list[str]
    supporting_paths: list[str] = field(default_factory=list)


def resolve_submit_task_authority(
    root: Path,
    *,
    task_id: Any,
    caller_prose: Any,
    real_paths: list[str],
) -> SubmitTaskAuthority:
    if _has_caller_prose(caller_prose) and not _valid_task_id(task_id):
        return SubmitTaskAuthority(
            ok=False,
            blockers=["caller-supplied prose cannot replace Task Book authority"],
            route="stop",
        )
    if task_id not in (None, ""):
        resolved = resolve_task(root, task_id=task_id, caller_prose=caller_prose)
        if not resolved.ok or resolved.task is None:
            return SubmitTaskAuthority(
                ok=False,
                blockers=list(resolved.blockers),
                route=resolved.route or "stop",
            )
        return SubmitTaskAuthority(ok=True, task=resolved.task, no_task=False)
    return _select_applicable(root, real_paths)


def resolve_task_scope(root: Path, task: dict[str, Any] | None) -> TaskScopeResolution:
    """Paths ∪ resolved modules, with excludes. Unresolved modules fail closed."""
    if not isinstance(task, dict):
        return TaskScopeResolution([], [], [], False, [], [], [])
    scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
    declared_paths = _normalize_list(scope.get("paths"))
    excludes = _normalize_list(scope.get("exclude"))
    supporting_paths = _normalize_list(scope.get("supporting_paths"))
    declared_modules = [
        str(item).strip()
        for item in (scope.get("modules") or [])
        if isinstance(item, str) and str(item).strip()
    ]
    resolved, unresolved, authority_issues = resolve_module_paths(
        root, declared_modules
    )
    issues = list(authority_issues)
    for name in unresolved:
        issues.append(f"Task Book module is UNKNOWN: {name}")
    allowed: list[str] = []
    seen: set[str] = set()
    for item in declared_paths + resolved:
        if item not in seen:
            seen.add(item)
            allowed.append(item)
    constrained = bool(declared_paths or declared_modules or supporting_paths)
    return TaskScopeResolution(
        allowed=allowed,
        excludes=excludes,
        issues=issues,
        constrained=constrained,
        declared_paths=declared_paths,
        declared_modules=declared_modules,
        resolved_module_paths=resolved,
        supporting_paths=supporting_paths,
    )


def resolve_module_paths(
    root: Path, names: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Same modules.yaml identity as P7: id/name + path/root. Never guess a path."""
    wanted = [str(item).strip() for item in names if str(item).strip()]
    if not wanted:
        return [], [], []
    path = root / MODULES_YAML
    if not path.is_file():
        return [], list(wanted), ["required project knowledge is missing: modules.yaml"]
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return (
            [],
            list(wanted),
            ["required project knowledge is unreadable: modules.yaml"],
        )
    rows = (raw or {}).get("modules") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return [], list(wanted), ["required project knowledge is malformed: modules.yaml"]
    by_id: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("id") or row.get("name") or "").strip()
        declared = _normalize(row.get("path") or row.get("root"))
        if ident and declared:
            by_id[ident] = declared
    resolved: list[str] = []
    unresolved: list[str] = []
    seen_paths: set[str] = set()
    for name in wanted:
        declared = by_id.get(name, "")
        if not declared:
            unresolved.append(name)
            continue
        if declared not in seen_paths:
            seen_paths.add(declared)
            resolved.append(declared)
    return resolved, unresolved, []


def path_in_resolved_scope(path: str, resolution: TaskScopeResolution) -> bool:
    if any(path_covered(path, excluded) for excluded in resolution.excludes):
        return False
    return any(path_covered(path, allowed) for allowed in resolution.allowed)


def path_in_supporting_scope(path: str, resolution: TaskScopeResolution) -> bool:
    if any(path_covered(path, excluded) for excluded in resolution.excludes):
        return False
    return any(path_covered(path, declared) for declared in resolution.supporting_paths)


def path_in_task_candidate(path: str, resolution: TaskScopeResolution) -> bool:
    return path_in_resolved_scope(path, resolution) or path_in_supporting_scope(
        path, resolution
    )


def classify_task_applicability(
    root: Path, task: dict[str, Any], real_paths: list[str]
) -> tuple[str, list[str]]:
    """Tri-state applicability. UNKNOWN is not NOT_APPLICABLE."""
    if not isinstance(task, dict) or task.get("status") == "CANCELED":
        return NOT_APPLICABLE, []
    resolution = resolve_task_scope(root, task)
    relevant_paths = [
        path
        for path in real_paths
        if path and not str(path).startswith(".scaffold/")
    ]
    if any(path_in_task_candidate(path, resolution) for path in relevant_paths):
        return APPLICABLE, []
    if resolution.issues:
        return UNKNOWN, list(resolution.issues)
    return NOT_APPLICABLE, []


def task_covers_diff(
    root: Path, task: dict[str, Any], real_paths: list[str]
) -> bool:
    state, _reasons = classify_task_applicability(root, task, real_paths)
    return state == APPLICABLE


def _select_applicable(root: Path, real_paths: list[str]) -> SubmitTaskAuthority:
    tasks, issues = valid_tasks(root)
    if issues:
        return SubmitTaskAuthority(
            ok=False,
            blockers=["Task Book authority is malformed"] + list(issues),
            route="stop",
        )
    applicable: list[dict[str, Any]] = []
    unknown: list[tuple[dict[str, Any], list[str]]] = []
    for task in tasks:
        state, reasons = classify_task_applicability(root, task, real_paths)
        if state == APPLICABLE:
            applicable.append(task)
        elif state == UNKNOWN:
            unknown.append((task, reasons))
    if unknown:
        blockers = [
            "Task applicability is UNKNOWN because Task scope authority cannot "
            "be resolved: "
            + _task_label(task)
            + " / "
            + ("; ".join(reasons) if reasons else "Task scope authority is UNKNOWN")
            for task, reasons in unknown
        ]
        return SubmitTaskAuthority(
            ok=False,
            no_task=False,
            blockers=blockers,
            route="understand.refresh",
        )
    if not applicable:
        return SubmitTaskAuthority(ok=True, task=None, no_task=True)
    if len(applicable) > 1:
        ids = [
            str(task.get("record_id"))
            for task in applicable
            if isinstance(task.get("record_id"), str)
            and TASK_ID_RE.fullmatch(str(task.get("record_id")))
        ]
        return SubmitTaskAuthority(
            ok=False,
            blockers=[
                "ambiguous applicable Task Book identity; task_id is required: "
                + ", ".join(ids)
            ],
            route="stop",
        )
    return SubmitTaskAuthority(ok=True, task=applicable[0], no_task=False)


def _task_label(task: dict[str, Any]) -> str:
    record_id = task.get("record_id")
    if isinstance(record_id, str) and TASK_ID_RE.fullmatch(record_id):
        return record_id
    return "unknown-task"


def _has_caller_prose(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_task_id(value: Any) -> bool:
    return isinstance(value, str) and bool(TASK_ID_RE.fullmatch(value))


def _normalize_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _normalize(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.strip("/")

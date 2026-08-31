"""S3 Structural Review. Judges the real Diff. Does not edit source."""

from __future__ import annotations

from typing import Any

from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS


def review_structure(
    *,
    task: dict[str, Any],
    real_paths: list[str],
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    repair: list[str] = []
    scope = ((task.get("scope") or {}).get("paths") or []) if task else []
    scope_paths = [str(item) for item in scope if isinstance(item, str)]
    ownership = (project or {}).get("ownership") or {}

    unexpected_core = [
        path for path in real_paths if path in CORE_MACHINE_ARTIFACTS
    ]
    if unexpected_core:
        blockers.append(
            "unexpected core machine artifact change: " + ", ".join(unexpected_core)
        )

    undeclared = [
        path
        for path in real_paths
        if _is_source_path(path)
        and scope_paths
        and path not in scope_paths
        and path not in CORE_MACHINE_ARTIFACTS
    ]
    if undeclared:
        blockers.append(
            "real Diff contains undeclared Task Book paths: " + ", ".join(undeclared)
        )

    for path in scope_paths:
        if path not in real_paths and not _exists_in_scope_claim(path, real_paths):
            continue
    missing_scoped = [
        path
        for path in scope_paths
        if _is_source_path(path) and path not in real_paths
    ]
    # Missing scoped source is a substantive repair only when the path is required
    # and the Task claims READY_FOR_REVIEW against that scope.
    for path in scope_paths:
        if _is_source_path(path) and path not in real_paths:
            # existence is checked by caller via workspace; here flag if listed
            # as changed-or-required but absent from Diff and from ownership known files
            if ownership.get(path) in {None, ""}:
                continue

    unknown_ownership = [
        path
        for path in real_paths
        if _is_source_path(path) and path not in ownership
    ]
    if unknown_ownership:
        blockers.append(
            "changed source path has UNKNOWN ownership: " + ", ".join(unknown_ownership)
        )

    return {
        "structural_review_pass": not blockers and not repair,
        "blockers": blockers,
        "repair_required": repair,
        "unexpected_core": unexpected_core,
        "undeclared": undeclared,
        "missing_scoped": missing_scoped,
    }


def missing_scoped_source(root_exists: set[str], task: dict[str, Any]) -> list[str]:
    scope = ((task.get("scope") or {}).get("paths") or []) if task else []
    missing = []
    for item in scope:
        path = str(item)
        if _is_source_path(path) and path not in root_exists:
            missing.append(path)
    return missing


def _exists_in_scope_claim(path: str, real_paths: list[str]) -> bool:
    return path in real_paths


def _is_source_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if normalized.startswith(".scaffold/"):
        return False
    if normalized.startswith("docs/"):
        return False
    if normalized in {"README.md", "AGENTS.md"}:
        return False
    return True

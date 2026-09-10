"""Deterministic Repair Stage targeting. Never guess first/last/all Stages."""

from __future__ import annotations

from typing import Any


UNRESOLVED_TARGET_MAPPING = "unresolved"
EXECUTION_BINDING_MAPPING = "execution_binding"


def bound_test_profile_id(item: dict[str, Any]) -> str:
    """Only explicit execution_binding.kind=test_profile may map a profile."""
    binding = item.get("execution_binding")
    if not isinstance(binding, dict):
        return ""
    if binding.get("kind") != "test_profile":
        return ""
    profile_id = binding.get("profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    return ""


def map_repair_target_stage_ids(
    task: dict[str, Any],
    *,
    fail_ids: list[str] | None = None,
    missing_source: list[str] | None = None,
) -> list[str]:
    """Name Stages only when a blocker maps through execution_binding. Never guess."""
    stages = [
        stage
        for stage in (task.get("stages") or [])
        if isinstance(stage, dict) and str(stage.get("stage_id") or "").strip()
    ]
    if fail_ids:
        wanted = {str(item) for item in fail_ids if str(item)}
        mapped: list[str] = []
        for stage in stages:
            for item in stage.get("required_tests") or []:
                if not isinstance(item, dict):
                    continue
                bound_profile = bound_test_profile_id(item)
                if bound_profile and bound_profile in wanted:
                    mapped.append(str(stage["stage_id"]))
                    break
        return sorted(set(mapped))
    if missing_source:
        return []
    return []


def failed_profile_ids_from_test(test_result: Any) -> list[str]:
    """Portable P6 report locators. Not a caller PASS/FAIL dictionary."""
    extras = getattr(test_result, "extras", None)
    if not isinstance(extras, dict):
        return []
    report = extras.get("report")
    if not isinstance(report, dict):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in report.get("profiles") or []:
        if not isinstance(row, dict):
            continue
        if row.get("result") not in {"FAIL", "BLOCKED"}:
            continue
        profile_id = row.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            continue
        value = profile_id.strip()
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def attach_test_failure_targets(
    payload: dict[str, Any],
    *,
    task: dict[str, Any] | None,
    test_result: Any = None,
) -> dict[str, Any]:
    """Add deterministic target_stage_ids when execution_binding mapping exists."""
    updated = dict(payload)
    fail_ids = failed_profile_ids_from_test(test_result)
    if fail_ids:
        updated["fail_ids"] = list(fail_ids)
    if task is None:
        updated["target_mapping"] = UNRESOLVED_TARGET_MAPPING
        return updated
    targets = map_repair_target_stage_ids(task, fail_ids=fail_ids)
    if targets:
        updated["target_stage_ids"] = targets
        updated["target_mapping"] = EXECUTION_BINDING_MAPPING
    else:
        updated["target_mapping"] = UNRESOLVED_TARGET_MAPPING
    return updated

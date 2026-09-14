"""P7-owned Task Book / Develop Session validation. Not a Foundation schema file."""

from __future__ import annotations

import re
from typing import Any

from scaffold_p7.models import (
    RECORD_SCHEMA_VERSION,
    SESSION_RECORD_TYPE,
    SESSION_STATES,
    STAGE_STATUSES,
    TASK_RECORD_TYPE,
    TASK_STATUSES,
)


RECORD_ID_RE = re.compile(
    r"^(task|change|dev|adopt)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$"
)
TASK_ID_RE = re.compile(r"^task-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
SESSION_ID_RE = re.compile(r"^dev-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")

_TASK_REQUIRED = (
    "record_type",
    "schema_version",
    "record_id",
    "created_at",
    "updated_at",
    "record_revision",
    "title",
    "goal",
    "acceptance",
    "baseline",
    "scope",
    "stages",
    "final_tests",
    "status",
    "develop_session_ids",
)
_STAGE_REQUIRED = ("stage_id", "goal", "acceptance", "status")
_SESSION_REQUIRED = (
    "record_type",
    "schema_version",
    "record_id",
    "created_at",
    "updated_at",
    "status",
    "task_id",
    "mode",
    "project_name",
    "baseline",
    "workspace_overlay_s0",
    "observed_candidate_digest",
)
_BASELINE_KINDS = {"git", "perforce", "project", "none", "unavailable"}
_OVERLAY_COVERAGE = {"complete", "partial", "unavailable"}
_TEST_OUTCOMES = {"PASS", "FAIL", "NOT_EXECUTED", "UNKNOWN"}
_CHANGE_KINDS = {"created", "modified", "deleted", "type_changed"}
_PATH_KINDS = {"missing", "regular_file", "symlink", "other"}


def validate_task_book(data: Any, *, expected_id: str | None = None) -> list[str]:
    if not isinstance(data, dict):
        return ["Task Book is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != TASK_RECORD_TYPE:
        issues.append("record_type must be task_book")
    if str(data.get("schema_version") or "") != RECORD_SCHEMA_VERSION:
        issues.append("Task Book schema_version must be 1")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not TASK_ID_RE.fullmatch(record_id):
        issues.append("Task Book record_id is missing or malformed")
    elif expected_id and record_id != expected_id:
        issues.append("Task Book record_id does not match filename")
    for field in _TASK_REQUIRED:
        if field not in data:
            issues.append(f"Task Book missing required field {field}")
    if not _nonempty_text(data.get("title")):
        issues.append("Task Book title is required")
    if not _nonempty_text(data.get("goal")):
        issues.append("Task Book goal is required")
    if not _nonempty_text(data.get("acceptance")):
        issues.append("Task Book acceptance is required")
    if data.get("status") not in TASK_STATUSES:
        issues.append("Task Book status is missing or not a frozen Task status")
    if not isinstance(data.get("baseline"), dict):
        issues.append("Task Book baseline must be a mapping")
    elif data["baseline"].get("kind") not in _BASELINE_KINDS:
        issues.append("Task Book baseline.kind is UNKNOWN")
    issues.extend(_scope_issues(data.get("scope")))
    issues.extend(
        _id_list_issues(
            data.get("develop_session_ids"),
            field="develop_session_ids",
            pattern=SESSION_ID_RE,
        )
    )
    issues.extend(_test_ref_list_issues(data.get("final_tests"), "final_tests"))
    revision = data.get("record_revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        issues.append("record_revision must be a positive integer")
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        issues.append("Task Book must have one or more stages")
        return issues
    seen: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            issues.append(f"stage {index} is not a mapping")
            continue
        for field in _STAGE_REQUIRED:
            if field not in stage:
                issues.append(f"stage {index} missing {field}")
        stage_id = stage.get("stage_id")
        if not isinstance(stage_id, str) or not stage_id:
            issues.append(f"stage {index} stage_id is missing")
        elif stage_id in seen:
            issues.append(f"duplicate stage_id {stage_id}")
        else:
            seen.add(stage_id)
        if stage.get("status") not in STAGE_STATUSES:
            issues.append(f"stage {stage_id or index} status is not a frozen Stage status")
        if "required_tests" in stage:
            issues.extend(
                _test_ref_list_issues(
                    stage.get("required_tests"),
                    f"stage {stage_id or index} required_tests",
                )
            )
        if "completion_decision" in stage:
            issues.extend(
                _stage_completion_decision_issues(
                    stage.get("completion_decision"),
                    field=f"stage {stage_id or index} completion_decision",
                    stage_id=stage_id if isinstance(stage_id, str) else None,
                )
            )
    if "task_completion_decision" in data:
        issues.extend(
            _task_completion_decision_issues(
                data.get("task_completion_decision"),
                field="task_completion_decision",
            )
        )
    return issues


def validate_develop_session(
    data: Any,
    *,
    expected_id: str | None = None,
) -> list[str]:
    if not isinstance(data, dict):
        return ["Develop Session is not a mapping"]
    issues: list[str] = []
    if data.get("record_type") != SESSION_RECORD_TYPE:
        issues.append("record_type must be develop_session")
    if str(data.get("schema_version") or "") != RECORD_SCHEMA_VERSION:
        issues.append("Develop Session schema_version must be 1")
    record_id = data.get("record_id")
    if not isinstance(record_id, str) or not SESSION_ID_RE.fullmatch(record_id):
        issues.append("Develop Session record_id is missing or malformed")
    elif expected_id and record_id != expected_id:
        issues.append("Develop Session record_id does not match directory name")
    for field in _SESSION_REQUIRED:
        if field not in data:
            issues.append(f"Develop Session missing required field {field}")
    if data.get("status") not in SESSION_STATES:
        issues.append("Develop Session status is not OPEN, SEALED, or ABORTED")
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        issues.append("Develop Session task_id is missing or malformed")
    if data.get("mode") not in {"normal_task", "repair"}:
        issues.append("Develop Session mode must be normal_task or repair")
    if "project_name" in data and not isinstance(data.get("project_name"), str):
        issues.append("Develop Session project_name must be a string")
    elif "project_name" not in data:
        issues.append("Develop Session project_name is required")
    if data.get("status") == "SUBMITTED":
        issues.append("Develop Session must not use SUBMITTED")
    issues.extend(_session_baseline_issues(data.get("baseline")))
    issues.extend(_overlay_issues(data.get("workspace_overlay_s0"), "workspace_overlay_s0"))
    digest = data.get("observed_candidate_digest")
    if not _nonempty_text(digest):
        issues.append("Develop Session observed_candidate_digest is missing or unusable")
    return issues


def validate_files_yaml(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return ["files.yaml must be a mapping"]
    files = data.get("files")
    if not isinstance(files, list):
        return ["files.yaml files must be a list"]
    issues: list[str] = []
    for index, row in enumerate(files):
        if not isinstance(row, dict):
            issues.append(f"files.yaml row {index} is not a mapping")
            continue
        path = row.get("path")
        if not _nonempty_text(path):
            issues.append(f"files.yaml row {index} path is missing or empty")
        if "change_kind" in row and row.get("change_kind") not in _CHANGE_KINDS:
            issues.append(f"files.yaml row {index} change_kind is malformed")
        for kind_field in ("before_kind", "after_kind"):
            if kind_field in row and row.get(kind_field) not in _PATH_KINDS:
                issues.append(f"files.yaml row {index} {kind_field} is malformed")
        if "stage_ids" in row and not isinstance(row.get("stage_ids"), list):
            issues.append(f"files.yaml row {index} stage_ids must be a list")
        elif isinstance(row.get("stage_ids"), list):
            if any(not _nonempty_text(item) for item in row["stage_ids"]):
                issues.append(f"files.yaml row {index} stage_ids contains an invalid id")
    return issues


def _scope_issues(scope: Any) -> list[str]:
    if not isinstance(scope, dict):
        return ["Task Book scope must be a mapping"]
    issues: list[str] = []
    for field in ("paths", "modules", "exclude", "supporting_paths"):
        if field not in scope:
            continue
        issues.extend(_string_list_issues(scope.get(field), f"scope.{field}"))
    return issues


def _string_list_issues(value: Any, field: str) -> list[str]:
    if isinstance(value, dict):
        return [f"{field} must be a list of strings, not a mapping"]
    if not isinstance(value, list):
        return [f"{field} must be a list of strings"]
    issues: list[str] = []
    for index, item in enumerate(value):
        if not _nonempty_text(item):
            issues.append(f"{field}[{index}] must be a nonempty string")
    return issues


def _id_list_issues(value: Any, *, field: str, pattern) -> list[str]:
    if not isinstance(value, list):
        return [f"{field} must be a list"]
    issues: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not pattern.fullmatch(item):
            issues.append(f"{field}[{index}] is not a valid record id")
    return issues


def _test_ref_list_issues(value: Any, field: str) -> list[str]:
    if isinstance(value, dict):
        return [f"{field} must be a list of test references, not a mapping"]
    if not isinstance(value, list):
        return [f"{field} must be a list of test references"]
    issues: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            issues.append(f"{field}[{index}] must be a mapping")
            continue
        if not _nonempty_text(item.get("requirement_id")):
            issues.append(f"{field}[{index}] requirement_id is missing or empty")
        outcome = item.get("observed_outcome")
        if outcome is not None and outcome not in _TEST_OUTCOMES:
            issues.append(f"{field}[{index}] observed_outcome is not a frozen test outcome")
        evidence = item.get("evidence_ref")
        if evidence is not None and not isinstance(evidence, dict):
            issues.append(f"{field}[{index}] evidence_ref must be a mapping")
        issues.extend(_execution_binding_issues(item.get("execution_binding"), f"{field}[{index}]"))
    return issues


def _session_baseline_issues(baseline: Any) -> list[str]:
    if not isinstance(baseline, dict):
        return ["Develop Session baseline must be a mapping"]
    if baseline.get("kind") not in _BASELINE_KINDS:
        return ["Develop Session baseline.kind is UNKNOWN"]
    return []


def _overlay_issues(overlay: Any, field: str) -> list[str]:
    if not isinstance(overlay, dict):
        return [f"{field} must be a mapping"]
    issues: list[str] = []
    if overlay.get("coverage") not in _OVERLAY_COVERAGE:
        issues.append(f"{field}.coverage must be complete, partial, or unavailable")
    paths = overlay.get("paths")
    if not isinstance(paths, list):
        issues.append(f"{field}.paths must be a list")
        return issues
    for index, item in enumerate(paths):
        if not isinstance(item, dict) or not _nonempty_text(item.get("path")):
            issues.append(f"{field}.paths[{index}] must be a mapping with a path")
    return issues


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def execution_binding_issues(value: Any, field: str) -> list[str]:
    """Shared FND3 execution_binding constraints. Absent/None is valid."""
    return _execution_binding_issues(value, field)


def _execution_binding_issues(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{field} execution_binding must be a mapping"]
    issues: list[str] = []
    if value.get("kind") != "test_profile":
        issues.append(f"{field} execution_binding.kind must be test_profile")
    if not _nonempty_text(value.get("profile_id")):
        issues.append(f"{field} execution_binding.profile_id is missing or empty")
    return issues


_DECISION_OUTCOMES = {"SATISFIED", "UNSATISFIED", "UNKNOWN"}


def _stage_completion_decision_issues(
    value: Any,
    *,
    field: str,
    stage_id: str | None = None,
) -> list[str]:
    issues = _decision_body_issues(value, field=field)
    if not isinstance(value, dict):
        return issues
    target = value.get("stage_id")
    if not isinstance(target, str) or not target.strip():
        issues.append(
            f"{field} stage_id is missing; Stage Completion Decision is unscoped"
        )
    elif stage_id is not None and target != stage_id:
        issues.append(f"{field} stage_id must match the containing Stage")
    return issues


def _task_completion_decision_issues(value: Any, *, field: str) -> list[str]:
    return _decision_body_issues(value, field=field)


def _completion_decision_issues(
    value: Any,
    *,
    field: str,
    stage_id: str | None = None,
) -> list[str]:
    """Compatibility wrapper. Prefer the Stage/Task-specific validators."""
    if stage_id is not None:
        return _stage_completion_decision_issues(
            value, field=field, stage_id=stage_id
        )
    return _task_completion_decision_issues(value, field=field)


def _decision_body_issues(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{field} must be a mapping"]
    issues: list[str] = []
    if value.get("outcome") not in _DECISION_OUTCOMES:
        issues.append(
            f"{field} outcome must be SATISFIED, UNSATISFIED, or UNKNOWN"
        )
    if not _nonempty_text(value.get("candidate_digest")):
        issues.append(f"{field} candidate_digest is missing")
    if not _nonempty_text(value.get("rationale")):
        issues.append(f"{field} rationale is missing")
    basis = value.get("basis")
    if not isinstance(basis, list) or not basis:
        issues.append(f"{field} basis must be a nonempty list")
    else:
        for index, item in enumerate(basis):
            if not isinstance(item, dict):
                issues.append(f"{field} basis[{index}] must be a mapping")
                continue
            if not _nonempty_text(item.get("kind")) or not _nonempty_text(item.get("summary")):
                issues.append(f"{field} basis[{index}] must name kind and summary")
            if item.get("report") is not None or item.get("raw_report") is not None:
                issues.append(f"{field} basis[{index}] must not store a raw Test Report")
            ref = item.get("evidence_ref")
            if ref is None:
                continue
            if not isinstance(ref, dict):
                issues.append(f"{field} basis[{index}] evidence_ref must be a mapping")
                continue
            locator = ref.get("locator")
            if not isinstance(locator, str) or not locator.strip():
                issues.append(f"{field} basis[{index}] evidence locator is missing")
            elif locator.startswith("/") or "\\" in locator or ":" in locator.split("/", 1)[0]:
                issues.append(f"{field} basis[{index}] evidence locator is not portable")
    supersedes = value.get("supersedes")
    if supersedes is None:
        return issues
    if not isinstance(supersedes, dict):
        issues.append(f"{field} supersedes must be a mapping")
        return issues
    for key in ("candidate_digest", "outcome", "rationale"):
        if not _nonempty_text(supersedes.get(key)):
            issues.append(f"{field} supersedes.{key} is missing")
    return issues

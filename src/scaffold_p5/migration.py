from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.adoption import iso_now, make_id
from scaffold_p5.host_state import (
    COMMANDS_YAML,
    MIGRATION_EXECS,
    MODULES_YAML,
    PROJECT_YAML,
    SKILLS_LOCK,
    TESTS_YAML,
    inspect_project,
)
from scaffold_p5.io_util import file_digest, read_yaml, sha256_text, write_yaml_atomic
from scaffold_p5.schemas import whole_file_mutation_allowed
from scaffold_p5 import yaml_lite


CONTRACT_GENERATION_UPDATED = "CONTRACT_GENERATION_UPDATED"
VALIDATION_PASSED = "VALIDATION_PASSED"
MIGRATION_CHECKPOINTS = [CONTRACT_GENERATION_UPDATED, VALIDATION_PASSED]
CORE_SCAFFOLD_AUTHORITIES = (
    PROJECT_YAML,
    SKILLS_LOCK,
    MODULES_YAML,
    COMMANDS_YAML,
    TESTS_YAML,
)


def observe_source_scaffold_state(
    root: Path,
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    ownership = (project or {}).get("ownership") or {}
    paths = set(CORE_SCAFFOLD_AUTHORITIES)
    if isinstance(ownership, dict):
        paths.update(
            str(path)
            for path, mode in ownership.items()
            if mode in {"GENERATED", "MANAGED"}
        )
    for client in (project or {}).get("clients") or []:
        if not isinstance(client, dict):
            continue
        path = str(client.get("path") or "")
        if path and ownership.get(path) in {"GENERATED", "MANAGED"}:
            paths.add(path)
    inventory: dict[str, dict[str, str]] = {}
    for rel in sorted(paths):
        normalized = rel.replace("\\", "/")
        if (
            not normalized
            or normalized.startswith(".scaffold/runtime/")
            or normalized.endswith(".tmp")
            or "/__pycache__/" in f"/{normalized}"
            or normalized.endswith(".pyc")
        ):
            continue
        path = root / normalized
        if path.is_file():
            inventory[normalized] = {
                "type": "file",
                "digest": file_digest(path),
            }
        elif path.is_dir():
            inventory[normalized] = {
                "type": "directory",
                "digest": _durable_directory_digest(path),
            }
        else:
            inventory[normalized] = {"type": "absent"}
    state = {
        "schema_version": "1",
        "inventory": inventory,
    }
    state["fingerprint"] = sha256_text(
        yaml_lite.dump(
            {
                "schema_version": state["schema_version"],
                "inventory": state["inventory"],
            }
        )
    )
    return state


def _durable_directory_digest(path: Path) -> str:
    parts: list[str] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = str(child.relative_to(path)).replace("\\", "/")
        if (
            "/__pycache__/" in f"/{rel}"
            or rel.endswith(".pyc")
            or rel.endswith(".tmp")
            or "/.scaffold/runtime/" in f"/{rel}"
        ):
            continue
        parts.append(rel + "\n" + file_digest(child))
    return sha256_text(*parts)


def derive_migration_target(
    evaluation: dict[str, Any],
    requested_target: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    all_valid_rows = [
        row
        for _, row in sorted((evaluation.get("results") or {}).items())
        if row.get("validity") == "VALID"
    ]
    rows = [
        row
        for row in all_valid_rows
        if row.get("result") == "MIGRATION_REQUIRED"
    ]
    issues: list[str] = []
    if not rows:
        return None, None, ["migration target requires explicit MIGRATION_REQUIRED evidence"]

    candidate_sets: list[set[str]] = []
    normalized_targets: list[dict[str, Any]] = []
    for row in rows:
        causes = row.get("migration_causes") or []
        if not causes:
            issues.append(
                f"{row.get('skill_id') or 'unknown'} migration cause is not explicit"
            )
            continue
        for cause in causes:
            if (
                not isinstance(cause, dict)
                or cause.get("kind") != "project_contract_generation"
                or cause.get("supported_by_bounded_action") is not True
            ):
                issues.append(
                    f"{row.get('skill_id') or 'unknown'} migration cause is not supported by the bounded project-generation action"
                )
                continue
            supported = {
                str(value)
                for value in cause.get("supported_target_generations") or []
                if str(value)
            }
            if not supported:
                issues.append(
                    f"{row.get('skill_id') or 'unknown'} migration target is undeclared"
                )
                continue
            candidate_sets.append(supported)
        normalized_targets.append(_normalized_target_row(row))

    for row in all_valid_rows:
        inputs = row.get("evaluation_inputs") or {}
        supported = {
            str(value)
            for value in inputs.get(
                "supported_project_contract_generations"
            )
            or []
            if str(value)
        }
        if supported:
            candidate_sets.append(supported)

    common = set.intersection(*candidate_sets) if candidate_sets else set()
    if len(common) != 1:
        issues.append(
            "compatibility evidence does not establish exactly one safe project contract target"
        )
    target = sorted(common)[0] if len(common) == 1 else None
    if requested_target is not None and target is not None and str(requested_target) != target:
        issues.append(
            f"requested target generation {requested_target} conflicts with evaluated target {target}"
        )
    if issues or target is None:
        return None, None, issues

    source_generations = {
        str(
            (row.get("evaluation_inputs") or {}).get(
                "project_contract_generation"
            )
            or ""
        )
        for row in rows
    }
    if len(source_generations) != 1:
        return (
            None,
            None,
            ["migration evidence does not establish one source project generation"],
        )
    source_generation = next(iter(source_generations))
    binding = {
        "overall": "MIGRATION_REQUIRED",
        "source_project_contract_generation": source_generation,
        "target_project_contract_generation": target,
        "targets": normalized_targets,
        "package_constraints": [
            _normalized_target_row(row) for row in all_valid_rows
        ],
    }
    binding["evaluation_digest"] = sha256_text(yaml_lite.dump(binding))
    return target, binding, []


def build_migration_plan(
    root: Path,
    snapshot,
    *,
    target_generation: str,
    compatibility_binding: dict[str, Any],
) -> dict[str, Any]:
    source_lock = snapshot.lock.data or {}
    envelope = [PROJECT_YAML]
    source_scaffold_state = observe_source_scaffold_state(
        root,
        snapshot.project or {},
    )
    record_requirements: dict[str, str] = {}
    for target in compatibility_binding.get("targets") or []:
        inputs = target.get("evaluation_inputs") or {}
        for kind, generation in (
            inputs.get("record_schema_requirements") or {}
        ).items():
            record_requirements[str(kind)] = str(generation)
    body = {
        "schema_version": "1",
        "kind": "migration_plan",
        "source_lock": source_lock,
        "source_scaffold_state": source_scaffold_state,
        "source_fingerprint": source_scaffold_state["fingerprint"],
        "source_project": snapshot.project or {},
        "source_contract_generation": str(
            (snapshot.project or {}).get("project_contract_generation") or ""
        ),
        "target_contract_generation": target_generation,
        "target_intent": {
            "kind": "project_contract_generation",
            "source": str(
                (snapshot.project or {}).get("project_contract_generation")
                or ""
            ),
            "target": target_generation,
        },
        "mutation_envelope": envelope,
        "compatibility": "MIGRATION_REQUIRED",
        "compatibility_binding": compatibility_binding,
        "record_generations": {
            "project": {
                "source": str(
                    (snapshot.project or {}).get(
                        "project_contract_generation"
                    )
                    or ""
                ),
                "target": target_generation,
            },
            "records": record_requirements,
        },
    }
    digest = sha256_text(yaml_lite.dump(body))
    body["plan_id"] = f"migplan-{digest[:16]}"
    body["digest"] = digest
    return body


def approval_matches(plan: dict[str, Any], approval: dict[str, Any] | None) -> bool:
    if not approval or not approval.get("approved"):
        return False
    return (
        approval.get("plan_id") == plan.get("plan_id")
        and (approval.get("plan_digest") or approval.get("digest"))
        == plan.get("digest")
    )


def create_execution(root: Path, plan: dict[str, Any], observed_approved: bool) -> Path:
    exec_id = make_id("mig")
    directory = root / MIGRATION_EXECS / exec_id
    directory.mkdir(parents=True, exist_ok=True)
    now = iso_now()
    data = {
        "record_type": "migration_execution",
        "schema_version": "1",
        "record_id": exec_id,
        "created_at": now,
        "updated_at": now,
        "status": "PREPARED",
        "plan": {
            "identity": plan["plan_id"],
            "digest": plan["digest"],
            "observed_approved": observed_approved,
        },
        "source_lock": plan.get("source_lock"),
        "source_scaffold_state": plan.get("source_scaffold_state"),
        "source_fingerprint": plan.get("source_fingerprint"),
        "source_project": plan.get("source_project"),
        "source_contract_generation": plan.get("source_contract_generation"),
        "target_contract_generation": plan.get("target_contract_generation"),
        "target_intent": plan.get("target_intent"),
        "compatibility_binding": plan.get("compatibility_binding"),
        "record_generations": plan.get("record_generations"),
        "mutation_envelope": plan.get("mutation_envelope"),
        "checkpoints_completed": [],
        "checkpoints_remaining": list(MIGRATION_CHECKPOINTS),
        "observed_expected_state": "PRE_MUTATION",
        "blockers": [],
    }
    write_yaml_atomic(directory / "plan.yaml", plan)
    write_yaml_atomic(directory / "execution.yaml", data)
    return directory


def load_execution(directory: Path) -> dict[str, Any]:
    return read_yaml(directory / "execution.yaml")


def save_execution(directory: Path, data: dict[str, Any]) -> None:
    data["updated_at"] = iso_now()
    write_yaml_atomic(directory / "execution.yaml", data)


def bindings_still_hold(
    root: Path,
    plan: dict[str, Any],
    snapshot,
    evaluation: dict[str, Any] | None = None,
) -> list[str]:
    issues = validate_plan_content(plan)
    issues.extend(
        source_scaffold_state_issues(
            root,
            plan,
            allow_envelope_changes=False,
        )
    )
    if (snapshot.lock.data or {}) != (plan.get("source_lock") or {}):
        issues.append("source skills.lock changed before migration mutation")
    if (snapshot.project or {}) != (plan.get("source_project") or {}):
        issues.append("source project state changed before migration mutation")
    if evaluation is not None:
        issues.extend(runtime_binding_issues(plan, evaluation))
    return issues


def source_scaffold_state_issues(
    root: Path,
    plan: dict[str, Any],
    *,
    allow_envelope_changes: bool,
) -> list[str]:
    expected_state = plan.get("source_scaffold_state") or {}
    expected = expected_state.get("inventory")
    if not isinstance(expected, dict):
        return ["Migration Plan lacks durable source Scaffold-state inventory"]
    current = observe_source_scaffold_state(
        root,
        plan.get("source_project") or {},
    ).get("inventory") or {}
    ignored = (
        set(plan.get("mutation_envelope") or [])
        if allow_envelope_changes
        else set()
    )
    changed = [
        path
        for path in sorted(set(expected) | set(current))
        if path not in ignored and expected.get(path) != current.get(path)
    ]
    return [
        "source durable Scaffold state changed before migration applicability: "
        + path
        for path in changed
    ]


def _project_whole_file_allowed(view) -> bool:
    if not view.valid or view.data is None:
        return False
    allowed, _reason = whole_file_mutation_allowed(
        view.data.get("ownership"),
        PROJECT_YAML,
    )
    return allowed


def apply_contract_generation(root: Path, target: str) -> bool:
    view = inspect_project(root / PROJECT_YAML)
    if not _project_whole_file_allowed(view):
        return False
    data = dict(view.data)
    data["project_contract_generation"] = target
    maintenance = [m for m in (data.get("maintenance") or []) if m != "NEEDS_MIGRATION"]
    data["maintenance"] = maintenance
    write_yaml_atomic(root / PROJECT_YAML, data)
    return inspect_project(root / PROJECT_YAML).valid


def mark_needs_migration(root: Path) -> bool:
    view = inspect_project(root / PROJECT_YAML)
    if not _project_whole_file_allowed(view):
        return False
    data = dict(view.data)
    maintenance = list(data.get("maintenance") or [])
    if "NEEDS_MIGRATION" not in maintenance:
        maintenance.append("NEEDS_MIGRATION")
    else:
        return False
    data["maintenance"] = maintenance
    write_yaml_atomic(root / PROJECT_YAML, data)
    return True


def mark_recovery_required(root: Path) -> bool:
    view = inspect_project(root / PROJECT_YAML)
    if not _project_whole_file_allowed(view):
        return False
    data = dict(view.data)
    data["lifecycle"] = "RECOVERY_REQUIRED"
    write_yaml_atomic(root / PROJECT_YAML, data)
    return inspect_project(root / PROJECT_YAML).valid


def complete_migration(root: Path, target: str) -> bool:
    view = inspect_project(root / PROJECT_YAML)
    if not _project_whole_file_allowed(view):
        return False
    data = dict(view.data)
    data["project_contract_generation"] = target
    data["maintenance"] = [
        value for value in (data.get("maintenance") or []) if value != "NEEDS_MIGRATION"
    ]
    if data.get("lifecycle") == "RECOVERY_REQUIRED":
        data["lifecycle"] = "ACTIVE"
    write_yaml_atomic(root / PROJECT_YAML, data)
    return inspect_project(root / PROJECT_YAML).valid


def validate_plan_content(plan: dict[str, Any]) -> list[str]:
    required = {
        "schema_version",
        "kind",
        "source_lock",
        "source_scaffold_state",
        "source_fingerprint",
        "source_project",
        "source_contract_generation",
        "target_contract_generation",
        "target_intent",
        "mutation_envelope",
        "compatibility",
        "compatibility_binding",
        "record_generations",
        "plan_id",
        "digest",
    }
    if not required.issubset(plan):
        return ["Migration Plan is missing required structure"]
    body = {
        "schema_version": plan["schema_version"],
        "kind": plan["kind"],
        "source_lock": plan["source_lock"],
        "source_scaffold_state": plan["source_scaffold_state"],
        "source_fingerprint": plan["source_fingerprint"],
        "source_project": plan["source_project"],
        "source_contract_generation": plan["source_contract_generation"],
        "target_contract_generation": plan["target_contract_generation"],
        "target_intent": plan["target_intent"],
        "mutation_envelope": plan["mutation_envelope"],
        "compatibility": plan["compatibility"],
        "compatibility_binding": plan["compatibility_binding"],
        "record_generations": plan["record_generations"],
    }
    digest = sha256_text(yaml_lite.dump(body))
    issues: list[str] = []
    if digest != plan.get("digest"):
        issues.append("Migration Plan content digest mismatch")
    if plan.get("plan_id") != f"migplan-{digest[:16]}":
        issues.append("Migration Plan identity/content binding mismatch")
    if plan.get("mutation_envelope") != [PROJECT_YAML]:
        issues.append("Migration Plan mutation envelope is not the supported bounded envelope")
    source_state = plan.get("source_scaffold_state") or {}
    source_body = {
        "schema_version": source_state.get("schema_version"),
        "inventory": source_state.get("inventory"),
    }
    source_digest = sha256_text(yaml_lite.dump(source_body))
    if (
        source_state.get("fingerprint") != source_digest
        or plan.get("source_fingerprint") != source_digest
    ):
        issues.append("Migration Plan source Scaffold-state fingerprint mismatch")
    binding = plan.get("compatibility_binding") or {}
    binding_body = {
        key: value
        for key, value in binding.items()
        if key != "evaluation_digest"
    }
    if binding.get("evaluation_digest") != sha256_text(
        yaml_lite.dump(binding_body)
    ):
        issues.append("Migration Plan compatibility evaluation binding digest mismatch")
    if (
        str(binding.get("source_project_contract_generation") or "")
        != str(plan.get("source_contract_generation") or "")
        or str(binding.get("target_project_contract_generation") or "")
        != str(plan.get("target_contract_generation") or "")
    ):
        issues.append("Migration Plan target generation differs from compatibility evidence")
    return issues


def validate_recovery_state(
    root: Path,
    execution: dict[str, Any],
    plan: dict[str, Any],
    snapshot,
    evaluation: dict[str, Any] | None = None,
) -> list[str]:
    issues = validate_plan_content(plan)
    if execution.get("record_type") != "migration_execution":
        issues.append("Migration Execution record_type is invalid")
    if str(execution.get("schema_version") or "") != "1":
        issues.append("Migration Execution schema_version is unsupported")
    binding = execution.get("plan") or {}
    if binding.get("identity") != plan.get("plan_id"):
        issues.append("Migration Execution/Plan identity mismatch")
    if binding.get("digest") != plan.get("digest"):
        issues.append("Migration Execution/Plan digest mismatch")
    if execution.get("mutation_envelope") != plan.get("mutation_envelope"):
        issues.append("Migration Execution mutation envelope differs from Plan")
    if execution.get("source_lock") != plan.get("source_lock"):
        issues.append("Migration Execution source lock differs from Plan")
    for field in (
        "source_scaffold_state",
        "source_fingerprint",
        "source_project",
        "source_contract_generation",
        "target_contract_generation",
        "target_intent",
        "compatibility_binding",
        "record_generations",
    ):
        if execution.get(field) != plan.get(field):
            issues.append(f"Migration Execution {field} differs from Plan")
    if (snapshot.lock.data or {}) != (plan.get("source_lock") or {}):
        issues.append("skills.lock diverged unexpectedly during migration")
    if evaluation is not None:
        issues.extend(runtime_binding_issues(plan, evaluation))

    completed_raw = execution.get("checkpoints_completed")
    remaining_raw = execution.get("checkpoints_remaining")
    if not isinstance(completed_raw, list) or any(
        not isinstance(value, str) for value in completed_raw
    ):
        issues.append("Migration Execution completed checkpoints are malformed")
        completed: list[str] = []
    else:
        completed = completed_raw
    if not isinstance(remaining_raw, list) or any(
        not isinstance(value, str) for value in remaining_raw
    ):
        issues.append("Migration Execution remaining checkpoints are malformed")
        remaining: list[str] = []
    else:
        remaining = remaining_raw
    prefix_length = len(completed)
    if completed != MIGRATION_CHECKPOINTS[:prefix_length]:
        issues.append("Migration Execution checkpoints are not a provable expected prefix")
    if remaining != MIGRATION_CHECKPOINTS[prefix_length:]:
        issues.append("Migration Execution remaining checkpoints contradict completed prefix")
    issues.extend(
        source_scaffold_state_issues(
            root,
            plan,
            allow_envelope_changes=prefix_length >= 1,
        )
    )

    expected_observation = {
        0: "PRE_MUTATION",
        1: "VALIDATING",
        2: "VALIDATION_PASSED",
    }.get(prefix_length)
    if expected_observation is None:
        issues.append("Migration Execution checkpoint prefix is longer than supported")
    elif execution.get("observed_expected_state") != expected_observation:
        issues.append("Migration Execution observed checkpoint state is inconsistent")

    status = execution.get("status")
    if status not in {"PREPARED", "APPLYING", "VALIDATING", "RECOVERY_REQUIRED"}:
        issues.append("Migration Execution is not in a resumable state")
    if prefix_length == 0 and status not in {
        "PREPARED",
        "APPLYING",
        "RECOVERY_REQUIRED",
    }:
        issues.append("Migration Execution status contradicts pre-mutation checkpoint")
    if prefix_length in {1, 2} and status not in {
        "VALIDATING",
        "RECOVERY_REQUIRED",
    }:
        issues.append("Migration Execution status contradicts validation checkpoint")

    expected_project = _project_at_checkpoint(
        plan,
        target_applied=prefix_length >= 1,
        recovery_lifecycle=(
            (snapshot.project or {}).get("lifecycle")
            == "RECOVERY_REQUIRED"
        ),
    )
    if (snapshot.project or {}) != expected_project:
        issues.append("actual project state diverged from the approved migration checkpoint")
    return issues


def reconcile_execution_checkpoint(
    directory: Path,
    execution: dict[str, Any],
    plan: dict[str, Any],
    snapshot,
) -> bool:
    """Publish the next checkpoint after an exact write/checkpoint crash gap."""
    if execution.get("status") not in {"APPLYING", "RECOVERY_REQUIRED"}:
        return False
    if (execution.get("checkpoints_completed") or []) != []:
        return False
    if (execution.get("checkpoints_remaining") or []) != MIGRATION_CHECKPOINTS:
        return False
    if execution.get("observed_expected_state") != "PRE_MUTATION":
        return False
    recovery_lifecycle = (
        (snapshot.project or {}).get("lifecycle") == "RECOVERY_REQUIRED"
    )
    expected = _project_at_checkpoint(
        plan,
        target_applied=True,
        recovery_lifecycle=recovery_lifecycle,
    )
    if (snapshot.project or {}) != expected:
        return False
    if (snapshot.lock.data or {}) != (plan.get("source_lock") or {}):
        return False
    if source_scaffold_state_issues(
        snapshot.root,
        plan,
        allow_envelope_changes=True,
    ):
        return False
    execution["status"] = (
        "RECOVERY_REQUIRED" if recovery_lifecycle else "VALIDATING"
    )
    execution["checkpoints_completed"] = [CONTRACT_GENERATION_UPDATED]
    execution["checkpoints_remaining"] = [VALIDATION_PASSED]
    execution["observed_expected_state"] = "VALIDATING"
    save_execution(directory, execution)
    return True


def validate_applied_state(
    plan: dict[str, Any],
    snapshot,
) -> list[str]:
    issues: list[str] = []
    if (snapshot.lock.data or {}) != (plan.get("source_lock") or {}):
        issues.append("skills.lock changed outside the approved migration envelope")
    issues.extend(
        source_scaffold_state_issues(
            snapshot.root,
            plan,
            allow_envelope_changes=True,
        )
    )
    expected_project = dict(plan.get("source_project") or {})
    expected_project["project_contract_generation"] = str(
        plan.get("target_contract_generation") or ""
    )
    expected_project["maintenance"] = [
        value
        for value in (expected_project.get("maintenance") or [])
        if value != "NEEDS_MIGRATION"
    ]
    if (snapshot.project or {}) != expected_project:
        issues.append("post-apply project state differs from the approved target")
    return issues


def runtime_binding_issues(
    plan: dict[str, Any],
    evaluation: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    planned_targets = {
        str(row.get("skill_id") or ""): row
        for row in (
            (plan.get("compatibility_binding") or {}).get(
                "package_constraints"
            )
            or []
        )
    }
    current_results = evaluation.get("results") or {}
    for skill_id, planned in sorted(planned_targets.items()):
        current = current_results.get(skill_id)
        if not isinstance(current, dict) or current.get("validity") != "VALID":
            issues.append(
                f"current compatibility package for {skill_id} is unavailable or invalid"
            )
            continue
        if _runtime_signature(current) != _runtime_signature(planned):
            issues.append(
                f"current compatibility package/evaluation binding changed for {skill_id}"
            )
    return issues


def _normalized_target_row(row: dict[str, Any]) -> dict[str, Any]:
    inputs = row.get("evaluation_inputs") or {}
    return {
        "skill_id": str(row.get("skill_id") or ""),
        "evaluation_result": str(row.get("result") or ""),
        "expected_package": dict(row.get("expected_package") or {}),
        "actual_package": dict(row.get("actual_package") or {}),
        "evaluation_inputs": {
            "project_contract_generation": str(
                inputs.get("project_contract_generation") or ""
            ),
            "supported_project_contract_generations": sorted(
                {
                    str(value)
                    for value in inputs.get(
                        "supported_project_contract_generations"
                    )
                    or []
                }
            ),
            "requires_host_migration": bool(
                inputs.get("requires_host_migration")
            ),
            "record_schema_requirements": {
                str(kind): str(value)
                for kind, value in sorted(
                    (inputs.get("record_schema_requirements") or {}).items()
                )
            },
            "record_schema_capabilities": {
                str(kind): sorted({str(value) for value in values or []})
                for kind, values in sorted(
                    (
                        inputs.get("record_schema_capabilities") or {}
                    ).items()
                )
            },
        },
        "migration_causes": [
            dict(cause)
            for cause in row.get("migration_causes") or []
            if isinstance(cause, dict)
        ],
    }


def _runtime_signature(row: dict[str, Any]) -> dict[str, Any]:
    normalized = (
        row
        if "evaluation_result" in row
        else _normalized_target_row(row)
    )
    inputs = normalized.get("evaluation_inputs") or {}
    return {
        "skill_id": str(normalized.get("skill_id") or ""),
        "expected_package": dict(normalized.get("expected_package") or {}),
        "actual_package": dict(normalized.get("actual_package") or {}),
        "supported_project_contract_generations": list(
            inputs.get("supported_project_contract_generations") or []
        ),
        "requires_host_migration": bool(
            inputs.get("requires_host_migration")
        ),
        "record_schema_requirements": dict(
            inputs.get("record_schema_requirements") or {}
        ),
        "record_schema_capabilities": dict(
            inputs.get("record_schema_capabilities") or {}
        ),
    }


def _project_at_checkpoint(
    plan: dict[str, Any],
    *,
    target_applied: bool,
    recovery_lifecycle: bool,
) -> dict[str, Any]:
    project = dict(plan.get("source_project") or {})
    if target_applied:
        project["project_contract_generation"] = str(
            plan.get("target_contract_generation") or ""
        )
        project["maintenance"] = [
            value
            for value in (project.get("maintenance") or [])
            if value != "NEEDS_MIGRATION"
        ]
    if recovery_lifecycle:
        project["lifecycle"] = "RECOVERY_REQUIRED"
    return project


def delete_execution(directory: Path) -> None:
    for child in directory.iterdir():
        child.unlink()
    directory.rmdir()

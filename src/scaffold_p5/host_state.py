from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite
from scaffold_p5.inventory import (
    CLASS_EXCLUDED,
    EXCLUDED_DIR_NAMES,
    InventoryBudget,
    bounded_metadata_walk,
    hashed_inventory,
    observe_inventory,
    project_relative_path,
)
from scaffold_p5.io_util import file_digest, list_files, read_text, read_yaml, sha256_text
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import is_digest, is_format_version, is_semver
from scaffold_p5.scm import observe_scm
from scaffold_p5.schemas import (
    validate_adoption_plan_data,
    validate_adoption_session_data,
    validate_project_data,
)


PROJECT_YAML = ".scaffold/project.yaml"
MODULES_YAML = ".scaffold/modules.yaml"
COMMANDS_YAML = ".scaffold/commands.yaml"
TESTS_YAML = ".scaffold/tests.yaml"
SKILLS_LOCK = ".scaffold/skills.lock"
AGENTS_MD = "AGENTS.md"
OVERVIEW_MD = "docs/project/overview.md"
ARCHITECTURE_MD = "docs/project/architecture.md"
DEVELOPMENT_MD = "docs/project/development.md"
TESTING_MD = "docs/project/testing.md"
MODULE_DOCS = "docs/project/modules"
ADOPTION_SESSIONS = ".scaffold/runtime/adoption-sessions"
MIGRATION_EXECS = ".scaffold/runtime/migration-executions"
DERIVED_UNDERSTAND = ".scaffold/derived/understand.md"

CLIENT_HINTS = (
    "AGENTS.md",
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".cursorrules",
    "CODEX.md",
    ".github/copilot-instructions.md",
)


@dataclass
class LockView:
    status: str
    data: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def complete_authoritative(self) -> bool:
        return self.status == "complete_authoritative"


@dataclass
class ProjectView:
    status: str
    data: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.status == "VALID"


@dataclass
class HostSnapshot:
    root: Path
    files: list[str]
    project: dict[str, Any] | None
    project_view: ProjectView
    lock: LockView
    sessions: list[dict[str, Any]]
    adoption_recovery: dict[str, Any]
    migrations: list[dict[str, Any]]
    migration_recovery: dict[str, Any]
    workspace_baseline: dict[str, Any]
    host_class: str
    preflight_context: str
    blockers: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def lifecycle(self) -> str | None:
        if not self.project_view.valid or not self.project:
            return None
        return self.project.get("lifecycle")

    @property
    def has_session(self) -> bool:
        return bool(self.sessions)


def snapshot_host(root: str | Path) -> HostSnapshot:
    host = Path(root)
    files = list_files(host)
    project_view = inspect_project(host / PROJECT_YAML)
    project = project_view.data
    lock = inspect_lock(host / SKILLS_LOCK)
    adoption_recovery = inspect_adoption_recovery(host / ADOPTION_SESSIONS)
    sessions = list(adoption_recovery.get("resumable") or [])
    migration_recovery = inspect_migration_recovery(host / MIGRATION_EXECS)
    migrations = list(migration_recovery.get("resumable") or [])
    baseline = scm_baseline(host)
    host_class, context, blockers, evidence = classify_host(
        host,
        files,
        project_view,
        lock,
        adoption_recovery,
        migration_recovery,
    )
    return HostSnapshot(
        root=host,
        files=files,
        project=project,
        project_view=project_view,
        lock=lock,
        sessions=sessions,
        adoption_recovery=adoption_recovery,
        migrations=migrations,
        migration_recovery=migration_recovery,
        workspace_baseline=baseline,
        host_class=host_class,
        preflight_context=context,
        blockers=blockers,
        evidence=evidence,
    )


def inspect_project(path: Path) -> ProjectView:
    if not path.exists():
        return ProjectView("ABSENT", reasons=["project.yaml missing"])
    data, error = _read_mapping_artifact(path)
    if error:
        return ProjectView("MALFORMED", reasons=[error])
    status, reasons = validate_project_data(data)
    return ProjectView(status, data=data, reasons=reasons)


def inspect_lock(path: Path) -> LockView:
    if not path.exists():
        tmp = path.with_name(path.name + ".tmp")
        if tmp.exists():
            return LockView("unpublished", reasons=["interrupted lock publication"])
        return LockView("absent", reasons=["skills.lock missing"])
    try:
        data = read_yaml(path)
    except Exception:
        return LockView("malformed", reasons=["skills.lock is not parseable"])
    if not isinstance(data, dict):
        return LockView("malformed", reasons=["skills.lock is not a map"])
    reasons: list[str] = []
    if str(data.get("lock_format_version") or "") != "1":
        reasons.append("unsupported or missing lock_format_version")
    if str(data.get("schema_version") or "") != "1":
        reasons.append("unsupported or missing lock schema_version")
    skills = data.get("skills")
    if not isinstance(skills, dict):
        reasons.append("skills map missing")
        return LockView("malformed", data=data, reasons=reasons)
    missing = [s for s in CORE_SKILLS if s not in skills]
    extra = [s for s in skills if s not in CORE_SKILLS]
    if missing:
        reasons.append("partial lock missing " + ",".join(missing))
    if extra:
        reasons.append("lock contains non-core Skill identities: " + ",".join(sorted(extra)))
    if missing or extra:
        return LockView("partial", data=data, reasons=reasons)
    for skill_id in CORE_SKILLS:
        entry = skills.get(skill_id) or {}
        if not isinstance(entry, dict):
            reasons.append(f"{skill_id} lock entry must be a mapping")
            continue
        if not is_semver(str(entry.get("skill_version") or "")):
            reasons.append(f"{skill_id} lacks a valid exact semantic version")
        if not is_digest(str(entry.get("package_digest") or "")):
            reasons.append(f"{skill_id} lacks a valid package identity digest")
        if not is_format_version(str(entry.get("package_format_version") or "")):
            reasons.append(f"{skill_id} lacks valid package_format_version")
    if reasons:
        return LockView("incomplete", data=data, reasons=reasons)
    if data.get("authoritative") is not True:
        return LockView(
            "complete_candidate",
            data=data,
            reasons=["lock authoritative establishment is absent, false, or unproven"],
        )
    return LockView("complete_authoritative", data=data)


def inspect_adoption_recovery(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "classification": "NONE",
            "entries": [],
            "blockers": [],
            "requires_isolation": False,
            "resumable": [],
        }
    if not root.is_dir():
        entry = {
            "path": str(root),
            "entry_id": root.name,
            "classification": "ORPHAN_ENTRY",
            "issues": ["Adoption recovery root is not a directory"],
        }
        return _adoption_recovery_result([entry], [])

    children = sorted(root.iterdir(), key=lambda path: path.name)
    if not children:
        entry = {
            "path": str(root),
            "entry_id": ".",
            "classification": "ORPHAN_DIRECTORY",
            "issues": ["Adoption recovery root is empty but still present"],
        }
        return _adoption_recovery_result([entry], [])

    entries: list[dict[str, Any]] = []
    resumable: list[dict[str, Any]] = []
    for child in children:
        observation: dict[str, Any] = {
            "path": str(child),
            "entry_id": child.name,
        }
        if not child.is_dir():
            observation["classification"] = "ORPHAN_ENTRY"
            observation["issues"] = ["Adoption recovery entry is not a directory"]
            entries.append(observation)
            continue

        session_path = child / "session.yaml"
        plan_path = child / "plan.yaml"
        session, session_error = _read_mapping_artifact(session_path)
        plan, plan_error = _read_mapping_artifact(plan_path)
        issues: list[str] = []
        if not session_path.exists() and plan_path.exists():
            kind = "PLAN_WITHOUT_SESSION"
            issues.append("Adoption Plan exists without session.yaml")
        elif session_path.exists() and not plan_path.exists():
            kind = "SESSION_WITHOUT_PLAN"
            issues.append("Adoption Session exists without plan.yaml")
        elif not session_path.exists() and not plan_path.exists():
            kind = "ORPHAN_DIRECTORY"
            issues.append("Adoption recovery directory has no Session or Plan")
        elif session_error:
            kind = "MALFORMED_SESSION"
            issues.append(session_error)
        elif plan_error:
            kind = "MALFORMED_PLAN"
            issues.append(plan_error)
        else:
            session_status, session_issues = validate_adoption_session_data(
                session
            )
            plan_status, plan_issues = validate_adoption_plan_data(plan)
            issues.extend(session_issues)
            issues.extend(plan_issues)
            if (
                session
                and str(session.get("record_id") or "") != child.name
            ):
                issues.append(
                    "Adoption Session record_id does not match its recovery directory"
                )
            if session and plan:
                binding = session.get("plan")
                if isinstance(binding, dict):
                    if binding.get("identity") != plan.get("plan_id"):
                        issues.append(
                            "Adoption Session/Plan identity binding is invalid"
                        )
                    if binding.get("digest") != plan.get("digest"):
                        issues.append(
                            "Adoption Session/Plan digest binding is invalid"
                        )
                for field in (
                    "baseline",
                    "release_id",
                    "intended_lock",
                    "mutation_envelope",
                ):
                    if session.get(field) != plan.get(field):
                        issues.append(
                            f"Adoption Session {field} differs from Plan"
                        )
            if session_status == "UNSUPPORTED":
                kind = "UNSUPPORTED_SESSION"
            elif session_status != "VALID":
                kind = "INCOMPLETE_SESSION"
            elif plan_status == "UNSUPPORTED":
                kind = "UNSUPPORTED_PLAN"
            elif plan_status != "VALID":
                kind = "INCOMPLETE_PLAN"
            elif issues:
                kind = "UNSUPPORTED_OR_INCOMPLETE"
            else:
                kind = "VALID_CURRENT"
                row = dict(session or {})
                row["_path"] = str(session_path)
                row["_dir"] = str(child)
                resumable.append(row)
        observation["classification"] = kind
        observation["issues"] = sorted(set(issues))
        entries.append(observation)
    return _adoption_recovery_result(entries, resumable)


def _adoption_recovery_result(
    entries: list[dict[str, Any]],
    resumable: list[dict[str, Any]],
) -> dict[str, Any]:
    unresolved = len(entries)
    if not entries:
        classification = "NONE"
    elif unresolved == 1 and len(resumable) == 1:
        classification = "ONE_VALID_UNRESOLVED"
    elif unresolved > 1:
        classification = "AMBIGUOUS"
    else:
        classification = "UNRESOLVED_EVIDENCE"
    blockers = [
        f"{entry['classification']}: {entry['entry_id']}"
        + (
            " (" + "; ".join(entry.get("issues") or []) + ")"
            if entry.get("issues")
            else ""
        )
        for entry in entries
        if entry["classification"] != "VALID_CURRENT"
    ]
    return {
        "classification": classification,
        "entries": entries,
        "blockers": blockers,
        "requires_isolation": bool(entries),
        "resumable": resumable,
    }


def inspect_migration_recovery(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "classification": "NONE",
            "entries": [],
            "blockers": [],
            "requires_isolation": False,
            "resumable": [],
        }
    if not root.is_dir():
        entry = {
            "path": str(root),
            "entry_id": root.name,
            "classification": "ORPHAN_ENTRY",
            "issues": ["migration recovery root is not a directory"],
        }
        return {
            "classification": "UNRESOLVED_EVIDENCE",
            "entries": [entry],
            "blockers": [
                "ORPHAN_ENTRY: "
                + root.name
                + " (migration recovery root is not a directory)"
            ],
            "requires_isolation": True,
            "resumable": [],
        }
    entries: list[dict[str, Any]] = []
    resumable: list[dict[str, Any]] = []
    unresolved_count = 0
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        observation: dict[str, Any] = {
            "path": str(child),
            "entry_id": child.name,
        }
        if not child.is_dir():
            observation["classification"] = "ORPHAN_ENTRY"
            observation["issues"] = ["migration recovery entry is not a directory"]
            unresolved_count += 1
            entries.append(observation)
            continue
        execution_path = child / "execution.yaml"
        plan_path = child / "plan.yaml"
        execution, execution_error = _read_mapping_artifact(execution_path)
        plan, plan_error = _read_mapping_artifact(plan_path)
        issues: list[str] = []
        if not execution_path.exists() and plan_path.exists():
            kind = "PLAN_WITHOUT_EXECUTION"
            issues.append("Migration Plan exists without execution.yaml")
        elif execution_path.exists() and not plan_path.exists():
            kind = "EXECUTION_WITHOUT_PLAN"
            issues.append("Migration Execution exists without plan.yaml")
        elif not execution_path.exists() and not plan_path.exists():
            kind = "ORPHAN_DIRECTORY"
            issues.append("migration directory has no Plan or Execution")
        elif execution_error:
            kind = "MALFORMED_EXECUTION"
            issues.append(execution_error)
        elif plan_error:
            kind = "MALFORMED_PLAN"
            issues.append(plan_error)
        else:
            issues.extend(_migration_artifact_issues(execution or {}, plan or {}))
            status = str((execution or {}).get("status") or "")
            if issues:
                kind = "UNSUPPORTED_OR_INCOMPLETE"
            elif status == "COMPLETED":
                kind = "VALID_COMPLETED"
            elif status == "ABORTED":
                kind = "VALID_ABORTED"
            else:
                kind = "VALID_UNRESOLVED"
                row = dict(execution or {})
                row["_path"] = str(execution_path)
                row["_dir"] = str(child)
                resumable.append(row)
        observation["classification"] = kind
        observation["issues"] = issues
        if kind not in {"VALID_COMPLETED", "VALID_ABORTED"}:
            unresolved_count += 1
        entries.append(observation)
    if not entries:
        classification = "NONE"
    elif unresolved_count == 0:
        classification = "HISTORICAL_ONLY"
    elif unresolved_count == 1 and len(resumable) == 1:
        classification = "ONE_VALID_UNRESOLVED"
    elif unresolved_count > 1:
        classification = "AMBIGUOUS"
    else:
        classification = "UNRESOLVED_EVIDENCE"
    blockers = [
        f"{entry['classification']}: {entry['entry_id']}"
        + (
            " (" + "; ".join(entry.get("issues") or []) + ")"
            if entry.get("issues")
            else ""
        )
        for entry in entries
        if entry["classification"] not in {"VALID_COMPLETED", "VALID_ABORTED"}
    ]
    return {
        "classification": classification,
        "entries": entries,
        "blockers": blockers,
        "requires_isolation": unresolved_count > 0,
        "resumable": resumable,
    }


def _read_mapping_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, None
    try:
        value = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, f"{path.name} is malformed or unreadable"
    if not isinstance(value, dict):
        return None, f"{path.name} is not a mapping"
    return value, None


def _migration_artifact_issues(
    execution: dict[str, Any],
    plan: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    required_execution = {
        "record_type",
        "schema_version",
        "record_id",
        "status",
        "plan",
        "source_lock",
        "source_scaffold_state",
        "source_fingerprint",
        "source_project",
        "source_contract_generation",
        "target_contract_generation",
        "target_intent",
        "compatibility_binding",
        "record_generations",
        "mutation_envelope",
        "checkpoints_completed",
        "checkpoints_remaining",
        "observed_expected_state",
    }
    if not required_execution.issubset(execution):
        issues.append("Migration Execution is incomplete")
    if execution.get("record_type") != "migration_execution":
        issues.append("Migration Execution record_type is invalid")
    if str(execution.get("schema_version") or "") != "1":
        issues.append("Migration Execution schema_version is unsupported")
    status = str(execution.get("status") or "")
    if status not in {
        "PREPARED",
        "APPLYING",
        "VALIDATING",
        "COMPLETED",
        "RECOVERY_REQUIRED",
        "ABORTED",
    }:
        issues.append("Migration Execution status is unsupported")
    completed = execution.get("checkpoints_completed")
    remaining = execution.get("checkpoints_remaining")
    if not isinstance(completed, list) or any(
        not isinstance(value, str) for value in completed
    ):
        issues.append("Migration Execution completed checkpoints are malformed")
        completed = []
    if not isinstance(remaining, list) or any(
        not isinstance(value, str) for value in remaining
    ):
        issues.append("Migration Execution remaining checkpoints are malformed")
        remaining = []
    required_plan = {
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
    if not required_plan.issubset(plan):
        issues.append("Migration Plan is incomplete")
        return issues
    if plan.get("kind") != "migration_plan" or str(plan.get("schema_version") or "") != "1":
        issues.append("Migration Plan kind/schema is unsupported")
    body = {
        key: plan[key]
        for key in (
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
        )
    }
    digest = sha256_text(yaml_lite.dump(body))
    if plan.get("digest") != digest or plan.get("plan_id") != f"migplan-{digest[:16]}":
        issues.append("Migration Plan identity/content binding is invalid")
    binding = execution.get("plan")
    if not isinstance(binding, dict):
        issues.append("Migration Execution Plan binding is malformed")
    elif (
        binding.get("identity") != plan.get("plan_id")
        or binding.get("digest") != plan.get("digest")
    ):
        issues.append("Migration Execution/Plan binding is invalid")
    for field in (
        "source_lock",
        "source_scaffold_state",
        "source_fingerprint",
        "source_project",
        "source_contract_generation",
        "target_contract_generation",
        "target_intent",
        "compatibility_binding",
        "record_generations",
        "mutation_envelope",
    ):
        if execution.get(field) != plan.get(field):
            issues.append(f"Migration Execution {field} differs from Plan")
    if status == "COMPLETED" and (
        completed != ["CONTRACT_GENERATION_UPDATED", "VALIDATION_PASSED"]
        or remaining != []
        or execution.get("observed_expected_state") != "VALIDATION_PASSED"
    ):
        issues.append("completed Migration Execution lacks final checkpoint")
    if status == "ABORTED" and (
        completed != []
        or remaining
        != ["CONTRACT_GENERATION_UPDATED", "VALIDATION_PASSED"]
        or execution.get("observed_expected_state") != "PRE_MUTATION"
    ):
        issues.append("aborted Migration Execution contains applied checkpoints")
    return issues


def classify_host(
    host: Path,
    files: list[str],
    project_view: ProjectView,
    lock: LockView,
    adoption_recovery: dict[str, Any],
    migration_recovery: dict[str, Any],
) -> tuple[str, str, list[str], list[str]]:
    evidence: list[str] = []
    blockers: list[str] = []
    project = project_view.data
    declared_lifecycle = (
        project.get("lifecycle")
        if isinstance(project, dict)
        else None
    )
    lifecycle = (
        declared_lifecycle
        if project_view.valid and project
        else None
    )
    sessions = list(adoption_recovery.get("resumable") or [])
    identity = _identity_evidence(
        host,
        files,
        project_view,
        lock,
        adoption_recovery,
        migration_recovery,
    )
    evidence.extend(identity)
    if project_view.status not in {"ABSENT", "VALID"}:
        blockers.extend(project_view.reasons)
        evidence.append(f"project.yaml observation={project_view.status}")

    recoverable = [s for s in sessions if s.get("status") in {"OPEN", "INTERRUPTED", "BLOCKED"}]
    adopting = lifecycle == "ADOPTING"
    active = lifecycle == "ACTIVE"
    recovery_lc = lifecycle == "RECOVERY_REQUIRED"

    activation_pending = any(
        set(session.get("checkpoints") or [])
        & {"B7_PASSED", "LOCK_AUTHORITY_ESTABLISHED", "B8_ACTIVE"}
        for session in recoverable
    )

    coherent_adoption = (
        adoption_recovery.get("classification")
        == "ONE_VALID_UNRESOLVED"
    )

    if (
        recoverable
        and coherent_adoption
        and (adopting or project_view.status == "ABSENT")
        and migration_recovery.get("classification") == "NONE"
    ):
        evidence.append("current interrupted initial Adoption")
        if lock.complete_authoritative:
            evidence.append("initial lock authority established; Plan release authority expired")
        return "INTERRUPTED_INITIAL_ADOPTION", "HOST_COMPATIBILITY", blockers, evidence

    if (
        active
        and recoverable
        and activation_pending
        and coherent_adoption
        and migration_recovery.get("classification") == "NONE"
    ):
        evidence.append("initial Adoption activation/cleanup checkpoint remains")
        return "INTERRUPTED_INITIAL_ADOPTION", "HOST_COMPATIBILITY", blockers, evidence

    if adoption_recovery.get("classification") != "NONE":
        blockers.extend(adoption_recovery.get("blockers") or [])
        if adoption_recovery.get("classification") == "AMBIGUOUS":
            blockers.append("ambiguous Adoption recovery evidence")
        blockers.append(
            "unresolved Adoption recovery evidence requires consistency resolution"
        )
        if active or recovery_lc:
            return (
                "ESTABLISHED_HOST_CONSISTENCY",
                "HOST_COMPATIBILITY",
                sorted(set(blockers)),
                evidence,
            )

    if (
        not project_view.valid
        and declared_lifecycle in ("ACTIVE", "RECOVERY_REQUIRED")
    ):
        blockers.append(
            "established lifecycle evidence is not executable under the project schema"
        )
        return (
            "ESTABLISHED_HOST_CONSISTENCY",
            "HOST_COMPATIBILITY",
            sorted(set(blockers)),
            evidence,
        )

    if (active or recovery_lc) and lock.complete_authoritative:
        evidence.append("complete authoritative skills.lock")
        if recovery_lc:
            evidence.append("host lifecycle RECOVERY_REQUIRED with lock authority intact")
        return "ESTABLISHED_HOST", "HOST_COMPATIBILITY", blockers, evidence

    if active and not lock.complete_authoritative:
        blockers.append("established host lacks authoritative skills.lock")
        evidence.append("ACTIVE host consistency/recovery — historical Plan is not lock authority")
        return "ESTABLISHED_HOST_CONSISTENCY", "HOST_COMPATIBILITY", blockers, evidence

    if recovery_lc:
        blockers.append("host lifecycle is RECOVERY_REQUIRED")
        return "ESTABLISHED_HOST_CONSISTENCY", "HOST_COMPATIBILITY", blockers, evidence

    if (
        project_view.status != "ABSENT"
        or recoverable
        or lock.status != "absent"
        or adoption_recovery.get("classification") != "NONE"
        or migration_recovery.get("classification") != "NONE"
        or identity
    ):
        blockers.append("prior Scaffold identity/recovery evidence — missing lock is not bootstrap")
        return (
            "PRIOR_FOOTPRINT",
            "HOST_COMPATIBILITY",
            sorted(set(blockers)),
            evidence,
        )

    evidence.append("ordinary project with legitimate NOT_ADOPTED")
    return "NOT_ADOPTED", "PRE_ADOPTION_BOOTSTRAP", blockers, evidence


def _identity_evidence(
    host: Path,
    files: list[str],
    project_view: ProjectView,
    lock: LockView,
    adoption_recovery: dict[str, Any],
    migration_recovery: dict[str, Any],
) -> list[str]:
    out: list[str] = []
    if (host / PROJECT_YAML).exists():
        out.append(f"project.yaml present status={project_view.status}")
    if lock.status != "absent":
        out.append(f"skills.lock status={lock.status}")
    if adoption_recovery.get("classification") != "NONE":
        out.append(
            "Adoption recovery evidence="
            + str(adoption_recovery.get("classification"))
        )
    if migration_recovery.get("classification") != "NONE":
        out.append(
            "Migration recovery evidence="
            + str(migration_recovery.get("classification"))
        )
    if (host / AGENTS_MD).exists():
        text = read_text(host / AGENTS_MD)
        if "This host is managed by AI-Native Project Scaffold." in text:
            out.append("AGENTS.md carries established Scaffold host identity")
    scaffold_specific = {
        MODULES_YAML,
        COMMANDS_YAML,
        TESTS_YAML,
    }
    present_specific = sorted(scaffold_specific.intersection(files))
    if present_specific:
        out.append(
            "recognized Scaffold core metadata present: "
            + ",".join(present_specific)
        )
    return out


def workspace_fingerprint(root: Path, paths: list[str]) -> str:
    parts = []
    for rel in paths:
        path = root / rel
        if path.exists():
            parts.append(rel + "\n" + file_digest(path))
        else:
            parts.append(rel + "\nABSENT")
    return sha256_text(*parts)


def durable_inventory(
    root: Path,
    *,
    exact_observe: list[str] | None = None,
    budget: Any = None,
    coverage_out: dict[str, Any] | None = None,
    counter: Any = None,
    on_directory: Any = None,
    dir_cache: Any = None,
) -> dict[str, dict[str, str]]:
    """In-scope digest evidence. Excluded heavy roots are not recursively hashed."""
    observation = observe_inventory(
        root,
        exact_observe=exact_observe,
        budget=budget,
        counter=counter,
        on_directory=on_directory,
        dir_cache=dir_cache,
    )
    if coverage_out is not None:
        coverage_out.clear()
        coverage_out.update(observation.coverage_dict())
    return hashed_inventory(observation)


def _inventory_sig(row: Any) -> tuple[str, str]:
    if not isinstance(row, dict):
        return ("", "")
    return (str(row.get("type") or ""), str(row.get("digest") or ""))


def _norm_inventory_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def compare_adoption_state(
    root: Path,
    baseline: dict[str, Any],
    mutation_envelope: list[str],
    session: dict[str, Any] | None = None,
) -> list[str]:
    expected = baseline.get("inventory")
    if not isinstance(expected, dict):
        return ["Adoption Baseline lacks durable inventory evidence"]
    envelope = [str(item) for item in mutation_envelope if str(item or "").strip()]
    observe_keys = sorted(
        {
            _norm_inventory_path(path)
            for path in list(expected) + envelope
            if _norm_inventory_path(path)
        }
    )
    current_coverage: dict[str, Any] = {}
    current = durable_inventory(
        root, exact_observe=observe_keys, coverage_out=current_coverage
    )
    allowed = set(envelope)
    allowed_norm = {_norm_inventory_path(item) for item in envelope}
    issues: list[str] = []
    coverage = baseline.get("inventory_coverage")
    exact_observed = {
        _norm_inventory_path(item)
        for item in ((coverage or {}).get("exact_observed") or [])
        if isinstance(coverage, dict)
    }
    expected_norm = {_norm_inventory_path(path) for path in expected}
    for target in envelope:
        if str(target).endswith("/"):
            continue
        normalized = _norm_inventory_path(target)
        safe, _reason = project_relative_path(root, target)
        if safe is None:
            issues.append(f"mutation envelope target is unobserved: {target}")
            continue
        if normalized not in exact_observed and normalized not in expected_norm:
            issues.append(f"mutation envelope target is unobserved: {target}")
    if isinstance(coverage, dict) and coverage.get("verified_complete") is True:
        if coverage.get("status") != "FULLY_OBSERVED":
            issues.append("inventory claimed VERIFIED completeness without full observation")
    if isinstance(coverage, dict):
        issues.extend(
            _excluded_presence_issues(
                coverage, current_coverage, allowed_norm
            )
        )
    for path, before in expected.items():
        after = current.get(path)
        if after is None:
            if isinstance(before, dict) and before.get("type") == "absent":
                if not (root / path).exists():
                    continue
            if path not in allowed or before is not None:
                issues.append(f"pre-existing durable path removed outside envelope: {path}")
        elif _inventory_sig(after) != _inventory_sig(before):
            if path not in allowed:
                issues.append(f"pre-existing durable path changed outside envelope: {path}")
            elif not _adoption_progress_proven(path, after, session, root):
                issues.append(
                    f"in-envelope path changed without current Session provenance: {path}"
                )
    for path, row in current.items():
        if path in expected:
            continue
        if isinstance(row, dict) and row.get("type") in {"absent", "directory"}:
            continue
        if path not in allowed and _norm_inventory_path(path) not in allowed_norm:
            issues.append(f"unexpected durable path outside envelope: {path}")
        elif not _adoption_progress_proven(path, current[path], session, root):
            issues.append(
                f"in-envelope path appeared without current Session provenance: {path}"
            )
    if session:
        for mutation in session.get("applied_mutation_summary") or []:
            target = mutation.get("target") if isinstance(mutation, dict) else None
            if not target or target not in allowed:
                issues.append(f"Session mutation is outside approved envelope: {target}")
            elif target not in current:
                issues.append(f"Session checkpoint target is not present: {target}")
            elif mutation.get("digest") and current[target].get("digest") != mutation.get(
                "digest"
            ):
                checkpoints = set(session.get("checkpoints") or [])
                lock_data = _safe_yaml(root / SKILLS_LOCK)
                project_data = _safe_yaml(root / PROJECT_YAML)
                lock_handoff = (
                    target == SKILLS_LOCK
                    and lock_data.get("authoritative") is True
                    and lock_data.get("skills") == session.get("intended_lock")
                    and "B7_PASSED" in checkpoints
                )
                active_handoff = (
                    target == PROJECT_YAML
                    and project_data.get("lifecycle") == "ACTIVE"
                    and "LOCK_AUTHORITY_ESTABLISHED" in checkpoints
                    and current[target].get("digest")
                    == session.get("expected_active_project_digest")
                )
                if not lock_handoff and not active_handoff:
                    issues.append(
                        f"actual checkpoint digest differs from Session observation: {target}"
                    )
    return sorted(set(issues))


def _excluded_presence_issues(
    baseline_coverage: dict[str, Any],
    current_coverage: dict[str, Any],
    allowed_norm: set[str],
) -> list[str]:
    issues: list[str] = []
    before_roots = {
        _norm_inventory_path(str(row.get("path") or "")): row
        for row in (baseline_coverage.get("roots") or [])
        if isinstance(row, dict) and row.get("classification") == CLASS_EXCLUDED
    }
    after_roots = {
        _norm_inventory_path(str(row.get("path") or "")): row
        for row in (current_coverage.get("roots") or [])
        if isinstance(row, dict) and row.get("classification") == CLASS_EXCLUDED
    }
    for path, before in before_roots.items():
        if not path or _path_allowed(path, allowed_norm):
            continue
        after = after_roots.get(path)
        if before.get("present") is True and (after is None or after.get("present") is not True):
            issues.append(f"excluded root presence changed outside envelope: {path}")
    return issues


def _path_allowed(path: str, allowed_norm: set[str]) -> bool:
    normalized = _norm_inventory_path(path)
    if normalized in allowed_norm:
        return True
    return any(
        normalized == allowed or normalized.startswith(allowed.rstrip("/") + "/")
        for allowed in allowed_norm
        if allowed
    )


def _adoption_progress_proven(
    target: str,
    current: dict[str, str],
    session: dict[str, Any] | None,
    root: Path,
) -> bool:
    if not session:
        return False
    digest = current.get("digest")
    summaries = [
        value
        for value in session.get("applied_mutation_summary") or []
        if isinstance(value, dict) and value.get("target") == target
    ]
    if any(value.get("digest") == digest for value in summaries):
        return True
    expected = (session.get("expected_mutations") or {}).get(target)
    plan_binding = session.get("plan") or {}
    expected_bound = (
        session.get("expected_mutations_plan_id")
        == plan_binding.get("identity")
    )
    if (
        expected_bound
        and isinstance(expected, dict)
        and expected.get("digest") == digest
    ):
        return True
    checkpoints = set(session.get("checkpoints") or [])
    lock_data = _safe_yaml(root / SKILLS_LOCK)
    project_data = _safe_yaml(root / PROJECT_YAML)
    if (
        target == SKILLS_LOCK
        and lock_data.get("authoritative") is True
        and lock_data.get("skills") == session.get("intended_lock")
        and "B7_PASSED" in checkpoints
    ):
        return True
    return bool(
        target == PROJECT_YAML
        and project_data.get("lifecycle") == "ACTIVE"
        and "LOCK_AUTHORITY_ESTABLISHED" in checkpoints
        and digest == session.get("expected_active_project_digest")
    )


def scm_baseline(
    root: Path,
    *,
    budget: InventoryBudget | None = None,
    state: Any = None,
    on_directory: Any = None,
    dir_cache: Any = None,
) -> dict[str, Any]:
    filesystem = _filesystem_baseline(
        root,
        budget=budget,
        counter=state,
        on_directory=on_directory,
        dir_cache=dir_cache,
    )
    nested = _nested_workspaces(
        root,
        budget=budget,
        state=state,
        on_directory=on_directory,
        dir_cache=dir_cache,
    )
    nested_status = nested["status"]
    nested_rows = nested["workspaces"]
    observed = observe_scm(root)
    if observed.kind == "none":
        return {
            "kind": "none",
            "value": None,
            "confidence": "VERIFIED",
            "observation_state": observed.observation_state,
            "observation_ok": True,
            "project_root": ".",
            "scm_root": None,
            "revision": None,
            "branch": None,
            "head_state": "not_applicable",
            "working_tree": "unknown",
            "tracked_changes": "unknown",
            "untracked_changes": "unknown",
            "nested_workspace": nested_status,
            "nested_workspaces": nested_rows,
            "filesystem": filesystem,
        }
    if not observed.ok:
        return {
            "kind": "git",
            "value": None,
            "confidence": "UNKNOWN",
            "observation_state": observed.observation_state,
            "observation_ok": False,
            "project_root": ".",
            "scm_root": observed.scm_root_label,
            "revision": None,
            "branch": None,
            "head_state": "unavailable",
            "working_tree": "unknown",
            "tracked_changes": "unknown",
            "untracked_changes": "unknown",
            "nested_workspace": nested_status,
            "nested_workspaces": nested_rows,
            "filesystem": filesystem,
            "blockers": list(observed.blockers),
        }
    status_entries = list(observed.entries)
    tracked = any(not row.get("untracked") for row in status_entries)
    untracked = any(row.get("untracked") for row in status_entries)
    return {
        "kind": "git",
        "value": observed.revision,
        "confidence": "VERIFIED",
        "observation_state": observed.observation_state,
        "observation_ok": True,
        "project_root": ".",
        "scm_root": observed.scm_root_label,
        "revision": observed.revision,
        "branch": observed.branch,
        "head_state": observed.head_state,
        "working_tree": "dirty" if status_entries else "clean",
        "tracked_changes": "present" if tracked else "absent",
        "untracked_changes": "present" if untracked else "absent",
        "nested_workspace": nested_status,
        "nested_workspaces": nested_rows,
        "filesystem": filesystem,
    }


def _filesystem_baseline(
    root: Path,
    *,
    budget: Any = None,
    counter: Any = None,
    on_directory: Any = None,
    dir_cache: Any = None,
) -> dict[str, Any]:
    inventory = {
        path: value
        for path, value in durable_inventory(
            root,
            budget=budget,
            counter=counter,
            on_directory=on_directory,
            dir_cache=dir_cache,
        ).items()
        if path != PROJECT_YAML
        and isinstance(value, dict)
        and value.get("type") == "file"
    }
    parts = [
        f"{path}\n{value.get('type')}\n{value.get('digest')}"
        for path, value in sorted(inventory.items())
    ]
    return {
        "project_state": "empty" if not inventory else "existing",
        "fingerprint": sha256_text(*parts),
        "file_count": len(inventory),
    }


def _nested_workspaces(
    root: Path,
    *,
    budget: InventoryBudget | None = None,
    state: Any = None,
    on_directory: Any = None,
    dir_cache: Any = None,
) -> dict[str, Any]:
    nested: list[dict[str, str]] = []
    if not root.exists():
        return {
            "status": "absent",
            "workspaces": nested,
            "truncated": False,
            "unknown": False,
        }
    skip_nested = {name for name in EXCLUDED_DIR_NAMES if name != ".git"}
    walked = bounded_metadata_walk(
        root,
        budget=budget or InventoryBudget(),
        skip_dir_names=skip_nested,
        stop_dir_names={".git"},
        state=state,
        on_directory=on_directory,
        dir_cache=dir_cache,
    )
    seen: set[str] = set()
    for rel in list(walked.directories) + list(walked.files):
        if Path(rel).name != ".git":
            continue
        parent = str(Path(rel).parent).replace("\\", "/")
        if parent in {".", ""}:
            continue
        if parent in seen:
            continue
        seen.add(parent)
        nested.append({"path": parent, "kind": "git", "confidence": "VERIFIED"})
    if walked.unknown:
        status = "unknown"
    elif walked.truncated:
        status = "truncated"
    elif nested:
        status = "observed"
    else:
        status = "absent"
    nested.sort(key=lambda row: row["path"])
    return {
        "status": status,
        "workspaces": nested,
        "truncated": walked.truncated,
        "unknown": walked.unknown,
        "entries_enumerated": walked.entries_enumerated,
    }


def _safe_yaml(path: Path) -> dict[str, Any]:
    try:
        value = read_yaml(path)
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def existing_clients(root: Path) -> list[str]:
    found = []
    for rel in CLIENT_HINTS:
        if (root / rel).exists():
            found.append(rel)
    cursor = root / ".cursor" / "rules"
    if cursor.exists():
        found.append(".cursor/rules")
    return found

"""Resolve the Test Contract from tests.yaml + commands.yaml. No invention."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.host_state import inspect_project
from scaffold_p5.io_util import read_yaml
from scaffold_p5.models import FACT_CLASSES
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS

from scaffold_p6.models import (
    ADAPTERS,
    APPLICABILITY,
    COMMANDS_YAML,
    EVIDENCE_KINDS,
    PROJECT_YAML,
    PROVENANCE,
    TESTS_YAML,
    ContractResolution,
    Profile,
)


def inspect_host_project(root: Path) -> tuple[str, list[str], dict[str, Any] | None]:
    path = root / PROJECT_YAML
    if not path.exists():
        return "ABSENT", [], None
    view = inspect_project(path)
    return view.status, list(view.reasons), view.data


def resolve_contract(
    root: Path,
    *,
    project_status: str,
    project: dict[str, Any] | None,
) -> ContractResolution:
    tests_path = root / TESTS_YAML
    active = (
        project_status == "VALID"
        and isinstance(project, dict)
        and project.get("lifecycle") == "ACTIVE"
    )
    if not tests_path.exists():
        if active:
            return ContractResolution(
                status="MISSING_ACTIVE",
                applicability="UNKNOWN",
                confidence="UNKNOWN",
                blockers=["tests.yaml missing on ACTIVE host"],
                route="understand.refresh",
            )
        return ContractResolution(
            status="MISSING",
            applicability="UNKNOWN",
            confidence="UNKNOWN",
            blockers=["tests.yaml is missing; Test cannot invent a contract"],
            route="understand.refresh",
        )

    try:
        raw = read_yaml(tests_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return ContractResolution(
            status="MALFORMED",
            applicability="UNKNOWN",
            confidence="UNKNOWN",
            blockers=["tests.yaml is malformed or unreadable"],
            route="understand.refresh",
        )
    if not isinstance(raw, dict):
        return ContractResolution(
            status="MALFORMED",
            applicability="UNKNOWN",
            confidence="UNKNOWN",
            blockers=["tests.yaml is not a mapping"],
            route="understand.refresh",
        )
    if str(raw.get("schema_version") or "") != "1":
        return ContractResolution(
            status="UNSUPPORTED",
            applicability="UNKNOWN",
            confidence="UNKNOWN",
            blockers=["tests.yaml schema_version is unsupported"],
            route="understand.refresh",
            raw=raw,
        )

    confidence = raw.get("confidence", "UNKNOWN")
    applicability = raw.get("applicability", "UNKNOWN")
    if not isinstance(confidence, str) or confidence not in FACT_CLASSES:
        return _malformed(raw, "tests.yaml confidence is not a legal fact class")
    if not isinstance(applicability, str) or applicability not in APPLICABILITY:
        return _malformed(raw, "tests.yaml applicability is unsupported")
    if "applicable" in raw and not isinstance(raw.get("applicable"), bool):
        return _malformed(raw, "tests.yaml applicable must be a boolean")
    if "required_authority" in raw and raw.get("required_authority") not in FACT_CLASSES:
        return _malformed(raw, "tests.yaml required_authority is not a legal fact class")
    applicable = raw.get("applicable") if isinstance(raw.get("applicable"), bool) else None
    applicable_conflict = _applicable_conflict(applicable, applicability)
    if applicable_conflict:
        return ContractResolution(
            status="CONFLICTING",
            applicability="CONFLICTING",
            confidence=confidence if confidence == "CONFLICTING" else "CONFLICTING",
            blockers=[applicable_conflict],
            route="understand.refresh",
            raw=raw,
        )

    if confidence == "CONFLICTING" or applicability == "CONFLICTING":
        return ContractResolution(
            status="CONFLICTING",
            applicability="CONFLICTING",
            confidence="CONFLICTING",
            blockers=["CONFLICTING Test Contract authority"],
            route="understand.refresh",
            raw=raw,
        )

    commands, command_blockers = _load_commands(root / COMMANDS_YAML)
    if command_blockers:
        return ContractResolution(
            status="MALFORMED",
            applicability=applicability,
            confidence=confidence,
            blockers=command_blockers,
            route="understand.refresh",
            raw=raw,
        )
    profiles_raw = raw.get("profiles")
    if profiles_raw is None:
        profiles_raw = []
    if not isinstance(profiles_raw, list) or any(
        not isinstance(row, dict) for row in profiles_raw
    ):
        return _malformed(raw, "tests.yaml profiles must be a list of mappings")

    profile_issues: list[str] = []
    seen_ids: set[str] = set()
    profiles: list[Profile] = []
    for row in profiles_raw:
        issues = _profile_issues(row)
        profile_id = row.get("id")
        if isinstance(profile_id, str) and profile_id:
            if profile_id in seen_ids:
                issues.append(f"duplicate profile id: {profile_id}")
            seen_ids.add(profile_id)
        if issues:
            profile_issues.extend(issues)
            continue
        profiles.append(Profile(dict(row)))

    if profile_issues:
        return ContractResolution(
            status="MALFORMED",
            applicability=applicability,
            confidence=confidence,
            commands=commands,
            blockers=profile_issues,
            route="understand.refresh",
            raw=raw,
        )

    authority_issues = _required_policy_issues(profiles, confidence)
    applicability_issues = _profile_applicability_issues(profiles)
    if applicability_issues:
        return ContractResolution(
            status="CONFLICTING",
            applicability="CONFLICTING",
            confidence=confidence,
            profiles=profiles,
            required=[p for p in profiles if p.required],
            optional=[p for p in profiles if not p.required],
            commands=commands,
            blockers=applicability_issues,
            route="understand.refresh",
            raw=raw,
        )
    if authority_issues:
        return ContractResolution(
            status="AUTHORITY",
            applicability=applicability,
            confidence=confidence,
            profiles=profiles,
            required=[p for p in profiles if p.required],
            optional=[p for p in profiles if not p.required],
            commands=commands,
            blockers=authority_issues + command_blockers,
            route="understand.refresh",
            raw=raw,
        )

    required = [p for p in profiles if p.required]
    optional = [p for p in profiles if not p.required]

    if applicability == "UNKNOWN" or confidence == "UNKNOWN":
        return ContractResolution(
            status="UNKNOWN",
            applicability="UNKNOWN",
            confidence="UNKNOWN",
            profiles=profiles,
            required=required,
            optional=optional,
            commands=commands,
            blockers=["UNKNOWN Test applicability; not a verified no-test contract"]
            + command_blockers,
            route="understand.refresh",
            raw=raw,
        )

    set_authoritative = _required_set_is_authoritative(
        raw,
        required=required,
        confidence=confidence,
        applicability=applicability,
        authority_issues=authority_issues,
    )
    verified_none = (
        set_authoritative
        and applicability == "NOT_APPLICABLE"
        and raw.get("applicable") is False
        and not required
    )
    if verified_none:
        return ContractResolution(
            status="VERIFIED_NONE",
            applicability="NOT_APPLICABLE",
            confidence="VERIFIED",
            profiles=profiles,
            required=[],
            optional=optional,
            commands=commands,
            verified_no_required=True,
            required_set_authoritative=True,
            raw=raw,
        )

    if applicability == "NOT_APPLICABLE" and required:
        return ContractResolution(
            status="CONFLICTING",
            applicability="CONFLICTING",
            confidence="CONFLICTING",
            profiles=profiles,
            required=required,
            optional=optional,
            commands=commands,
            blockers=["tests.yaml claims NOT_APPLICABLE but declares required profiles"],
            route="understand.refresh",
            raw=raw,
        )

    return ContractResolution(
        status="RESOLVED",
        applicability=applicability,
        confidence=confidence,
        profiles=profiles,
        required=required,
        optional=optional,
        commands=commands,
        blockers=command_blockers,
        route="understand.refresh" if command_blockers else "",
        required_set_authoritative=set_authoritative,
        raw=raw,
    )


def project_blocks_execution(
    status: str,
    reasons: list[str],
    project: dict[str, Any] | None,
) -> list[str]:
    if status == "ABSENT":
        return []
    if status != "VALID":
        return [
            f"project.yaml is {status} and non-executable",
            *reasons,
        ]
    ownership = (project or {}).get("ownership")
    if not isinstance(ownership, dict):
        return ["project.yaml ownership registry is missing"]
    missing = [path for path in CORE_MACHINE_ARTIFACTS if path not in ownership]
    if missing:
        return [f"illegal or incomplete core machine ownership: {', '.join(missing)}"]
    return []


def generated_output_exclusions(root: Path) -> list[str]:
    path = root / TESTS_YAML
    if not path.exists():
        return []
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return []
    if not isinstance(raw, dict):
        return []
    value = raw.get("generated_outputs")
    if value is None:
        value = raw.get("candidate_exclusions")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and not Path(item).is_absolute():
            out.append(item.replace("\\", "/").strip("/"))
    return out


def command_execution_allowed(command: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(command, dict):
        return False, "declared command missing"
    if not command_is_executable(command):
        return False, "declared command is not executable"
    confidence = command.get("confidence")
    if confidence in {"UNKNOWN", "CONFLICTING"}:
        return False, f"command authority is {confidence}"
    if confidence == "INFERRED":
        return True, ""
    if confidence != "VERIFIED":
        return False, "command execution authority is UNKNOWN"
    return True, ""


def command_is_executable(command: dict[str, Any] | None) -> bool:
    if not isinstance(command, dict):
        return False
    argv = command.get("argv")
    return isinstance(argv, list) and all(isinstance(part, str) for part in argv) and bool(argv)


def adapter_supported(name: str) -> bool:
    return name in ADAPTERS


def working_directory_declaration_valid(value: Any) -> tuple[bool, str]:
    if not isinstance(value, str) or not value.strip():
        return False, "working_directory must be a nonempty project-relative path"
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/") or raw.startswith("//"):
        return False, "working_directory must be project-relative"
    if len(value.strip()) >= 2 and value.strip()[1] == ":":
        return False, "working_directory must be project-relative"
    path = Path(raw)
    if path.is_absolute():
        return False, "working_directory must be project-relative"
    if ".." in path.parts:
        return False, "working_directory must not escape the project"
    return True, ""


def resolve_project_working_directory(
    root: Path,
    declared: str | None,
) -> tuple[bool, str, Path | None]:
    raw = declared if declared not in {None, ""} else "."
    ok, reason = working_directory_declaration_valid(raw)
    if not ok:
        return False, reason, None
    host = root.resolve()
    candidate = (host / raw).resolve()
    try:
        candidate.relative_to(host)
    except ValueError:
        return False, "working_directory is not project-bound", None
    if not candidate.exists() or not candidate.is_dir():
        return False, f"required working directory missing: {raw}", None
    return True, "", candidate


def validate_selected(
    selected: Any,
    known_ids: set[str],
) -> tuple[list[str] | None, list[str]]:
    if selected is None:
        return None, []
    if isinstance(selected, str):
        return None, ["selected must be a list of profile ids, not a string"]
    if not isinstance(selected, list):
        return None, ["selected must be a list of unique nonempty profile ids"]
    out: list[str] = []
    seen: set[str] = set()
    for item in selected:
        if not isinstance(item, str) or not item.strip():
            return None, ["selected profile id must be a nonempty string"]
        if item in seen:
            return None, [f"duplicate selected profile id: {item}"]
        if item not in known_ids:
            return None, [f"unknown selected profile id: {item}"]
        seen.add(item)
        out.append(item)
    return out, []


def generated_classification_prefixes(root: Path) -> list[str]:
    path = root / ".scaffold/modules.yaml"
    if not path.exists():
        return []
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("modules")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or row.get("classification") or "").strip().lower()
        if kind != "generated":
            continue
        prefix = str(row.get("path") or "").replace("\\", "/").strip("/")
        if prefix and not Path(prefix).is_absolute():
            out.append(prefix)
    return out


def _applicable_conflict(applicable: bool | None, applicability: str) -> str:
    if applicable is False and applicability == "APPLICABLE":
        return "applicable false contradicts applicability APPLICABLE"
    if applicable is True and applicability == "NOT_APPLICABLE":
        return "applicable true contradicts applicability NOT_APPLICABLE"
    return ""


def _profile_applicability_issues(profiles: list[Profile]) -> list[str]:
    issues: list[str] = []
    for profile in profiles:
        applicability = profile.data.get("applicability")
        if applicability == "NOT_APPLICABLE" and profile.required:
            issues.append(
                f"profile {profile.profile_id} is required and NOT_APPLICABLE"
            )
        if profile.required and applicability in {"UNKNOWN", "CONFLICTING"}:
            issues.append(
                f"profile {profile.profile_id} required applicability is {applicability}"
            )
    return issues


def _malformed(raw: dict[str, Any] | None, message: str) -> ContractResolution:
    return ContractResolution(
        status="MALFORMED",
        applicability="UNKNOWN",
        confidence="UNKNOWN",
        blockers=[message],
        route="understand.refresh",
        raw=raw,
    )


def _profile_issues(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    profile_id = row.get("id")
    if not isinstance(profile_id, str) or not profile_id.strip():
        issues.append("profile id must be a nonempty string")
    if "purpose" in row and not isinstance(row.get("purpose"), str):
        issues.append(f"profile {profile_id!r} purpose must be a string")
    if "required" in row and not isinstance(row.get("required"), bool):
        issues.append(f"profile {profile_id!r} required must be a boolean")
    if "adapter" in row and not isinstance(row.get("adapter"), str):
        issues.append(f"profile {profile_id!r} adapter must be a string")
    if "command_ref" in row and not isinstance(row.get("command_ref"), str):
        issues.append(f"profile {profile_id!r} command_ref must be a string")
    if "working_directory" in row and not isinstance(row.get("working_directory"), str):
        issues.append(f"profile {profile_id!r} working_directory must be a string")
    if "timeout_seconds" in row:
        timeout = row.get("timeout_seconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0:
            issues.append(f"profile {profile_id!r} timeout_seconds must be a non-negative number")
    if "success" in row:
        success = row.get("success")
        if not isinstance(success, dict):
            issues.append(f"profile {profile_id!r} success must be a mapping")
        elif "exit_code" in success:
            code = success.get("exit_code")
            if isinstance(code, bool) or not isinstance(code, int):
                issues.append(f"profile {profile_id!r} success.exit_code must be an integer")
    if "working_directory" in row:
        ok, reason = working_directory_declaration_valid(row.get("working_directory"))
        if not ok:
            issues.append(f"profile {profile_id!r} {reason}")
    if "evidence_required" in row:
        value = row.get("evidence_required")
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            issues.append(f"profile {profile_id!r} evidence_required must be a list of strings")
        elif any(item not in EVIDENCE_KINDS for item in value):
            issues.append(f"profile {profile_id!r} evidence_required contains an unsupported kind")
    if "provenance" in row:
        provenance = row.get("provenance")
        if provenance not in PROVENANCE:
            issues.append(f"profile {profile_id!r} provenance is unsupported")
    if "applicability" in row and row.get("applicability") not in APPLICABILITY:
        issues.append(f"profile {profile_id!r} applicability is unsupported")
    if "confidence" in row and row.get("confidence") not in FACT_CLASSES:
        issues.append(f"profile {profile_id!r} confidence is unsupported")
    if "required_authority" in row and row.get("required_authority") not in FACT_CLASSES:
        issues.append(f"profile {profile_id!r} required_authority is not a legal fact class")
    return issues


def _required_set_is_authoritative(
    raw: dict[str, Any],
    *,
    required: list[Profile],
    confidence: str,
    applicability: str,
    authority_issues: list[str],
) -> bool:
    if authority_issues:
        return False
    if confidence != "VERIFIED" or applicability not in {"APPLICABLE", "NOT_APPLICABLE"}:
        return False
    for profile in required:
        source = (
            profile.data.get("required_authority")
            or profile.data.get("confidence")
            or confidence
        )
        if source != "VERIFIED":
            return False
        if profile.data.get("policy") == "observed" and (
            profile.data.get("required_authority") != "VERIFIED"
        ):
            return False
    declared = raw.get("required_authority")
    if not required:
        return declared == "VERIFIED"
    if declared is not None:
        return declared == "VERIFIED"
    return True


def _required_policy_issues(profiles: list[Profile], contract_confidence: str) -> list[str]:
    issues: list[str] = []
    for profile in profiles:
        if not profile.required:
            continue
        source = (
            profile.data.get("required_authority")
            or profile.data.get("confidence")
            or contract_confidence
        )
        if source in {"UNKNOWN", "CONFLICTING"}:
            issues.append(
                f"profile {profile.profile_id} required-policy authority is {source}"
            )
        elif profile.data.get("policy") == "observed" and (
            profile.data.get("required_authority") != "VERIFIED"
        ):
            issues.append(
                f"profile {profile.profile_id} observed availability is not "
                "an authoritative REQUIRED policy"
            )
        elif source == "INFERRED":
            continue
        elif source != "VERIFIED":
            issues.append(
                f"profile {profile.profile_id} required-policy authority is unresolved"
            )
    return issues


def _load_commands(path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not path.exists():
        return {}, []
    try:
        raw = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {}, ["commands.yaml is malformed or unreadable"]
    if not isinstance(raw, dict):
        return {}, ["commands.yaml is not a mapping"]
    if str(raw.get("schema_version") or "") != "1":
        return {}, ["commands.yaml schema_version is unsupported"]
    rows = raw.get("commands")
    if not isinstance(rows, list):
        return {}, ["commands.yaml commands must be a list"]
    commands: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return {}, ["commands.yaml contains a malformed command"]
        command_id = row.get("id")
        if not isinstance(command_id, str) or not command_id.strip():
            return {}, ["commands.yaml contains a command with an empty id"]
        if command_id in seen:
            return {}, [f"duplicate command id: {command_id}"]
        seen.add(command_id)
        if "confidence" in row and row.get("confidence") not in FACT_CLASSES:
            return {}, [f"command {command_id} confidence is unsupported"]
        commands[command_id] = row
    return commands, []

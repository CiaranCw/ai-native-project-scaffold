"""P6 Test Report / Evidence schema checks. Implementation-owned, not Foundation."""

from __future__ import annotations

from collections import Counter
from typing import Any

from scaffold_p5 import yaml_lite

from scaffold_p6.models import (
    CANONICAL_DEVELOPMENT_RECORDS,
    EVIDENCE_KINDS,
    PROVENANCE,
    RECORD_CLASS,
    REPORT_SCHEMA_VERSION,
    SCENARIO_RESULTS,
    SUPPORT_KIND,
    TERMINAL_USABLE,
)


ID_LIST_FIELDS = (
    "required",
    "optional",
    "selected",
    "executed",
    "terminal_usable",
    "missing_required",
    "blocked_required",
)

REQUIRED_COUNTERS = (
    "required_pass",
    "required_fail",
    "required_blocked",
    "required_not_run",
    "required_terminal_usable",
)

REQUIRED_COMPLETENESS_INTS = (
    "required_total",
    "optional_total",
) + REQUIRED_COUNTERS

REQUIRED_COMPLETENESS_BOOLS = (
    "candidate_match",
    "evidence_complete",
    "batch_evidence_complete",
    "test_pass",
    "test_complete",
    "required_set_authoritative",
)


def validate_report(data: Any) -> tuple[str, list[str]]:
    try:
        return _validate_report(data)
    except (TypeError, ValueError, AttributeError, KeyError):
        return "INCOMPLETE", ["report semantic validation failed on malformed content"]


def _validate_report(data: Any) -> tuple[str, list[str]]:
    if not isinstance(data, dict):
        return "MALFORMED", ["Test Report is not a mapping"]
    issues: list[str] = []
    if str(data.get("schema_version") or "") != REPORT_SCHEMA_VERSION:
        issues.append("report schema_version is unsupported")
    if data.get("kind") != SUPPORT_KIND:
        issues.append("report kind must be test_report")
    if data.get("record_class") != RECORD_CLASS:
        issues.append("report record_class must be support_artifact")
    if data.get("record_class") in CANONICAL_DEVELOPMENT_RECORDS:
        issues.append("Test Report must not claim a canonical development record kind")
    if data.get("submit_authorized") is True:
        issues.append("Test Report must not set submit_authorized")
    if data.get("report_status") != "COMPLETED":
        issues.append("completed report_status must be COMPLETED")
    required = (
        "report_id",
        "skill_id",
        "skill_version",
        "mode",
        "candidate",
        "candidate_match",
        "profiles",
        "completeness",
        "verification",
        "created_at",
    )
    for field in required:
        if field not in data:
            issues.append(f"report missing {field}")
    candidate = data.get("candidate")
    if not isinstance(candidate, dict) or not candidate.get("candidate_digest"):
        issues.append("report candidate binding is missing")
    if not _is_bool(data.get("candidate_match")):
        issues.append("candidate_match must be a boolean")
    profiles_raw = data.get("profiles")
    if not isinstance(profiles_raw, list):
        issues.append("profiles must be a list of profile mappings")
        profiles_raw = []
    for row in profiles_raw:
        if not isinstance(row, dict) or row.get("result") not in SCENARIO_RESULTS:
            issues.append("profile result is not a legal verification result")
            continue
        if not (isinstance(row.get("id"), str) and row.get("id", "").strip()):
            issues.append("profile id must be a nonempty string")
        if not _is_bool(row.get("required")):
            issues.append("profile required must be a boolean")
        if row.get("provenance") not in PROVENANCE and row.get("result") != "NOT_RUN":
            if row.get("provenance"):
                issues.append("profile provenance is unsupported")
        if not _is_bool(row.get("evidence_complete")):
            issues.append("profile evidence_complete must be a boolean")
    completeness = data.get("completeness")
    verification = data.get("verification")
    if not isinstance(completeness, dict):
        issues.append("completeness must be a mapping")
    if not isinstance(verification, dict):
        issues.append("verification must be a mapping")
    if isinstance(completeness, dict):
        issues.extend(_required_completeness_field_issues(completeness))
        issues.extend(_id_list_issues(completeness))
    if isinstance(verification, dict):
        if not _is_bool(verification.get("test_pass")):
            issues.append("verification.test_pass must be a boolean")
        if not _is_bool(verification.get("test_complete")):
            issues.append("verification.test_complete must be a boolean")
    evidence = data.get("evidence")
    if evidence is None:
        evidence = []
    elif not isinstance(evidence, list):
        issues.append("evidence must be a list")
        evidence = []
    seen_evidence: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            issues.append("evidence item is not a mapping")
            continue
        if item.get("provenance") not in PROVENANCE:
            issues.append("unsupported evidence provenance")
        if item.get("kind") not in EVIDENCE_KINDS:
            issues.append("unsupported evidence kind")
        if not item.get("candidate_digest"):
            issues.append("evidence candidate binding is missing")
        if not item.get("profile_id"):
            issues.append("evidence profile binding is missing")
        evidence_id = item.get("evidence_id")
        if evidence_id in seen_evidence:
            issues.append("duplicate evidence id")
        if evidence_id:
            seen_evidence.add(str(evidence_id))
    refs = data.get("evidence_refs")
    if refs is None:
        refs = []
    elif not isinstance(refs, list):
        issues.append("evidence_refs must be a list")
        refs = []
    seen_refs: set[str] = set()
    report_id = data.get("report_id")
    candidate_digest = (
        (candidate or {}).get("candidate_digest") if isinstance(candidate, dict) else None
    )
    for ref in refs:
        if not isinstance(ref, dict):
            issues.append("evidence ref is not a mapping")
            continue
        ref_id = ref.get("ref_id")
        if not (isinstance(ref_id, str) and ref_id.strip()):
            issues.append("evidence ref is missing ref_id")
        if ref_id in seen_refs:
            issues.append("duplicate evidence ref id")
        if ref_id:
            seen_refs.add(str(ref_id))
        if not (isinstance(ref.get("report_id"), str) and ref.get("report_id")):
            issues.append("evidence ref is missing report_id")
        elif ref.get("report_id") != report_id:
            issues.append("evidence ref report_id does not match the report")
        if not (isinstance(ref.get("candidate_digest"), str) and ref.get("candidate_digest")):
            issues.append("evidence ref is missing candidate_digest")
        elif candidate_digest and ref.get("candidate_digest") != candidate_digest:
            issues.append("evidence ref candidate_digest does not match the report candidate")
        if ref.get("resolvable") is True:
            digest = ref.get("digest")
            if not (isinstance(digest, str) and digest.strip()):
                issues.append("resolvable evidence ref requires a digest")
    issues.extend(_semantic_consistency(data))
    if issues:
        return "INCOMPLETE", issues
    return "VALID", []


def _required_completeness_field_issues(completeness: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in REQUIRED_COMPLETENESS_INTS:
        if field not in completeness:
            issues.append(f"completeness missing {field}")
        elif not _is_int(completeness.get(field)):
            issues.append(f"{field} must be an integer")
    for field in REQUIRED_COMPLETENESS_BOOLS:
        if field not in completeness:
            issues.append(f"completeness missing {field}")
        elif not _is_bool(completeness.get(field)):
            issues.append(f"{field} must be a boolean")
    return issues


def _id_list_issues(completeness: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in ID_LIST_FIELDS:
        if field not in completeness:
            issues.append(f"completeness missing {field}")
            continue
        value = completeness.get(field)
        if not isinstance(value, list):
            issues.append(f"completeness.{field} must be a list")
            continue
        if any(not isinstance(item, str) or not item.strip() for item in value):
            issues.append(f"completeness.{field} ids must be nonempty strings")
    return issues


def _semantic_consistency(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    completeness = data.get("completeness")
    verification = data.get("verification")
    if not isinstance(completeness, dict) or not isinstance(verification, dict):
        return issues
    if verification.get("test_pass") != completeness.get("test_pass"):
        issues.append("verification.test_pass does not match completeness.test_pass")
    if verification.get("test_complete") != completeness.get("test_complete"):
        issues.append("verification.test_complete does not match completeness.test_complete")
    if (
        _is_bool(data.get("candidate_match"))
        and _is_bool(completeness.get("candidate_match"))
        and data.get("candidate_match") != completeness.get("candidate_match")
    ):
        issues.append("candidate_match does not match completeness.candidate_match")
    if data.get("candidate_match") is False or completeness.get("candidate_match") is False:
        if completeness.get("test_pass") is True or completeness.get("test_complete") is True:
            issues.append("candidate mismatch cannot yield pass or coverage completeness")
    required_ids = _id_list(completeness, "required")
    optional_ids = _id_list(completeness, "optional")
    if required_ids is not None and optional_ids is not None:
        overlap = set(required_ids) & set(optional_ids)
        if overlap:
            issues.append("profile cannot be both required and optional")
    if required_ids is not None:
        issues.extend(_total_issues(completeness, "required_total", required_ids))
    if optional_ids is not None:
        issues.extend(_total_issues(completeness, "optional_total", optional_ids))
    profiles_raw = data.get("profiles")
    if not isinstance(profiles_raw, list):
        return issues
    profiles = [row for row in profiles_raw if isinstance(row, dict)]
    ids = [row.get("id") for row in profiles]
    counts = Counter(ids)
    if any(counts[key] > 1 for key in counts if key not in {None, ""}):
        issues.append("duplicate profile id")
    if required_ids is not None:
        for required_id in required_ids:
            if counts.get(required_id, 0) != 1:
                issues.append(f"required profile {required_id!r} is missing from profiles")
    if optional_ids is not None:
        for optional_id in optional_ids:
            if counts.get(optional_id, 0) != 1:
                issues.append(f"optional profile {optional_id!r} is missing from profiles")
    issues.extend(_membership_issues(profiles, required_ids, optional_ids))
    results = [row.get("result") for row in profiles]
    if "FAIL" in results and completeness.get("test_pass") is True:
        issues.append("profile FAIL is inconsistent with test_pass true")
    if "BLOCKED" in results and completeness.get("test_pass") is True:
        issues.append("profile BLOCKED is inconsistent with test_pass true")
    required_rows = (
        [row for row in profiles if row.get("id") in required_ids]
        if required_ids is not None
        else []
    )
    if required_ids is not None:
        _check_required_counters(completeness, required_rows, issues)
    batch = [row for row in profiles if row.get("result") != "NOT_RUN"]
    derived_batch_evidence = all(row.get("evidence_complete") is True for row in batch)
    if (
        _is_bool(completeness.get("batch_evidence_complete"))
        and completeness.get("batch_evidence_complete") is not derived_batch_evidence
    ):
        issues.append("batch_evidence_complete does not match executed profile evidence")
    derived_coverage = _derived_required_evidence_complete(required_ids, required_rows)
    if (
        _is_bool(completeness.get("evidence_complete"))
        and completeness.get("evidence_complete") is not derived_coverage
    ):
        issues.append("evidence_complete does not match required profile evidence")
    if completeness.get("test_pass") is True:
        if (
            not batch
            or any(row.get("result") != "PASS" for row in batch)
            or not derived_batch_evidence
            or completeness.get("batch_evidence_complete") is not True
            or data.get("candidate_match") is not True
            or completeness.get("candidate_match") is not True
        ):
            issues.append("test_pass is inconsistent with executed PASS evidence")
    if completeness.get("test_complete") is True:
        if completeness.get("required_set_authoritative") is not True:
            issues.append("test_complete requires authoritative required-set coverage")
        if completeness.get("evidence_complete") is not True or not derived_coverage:
            issues.append("test_complete requires required evidence completeness")
        if required_ids is not None:
            if any(row.get("result") not in TERMINAL_USABLE for row in required_rows):
                issues.append("required BLOCKED/NOT_RUN cannot yield test_complete")
        elif completeness.get("required_set_authoritative") is False:
            issues.append("non-authoritative empty required set cannot yield test_complete")
    return issues


def _membership_issues(
    profiles: list[dict[str, Any]],
    required_ids: list[str] | None,
    optional_ids: list[str] | None,
) -> list[str]:
    if required_ids is None or optional_ids is None:
        return []
    issues: list[str] = []
    required_set = set(required_ids)
    optional_set = set(optional_ids)
    by_id = {
        row.get("id"): row
        for row in profiles
        if isinstance(row.get("id"), str) and row.get("id")
    }
    for row in profiles:
        profile_id = row.get("id")
        if not (isinstance(profile_id, str) and profile_id.strip()) or not _is_bool(
            row.get("required")
        ):
            continue
        in_required = required_ids.count(profile_id)
        in_optional = optional_ids.count(profile_id)
        if row.get("required") is True:
            if in_required != 1 or profile_id in optional_set:
                issues.append(
                    f"required profile {profile_id!r} is not exactly in completeness.required"
                )
        else:
            if in_optional != 1 or profile_id in required_set:
                issues.append(
                    f"optional profile {profile_id!r} is not exactly in completeness.optional"
                )
        if in_required == 0 and in_optional == 0:
            issues.append(f"profile {profile_id!r} belongs to neither required nor optional")
    for required_id in required_ids:
        row = by_id.get(required_id)
        if row is not None and row.get("required") is not True:
            issues.append(f"completeness.required id {required_id!r} is not a required profile")
    for optional_id in optional_ids:
        row = by_id.get(optional_id)
        if row is not None and row.get("required") is not False:
            issues.append(f"completeness.optional id {optional_id!r} is not an optional profile")
    return issues


def _derived_required_evidence_complete(
    required_ids: list[str] | None,
    required_rows: list[dict[str, Any]],
) -> bool:
    if required_ids is None:
        return True
    by_id = {row.get("id"): row for row in required_rows}
    for profile_id in required_ids:
        row = by_id.get(profile_id)
        if row is None or row.get("evidence_complete") is not True:
            return False
    return True


def _id_list(completeness: dict[str, Any], field: str) -> list[str] | None:
    if field not in completeness:
        return None
    value = completeness.get(field)
    if not isinstance(value, list):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return None
    return value


def _total_issues(
    completeness: dict[str, Any],
    field: str,
    ids: list[str],
) -> list[str]:
    if field not in completeness:
        return []
    value = completeness.get(field)
    if not _is_int(value):
        return [f"{field} must be an integer"]
    if value != len(ids):
        return [f"{field} does not match {field.replace('_total', '')}"]
    return []


def _check_required_counters(
    completeness: dict[str, Any],
    required_rows: list[dict[str, Any]],
    issues: list[str],
) -> None:
    actual = {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_RUN": 0}
    for row in required_rows:
        result = row.get("result")
        if result in actual:
            actual[result] += 1
    mapping = (
        ("required_pass", "PASS"),
        ("required_fail", "FAIL"),
        ("required_blocked", "BLOCKED"),
        ("required_not_run", "NOT_RUN"),
    )
    for field, result in mapping:
        if field not in completeness:
            continue
        value = completeness.get(field)
        if not _is_int(value):
            issues.append(f"{field} must be an integer")
        elif value != actual[result]:
            issues.append(f"{field} does not match required profile results")
    if "required_terminal_usable" in completeness:
        value = completeness.get("required_terminal_usable")
        expected = actual["PASS"] + actual["FAIL"]
        if not _is_int(value):
            issues.append("required_terminal_usable must be an integer")
        elif value != expected:
            issues.append("required_terminal_usable does not match required profile results")


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def yaml_safe(value: Any) -> Any:
    """P5 yaml_lite cannot round-trip raw newlines inside scalars."""
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\n", "\\n")
    if isinstance(value, dict):
        return {key: yaml_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [yaml_safe(item) for item in value]
    return value


def roundtrip(data: dict[str, Any]) -> dict[str, Any]:
    return yaml_lite.load(yaml_lite.dump(yaml_safe(data)))


def reports_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return yaml_lite.dump(left) == yaml_lite.dump(right)

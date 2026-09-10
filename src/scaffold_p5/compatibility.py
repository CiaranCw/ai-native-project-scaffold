from __future__ import annotations

from typing import Any

from scaffold_p5.distribution import Distribution
from scaffold_p5.host_state import SKILLS_LOCK, HostSnapshot
from scaffold_p5.models import COMPAT_RESULTS, CORE_SKILLS, LoadedPackage, PackageRef
from scaffold_p5.packages import (
    capability_owner,
    exact_match,
    is_digest,
    is_format_version,
    is_semver,
)
from scaffold_p5.schemas import whole_file_mutation_allowed


def evaluate_package(
    expected: PackageRef,
    actual: LoadedPackage,
    *,
    project: dict[str, Any] | None,
    distribution: Distribution,
    applicable_packages: dict[str, LoadedPackage] | None = None,
) -> dict[str, Any]:
    evidence = _evaluation_evidence(expected, actual, project)
    if actual.validity != "VALID":
        return {
            "validity": "INVALID",
            "result": None,
            "reasons": list(actual.validity_reasons),
            "skill_id": actual.ref.skill_id,
            "expected_version": expected.skill_version,
            "actual_version": actual.ref.skill_version,
            **evidence,
        }
    environment_result, environment_reasons = distribution.environment_issues(
        actual,
        applicable_packages,
    )
    if environment_result:
        return _valid_result(
            environment_result,
            expected,
            actual,
            environment_reasons,
            evidence=evidence,
        )

    host_gen_value = (project or {}).get("project_contract_generation")
    host_gen = str(host_gen_value) if host_gen_value is not None else ""
    supported = [str(x) for x in (actual.manifest.get("contracts") or {}).get("project_contract_generations") or []]
    if supported and not host_gen:
        return _valid_result(
            "UNKNOWN",
            expected,
            actual,
            ["project contract generation is required but unknown"],
        )
    host_generation_satisfied = not supported or host_gen in supported
    requires_migration = bool(actual.manifest.get("requires_host_migration")) and not host_generation_satisfied

    record_result = _record_compatibility(actual, project)
    if record_result:
        result, reasons, cause = record_result
        return _valid_result(
            result,
            expected,
            actual,
            reasons,
            evidence=evidence,
            migration_causes=[cause] if cause else [],
        )

    incompatible_with = [str(x) for x in actual.manifest.get("incompatible_with") or []]
    ok, reasons = exact_match(expected, actual)
    if ok:
        if not host_generation_satisfied:
            return _valid_result(
                "MIGRATION_REQUIRED",
                expected,
                actual,
                [f"host contract {host_gen} not in {supported}"],
                evidence=evidence,
                migration_causes=[_project_generation_cause(host_gen, supported)],
            )
        return _valid_result(
            "EXACT",
            expected,
            actual,
            ["identity and integrity match"],
            evidence=evidence,
        )
    if expected.skill_version in incompatible_with or actual.ref.skill_version in incompatible_with:
        return _valid_result(
            "INCOMPATIBLE",
            expected,
            actual,
            ["package declares incompatibility"],
            evidence=evidence,
        )
    if requires_migration or not host_generation_satisfied:
        return _valid_result(
            "MIGRATION_REQUIRED",
            expected,
            actual,
            ["host persistent Scaffold representation must change"],
            evidence=evidence,
            migration_causes=[_project_generation_cause(host_gen, supported)],
        )
    substitute = _declared_substitute(
        actual,
        expected,
        host_generation_satisfied=host_generation_satisfied,
    )
    if substitute == "COMPATIBLE":
        return _valid_result(
            "COMPATIBLE",
            expected,
            actual,
            ["explicit may_substitute_for declaration; lock unchanged"],
            evidence=evidence,
        )
    if substitute == "UNKNOWN" or not substitute:
        return _valid_result(
            "UNKNOWN",
            expected,
            actual,
            reasons + ["no explicit compatibility declaration; MUST NOT guess"],
            evidence=evidence,
        )
    return _valid_result("UNKNOWN", expected, actual, reasons, evidence=evidence)


def _pending_core_requirement_owners(
    package: LoadedPackage,
    *,
    self_id: str,
    applicable_packages: dict[str, LoadedPackage],
    closed_owners: set[str],
) -> set[str]:
    pending: set[str] = set()
    known = set(applicable_packages) | set(closed_owners)
    for requirement in package.manifest.get("requires") or []:
        owner = capability_owner(str(requirement))
        if owner in CORE_SKILLS and owner != self_id and owner not in known:
            pending.add(owner)
    return pending


def resolve_established_host_actual(
    expected: PackageRef,
    *,
    distribution: Distribution,
    project: dict[str, Any] | None,
    applicable_packages: dict[str, LoadedPackage],
    closed_owners: set[str] | None = None,
) -> tuple[LoadedPackage | None, str, list[str]]:
    """Resolve lock expected identity against available Distribution packages.

    Exact identity has priority. A unique explicit COMPATIBLE substitute may
    be selected only when the exact package is absent. Multiple eligible
    substitutes are UNKNOWN. INVALID packages never become COMPATIBLE.
    A uniquely resolved intrinsically VALID package that is not COMPATIBLE
    remains VALID and is returned for compatibility evaluation. Absence of
    any same-skill package remains a resolution blocker. Core capability
    owners that are not yet bound are deferred rather than treated as a
    final environment miss.
    """
    exact = distribution.index.resolve_exact(expected)
    if exact is not None:
        return exact, "exact", []
    closed = set(closed_owners or ())
    compatible: list[LoadedPackage] = []
    valid: list[LoadedPackage] = []
    invalid: list[LoadedPackage] = []
    deferred = False
    for package in distribution.index.find(expected.skill_id):
        if package.validity != "VALID":
            invalid.append(package)
            continue
        valid.append(package)
        pending = _pending_core_requirement_owners(
            package,
            self_id=expected.skill_id,
            applicable_packages=applicable_packages,
            closed_owners=closed,
        )
        if pending:
            deferred = True
            continue
        provision = dict(applicable_packages)
        provision[expected.skill_id] = package
        row = evaluate_package(
            expected,
            package,
            project=project,
            distribution=distribution,
            applicable_packages=provision,
        )
        if row.get("validity") == "VALID" and row.get("result") == "COMPATIBLE":
            compatible.append(package)
    if len(compatible) == 1 and not deferred:
        return compatible[0], "compatible", []
    if len(compatible) > 1:
        return None, "ambiguous", [
            f"{expected.skill_id} has multiple compatible substitutions; MUST NOT guess"
        ]
    if deferred:
        return None, "deferred", [
            f"{expected.skill_id} waits for unresolved core capability owners"
        ]
    if len(compatible) == 1:
        return compatible[0], "compatible", []
    if len(valid) == 1:
        return valid[0], "valid", []
    if len(valid) > 1:
        return None, "ambiguous", [
            f"{expected.skill_id} has multiple valid non-exact packages; MUST NOT guess"
        ]
    if invalid:
        reasons = list(invalid[0].validity_reasons) or [
            f"{expected.skill_id} substitution package is INVALID"
        ]
        return invalid[0], "invalid", reasons
    return None, "missing", [
        f"{expected.skill_id} exact lock package/input cannot be resolved"
    ]


def evaluate_host(snapshot: HostSnapshot, distribution: Distribution) -> dict[str, Any]:
    if not snapshot.project_view.valid:
        return {
            "ok": False,
            "blockers": [
                "project.yaml concrete schema is not executable"
            ]
            + list(snapshot.project_view.reasons),
            "results": {},
            "overall": None,
            "project_observation": snapshot.project_view.status,
        }
    if not snapshot.lock.complete_authoritative or not snapshot.lock.data:
        return {
            "ok": False,
            "blockers": ["partial/malformed/absent lock is not ordinary compatibility authority"]
            + snapshot.lock.reasons,
            "results": {},
        }
    skills = snapshot.lock.data.get("skills") or {}
    results = {}
    blockers = []
    expected_refs: dict[str, PackageRef] = {}
    actual_packages: dict[str, LoadedPackage] = {}
    for skill_id in CORE_SKILLS:
        entry = skills[skill_id]
        expected = PackageRef(
            skill_id=skill_id,
            skill_version=str(entry["skill_version"]),
            package_digest=str(entry["package_digest"]),
            package_format_version=str(entry.get("package_format_version") or "1"),
        )
        expected_refs[skill_id] = expected
        if skill_id == "understand":
            actual_packages[skill_id] = distribution.actual_understand
            continue
        exact = distribution.index.resolve_exact(expected)
        if exact is not None:
            actual_packages[skill_id] = exact
    closed_owners = set(actual_packages)
    unresolved = [skill_id for skill_id in CORE_SKILLS if skill_id not in actual_packages]
    while unresolved:
        still: list[str] = []
        progress = False
        for skill_id in unresolved:
            expected = expected_refs[skill_id]
            resolved, status, resolve_reasons = resolve_established_host_actual(
                expected,
                distribution=distribution,
                project=snapshot.project,
                applicable_packages=actual_packages,
                closed_owners=closed_owners,
            )
            if status == "deferred":
                still.append(skill_id)
                continue
            progress = True
            closed_owners.add(skill_id)
            if status == "ambiguous":
                blockers.extend(resolve_reasons)
                results[skill_id] = {
                    "validity": "VALID",
                    "result": "UNKNOWN",
                    "reasons": list(resolve_reasons),
                    "skill_id": skill_id,
                    "expected_version": expected.skill_version,
                    "actual_version": None,
                }
                continue
            if resolved is None:
                blockers.extend(resolve_reasons)
                results[skill_id] = {
                    "validity": "INVALID",
                    "result": None,
                    "reasons": list(resolve_reasons),
                    "skill_id": skill_id,
                    "expected_version": expected.skill_version,
                }
                continue
            if status == "invalid":
                blockers.append(f"{skill_id} package INVALID")
                results[skill_id] = {
                    "validity": "INVALID",
                    "result": None,
                    "reasons": list(resolve_reasons) or list(resolved.validity_reasons),
                    "skill_id": skill_id,
                    "expected_version": expected.skill_version,
                    "actual_version": resolved.ref.skill_version,
                }
                continue
            actual_packages[skill_id] = resolved
        if not progress:
            for skill_id in still:
                reason = (
                    f"{skill_id} cannot be resolved until core dependency owners "
                    "are available; MUST NOT guess"
                )
                blockers.append(reason)
                expected = expected_refs[skill_id]
                results[skill_id] = {
                    "validity": "VALID",
                    "result": "UNKNOWN",
                    "reasons": [reason],
                    "skill_id": skill_id,
                    "expected_version": expected.skill_version,
                    "actual_version": None,
                }
            break
        unresolved = still
    graph_issues = (
        distribution.graph_issues(actual_packages)
        if len(actual_packages) == len(CORE_SKILLS)
        else []
    )
    blockers.extend(graph_issues)
    for skill_id in CORE_SKILLS:
        if skill_id not in actual_packages:
            continue
        actual = actual_packages[skill_id]
        expected = expected_refs[skill_id]
        results[skill_id] = evaluate_package(
            expected,
            actual,
            project=snapshot.project,
            distribution=distribution,
            applicable_packages=actual_packages,
        )
        if results[skill_id]["validity"] == "INVALID":
            blockers.append(f"{skill_id} package INVALID")
    overall = None if graph_issues else _overall(results)
    valid = not any(row.get("validity") == "INVALID" for row in results.values())
    return {
        "ok": valid and not blockers,
        "blockers": blockers,
        "results": results,
        "overall": overall,
    }


def lock_update_plan(
    snapshot: HostSnapshot,
    distribution: Distribution,
    new_expected: dict[str, dict[str, str]],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    old: dict[str, dict[str, str]] = {}
    skills = (snapshot.lock.data or {}).get("skills") or {}
    for skill_id, entry in skills.items():
        old[skill_id] = {
            "skill_version": entry.get("skill_version"),
            "package_digest": entry.get("package_digest"),
            "package_format_version": entry.get("package_format_version"),
        }
    blockers: list[str] = []
    if not snapshot.project_view.valid:
        blockers.extend(
            ["project.yaml concrete schema blocks lock-update planning"]
            + list(snapshot.project_view.reasons)
        )
    else:
        allowed, reason = whole_file_mutation_allowed(
            (snapshot.project or {}).get("ownership"),
            SKILLS_LOCK,
        )
        if not allowed:
            blockers.append(reason)
    if not isinstance(new_expected, dict) or not new_expected:
        blockers.append("lock update must contain at least one core Skill target")
        new_expected = {}
    illegal = sorted(set(new_expected) - set(CORE_SKILLS))
    if illegal:
        blockers.append("lock update contains non-core Skill ids: " + ",".join(illegal))
    final_skills = {
        skill_id: dict(entry)
        for skill_id, entry in skills.items()
        if skill_id in CORE_SKILLS and isinstance(entry, dict)
    }
    change_results: dict[str, dict[str, Any]] = {}
    normalized_targets: dict[str, dict[str, str]] = {}
    target_packages: dict[str, LoadedPackage] = {}
    old_refs: dict[str, PackageRef] = {}
    for skill_id, raw in new_expected.items():
        if skill_id not in CORE_SKILLS:
            continue
        if not isinstance(raw, dict):
            blockers.append(f"{skill_id} lock-update target must be a mapping")
            continue
        version = str(raw.get("skill_version") or "")
        digest = str(raw.get("package_digest") or "")
        package_format = str(raw.get("package_format_version") or "")
        if not is_semver(version):
            blockers.append(f"{skill_id} target has invalid exact semantic version")
        if not is_digest(digest):
            blockers.append(f"{skill_id} target has invalid package digest")
        hits = distribution.index.find(skill_id, version, digest)
        if len(hits) != 1:
            blockers.append(f"{skill_id} target identity is not uniquely resolvable")
            continue
        package = hits[0]
        if package.validity != "VALID":
            blockers.append(
                f"{skill_id} target package is INVALID: "
                + "; ".join(package.validity_reasons)
            )
            continue
        if package_format and package_format != package.ref.package_format_version:
            blockers.append(f"{skill_id} target package_format_version mismatch")
            continue
        package_format = package.ref.package_format_version
        if not is_format_version(package_format):
            blockers.append(f"{skill_id} target package format is invalid")
            continue
        target = {
            "skill_version": version,
            "package_digest": digest,
            "package_format_version": package_format,
        }
        normalized_targets[skill_id] = target
        final_skills[skill_id] = target
        target_packages[skill_id] = package
        old_entry = skills.get(skill_id) or {}
        old_refs[skill_id] = PackageRef(
            skill_id=skill_id,
            skill_version=str(old_entry.get("skill_version") or ""),
            package_digest=str(old_entry.get("package_digest") or ""),
            package_format_version=str(old_entry.get("package_format_version") or ""),
        )
    if set(final_skills) != set(CORE_SKILLS):
        blockers.append("final lock would not contain exactly four core Skills")
    final_packages: dict[str, LoadedPackage] = {}
    for skill_id, entry in final_skills.items():
        ref = PackageRef(
            skill_id=skill_id,
            skill_version=str(entry.get("skill_version") or ""),
            package_digest=str(entry.get("package_digest") or ""),
            package_format_version=str(entry.get("package_format_version") or ""),
        )
        package = target_packages.get(skill_id) or distribution.index.resolve_exact(ref)
        if package is None:
            blockers.append(f"{skill_id} final lock package is not exactly resolvable")
        else:
            final_packages[skill_id] = package
    if len(final_packages) == len(CORE_SKILLS):
        blockers.extend(distribution.graph_issues(final_packages))
    for skill_id, package in target_packages.items():
        change_results[skill_id] = evaluate_package(
            old_refs[skill_id],
            package,
            project=snapshot.project,
            distribution=distribution,
            applicable_packages=final_packages,
        )
    final_actual_packages = dict(final_packages)
    if "understand" not in target_packages:
        final_actual_packages["understand"] = distribution.actual_understand
    final_results: dict[str, dict[str, Any]] = {}
    if len(final_actual_packages) == len(CORE_SKILLS):
        blockers.extend(distribution.graph_issues(final_actual_packages))
        for skill_id in CORE_SKILLS:
            entry = final_skills.get(skill_id) or {}
            expected = PackageRef(
                skill_id=skill_id,
                skill_version=str(entry.get("skill_version") or ""),
                package_digest=str(entry.get("package_digest") or ""),
                package_format_version=str(
                    entry.get("package_format_version") or ""
                ),
            )
            row = evaluate_package(
                expected,
                final_actual_packages[skill_id],
                project=snapshot.project,
                distribution=distribution,
                applicable_packages=final_actual_packages,
            )
            final_results[skill_id] = row
            if row.get("validity") != "VALID" or row.get("result") in {
                "INCOMPATIBLE",
                "UNKNOWN",
                "MIGRATION_REQUIRED",
            }:
                blockers.append(
                    f"{skill_id} proposed final lock compatibility is "
                    f"{row.get('result') or row.get('validity')}"
                )
    migration_required = any(
        row.get("result") == "MIGRATION_REQUIRED" for row in change_results.values()
    )
    results = [row.get("result") for row in change_results.values() if row.get("result")]
    compatibility = _aggregate_results(results)
    blockers = sorted(set(blockers))
    body = {
        "kind": "lock_update",
        "old_expected": old,
        "new_expected": normalized_targets,
        "final_skills": final_skills,
        "compatibility": compatibility,
        "change_results": change_results,
        "final_results": final_results,
        "migration_required": migration_required,
        "reason": "explicit expected-version change; not implied by mere execution success",
        "valid": not blockers,
        "blockers": blockers,
    }
    from scaffold_p5.io_util import sha256_text
    from scaffold_p5 import yaml_lite

    body["digest"] = sha256_text(yaml_lite.dump({k: v for k, v in body.items() if k != "digest"}))
    return body


def _declared_substitute(
    actual: LoadedPackage,
    expected: PackageRef,
    *,
    host_generation_satisfied: bool,
) -> str | None:
    for entry in actual.may_substitute_for:
        if str(entry.get("skill_id") or actual.ref.skill_id) != expected.skill_id:
            continue
        if str(entry.get("skill_version")) != expected.skill_version:
            continue
        if entry.get("requires_host_migration") and not host_generation_satisfied:
            return "MIGRATION_REQUIRED"
        return "COMPATIBLE"
    return None


def _valid_result(
    result: str,
    expected: PackageRef,
    actual: LoadedPackage,
    reasons: list[str],
    *,
    evidence: dict[str, Any] | None = None,
    migration_causes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if result not in COMPAT_RESULTS:
        raise ValueError("compatibility result must stay in the five-value taxonomy")
    row = {
        "validity": "VALID",
        "result": result,
        "reasons": reasons,
        "skill_id": actual.ref.skill_id,
        "expected_version": expected.skill_version,
        "actual_version": actual.ref.skill_version,
        "expected_digest": expected.package_digest,
        "actual_digest": actual.ref.package_digest,
    }
    row.update(evidence or {})
    row["migration_causes"] = migration_causes or []
    return row


def _overall(results: dict[str, dict[str, Any]]) -> str | None:
    if any(row.get("validity") == "INVALID" for row in results.values()):
        return None
    order = ["INCOMPATIBLE", "UNKNOWN", "MIGRATION_REQUIRED", "COMPATIBLE", "EXACT"]
    present = [row["result"] for row in results.values() if row.get("result")]
    for item in order:
        if item in present:
            return item
    return present[0] if present else None


def _record_compatibility(
    actual: LoadedPackage,
    project: dict[str, Any] | None,
) -> tuple[str, list[str], dict[str, Any] | None] | None:
    requirements = (project or {}).get("record_schema_requirements") or {}
    if not isinstance(requirements, dict):
        return "UNKNOWN", ["record schema requirements are malformed"], None
    supported = (
        (actual.manifest.get("contracts") or {}).get("record_schema_capabilities") or {}
    )
    for kind, required in requirements.items():
        available = supported.get(kind)
        if available is None:
            return "UNKNOWN", [f"record schema capability for {kind} is undeclared"], None
        if str(required) not in [str(value) for value in available]:
            return (
                "MIGRATION_REQUIRED",
                [f"record schema {kind}@{required} requires host migration"],
                {
                    "kind": "record_schema",
                    "record_kind": str(kind),
                    "required_generation": str(required),
                    "package_capabilities": sorted(str(value) for value in available),
                    "supported_by_bounded_action": False,
                },
            )
    return None


def _evaluation_evidence(
    expected: PackageRef,
    actual: LoadedPackage,
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    contracts = actual.manifest.get("contracts") or {}
    supported_project = sorted(
        {str(value) for value in contracts.get("project_contract_generations") or []}
    )
    record_capabilities = contracts.get("record_schema_capabilities") or {}
    normalized_capabilities = {
        str(kind): sorted({str(value) for value in values or []})
        for kind, values in sorted(record_capabilities.items())
        if isinstance(values, list)
    }
    record_requirements = (project or {}).get("record_schema_requirements") or {}
    normalized_requirements = (
        {
            str(kind): str(value)
            for kind, value in sorted(record_requirements.items())
        }
        if isinstance(record_requirements, dict)
        else {}
    )
    return {
        "expected_package": _package_identity(expected),
        "actual_package": _package_identity(actual.ref),
        "evaluation_inputs": {
            "project_contract_generation": str(
                (project or {}).get("project_contract_generation") or ""
            ),
            "supported_project_contract_generations": supported_project,
            "requires_host_migration": bool(
                actual.manifest.get("requires_host_migration")
            ),
            "record_schema_requirements": normalized_requirements,
            "record_schema_capabilities": normalized_capabilities,
        },
    }


def _package_identity(ref: PackageRef) -> dict[str, str]:
    return {
        "skill_id": ref.skill_id,
        "skill_version": ref.skill_version,
        "package_digest": ref.package_digest,
        "package_format_version": ref.package_format_version,
    }


def _project_generation_cause(
    current: str,
    supported: list[str],
) -> dict[str, Any]:
    return {
        "kind": "project_contract_generation",
        "current_generation": current,
        "supported_target_generations": sorted(set(supported)),
        "supported_by_bounded_action": bool(supported),
    }


def _aggregate_results(results: list[str]) -> str | None:
    for value in ("INCOMPATIBLE", "UNKNOWN", "MIGRATION_REQUIRED", "COMPATIBLE", "EXACT"):
        if value in results:
            return value
    return None


def migration_need(evaluation: dict[str, Any]) -> dict[str, Any]:
    """Validity-first migration inspector. INVALID is never MIGRATION_REQUIRED."""
    rows = evaluation.get("results") or {}
    invalid = any(
        isinstance(row, dict) and row.get("validity") == "INVALID"
        for row in rows.values()
    )
    blockers = list(evaluation.get("blockers") or [])
    if invalid or evaluation.get("overall") is None and not evaluation.get("ok"):
        reasons = list(blockers)
        for row in rows.values():
            if isinstance(row, dict) and row.get("validity") == "INVALID":
                reasons.extend(str(item) for item in (row.get("reasons") or []) if item)
        return {
            "needed": False,
            "validity": "INVALID",
            "compatibility": None,
            "reasons": reasons,
            "migration_causes": [],
        }
    overall = evaluation.get("overall")
    causes: list[dict[str, Any]] = []
    reasons: list[str] = []
    for skill_id, row in rows.items() if isinstance(rows, dict) else []:
        if not isinstance(row, dict):
            continue
        if row.get("result") == "MIGRATION_REQUIRED":
            reasons.extend(str(item) for item in (row.get("reasons") or []) if item)
            for cause in row.get("migration_causes") or []:
                if isinstance(cause, dict):
                    annotated = dict(cause)
                    annotated.setdefault("skill_id", skill_id)
                    causes.append(annotated)
    if overall in {"EXACT", "COMPATIBLE"}:
        return {
            "needed": False,
            "validity": "VALID",
            "compatibility": overall,
            "reasons": [],
            "migration_causes": [],
        }
    if overall == "MIGRATION_REQUIRED":
        return {
            "needed": True,
            "validity": "VALID",
            "compatibility": "MIGRATION_REQUIRED",
            "reasons": reasons or blockers,
            "migration_causes": causes,
        }
    return {
        "needed": False,
        "validity": "VALID",
        "compatibility": overall,
        "reasons": reasons or blockers,
        "migration_causes": causes,
    }

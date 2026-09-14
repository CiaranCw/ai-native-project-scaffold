"""S5 Test Completeness. Uses published P6 reports. TEST_PASS != TEST_COMPLETE."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p6.models import TESTS_YAML


def evaluate_completeness(
    root: Path,
    *,
    task: dict[str, Any] | None,
    report: dict[str, Any] | None,
    invoke: bool,
    selected: list[str] | None,
    test_package: Path,
    report_id: str | None = None,
) -> dict[str, Any]:
    task_payload = task or {}
    task_requirements = _task_requirements(task_payload)
    task_required_ids = sorted({
        row["requirement_id"] for row in task_requirements
    })
    project_required_ids = _project_required_ids(root)
    required_ids = sorted(set(task_required_ids) | set(project_required_ids))
    candidate = observe_candidate(root)
    engine = TestEngine(root, test_package)
    used_report: dict[str, Any] | None = None
    diagnostic_report_id: str | None = None
    consumption_stale = False
    invoked = None
    trust_blockers: list[str] = []
    if report is not None:
        if report_id or invoke:
            trust_blockers.append(
                "raw Test report input conflicts with an authoritative report source"
            )
        else:
            trust_blockers.append(
                "raw caller-supplied Test report is untrusted; provide report_id"
            )
    elif invoke and report_id:
        trust_blockers.append(
            "invoke_test and report_id are ambiguous authoritative report sources"
        )
    elif invoke:
        invoked = engine.run(
            "scoped_verification",
            selected=selected or project_required_ids,
            task_id=task_payload.get("record_id"),
            scope_paths=list((task_payload.get("scope") or {}).get("paths") or []),
            scope_modules=list((task_payload.get("scope") or {}).get("modules") or []),
        )
        extras = getattr(invoked, "extras", {}) or {}
        invoked_id = extras.get("report_id") if isinstance(extras, dict) else None
        if isinstance(invoked_id, str) and invoked_id:
            consumed = _consume_published_report_for_task(
                engine,
                invoked_id,
                task_payload,
                trust_blockers,
            )
            used_report = consumed["authorized"]
            diagnostic_report_id = consumed.get("report_id")
            consumption_stale = bool(consumed.get("stale"))
        if used_report is None and not trust_blockers:
            trust_blockers.append(
                "invoked Test did not yield a validated published completed report"
            )
    elif report_id:
        consumed = _consume_published_report_for_task(
            engine,
            str(report_id),
            task_payload,
            trust_blockers,
        )
        used_report = consumed["authorized"]
        diagnostic_report_id = consumed.get("report_id")
        consumption_stale = bool(consumed.get("stale"))
        if used_report is None and not trust_blockers:
            trust_blockers.append(
                "completed Test report identity is missing, incomplete, or invalid"
            )

    usable = bool(used_report) and engine.report_usable_for_current(used_report)
    completeness = (used_report or {}).get("completeness") if used_report else {}
    if not isinstance(completeness, dict):
        completeness = {}

    stale = bool(consumption_stale or (used_report is not None and not usable))
    test_pass = bool(usable and completeness.get("test_pass") is True)
    report_required_fail = (
        int(completeness.get("required_fail") or 0) if usable else 0
    )
    if "coverage_complete" in completeness:
        coverage_complete = bool(
            usable and completeness.get("coverage_complete") is True
        )
    else:
        coverage_complete = bool(
            usable
            and completeness.get("required_set_authoritative") is True
            and completeness.get("required_not_run") == 0
            and completeness.get("required_blocked") == 0
        )
    test_complete = bool(usable and completeness.get("test_complete") is True)
    if report_required_fail:
        test_complete = False
    if completeness.get("required_set_authoritative") is not True:
        test_complete = False
    report_zero_required = bool(
        usable
        and completeness.get("required_set_authoritative") is True
        and completeness.get("required_total") == 0
        and completeness.get("verified_no_required_tests") is True
    )
    if not used_report or trust_blockers:
        test_complete = False
        test_pass = False
        coverage_complete = False

    task_coverage = _task_coverage(engine, candidate, task_requirements)
    project_coverage = _project_coverage(
        used_report if usable else None,
        project_required_ids,
    )
    fail_profile_ids = set(project_coverage["failed"])
    for row in task_requirements:
        if row["requirement_id"] in task_coverage["failed"]:
            profile_id = _automated_profile_id(row)
            if profile_id:
                fail_profile_ids.add(profile_id)
    required_fail_ids = sorted(
        set(task_coverage["failed"]) | set(project_coverage["failed"])
    )
    required_fail = max(report_required_fail, len(required_fail_ids))
    uncovered_required_ids = sorted(
        set(task_coverage["uncovered"])
        | set(task_coverage["incomplete"])
        | set(project_coverage["uncovered"])
        | set(project_coverage["incomplete"])
    )
    coverage_blockers = (
        list(task_coverage["blockers"]) + list(project_coverage["blockers"])
    )
    if report_zero_required and required_ids:
        coverage_blockers.append(
            "authoritative zero-required report conflicts with derived required obligations"
        )
    obligations_complete = bool(
        not required_fail
        and not uncovered_required_ids
        and not coverage_blockers
        and set(task_required_ids) <= set(task_coverage["proven"])
        and set(project_required_ids) <= set(project_coverage["proven"])
    )
    test_complete = bool(test_complete and obligations_complete)
    zero_required = bool(report_zero_required and not required_ids)

    evidence_refs: list[dict[str, str]] = []
    if usable and used_report:
        evidence_refs.extend(
            engine.build_evidence_refs(str(used_report.get("report_id") or ""))
        )
    evidence_refs.extend(task_coverage["evidence_refs"])
    evidence_refs = _unique_evidence_refs(evidence_refs)

    route = ""
    if stale:
        route = "test.scoped_verification"
    elif required_fail:
        route = "develop.repair"
    elif not used_report or not test_complete:
        route = "test.scoped_verification"

    return {
        "test_pass": test_pass,
        "test_complete": test_complete,
        "coverage_complete": coverage_complete,
        "required_fail": required_fail,
        "required_ids": required_ids,
        "stale_report": stale,
        "usable": usable,
        "zero_required": zero_required,
        "report": used_report,
        "report_id": diagnostic_report_id or (used_report or {}).get("report_id"),
        "evidence_refs": evidence_refs,
        "invoke_result": invoked,
        "route": route,
        "candidate_digest": candidate.digest,
        "task_required_ids": task_required_ids,
        "project_required_ids": project_required_ids,
        "proven_required_ids": sorted(
            set(task_coverage["proven"]) | set(project_coverage["proven"])
        ),
        "uncovered_required_ids": uncovered_required_ids,
        "required_fail_ids": required_fail_ids,
        "required_fail_profile_ids": sorted(fail_profile_ids),
        "blockers": sorted(set(trust_blockers + coverage_blockers)),
    }


def _consume_published_report_for_task(
    engine: TestEngine,
    report_id: str,
    task: dict[str, Any],
    trust_blockers: list[str],
) -> dict[str, Any]:
    """Canonical P6 consumption: authority verdict plus diagnostic identity.

    Possession of a published report object is not Task authority.
    """
    live = task if str((task or {}).get("record_id") or "").strip() else None
    consumed = engine.consume_published_report(report_id, task=live)
    blockers = [str(item) for item in (consumed.get("blockers") or []) if item]
    diagnostic = consumed.get("report") if isinstance(consumed.get("report"), dict) else None
    authorized = diagnostic if consumed.get("ok") is True and diagnostic is not None else None
    if authorized is None:
        trust_blockers.extend(blockers)
    diagnostic_id = consumed.get("report_id")
    if not diagnostic_id and diagnostic is not None:
        diagnostic_id = diagnostic.get("report_id")
    stale = bool(
        diagnostic is not None
        and authorized is None
        and any("stale for the current candidate" in item for item in blockers)
    )
    return {
        "authorized": authorized,
        "diagnostic": diagnostic,
        "report_id": diagnostic_id,
        "stale": stale,
    }


def _task_requirements(task: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in task.get("final_tests") or []:
        if isinstance(item, dict) and item.get("requirement_id"):
            out.append({**item, "requirement_id": str(item["requirement_id"])})
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict) and item.get("requirement_id"):
                out.append({**item, "requirement_id": str(item["requirement_id"])})
    return out


def _project_required_ids(root: Path) -> list[str]:
    ids: list[str] = []
    tests_path = root / TESTS_YAML
    if tests_path.is_file():
        try:
            data = read_yaml(tests_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            data = {}
        for profile in (data or {}).get("profiles") or []:
            if isinstance(profile, dict) and profile.get("required") is True:
                if profile.get("id"):
                    ids.append(str(profile["id"]))
    return sorted(set(ids))


def _task_coverage(
    engine: TestEngine,
    candidate,
    requirements: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in requirements:
        grouped.setdefault(str(row["requirement_id"]), []).append(row)
    proven: list[str] = []
    failed: list[str] = []
    incomplete: list[str] = []
    uncovered: list[str] = []
    blockers: list[str] = []
    evidence_refs: list[dict[str, str]] = []
    for requirement_id, rows in grouped.items():
        locators = {
            str((row.get("evidence_ref") or {}).get("locator") or "")
            for row in rows
            if isinstance(row.get("evidence_ref"), dict)
            and (row.get("evidence_ref") or {}).get("locator")
        }
        outcomes = {
            str(row.get("observed_outcome"))
            for row in rows
            if row.get("observed_outcome") is not None
        }
        if len(locators) != 1:
            uncovered.append(requirement_id)
            reason = (
                "has no P6 Evidence locator"
                if not locators
                else "has conflicting P6 Evidence locators"
            )
            blockers.append(f"Task requirement {requirement_id!r} {reason}")
            continue
        if len(outcomes) > 1:
            uncovered.append(requirement_id)
            blockers.append(
                f"Task requirement {requirement_id!r} has conflicting observed outcomes"
            )
            continue
        locator = next(iter(locators))
        resolved, issues = engine.resolve_evidence(locator)
        if resolved is None:
            uncovered.append(requirement_id)
            blockers.extend(
                f"Task requirement {requirement_id!r}: {issue}" for issue in issues
            )
            continue
        bound_profile = _automated_profile_id(rows[0])
        producer = _resolved_profile_id(resolved)
        if bound_profile and producer != bound_profile:
            uncovered.append(requirement_id)
            blockers.append(
                f"Task requirement {requirement_id!r} Evidence producer "
                "does not match execution_binding.profile_id"
            )
            continue
        report = resolved.get("report")
        if not isinstance(report, dict) or not engine.report_usable_for_current(report):
            uncovered.append(requirement_id)
            blockers.append(
                f"Task requirement {requirement_id!r} Evidence is stale for the current candidate"
            )
            continue
        result = str(resolved.get("result") or "")
        if outcomes:
            observed = next(iter(outcomes))
            expected = {
                "PASS": "PASS",
                "FAIL": "FAIL",
                "NOT_EXECUTED": "NOT_RUN",
                "UNKNOWN": "BLOCKED",
            }.get(observed)
            if expected != result:
                uncovered.append(requirement_id)
                blockers.append(
                    f"Task requirement {requirement_id!r} observed_outcome "
                    "does not match resolved P6 Evidence"
                )
                continue
        evidence_refs.append({"locator": locator})
        if result == "FAIL":
            failed.append(requirement_id)
        elif result == "PASS" and resolved.get("evidence_complete") is True:
            proven.append(requirement_id)
        else:
            incomplete.append(requirement_id)
            blockers.append(
                f"Task requirement {requirement_id!r} is not satisfactorily complete"
            )
    return {
        "proven": proven,
        "failed": failed,
        "incomplete": incomplete,
        "uncovered": uncovered,
        "blockers": blockers,
        "evidence_refs": evidence_refs,
    }


def _project_coverage(
    report: dict[str, Any] | None,
    required_ids: list[str],
) -> dict[str, list[str]]:
    profiles = {
        str(row.get("id")): row
        for row in (report or {}).get("profiles") or []
        if isinstance(row, dict) and row.get("id")
    }
    proven: list[str] = []
    failed: list[str] = []
    incomplete: list[str] = []
    uncovered: list[str] = []
    blockers: list[str] = []
    for profile_id in required_ids:
        row = profiles.get(profile_id)
        if not isinstance(row, dict) or row.get("required") is not True:
            uncovered.append(profile_id)
            blockers.append(
                f"project-required Test profile {profile_id!r} is absent from the validated report"
            )
            continue
        if row.get("result") == "FAIL":
            failed.append(profile_id)
        elif row.get("result") == "PASS" and row.get("evidence_complete") is True:
            proven.append(profile_id)
        else:
            incomplete.append(profile_id)
            blockers.append(
                f"project-required Test profile {profile_id!r} is not satisfactorily complete"
            )
    return {
        "proven": proven,
        "failed": failed,
        "incomplete": incomplete,
        "uncovered": uncovered,
        "blockers": blockers,
    }


def _unique_evidence_refs(
    refs: list[dict[str, str]],
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for ref in refs:
        locator = str(ref.get("locator") or "") if isinstance(ref, dict) else ""
        if locator and locator not in seen:
            seen.add(locator)
            out.append({"locator": locator})
    return out


def _automated_profile_id(item: dict[str, Any]) -> str:
    binding = item.get("execution_binding")
    if not isinstance(binding, dict):
        return ""
    if binding.get("kind") != "test_profile":
        return ""
    profile_id = binding.get("profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    return ""


def _resolved_profile_id(resolved: dict[str, Any]) -> str:
    profile_id = resolved.get("profile_id")
    if isinstance(profile_id, str) and profile_id.strip():
        return profile_id.strip()
    profile = resolved.get("profile")
    if isinstance(profile, dict) and profile.get("id"):
        return str(profile["id"])
    return ""

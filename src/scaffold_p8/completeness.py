"""S5 Test Completeness. Uses published P6 reports. TEST_PASS != TEST_COMPLETE."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.engine import TestEngine
from scaffold_p6.models import TESTS_YAML


def evaluate_completeness(
    root: Path,
    *,
    task: dict[str, Any],
    report: dict[str, Any] | None,
    invoke: bool,
    selected: list[str] | None,
    test_package: Path,
) -> dict[str, Any]:
    required_ids = _required_ids(root, task)
    candidate = observe_candidate(root)
    used_report = report
    invoked = None
    if invoke:
        engine = TestEngine(root, test_package)
        invoked = engine.run(
            "scoped_verification",
            selected=selected or required_ids,
            task_book=task.get("record_id"),
        )
        extras = getattr(invoked, "extras", {}) or {}
        used_report = extras.get("report") if isinstance(extras, dict) else None
        if not isinstance(used_report, dict):
            used_report = None

    usable = bool(used_report) and report_usable_for(used_report, candidate)
    completeness = (used_report or {}).get("completeness") if used_report else {}
    if not isinstance(completeness, dict):
        completeness = {}

    stale = bool(used_report) and not usable
    test_pass = bool(usable and completeness.get("test_pass") is True)
    test_complete = bool(usable and completeness.get("test_complete") is True)
    required_fail = int(completeness.get("required_fail") or 0) if usable else 0
    coverage_complete = bool(
        usable
        and completeness.get("required_set_authoritative") is True
        and completeness.get("required_not_run") == 0
        and completeness.get("required_blocked") == 0
    )
    zero_required = bool(
        usable
        and completeness.get("required_set_authoritative") is True
        and completeness.get("required_total") == 0
        and completeness.get("verified_no_required_tests") is True
    )
    if not used_report:
        test_complete = False
        test_pass = False
        coverage_complete = False

    route = ""
    if stale:
        route = "test.scoped_verification"
    elif not used_report or not test_complete:
        if required_ids:
            route = "test.scoped_verification"

    return {
        "test_pass": test_pass,
        "test_complete": test_complete,
        "coverage_complete": coverage_complete or test_complete,
        "required_fail": required_fail,
        "required_ids": required_ids,
        "stale_report": stale,
        "usable": usable,
        "zero_required": zero_required,
        "report": used_report,
        "report_id": (used_report or {}).get("run_id")
        or (used_report or {}).get("record_id"),
        "invoke_result": invoked,
        "route": route,
        "candidate_digest": candidate.digest,
    }


def _required_ids(root: Path, task: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in task.get("final_tests") or []:
        if isinstance(item, dict) and item.get("requirement_id"):
            ids.append(str(item["requirement_id"]))
    for stage in task.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict) and item.get("requirement_id"):
                ids.append(str(item["requirement_id"]))
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

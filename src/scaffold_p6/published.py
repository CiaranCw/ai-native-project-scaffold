"""Load a durable published P6 report as Test authority. Does not re-execute."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.result import skill_result
from scaffold_p6.candidate import observe_candidate, report_usable_for
from scaffold_p6.models import SKILL_ID, SKILL_VERSION
from scaffold_p6.sav import evaluate_sav_coverage, reconstruct_sav_plan
from scaffold_p6.storage import load_completed_report, run_dir


def consume_published_report(
    root: str | Path,
    report_id: str,
    *,
    task: dict[str, Any] | None = None,
    skill_version: str = "",
    requirement_id: str = "",
) -> dict[str, Any]:
    """Independently load and revalidate a published P6 report by id."""
    host = Path(root)
    blockers: list[str] = []
    if not isinstance(report_id, str) or not report_id.strip():
        return {
            "ok": False,
            "blockers": ["published Test report_id is missing"],
            "report": None,
        }
    report_id = report_id.strip()
    dest = run_dir(host, report_id)
    report_path = dest / "report.yaml"
    if not dest.is_dir() or not report_path.is_file():
        return {
            "ok": False,
            "blockers": ["published Test report is missing"],
            "report": None,
        }
    report = load_completed_report(host, report_id)
    if report is None:
        return {
            "ok": False,
            "blockers": ["published Test report is malformed, incomplete, or invalid"],
            "report": None,
        }
    refs = report.get("optional_refs") if isinstance(report.get("optional_refs"), dict) else {}
    bound_task = str(refs.get("task_book") or "").strip()
    live_task = str((task or {}).get("record_id") or "").strip()
    if bound_task and live_task and bound_task != live_task:
        blockers.append(
            "published Test report is bound to a different Task Book"
        )
    candidate = observe_candidate(host)
    if not candidate.usable:
        blockers.extend(
            list(candidate.data.get("blockers") or ["current candidate is unusable"])
        )
    if report.get("candidate_match") is not True:
        blockers.append("published Test report candidate_match is not true")
    stale_diagnostic: dict[str, Any] | None = None
    if not report_usable_for(report, candidate):
        blockers.append("published Test report is stale for the current candidate")
        stale_diagnostic = {
            "current_candidate_digest": candidate.digest,
            "evidence_candidate_digest": str(
                (
                    (report.get("candidate") or {}).get("candidate_digest")
                    if isinstance(report.get("candidate"), dict)
                    else ""
                )
                or ""
            ),
            "evidence_report_id": str(report.get("report_id") or ""),
            "remediation": (
                "re-run Test against the current candidate and rebind the "
                "published report; do not rewrite historical decisions or "
                "delete historical evidence"
            ),
        }

    completeness = report.get("completeness") if isinstance(report.get("completeness"), dict) else {}
    sav_payload = completeness.get("sav") if isinstance(completeness.get("sav"), dict) else {}
    if sav_payload.get("applied"):
        sav_blockers = _revalidate_published_sav(
            host,
            report,
            sav_payload,
            task=task,
            candidate_digest=candidate.digest,
            requested_requirement_id=requirement_id,
        )
        blockers.extend(sav_blockers)

    ok = not blockers
    return {
        "ok": ok,
        "blockers": blockers,
        "report": report,
        "report_id": report.get("report_id"),
        "test_pass": bool(completeness.get("test_pass") is True) if ok else False,
        "test_complete": bool(completeness.get("test_complete") is True) if ok else False,
        "candidate_match": report.get("candidate_match") is True,
        "sav": sav_payload,
        "evidence": list(report.get("evidence") or []),
        **({"stale_evidence": stale_diagnostic} if stale_diagnostic else {}),
    }


def published_report_skill_result(
    loaded: dict[str, Any],
    *,
    skill_version: str = "",
) -> Any:
    report = loaded.get("report") if isinstance(loaded.get("report"), dict) else None
    extras = {
        "test_pass": loaded.get("test_pass"),
        "test_complete": loaded.get("test_complete"),
        "coverage_complete": ((report or {}).get("completeness") or {}).get(
            "coverage_complete"
        ),
        "completeness": (report or {}).get("completeness") or {},
        "report_id": loaded.get("report_id"),
        "consumed_published_report": True,
        "sav": loaded.get("sav") or {},
        "candidate_match": loaded.get("candidate_match"),
    }
    if loaded.get("stale_evidence"):
        extras["stale_evidence"] = loaded["stale_evidence"]
    if report is not None:
        extras["report"] = report
    outcome = "COMPLETED" if loaded.get("ok") else "BLOCKED"
    return skill_result(
        skill_id=SKILL_ID,
        skill_version=skill_version or SKILL_VERSION,
        mode="scoped_verification",
        outcome=outcome,
        mutations="none",
        blockers=list(loaded.get("blockers") or []),
        next_route="" if loaded.get("ok") else "test.scoped_verification",
        extras=extras,
    )


def _revalidate_published_sav(
    host: Path,
    report: dict[str, Any],
    sav_payload: dict[str, Any],
    *,
    task: dict[str, Any] | None,
    candidate_digest: str,
    requested_requirement_id: str = "",
) -> list[str]:
    refs = report.get("optional_refs") if isinstance(report.get("optional_refs"), dict) else {}
    reconstruction = sav_payload.get("reconstruction") if isinstance(sav_payload.get("reconstruction"), dict) else {}
    task_id = str(
        reconstruction.get("task_id")
        or sav_payload.get("task_id")
        or refs.get("task_book")
        or (task or {}).get("record_id")
        or ""
    ).strip()
    bound_requirement = str(
        reconstruction.get("requirement_id")
        or sav_payload.get("requirement_id")
        or ""
    ).strip()
    requested = str(requested_requirement_id or "").strip()
    if requested and bound_requirement and requested != bound_requirement:
        return ["published SAV report is bound to a different Requirement"]
    if requested and not bound_requirement:
        return ["published SAV report lacks exact Requirement identity"]
    requirement_id = bound_requirement or requested
    if sav_payload.get("applied") and (not task_id or not requirement_id):
        return ["published SAV report cannot be revalidated without exact Task/requirement identity"]
    if not task_id or not requirement_id:
        if sav_payload.get("required"):
            return ["published SAV report cannot be revalidated without Task/requirement identity"]
        return []
    reconstructed = reconstruct_sav_plan(
        host, task_id=task_id, requirement_id=requirement_id, task=task
    )
    if not reconstructed.get("current"):
        return list(
            reconstructed.get("blockers")
            or ["published SAV plan is not current applicable Test authority"]
        )
    coverage = evaluate_sav_coverage(
        reconstructed.get("plan") or {},
        evidence=list(report.get("evidence") or []),
        profile_results=_profile_results(report),
        candidate_digest=candidate_digest,
    )
    if sav_payload.get("requirement_pass") and not coverage.get("requirement_pass"):
        return ["published SAV requirement_pass is not current against the loaded report"]
    return []


def _profile_results(report: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in report.get("profiles") or []:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = str(row.get("result") or "")
    return out

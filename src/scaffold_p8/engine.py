"""Submit Skill orchestration. Reviews the real candidate. Does not become Develop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.packages import load_package
from scaffold_p5.result import skill_result
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p7.tasks import resolve_task, task_complete

from scaffold_p8.authorization import check_push_authorized, check_submit_authorized
from scaffold_p8.cleanup import cleanup_sessions
from scaffold_p8.completeness import evaluate_completeness
from scaffold_p8.delta import classify_delta, load_sealed_sessions, observe_real_diff
from scaffold_p8.finalize import finalize_s10
from scaffold_p8.handoff import build_repair_handoff
from scaffold_p8.knowledge import evaluate_knowledge
from scaffold_p8.models import PROVIDES, REQUIRES, SKILL_ID
from scaffold_p8.preflight import (
    SubmitPreflight,
    evaluate_submit_preflight,
    inspect_host_project,
)
from scaffold_p8.push import push_if_authorized
from scaffold_p8.records import (
    build_change_record,
    new_change_id,
    persist_candidate_change,
    scm_base_value,
)
from scaffold_p8.structural import missing_scoped_source, review_structure


class SubmitEngine:
    def __init__(self, host_root: str | Path, package_root: str | Path | None = None):
        self.root = Path(host_root)
        self.package_root = (
            Path(package_root) if package_root else default_submit_package()
        )
        self.skill_version = ""
        self.preflight: SubmitPreflight | None = None
        if self.package_root.exists():
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version

    def run(self, mode: str = "", **opts: Any):
        if mode not in {"", "submit"}:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="FAILED",
                blockers=[f"Submit has no extra top-level mode {mode!r}"],
                next_route="stop",
                extras=self._capability_extras(),
            )
        if opts.get("writes"):
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="BLOCKED",
                blockers=["Submit must not silently edit source as Develop"],
                next_route="stop",
                extras=self._capability_extras(),
            )

        project_status, _reasons, project = inspect_host_project(self.root)
        self.preflight = evaluate_submit_preflight(
            self.root,
            package_root=self.package_root,
            project=project,
            project_status=project_status,
        )
        self.skill_version = self.preflight.skill_version or self.skill_version
        candidate = observe_candidate(self.root)
        if not self.preflight.allowed:
            return self._blocked(
                list(self.preflight.blockers),
                self.preflight.route or "understand.compatibility",
                candidate=candidate,
                project=project,
            )

        caller_prose = opts.get("task_text", opts.get("goal_override"))
        resolved = resolve_task(
            self.root,
            task_id=opts.get("task_id"),
            caller_prose=caller_prose,
        )
        if not resolved.ok or resolved.task is None:
            return self._blocked(
                resolved.blockers,
                resolved.route or "stop",
                candidate=candidate,
                project=project,
            )
        task = resolved.task
        if task.get("status") != "READY_FOR_REVIEW":
            return self._blocked(
                [
                    f"Task Book status {task.get('status')!r} is incompatible with "
                    "Submit; READY_FOR_REVIEW is required"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )

        linked_session_ids = {
            str(item) for item in (task.get("develop_session_ids") or [])
        }
        sessions = load_sealed_sessions(
            self.root, linked_ids=linked_session_ids
        )
        real_diff = observe_real_diff(self.root)
        if not real_diff.get("ok"):
            return self._blocked(
                list(real_diff.get("blockers") or ["real Diff is UNKNOWN"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S2", "real_diff": real_diff},
            )
        real_paths = list(real_diff.get("paths") or [])
        delta = classify_delta(
            self.root,
            real_paths=real_paths,
            sessions=sessions,
            entries=list(real_diff.get("entries") or []),
        )

        existing = {str(path.relative_to(self.root)).replace("\\", "/") for path in self.root.rglob("*") if path.is_file()}
        missing_source = missing_scoped_source(existing, task)
        structural = review_structure(
            task=task, real_paths=real_paths, project=project
        )
        if missing_source:
            structural = dict(structural)
            structural["structural_review_pass"] = False
            structural["repair_required"] = list(missing_source)
            handoff = build_repair_handoff(
                task_id=str(task["record_id"]),
                candidate_digest=observe_candidate(self.root).digest,
                blockers=[
                    "substantive repair required; scoped source is missing: "
                    + ", ".join(missing_source)
                ],
            )
            return self._blocked(
                handoff["blockers"],
                "develop.repair",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S3",
                    "repair_handoff": handoff,
                    "delta": delta,
                    "structural": structural,
                },
            )
        if not structural.get("structural_review_pass"):
            return self._blocked(
                list(structural.get("blockers") or ["structural review blocked"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S3", "delta": delta, "structural": structural},
            )

        knowledge = evaluate_knowledge(
            project=project,
            maintenance=list(self.preflight.maintenance),
        )
        if knowledge.get("route") == "understand.compatibility":
            return self._blocked(
                ["knowledge/compatibility is stale or conflicting"],
                "understand.compatibility",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S4", "knowledge": knowledge},
            )
        if knowledge.get("stale"):
            return self._blocked(
                ["stale project knowledge requires Understand refresh"],
                "understand.refresh",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S4", "knowledge": knowledge},
            )
        after_s4 = opts.get("after_s4")
        if callable(after_s4):
            after_s4()
            refreshed = observe_candidate(self.root)
            if refreshed.digest != candidate.digest:
                return self._blocked(
                    [
                        "material knowledge/candidate change invalidates prior "
                        "review state; return to S3"
                    ],
                    "submit",
                    candidate=refreshed,
                    project=project,
                    task=task,
                    extras={
                        "stage": "S8",
                        "loop": "S8→S3/S4/S5/S6",
                        "prior_candidate": candidate.digest,
                        "current_candidate": refreshed.digest,
                        "submit_authorized": False,
                    },
                )

        report = opts.get("report")
        if opts.get("report_id") and report is None:
            report = TestEngine(
                self.root, Path(opts["test_package"]) if opts.get("test_package") else default_test_package()
            ).load_report(str(opts["report_id"]))
        completeness = evaluate_completeness(
            self.root,
            task=task,
            report=report if isinstance(report, dict) else None,
            invoke=bool(opts.get("invoke_test")),
            selected=list(opts.get("selected") or []),
            test_package=Path(opts["test_package"])
            if opts.get("test_package")
            else default_test_package(),
        )
        if completeness.get("stale_report"):
            return self._blocked(
                ["Test report is not usable for the current candidate"],
                "test.scoped_verification",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S5", "completeness": _public_completeness(completeness)},
            )
        want_s10 = bool(opts.get("request_s10") or opts.get("finalize"))
        if (
            want_s10
            and completeness.get("route") == "test.scoped_verification"
            and not completeness.get("test_complete")
        ):
            return self._blocked(
                ["required-test coverage is incomplete; Submit routes to Test"],
                "test.scoped_verification",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S5", "completeness": _public_completeness(completeness)},
            )

        reviewed = observe_candidate(self.root)
        authorized, auth_reason = check_submit_authorized(
            opts.get("submit_authorized"),
            current_digest=reviewed.digest,
        )
        if opts.get("request_s10") or opts.get("finalize"):
            if not authorized:
                return self._blocked(
                    [auth_reason or "SUBMIT_AUTHORIZED is missing"],
                    "human",
                    candidate=reviewed,
                    project=project,
                    task=task,
                    extras={
                        "stage": "S6",
                        "ready_for_human_approval": True,
                        "submit_authorized": False,
                        "completeness": _public_completeness(completeness),
                    },
                )

        sync_hook = opts.get("before_s7") or opts.get("repository_sync")
        if callable(sync_hook):
            sync_hook()
        synced = observe_candidate(self.root)
        if synced.digest != reviewed.digest:
            return self._blocked(
                [
                    "material Repository Sync candidate change invalidates "
                    "S6 authorization; return to S3"
                ],
                "submit",
                candidate=synced,
                project=project,
                task=task,
                extras={
                    "stage": "S8",
                    "loop": "S8→S3/S4/S5/S6",
                    "prior_candidate": reviewed.digest,
                    "current_candidate": synced.digest,
                    "submit_authorized": False,
                    "repair_handoff": None,
                },
            )

        if not want_s10:
            next_route = "caller"
            if not completeness.get("test_complete"):
                next_route = "test.scoped_verification"
            elif not authorized:
                next_route = "human"
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="COMPLETED",
                baseline=synced.data,
                mutations="none",
                next_route=next_route,
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=self._result_extras(
                    task=task,
                    candidate=synced,
                    project=project,
                    delta=delta,
                    structural=structural,
                    knowledge=knowledge,
                    completeness=completeness,
                    authorized=authorized,
                    stage="S6",
                ),
            )

        if not task_complete(task):
            return self._blocked(
                ["TASK_COMPLETE does not hold; S10 is blocked"],
                "stop",
                candidate=synced,
                project=project,
                task=task,
            )
        if not completeness.get("test_complete"):
            return self._blocked(
                ["TEST_COMPLETE does not hold; S10 is blocked"],
                "test.scoped_verification",
                candidate=synced,
                project=project,
                task=task,
                extras={"completeness": _public_completeness(completeness)},
            )
        if completeness.get("required_fail"):
            return self._blocked(
                [
                    "required FAIL can yield TEST_COMPLETE coverage but cannot "
                    "enter S10 finalization"
                ],
                "develop.repair",
                candidate=synced,
                project=project,
                task=task,
                extras={
                    "stage": "S5",
                    "completeness": _public_completeness(completeness),
                    "repair_handoff": build_repair_handoff(
                        task_id=str(task["record_id"]),
                        candidate_digest=synced.digest,
                        blockers=["required test FAIL"],
                    ),
                },
            )
        if not completeness.get("test_pass") and completeness.get("required_ids"):
            return self._blocked(
                ["TEST_PASS does not hold for required tests; S10 is blocked"],
                "stop",
                candidate=synced,
                project=project,
                task=task,
                extras={"completeness": _public_completeness(completeness)},
            )

        record_id = str(opts.get("change_id") or new_change_id(self.root))
        kind, base_value = scm_base_value(self.root)
        record = build_change_record(
            record_id=record_id,
            task=task,
            real_paths=real_paths,
            delta=delta,
            structural=structural,
            knowledge=knowledge,
            completeness=completeness,
            candidate_kind=kind,
            baseline_value=base_value,
            diff_entries=list(real_diff.get("entries") or []),
            relevant_session_count=len(sessions),
        )
        persisted, persist_blockers, change_path = persist_candidate_change(
            self.root, record
        )
        if not persisted or change_path is None:
            return self._blocked(
                persist_blockers,
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S9", "s10": {"ok": False, "durable": False}},
            )
        after_s9 = observe_candidate(self.root)
        s9_digest = after_s9.digest
        before_s10 = opts.get("before_s10")
        if callable(before_s10):
            before_s10()
        if opts.get("fail_s10"):
            return self._blocked(
                ["S10 failed; Change Record remains a non-durable candidate"],
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S10",
                    "change_record": record,
                    "s9_durable": False,
                    "s10": {"ok": False, "durable": False},
                    "mutations": "change_record",
                },
                mutations="change_record",
            )
        s10 = finalize_s10(
            self.root,
            record_id=record_id,
            change_rel=change_path.relative_to(self.root).as_posix(),
            reviewed_paths=real_paths,
            expected_digest=s9_digest,
            scm_kind=kind if (self.root / ".git").exists() else "none",
            expected_parent=base_value if kind == "git" else None,
            reviewed_entries=list(real_diff.get("entries") or []),
            after_commit=opts.get("after_s10_commit"),
        )
        if not s10.get("ok"):
            if s10.get("durable"):
                return self._durable_but_blocked(
                    s10,
                    record=record,
                    change_path=change_path,
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    delta=delta,
                    structural=structural,
                    knowledge=knowledge,
                    completeness=completeness,
                )
            return self._blocked(
                list(s10.get("blockers") or ["S10 failed"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S10",
                    "change_record": record,
                    "s9_durable": False,
                    "s10": s10,
                    "s10_durable": False,
                    "durable_finalization_occurred": False,
                    "post_finalization_verification": "not_started",
                },
                mutations="change_record",
            )

        push_ok, _push_reason = check_push_authorized(
            opts.get("push_authorized"),
            current_digest=reviewed.digest,
        )
        before_s11 = opts.get("before_s11")
        if callable(before_s11):
            before_s11()
        push = push_if_authorized(
            self.root,
            authorized=push_ok,
            scm_kind=s10.get("kind") or "none",
            s10_ok=True,
            expected_commit=s10.get("commit"),
            expected_branch=s10.get("branch"),
            simulate_failure=bool(opts.get("fail_push")),
        )
        cleanup = cleanup_sessions(self.root, task=task, s10_ok=True)
        final_candidate = observe_candidate(self.root)
        s11_unresolved = bool(push_ok) and not push.get("ok")
        extras = self._result_extras(
            task=task,
            candidate=final_candidate,
            project=project,
            delta=delta,
            structural=structural,
            knowledge=knowledge,
            completeness=completeness,
            authorized=True,
            stage=(
                "S11"
                if s11_unresolved
                else ("S12" if cleanup.get("performed") else "S10")
            ),
        )
        extras.update(
            {
                "change_record": record,
                "s9_durable": False,
                "s10": s10,
                "s10_durable": True,
                "push": push,
                "cleanup": cleanup,
                "submit_authorized": True,
            }
        )
        if s11_unresolved:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="BLOCKED",
                baseline=final_candidate.data,
                mutations="change_record",
                artifacts=[change_path.as_posix()],
                blockers=[
                    str(
                        push.get("reason")
                        or "authorized S11 could not publish the exact S10 target"
                    )
                ],
                next_route="human",
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=extras,
            )
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="COMPLETED",
            baseline=final_candidate.data,
            mutations="change_record",
            artifacts=[change_path.as_posix()],
            next_route="caller",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _durable_but_blocked(
        self,
        s10: dict[str, Any],
        *,
        record: dict[str, Any],
        change_path: Path,
        candidate,
        project: dict[str, Any] | None,
        task: dict[str, Any] | None,
        delta: dict[str, Any],
        structural: dict[str, Any],
        knowledge: dict[str, Any],
        completeness: dict[str, Any],
    ):
        extras = self._result_extras(
            task=task,
            candidate=candidate,
            project=project,
            delta=delta,
            structural=structural,
            knowledge=knowledge,
            completeness=completeness,
            authorized=False,
            stage="S10",
        )
        extras.update(
            {
                "change_record": record,
                "s9_durable": False,
                "s10": s10,
                "s10_durable": True,
                "durable_finalization_occurred": True,
                "post_finalization_verification": "unresolved",
                "push": {"performed": False, "ok": False, "reason": "S11 cannot start while S10 post-Commit verification is unresolved"},
                "cleanup": {
                    "performed": False,
                    "cleaned": [],
                    "retained": [],
                    "reason": "normal S12 cleanup cannot run while S10 post-Commit verification is unresolved",
                },
                "submit_authorized": False,
                "capabilities": {
                    "commit": False,
                    "push": False,
                    "submit_authorized": False,
                },
            }
        )
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode="",
            outcome="BLOCKED",
            baseline=candidate.data if candidate is not None else None,
            mutations="durable_finalization",
            artifacts=[change_path.as_posix()],
            blockers=list(s10.get("blockers") or ["S10 post-Commit verification is unresolved"]),
            next_route="human",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _blocked(
        self,
        blockers: list[str],
        route: str,
        *,
        candidate=None,
        project: dict[str, Any] | None = None,
        task: dict[str, Any] | None = None,
        extras: dict[str, Any] | None = None,
        mutations: str = "none",
    ):
        payload = self._result_extras(
            task=task,
            candidate=candidate,
            project=project,
            authorized=False,
        )
        if extras:
            payload.update(extras)
        payload["submit_authorized"] = False
        payload.setdefault("s10", {"ok": False, "durable": False})
        payload.setdefault("submit_authorized", False)
        payload["capabilities"] = {
            "commit": False,
            "push": False,
            "submit_authorized": False,
        }
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode="",
            outcome="BLOCKED",
            baseline=candidate.data if candidate is not None else None,
            mutations=mutations,
            blockers=blockers,
            next_route=route,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=payload,
        )

    def _result_extras(
        self,
        *,
        task: dict[str, Any] | None,
        candidate,
        project: dict[str, Any] | None,
        delta: dict[str, Any] | None = None,
        structural: dict[str, Any] | None = None,
        knowledge: dict[str, Any] | None = None,
        completeness: dict[str, Any] | None = None,
        authorized: bool = False,
        stage: str = "S1",
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {
            "package": {
                "skill_id": SKILL_ID,
                "skill_version": self.skill_version,
                "modes": [],
                "provides": list(PROVIDES),
                "requires": list(REQUIRES),
            },
            "stage": stage,
            "stages": [
                "S1",
                "S2",
                "S3",
                "S4",
                "S5",
                "S6",
                "S7",
                "S8",
                "S9",
                "S10",
                "S11",
                "S12",
            ],
            "task_complete": task_complete(task) if task else False,
            "ready_for_review": bool(task and task.get("status") == "READY_FOR_REVIEW"),
            "submit_authorized": bool(authorized),
            "submit_authorized_persisted": False,
            "s10": {"ok": False, "durable": False},
            "capabilities": {
                "commit": False,
                "push": False,
                "submit_authorized": False,
            },
        }
        if self.preflight is not None:
            extras.update(self.preflight.extras())
        if task is not None:
            extras["task"] = {
                "record_id": task.get("record_id"),
                "status": task.get("status"),
                "record_revision": task.get("record_revision"),
            }
        if candidate is not None:
            extras["candidate"] = {
                "candidate_digest": candidate.digest,
                "kind": candidate.kind,
            }
        extras["project_reference"] = {
            "name": (project or {}).get("name"),
            "lifecycle": (project or {}).get("lifecycle"),
        }
        if delta is not None:
            extras["delta"] = {
                "paths": list(delta.get("paths") or []),
                "counts": delta.get("counts"),
                "session_memory_overridden": delta.get("session_memory_overridden"),
                "attribution_complete": delta.get("attribution_complete"),
                "classes": delta.get("classes"),
                "entries": delta.get("entries"),
            }
        if structural is not None:
            extras["structural"] = {
                "structural_review_pass": structural.get("structural_review_pass"),
                "blockers": structural.get("blockers"),
                "repair_required": structural.get("repair_required"),
            }
        if knowledge is not None:
            extras["knowledge"] = knowledge
        if completeness is not None:
            extras["completeness"] = _public_completeness(completeness)
            extras["test_pass"] = completeness.get("test_pass")
            extras["test_complete"] = completeness.get("test_complete")
        extras["repair_handoff"] = None
        extras["push"] = {"performed": False}
        extras["cleanup"] = {"performed": False, "cleaned": []}
        return extras

    def _capability_extras(self) -> dict[str, Any]:
        return {
            "submit_authorized": False,
            "capabilities": {
                "commit": False,
                "push": False,
                "submit_authorized": False,
            },
        }


def default_submit_package() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "submit"


def default_test_package() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "test"


def _public_completeness(completeness: dict[str, Any]) -> dict[str, Any]:
    return {
        "test_pass": completeness.get("test_pass"),
        "test_complete": completeness.get("test_complete"),
        "coverage_complete": completeness.get("coverage_complete"),
        "required_fail": completeness.get("required_fail"),
        "required_ids": completeness.get("required_ids"),
        "stale_report": completeness.get("stale_report"),
        "usable": completeness.get("usable"),
        "zero_required": completeness.get("zero_required"),
        "report_id": completeness.get("report_id"),
        "route": completeness.get("route"),
    }

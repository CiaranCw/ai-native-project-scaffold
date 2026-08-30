"""Develop Skill orchestration. Mutates source under Task Book + ownership authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.packages import load_package
from scaffold_p5.result import skill_result
from scaffold_p6.candidate import observe_candidate, report_usable_for

from scaffold_p7.handoff import (
    build_develop_to_test,
    build_submit_route,
    build_test_to_develop,
    invoke_test,
    validate_repair_handoff,
)
from scaffold_p7.models import DEVELOP_MODES, PROVIDES, REQUIRES, SKILL_ID
from scaffold_p7.mutation import apply_writes, authorize_writes, overlay_path_set
from scaffold_p7.preflight import (
    DevelopPreflight,
    evaluate_develop_preflight,
    inspect_host_project,
)
from scaffold_p7.session import (
    abort_session,
    create_session,
    load_session,
    persist_session,
    seal_session,
)
from scaffold_p7.tasks import (
    apply_session_progress,
    mode_compatible,
    persist_ready_for_review,
    publish_task,
    ready_for_review_gates,
    resolve_task,
    task_complete,
    task_revision,
)


class DevelopEngine:
    def __init__(self, host_root: str | Path, package_root: str | Path | None = None):
        self.root = Path(host_root)
        self.package_root = (
            Path(package_root) if package_root else default_develop_package()
        )
        self.skill_version = ""
        self.package_validity = "UNRESOLVED"
        self.preflight: DevelopPreflight | None = None
        if self.package_root.exists():
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version
            self.package_validity = loaded.validity

    def run(self, mode: str = "normal_task", **opts: Any):
        if mode not in DEVELOP_MODES:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="FAILED",
                blockers=[f"unsupported Develop mode: {mode}"],
                next_route="stop",
                extras=self._capability_extras(),
            )

        project_status, _project_reasons, project = inspect_host_project(self.root)
        self.preflight = evaluate_develop_preflight(
            self.root,
            package_root=self.package_root,
            project=project,
            project_status=project_status,
        )
        self.skill_version = self.preflight.skill_version or self.skill_version
        candidate = observe_candidate(self.root)
        if not self.preflight.allowed:
            return self._blocked(
                mode,
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
        if not resolved.ok or resolved.task is None or resolved.path is None:
            return self._blocked(
                mode,
                resolved.blockers,
                resolved.route,
                candidate=candidate,
                project=project,
            )
        task = resolved.task
        compatible, compat_reason = mode_compatible(task, mode)
        if not compatible:
            return self._blocked(
                mode,
                [compat_reason],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        repair_handoff = opts.get("test_to_develop") or opts.get("repair_handoff")
        if mode == "repair":
            usable, repair_reason = validate_repair_handoff(
                repair_handoff,
                task_id=str(task["record_id"]),
                candidate_digest=candidate.digest,
            )
            if not usable:
                return self._blocked(
                    mode,
                    [repair_reason],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                )

        plan = authorize_writes(
            self.root,
            writes=opts.get("writes"),
            task=task,
            project=project or {},
        )
        if not plan.ok:
            return self._blocked(
                mode,
                plan.blockers,
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )

        project_name = str((project or {}).get("name") or "")
        session_id = opts.get("session_id")
        if session_id:
            bound = load_session(
                self.root,
                str(session_id),
                task_id=str(task["record_id"]),
                mode=mode,
                project_name=project_name,
                current_candidate_digest=candidate.digest,
            )
        else:
            bound = create_session(
                self.root,
                task_id=str(task["record_id"]),
                mode=mode,
                project_name=project_name,
                candidate_digest=candidate.digest,
            )
        if not bound.ok or bound.session is None or bound.directory is None:
            return self._blocked(
                mode,
                bound.blockers,
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        session = bound.session
        expected = task_revision(task)
        if expected is None:
            return self._blocked(
                mode,
                ["Task Book record_revision is UNKNOWN"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
            )
        prepared = apply_session_progress(
            task, str(session["record_id"]), mode=mode
        )
        hook = opts.get("before_first_task_publish")
        if callable(hook):
            hook()
        first = publish_task(
            resolved.path, prepared, expected_revision=expected
        )
        if not first.ok or first.task is None:
            extras = {"task_publication": _publication_extras(first)}
            return self._blocked(
                mode,
                first.blockers,
                "stop",
                candidate=_candidate_after_publication(self.root, first, candidate),
                project=project,
                task=first.task or task,
                session=session,
                session_directory=bound.directory,
                extras=extras,
            )
        task = first.task
        task_mutated = True

        applied: list[str] = []
        if plan.writes:
            applied, bound.files = apply_writes(
                self.root,
                plan.writes,
                directory=bound.directory,
                files=bound.files,
                overlay_paths=overlay_path_set(session),
                stage_ids=_active_stage_ids(task),
            )
            persist_session(bound.directory, session)

        after = observe_candidate(self.root)
        stale_invalidated = False
        if mode == "repair" and isinstance(repair_handoff, dict) and applied:
            previous = {
                "candidate": {
                    "candidate_digest": repair_handoff.get("candidate_digest") or ""
                }
            }
            report = repair_handoff.get("report")
            if isinstance(report, dict):
                previous = report
            stale_invalidated = not report_usable_for(previous, after)

        develop_to_test = None
        test_to_develop = None
        test_result = None
        if opts.get("invoke_test"):
            develop_to_test = build_develop_to_test(
                task=task,
                session_id=str(session["record_id"]),
                candidate_digest=after.digest,
                selected=list(opts.get("selected") or []),
            )
            test_result = invoke_test(
                self.root,
                develop_to_test,
                test_package=Path(opts["test_package"])
                if opts.get("test_package")
                else default_test_package(),
            )
            test_to_develop = build_test_to_develop(
                task_id=str(task["record_id"]),
                session_id=str(session["record_id"]),
                candidate_digest=observe_candidate(self.root).digest,
                test_result=test_result,
            )

        submit_handoff = None
        next_route = "caller"
        if opts.get("request_ready_for_review"):
            gates_ok, gate_reason = ready_for_review_gates(task)
            test_pass = bool((test_to_develop or {}).get("test_pass"))
            if not gates_ok:
                reason = (
                    [
                        "TEST_PASS alone cannot set READY_FOR_REVIEW",
                        gate_reason,
                    ]
                    if test_pass
                    else [gate_reason]
                )
                return self._blocked(
                    mode,
                    reason,
                    "stop",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    writes_applied=applied,
                    task_mutated=task_mutated,
                    extras={
                        "develop_to_test": develop_to_test,
                        "test_to_develop": test_to_develop,
                        "writes_applied": applied,
                    },
                )
            ready_expected = task_revision(task)
            if ready_expected is None:
                return self._blocked(
                    mode,
                    ["Task Book record_revision is UNKNOWN"],
                    "stop",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    writes_applied=applied,
                    task_mutated=task_mutated,
                    extras={
                        "develop_to_test": develop_to_test,
                        "test_to_develop": test_to_develop,
                        "writes_applied": applied,
                    },
                )
            ready_task = persist_ready_for_review(task)
            ready_hook = opts.get("before_ready_task_publish")
            if callable(ready_hook):
                ready_hook()
            second = publish_task(
                resolved.path, ready_task, expected_revision=ready_expected
            )
            if not second.ok or second.task is None:
                return self._blocked(
                    mode,
                    second.blockers,
                    "stop",
                    candidate=_candidate_after_publication(self.root, second, after),
                    project=project,
                    task=second.task or task,
                    session=session,
                    session_directory=bound.directory,
                    writes_applied=applied,
                    task_mutated=task_mutated,
                    extras={
                        "develop_to_test": develop_to_test,
                        "test_to_develop": test_to_develop,
                        "writes_applied": applied,
                        "submit_handoff": None,
                        "task_publication": _publication_extras(second),
                    },
                )
            task = second.task
            after = observe_candidate(self.root)
            submit_handoff = build_submit_route(
                task_id=str(task["record_id"]),
                candidate_digest=after.digest,
            )
            next_route = "submit"
            if test_result is not None:
                report = (getattr(test_result, "extras", {}) or {}).get("report")
                if isinstance(report, dict):
                    stale_invalidated = stale_invalidated or (
                        not report_usable_for(report, after)
                    )

        if test_to_develop and test_to_develop.get("test_pass") is False:
            next_route = "develop.repair"

        session = seal_session(self.root, bound.directory, session)
        extras = self._result_extras(
            task=task,
            session=session,
            candidate=after,
            project=project,
            develop_to_test=develop_to_test,
            test_to_develop=test_to_develop,
            submit_handoff=submit_handoff,
            writes_applied=applied,
            stale_test_invalidated=stale_invalidated,
            repair_handoff=repair_handoff if mode == "repair" else None,
        )
        if test_result is not None:
            report = (getattr(test_result, "extras", {}) or {}).get("report")
            if isinstance(report, dict):
                extras["test_report_usable_for_current"] = report_usable_for(
                    report, after
                )
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="COMPLETED",
            baseline=after.data,
            mutations=_mutation_label(applied, task_mutated),
            artifacts=[f"{bound.directory.as_posix()}/session.yaml"],
            evidence=[],
            next_route=next_route,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _blocked(
        self,
        mode: str,
        blockers: list[str],
        route: str,
        *,
        candidate=None,
        project: dict[str, Any] | None = None,
        task: dict[str, Any] | None = None,
        session: dict[str, Any] | None = None,
        session_directory: Path | None = None,
        writes_applied: list[str] | None = None,
        task_mutated: bool = False,
        extras: dict[str, Any] | None = None,
    ):
        if (
            session is not None
            and session_directory is not None
            and session.get("status") == "OPEN"
        ):
            session = abort_session(session_directory, session)
        payload = self._result_extras(
            task=task,
            session=session,
            candidate=candidate,
            project=project,
            writes_applied=writes_applied,
        )
        if extras:
            payload.update(extras)
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="BLOCKED",
            baseline=candidate.data if candidate is not None else None,
            mutations=_mutation_label(writes_applied, task_mutated),
            blockers=blockers,
            next_route=route,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=payload,
        )

    def _result_extras(
        self,
        *,
        task: dict[str, Any] | None,
        session: dict[str, Any] | None,
        candidate,
        project: dict[str, Any] | None,
        develop_to_test: dict[str, Any] | None = None,
        test_to_develop: dict[str, Any] | None = None,
        submit_handoff: dict[str, Any] | None = None,
        writes_applied: list[str] | None = None,
        stale_test_invalidated: bool = False,
        repair_handoff: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {
            "package": {
                "skill_id": SKILL_ID,
                "skill_version": self.skill_version,
                "modes": list(DEVELOP_MODES),
                "provides": list(PROVIDES),
                "requires": list(REQUIRES),
            },
            "task_complete": task_complete(task) if task else False,
            "ready_for_review": bool(task and task.get("status") == "READY_FOR_REVIEW"),
            "submit_authorized": False,
            "test_pass": (test_to_develop or {}).get("test_pass"),
            "writes_applied": list(writes_applied or []),
            "stale_test_invalidated": stale_test_invalidated,
            "develop_to_test": develop_to_test,
            "test_to_develop": test_to_develop,
            "submit_handoff": submit_handoff,
            "repair_handoff": repair_handoff,
            "capabilities": {
                "commit": False,
                "push": False,
                "submit_authorized": False,
                "migration": False,
                "refresh": False,
            },
        }
        extras.update(self._capability_extras())
        if self.preflight is not None:
            extras.update(self.preflight.extras())
        if task is not None:
            extras["task"] = {
                "record_id": task.get("record_id"),
                "status": task.get("status"),
                "record_revision": task.get("record_revision"),
                "task_complete": task_complete(task),
                "stages": [
                    {"stage_id": row.get("stage_id"), "status": row.get("status")}
                    for row in (task.get("stages") or [])
                    if isinstance(row, dict)
                ],
            }
        if session is not None:
            extras["session"] = {
                "record_id": session.get("record_id"),
                "status": session.get("status"),
                "task_id": session.get("task_id"),
                "mode": session.get("mode"),
                "project_name": session.get("project_name"),
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
        return extras

    def _capability_extras(self) -> dict[str, Any]:
        return {
            "submit_authorized": False,
            "capabilities": {
                "commit": False,
                "push": False,
                "submit_authorized": False,
                "migration": False,
                "refresh": False,
            },
        }


def default_develop_package() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "develop"


def default_test_package() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "test"


def _candidate_after_publication(root: Path, publication, previous):
    if publication.conflict:
        return observe_candidate(root)
    return previous


def _publication_extras(publication) -> dict[str, Any]:
    return {
        "conflict": bool(publication.conflict),
        "expected_revision": publication.expected_revision,
        "actual_revision": publication.actual_revision,
        "published_revision": publication.published_revision,
    }


def _mutation_label(writes_applied: list[str] | None, task_mutated: bool) -> str:
    if writes_applied:
        return "source"
    if task_mutated:
        return "task_book"
    return "none"


def _active_stage_ids(task: dict[str, Any]) -> list[str]:
    out = []
    for stage in task.get("stages") or []:
        if isinstance(stage, dict) and stage.get("status") == "IN_PROGRESS":
            if stage.get("stage_id"):
                out.append(str(stage["stage_id"]))
    return out

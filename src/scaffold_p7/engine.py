"""Develop Skill orchestration. Mutates source under Task Book + ownership authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.host_state import scm_baseline
from scaffold_p5.io_util import read_yaml
from scaffold_p5.ownership import (
    normalize_project_path,
    ownership_registry_issues,
    path_covered,
    resolve_ownership,
)
from scaffold_p5.packages import load_package, resolve_skill_package
from scaffold_p5.result import skill_result
from scaffold_p5.rules import resolve_project_rules, rule_test_ids
from scaffold_p5.scm import DIVERGED, STALE, observe_upstream_currentness
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p6.candidate import observe_candidate, report_usable_for

from scaffold_p7.develop_authority import (
    bind_open_execution,
    clear_current_execution,
    editor_blocking_provenance_issues,
    execution_provenance_issues,
    list_canonical_open_sessions,
    load_canonical_open_session,
    load_execution_pointer,
    mutable_stage_ids,
    raw_open_sessions_for_task,
    reconcile_session_changes,
)
from scaffold_p7.handoff import (
    build_develop_to_test,
    build_submit_route,
    build_test_to_develop,
    consume_published_test_report,
    invoke_test,
    validate_ready_repair_handoff,
    validate_repair_handoff,
)
from scaffold_p7.intake import (
    IntakeDecision,
    assess_grounding,
    intake_task,
    prepare_proposal,
)
from scaffold_p7.lifecycle import (
    apply_ready_authority_refresh,
    apply_ready_repair_reopen,
    lifecycle_progressed,
    persist_ready_if_legal,
    prepare_lifecycle,
)
from scaffold_p7.migration_run import (
    execute_task_bound_migration,
    prepare_task_bound_migration_application,
)
from scaffold_p7.repair_state import (
    consumed_repair_replay,
    load_repair_state,
    persist_repair_state,
    reconstruct_repair_view,
)
from scaffold_p7.models import DEVELOP_MODES, PROVIDES, REQUIRES, SESSIONS_DIR, SKILL_ID
from scaffold_p7.mutation import (
    MutationPlan,
    apply_writes,
    authorize_writes,
    overlay_path_set,
    supporting_path_declaration_issues,
    supporting_path_grounding_issues,
)
from scaffold_p7.preflight import (
    DevelopPreflight,
    evaluate_develop_preflight,
    inspect_host_project,
)
from scaffold_p7.session import (
    abort_session,
    create_session,
    load_session,
    operational_project_name,
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
from scaffold_p7.unexplained import physical_authority_issues, reconcile_unexplained_drift


class DevelopEngine:
    def __init__(
        self,
        host_root: str | Path,
        package_root: str | Path | None = None,
    ):
        self.root = Path(host_root)
        self.package_root = (
            Path(package_root) if package_root else default_develop_package(self.root)
        )
        self.skill_version = ""
        self.package_validity = "UNRESOLVED"
        self.preflight: DevelopPreflight | None = None
        self.d1_currentness: dict[str, Any] | None = None
        if self.package_root.exists():
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version
            self.package_validity = loaded.validity

    def intake(
        self,
        *,
        structured_intent: Any,
        proposal: Any,
        grounding: Any,
    ):
        """Publish bounded Task authority as the Develop normal_task prelude.

        Does not write project source, invoke Test, Commit, Push, or grant
        Submit. Intake creates no Develop Session and does not transition
        Stage merely to manufacture editor mutation authority.
        """
        self.d1_currentness = None
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
            return self._intake_result(
                outcome="BLOCKED",
                blockers=list(self.preflight.blockers),
                route=self.preflight.route or "understand.compatibility",
                candidate=candidate,
                project=project,
                human_gate=_intake_gate(
                    "The host is not ready for Task Intake.",
                    "Host lifecycle, maintenance, or package compatibility blocks Task authority.",
                    "Complete the reported Understand route first.",
                    "Task Intake can then re-evaluate the current request.",
                ),
            )
        if not candidate.usable:
            return self._intake_result(
                outcome="BLOCKED",
                blockers=list(candidate.data.get("blockers") or [
                    "candidate SCM observation is unresolved"
                ]),
                route="human",
                candidate=candidate,
                project=project,
                human_gate=_intake_gate(
                    "Current repository/candidate truth is unresolved.",
                    "A Task baseline cannot be stated safely.",
                    "Resolve the SCM observation failure.",
                    "No Task or source will be changed before truth is restored.",
                ),
            )

        currentness = observe_upstream_currentness(self.root)
        self.d1_currentness = currentness.public()
        if not currentness.ok or currentness.state in {STALE, DIVERGED}:
            blockers = list(currentness.blockers)
            if not blockers:
                blockers = [
                    "Task Intake requires a current repository basis; "
                    f"configured upstream state is {currentness.state}"
                ]
            return self._intake_result(
                outcome="BLOCKED",
                blockers=blockers,
                route="human",
                candidate=candidate,
                project=project,
                human_gate=_intake_gate(
                    f"Repository currentness is {currentness.state}.",
                    "Task activation on a stale, diverged, or unknown basis is unsafe.",
                    "Synchronize or resolve repository currentness explicitly.",
                    "No Task or source has been changed.",
                ),
            )

        normalized, proposal_issues = prepare_proposal(proposal, self.root)
        if proposal_issues or normalized is None:
            return self._intake_result(
                outcome="NEEDS_HUMAN",
                blockers=proposal_issues,
                route="human",
                candidate=candidate,
                project=project,
                human_gate=_intake_gate(
                    "The human request has no complete bounded Task proposal.",
                    "Goal, scope, acceptance, stages, or test intent is unresolved.",
                    "Clarify the missing proposal facts.",
                    "A Task can be proposed without editing .scaffold manually.",
                ),
            )
        grounding_result = assess_grounding(
            structured_intent,
            grounding,
            normalized,
        )
        scope_issues = _intake_scope_issues(self.root, project or {}, normalized)
        if scope_issues:
            grounding_result = dict(grounding_result)
            grounding_result["fully_grounded"] = False
            grounding_result["direct_activation"] = False
            grounding_result["issues"] = sorted(
                set(list(grounding_result.get("issues") or []) + scope_issues)
            )

        scope = normalized["scope"]
        test_ids = _proposal_bound_profile_ids(normalized)
        project_rules = resolve_project_rules(
            self.root,
            project=project,
            skill_id="develop",
            paths=list(scope.get("paths") or []),
            modules=list(scope.get("modules") or []),
            test_ids=test_ids,
            operation="source_write",
        )
        if not project_rules.get("ok"):
            return self._intake_result(
                outcome="NEEDS_HUMAN",
                blockers=list(project_rules.get("blockers") or [
                    "Project Rule authority conflicts with Task Intake"
                ]),
                route=project_rules.get("route") or "understand.refresh",
                candidate=candidate,
                project=project,
                proposal=normalized,
                grounding=grounding_result,
                project_rules=project_rules,
                human_gate=_intake_gate(
                    "Applicable Project Rules conflict with or prohibit the proposed work.",
                    "Task activation cannot silently override governance.",
                    "Resolve or explicitly change the governing Rule through normal review.",
                    "No Task activation, source write, Commit, or Push occurs.",
                ),
            )

        decision = intake_task(
            self.root,
            proposal=normalized,
            baseline=scm_baseline(self.root),
            grounding=grounding_result,
        )
        route = (
            "develop.normal_task"
            if decision.task and decision.task.get("status") == "IN_PROGRESS"
            else ("human" if decision.outcome == "NEEDS_HUMAN" else "stop")
        )
        result = self._intake_result(
            outcome=decision.outcome,
            blockers=list(decision.blockers),
            route=route,
            candidate=candidate,
            project=project,
            decision=decision,
            proposal=normalized,
            grounding=grounding_result,
            project_rules=project_rules,
            human_gate=decision.human_gate,
        )
        return result

    def open_develop_session(self, *, task_id: str | None = None, mode: str = "normal_task"):
        """Open or reuse an OPEN Develop execution Session for an IN_PROGRESS Task.

        Does not write project source. Marks the first PENDING Stage
        IN_PROGRESS so mutation authority has a current mutable Stage.
        Intake must not call this.
        """
        chosen_mode = mode if mode in DEVELOP_MODES else "normal_task"
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
                chosen_mode,
                list(self.preflight.blockers),
                self.preflight.route or "understand.compatibility",
                candidate=candidate,
                project=project,
            )
        if not candidate.usable:
            return self._blocked(
                chosen_mode,
                list(candidate.data.get("blockers") or [
                    "candidate SCM observation is unresolved"
                ]),
                "stop",
                candidate=candidate,
                project=project,
            )
        resolved = resolve_task(self.root, task_id=task_id)
        if not resolved.ok or resolved.task is None or resolved.path is None:
            return self._blocked(
                chosen_mode,
                resolved.blockers,
                resolved.route or "stop",
                candidate=candidate,
                project=project,
            )
        task = resolved.task
        if task.get("status") != "IN_PROGRESS":
            return self._blocked(
                chosen_mode,
                [
                    f"Task status {task.get('status')} cannot open a Develop Session"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        pointer, pointer_error = load_execution_pointer(self.root)
        if pointer_error:
            return self._blocked(
                chosen_mode,
                [pointer_error],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        session = None
        if pointer:
            current, _directory, current_issues = load_canonical_open_session(
                self.root, str(pointer.get("session_id") or "")
            )
            if current is not None:
                if str(current.get("task_id") or "") != str(task["record_id"]):
                    return self._blocked(
                        chosen_mode,
                        [
                            "another Develop execution is OPEN; seal or abort it "
                            "before starting a new Session"
                        ],
                        "stop",
                        candidate=candidate,
                        project=project,
                        task=task,
                        session=current,
                    )
                session = current
        existing = raw_open_sessions_for_task(self.root, str(task["record_id"]))
        if len(existing) > 1:
            return self._blocked(
                chosen_mode,
                ["multiple OPEN Develop Sessions are bound to the current Task"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if session is None and existing:
            loaded, _directory, load_issues = load_canonical_open_session(
                self.root, str(existing[0].get("record_id") or "")
            )
            if loaded is None:
                return self._blocked(
                    chosen_mode,
                    load_issues
                    or ["existing OPEN Develop Session is not canonical"],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                )
            session = loaded
        other_open = [
            item
            for item, _directory in list_canonical_open_sessions(self.root)
            if str(item.get("task_id") or "") != str(task["record_id"])
        ]
        if other_open and (
            session is None
            or str(other_open[0].get("record_id") or "")
            != str(session.get("record_id") or "")
        ):
            return self._blocked(
                chosen_mode,
                [
                    "another Task already has an OPEN Develop execution; "
                    "seal or abort it first"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if session is None:
            bound = create_session(
                self.root,
                task_id=str(task["record_id"]),
                mode=chosen_mode,
                project_name=operational_project_name(project, self.root),
                candidate_digest=candidate.digest,
            )
            if not bound.ok or bound.session is None:
                return self._blocked(
                    chosen_mode,
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
                chosen_mode,
                ["Task Book record_revision is UNKNOWN"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                session=session,
            )
        prepared = apply_session_progress(
            task, str(session["record_id"]), mode="normal_task"
        )
        changed = (
            list(prepared.get("develop_session_ids") or [])
            != list(task.get("develop_session_ids") or [])
            or prepared.get("stages") != task.get("stages")
        )
        if changed:
            published = publish_task(
                resolved.path, prepared, expected_revision=expected
            )
            if not published.ok or published.task is None:
                return self._blocked(
                    chosen_mode,
                    published.blockers,
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=published.task or task,
                    session=session,
                )
            task = published.task
        directory = self.root / SESSIONS_DIR / str(session["record_id"])
        bind_open_execution(
            self.root,
            session_id=str(session["record_id"]),
            task_id=str(task["record_id"]),
            directory=directory,
            opened_candidate_digest=str(
                session.get("observed_candidate_digest") or candidate.digest
            ),
        )
        extras = {
            "operation": "develop_session",
            "session": {
                "record_id": session.get("record_id"),
                "status": session.get("status"),
                "task_id": session.get("task_id"),
            },
            "task": {
                "record_id": task.get("record_id"),
                "record_revision": task.get("record_revision"),
                "status": task.get("status"),
            },
            "mutable_stage_ids": mutable_stage_ids(task),
            "submit_authorized": False,
            "capabilities": {
                "source_write": False,
                "commit": False,
                "push": False,
                "submit_authorized": False,
            },
        }
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=chosen_mode,
            outcome="COMPLETED",
            baseline=candidate.data,
            mutations="task_book" if changed else "none",
            artifacts=[],
            blockers=[],
            next_route="develop.normal_task",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def seal_develop_execution(self, *, task_id: str | None = None, mode: str = "normal_task"):
        """Seal the current OPEN Develop execution. Closes editor mutation authority."""
        return self._close_develop_execution(
            task_id=task_id, mode=mode, action="seal"
        )

    def abort_develop_execution(self, *, task_id: str | None = None, mode: str = "normal_task"):
        """Abort the current OPEN Develop execution. Closes editor mutation authority."""
        return self._close_develop_execution(
            task_id=task_id, mode=mode, action="abort"
        )

    def _close_develop_execution(
        self,
        *,
        task_id: str | None,
        mode: str,
        action: str,
    ):
        chosen_mode = mode if mode in DEVELOP_MODES else "normal_task"
        project_status, _project_reasons, project = inspect_host_project(self.root)
        candidate = observe_candidate(self.root)
        pointer, pointer_error = load_execution_pointer(self.root)
        if pointer_error and action == "seal":
            return self._blocked(
                chosen_mode,
                [pointer_error],
                "stop",
                candidate=candidate,
                project=project,
            )
        session_id = ""
        wanted_task = str(task_id or "").strip()
        if wanted_task:
            existing = raw_open_sessions_for_task(self.root, wanted_task)
            if existing:
                session_id = str(existing[0].get("record_id") or "")
        if not session_id and pointer:
            if wanted_task and str(pointer.get("task_id") or "") != wanted_task:
                return self._blocked(
                    chosen_mode,
                    ["requested Task is not the current Develop execution"],
                    "stop",
                    candidate=candidate,
                    project=project,
                )
            session_id = str(pointer.get("session_id") or "")
        if not session_id:
            return self._blocked(
                chosen_mode,
                ["no OPEN Develop execution Session is available to close"],
                "stop",
                candidate=candidate,
                project=project,
            )
        directory = self.root / SESSIONS_DIR / session_id
        path = directory / "session.yaml"
        if not path.is_file():
            clear_current_execution(self.root, session_id=session_id)
            return self._blocked(
                chosen_mode,
                ["Develop Session is missing or orphaned"],
                "stop",
                candidate=candidate,
                project=project,
            )
        if action == "seal":
            session, loaded, issues = load_canonical_open_session(self.root, session_id)
            if session is None or loaded is None:
                return self._blocked(
                    chosen_mode,
                    issues or ["Develop Session is not valid for sealing"],
                    "stop",
                    candidate=candidate,
                    project=project,
                )
            resolved = resolve_task(self.root, task_id=str(session.get("task_id") or ""))
            task = resolved.task if resolved.ok else None
            if task is None:
                return self._blocked(
                    chosen_mode,
                    resolved.blockers,
                    "stop",
                    candidate=candidate,
                    project=project,
                    session=session,
                    session_directory=loaded,
                )
            reconcile_session_changes(
                self.root,
                loaded,
                task=task,
                session=session,
            )
            reconcile_unexplained_drift(self.root, boundary="seal")
            physical = physical_authority_issues(self.root)
            if physical:
                return self._blocked(
                    chosen_mode,
                    physical,
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=loaded,
                )
            pointer_issues = execution_provenance_issues(
                self.root,
                task=task,
                session=session,
                directory=loaded,
                for_seal=True,
            )
            if pointer_issues:
                return self._blocked(
                    chosen_mode,
                    pointer_issues,
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=loaded,
                )
            session = seal_session(self.root, loaded, session)
            session["sealed_candidate_digest"] = candidate.digest
            persist_session(loaded, session)
            clear_current_execution(self.root, session_id=session_id)
            operation = "develop_seal"
        else:
            try:
                session = read_yaml(path)
            except (OSError, ValueError, TypeError, UnicodeError):
                session = None
            if not isinstance(session, dict):
                reconcile_unexplained_drift(self.root, boundary="abort")
                clear_current_execution(self.root, session_id=session_id)
                return self._blocked(
                    chosen_mode,
                    ["Develop Session is malformed or unreadable"],
                    "stop",
                    candidate=candidate,
                    project=project,
                )
            reconcile_unexplained_drift(self.root, boundary="abort")
            if session.get("status") == "OPEN":
                session = abort_session(directory, session)
            clear_current_execution(self.root, session_id=session_id)
            operation = "develop_abort"
            resolved = resolve_task(
                self.root, task_id=str(session.get("task_id") or wanted_task or "")
            )
            task = resolved.task if resolved.ok else None
        extras = {
            "operation": operation,
            "session": {
                "record_id": session.get("record_id"),
                "status": session.get("status"),
                "task_id": session.get("task_id"),
            },
            "submit_authorized": False,
            "capabilities": {
                "source_write": False,
                "commit": False,
                "push": False,
                "submit_authorized": False,
            },
        }
        if isinstance(task, dict):
            extras["task"] = {
                "record_id": task.get("record_id"),
                "record_revision": task.get("record_revision"),
                "status": task.get("status"),
            }
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=chosen_mode,
            outcome="COMPLETED",
            baseline=candidate.data,
            mutations="none",
            artifacts=[],
            blockers=[],
            next_route="stop",
            extras=extras,
        )

    def run(self, mode: str = "normal_task", **opts: Any):
        self.d1_currentness = None
        opts.pop("authorization_provider", None)
        opts.pop("approval_origin", None)
        opts.pop("migration_authorization_ref", None)
        opts.pop("migration_authorization_attempt_id", None)
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
            allow_approved_migration=bool(opts.get("execute_approved_migration")),
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
        if not candidate.usable:
            return self._blocked(
                mode,
                list(candidate.data.get("blockers") or [
                    "candidate SCM observation is unresolved"
                ]),
                "stop",
                candidate=candidate,
                project=project,
                extras={"scm_observation": candidate.data},
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
        opened_task = task
        repair_handoff = (
            opts.get("submit_to_develop")
            or opts.get("test_to_develop")
            or opts.get("repair_handoff")
        )
        published_id = str(opts.get("published_test_report_id") or "").strip()
        raw_writes = opts.get("writes")
        has_source_writes = isinstance(raw_writes, list) and any(
            isinstance(item, dict) and item.get("path") for item in raw_writes
        )
        refresh_ready_authority = bool(opts.get("refresh_ready_authority"))
        ready_report_revalidation = (
            mode == "normal_task"
            and task.get("status") == "READY_FOR_REVIEW"
            and bool(published_id)
            and not opts.get("invoke_test")
            and not has_source_writes
            and not refresh_ready_authority
        )
        ready_authority_refresh = (
            refresh_ready_authority
            and mode == "normal_task"
            and task.get("status") == "READY_FOR_REVIEW"
        )
        ready_repair = False
        if not (
            (mode == "repair" and task.get("status") == "READY_FOR_REVIEW")
            or ready_report_revalidation
            or ready_authority_refresh
        ):
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
        currentness = observe_upstream_currentness(self.root)
        self.d1_currentness = currentness.public()
        if not currentness.ok:
            return self._blocked(
                mode,
                list(currentness.blockers)
                or ["D1 upstream currentness is UNKNOWN"],
                "human",
                candidate=candidate,
                project=project,
                task=task,
                extras={"d1_currentness": currentness.public()},
            )
        if currentness.state in {STALE, DIVERGED}:
            return self._blocked(
                mode,
                [
                    "D1 requires a current development basis; configured "
                    f"upstream state is {currentness.state}"
                ],
                "human",
                candidate=candidate,
                project=project,
                task=task,
                extras={"d1_currentness": currentness.public()},
            )
        if mode == "repair":
            if task.get("status") == "READY_FOR_REVIEW":
                usable, repair_reason = validate_ready_repair_handoff(
                    repair_handoff,
                    task=task,
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
                ready_repair = True
            else:
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
            replay = consumed_repair_replay(
                self.root, task=task, handoff=repair_handoff
            )
            if replay is not None:
                extras = self._result_extras(
                    task=task,
                    session=None,
                    candidate=candidate,
                    project=project,
                    repair_handoff=repair_handoff if isinstance(repair_handoff, dict) else None,
                )
                extras["repair_replayed"] = True
                extras["repair_state"] = replay
                extras["repair_view"] = reconstruct_repair_view(
                    self.root, str(task["record_id"])
                )
                extras["repair_reopen"] = False
                return skill_result(
                    skill_id=SKILL_ID,
                    skill_version=self.skill_version,
                    mode=mode,
                    outcome="COMPLETED",
                    baseline=candidate.data,
                    mutations="none",
                    artifacts=[],
                    evidence=[],
                    next_route="caller",
                    compatibility=(
                        self.preflight.compatibility if self.preflight else None
                    ),
                    extras=extras,
                )

        requested_writes = opts.get("writes")
        write_paths = [
            str(item.get("path"))
            for item in (requested_writes or [])
            if isinstance(item, dict) and item.get("path")
        ]
        task_scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        project_rules = resolve_project_rules(
            self.root,
            project=project,
            skill_id="develop",
            paths=write_paths or list(task_scope.get("paths") or []),
            modules=list(task_scope.get("modules") or []),
            test_ids=rule_test_ids(task=task, selected=opts.get("selected")),
            operation="source_write" if write_paths else "develop",
        )
        if not project_rules.get("ok"):
            return self._blocked(
                mode,
                list(project_rules.get("blockers") or ["Project Rule authority is conflicting"]),
                project_rules.get("route") or "understand.refresh",
                candidate=candidate,
                project=project,
                task=task,
                extras={"project_rules": project_rules},
            )

        if (
            opts.get("report") is not None
            or opts.get("raw_report") is not None
            or opts.get("test_report") is not None
        ):
            return self._blocked(
                mode,
                [
                    "raw caller-supplied Test report is untrusted; "
                    "provide published_test_report_id"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if opts.get("trusted") is True:
            return self._blocked(
                mode,
                [
                    "caller trusted=true is not Test authority; "
                    "provide published_test_report_id"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if isinstance(opts.get("evidence"), (list, dict)):
            return self._blocked(
                mode,
                [
                    "raw caller-supplied Test evidence is untrusted; "
                    "provide published_test_report_id"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if opts.get("invoke_test") and published_id:
            return self._blocked(
                mode,
                ["invoke_test and published_test_report_id are mutually exclusive"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if refresh_ready_authority:
            return self._refresh_ready_authority(
                mode=mode,
                opts=opts,
                task=task,
                resolved=resolved,
                candidate=candidate,
                project=project,
                published_id=published_id,
                write_paths=write_paths,
                project_rules=project_rules,
            )
        test_package = (
            Path(opts["test_package"])
            if opts.get("test_package")
            else default_test_package(self.root)
        )
        if (
            published_id
            and not write_paths
            and mode == "normal_task"
            and task.get("status") == "READY_FOR_REVIEW"
            and not opts.get("invoke_test")
        ):
            test_result = consume_published_test_report(
                self.root,
                report_id=published_id,
                test_package=test_package,
                task=task,
            )
            if getattr(test_result, "outcome", None) != "COMPLETED":
                return self._blocked(
                    mode,
                    list(getattr(test_result, "blockers", None) or [
                        "published Test report cannot be consumed"
                    ]),
                    "test.scoped_verification",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={"consumed_published_report": True},
                )
            extras_loaded = getattr(test_result, "extras", {}) or {}
            if extras_loaded.get("test_complete") is not True:
                return self._blocked(
                    mode,
                    ["published Test report TEST_COMPLETE is false; cannot support READY"],
                    "test.scoped_verification",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={"consumed_published_report": True, "test_to_develop": None},
                )
            ready_ok, ready_reason = ready_for_review_gates(
                task, candidate_digest=candidate.digest, root=self.root
            )
            if not ready_ok:
                return self._blocked(
                    mode,
                    [
                        "READY revalidation failed against published Test authority: "
                        + ready_reason
                    ],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={"consumed_published_report": True},
                )
            linked = [
                str(item)
                for item in (task.get("develop_session_ids") or [])
                if isinstance(item, str) and item
            ]
            test_to_develop = build_test_to_develop(
                task_id=str(task["record_id"]),
                session_id=linked[-1] if linked else "",
                candidate_digest=candidate.digest,
                test_result=test_result,
                task=task,
            )
            extras = self._result_extras(
                task=task,
                session=None,
                candidate=candidate,
                project=project,
                test_to_develop=test_to_develop,
            )
            extras["consumed_published_report"] = True
            extras["ready_revalidation"] = True
            extras["submit_handoff"] = build_submit_route(
                task_id=str(task["record_id"]),
                candidate_digest=candidate.digest,
            )
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="COMPLETED",
                baseline=candidate.data,
                mutations="none",
                artifacts=[],
                evidence=list(getattr(test_result, "evidence", None) or []),
                next_route="submit",
                compatibility=(
                    self.preflight.compatibility if self.preflight else None
                ),
                extras=extras,
            )

        plan = authorize_writes(
            self.root,
            writes=requested_writes,
            task=task,
            project=project or {},
        )
        if ready_repair and requested_writes:
            if not isinstance(requested_writes, list):
                return self._blocked(
                    mode,
                    ["writes must be a list of path/content maps"],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={"project_rules": project_rules},
                )
            plan = MutationPlan(ok=True, writes=[])
        elif not plan.ok:
            return self._blocked(
                mode,
                plan.blockers,
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"project_rules": project_rules},
            )

        prepared_migration = None
        if opts.get("execute_approved_migration"):
            bound_revision = task_revision(task)
            approval = opts.get("migration_approval") or opts.get("approval")
            prepared_migration = prepare_task_bound_migration_application(
                self.root,
                distribution=opts.get("distribution"),
                approval=approval,
                task_id=str(task["record_id"]),
                task_revision=bound_revision,
                candidate_digest=str(candidate.digest),
            )
            if not prepared_migration.ready:
                extras = {
                    "project_rules": project_rules,
                    "migration": prepared_migration.extras,
                    "pre_compatibility": (prepared_migration.extras or {}).get(
                        "pre_compatibility"
                    ),
                    "post_compatibility": (prepared_migration.extras or {}).get(
                        "post_compatibility"
                    ),
                }
                payload = self._result_extras(
                    task=task,
                    session=None,
                    candidate=candidate,
                    project=project,
                )
                payload.update(extras)
                payload["human_action"] = (prepared_migration.extras or {}).get(
                    "human_action"
                )
                if prepared_migration.outcome == "NEEDS_HUMAN":
                    return skill_result(
                        skill_id=SKILL_ID,
                        skill_version=self.skill_version,
                        mode=mode,
                        outcome="NEEDS_HUMAN",
                        baseline=candidate.data,
                        mutations="none",
                        artifacts=[],
                        blockers=list(prepared_migration.blockers),
                        next_route=prepared_migration.route or "human",
                        compatibility=(
                            (prepared_migration.extras or {}).get(
                                "pre_compatibility"
                            )
                            or (
                                self.preflight.compatibility
                                if self.preflight
                                else None
                            )
                        ),
                        extras=payload,
                    )
                return self._blocked(
                    mode,
                    list(prepared_migration.blockers),
                    prepared_migration.route or "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras=extras,
                    compatibility=(prepared_migration.extras or {}).get(
                        "pre_compatibility"
                    ),
                )

        project_name = operational_project_name(project, self.root)
        session_id = opts.get("session_id")
        require_candidate_match = True
        pointer, pointer_error = load_execution_pointer(self.root)
        if pointer_error:
            return self._blocked(
                mode,
                [pointer_error],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
            )
        if pointer:
            ptr_task = str(pointer.get("task_id") or "")
            ptr_session = str(pointer.get("session_id") or "")
            current, _directory, _issues = load_canonical_open_session(
                self.root, ptr_session
            )
            if current is not None and ptr_task != str(task["record_id"]):
                return self._blocked(
                    mode,
                    [
                        "another Develop execution is OPEN; seal or abort it "
                        "before starting a new Session"
                    ],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    session=current,
                )
            if not session_id and current is not None and ptr_task == str(task["record_id"]):
                session_id = ptr_session
                require_candidate_match = False
        if session_id:
            bound = load_session(
                self.root,
                str(session_id),
                task_id=str(task["record_id"]),
                mode=mode,
                project_name=project_name,
                current_candidate_digest=candidate.digest,
                require_candidate_match=require_candidate_match,
            )
            if (
                bound.ok
                and not require_candidate_match
                and bound.directory is not None
                and bound.session is not None
            ):
                provenance = execution_provenance_issues(
                    self.root,
                    task=task,
                    session=bound.session,
                    directory=bound.directory,
                )
                blocking = editor_blocking_provenance_issues(provenance)
                if blocking:
                    return self._blocked(
                        mode,
                        blocking,
                        "stop",
                        candidate=candidate,
                        project=project,
                        task=task,
                        session=bound.session,
                        session_directory=bound.directory,
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
        bind_open_execution(
            self.root,
            session_id=str(session["record_id"]),
            task_id=str(task["record_id"]),
            directory=bound.directory,
            opened_candidate_digest=str(
                session.get("observed_candidate_digest") or candidate.digest
            ),
        )
        physical = physical_authority_issues(self.root)
        if physical and has_source_writes:
            return self._blocked(
                mode,
                physical,
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
            )
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
        if ready_repair:
            prepared = apply_ready_repair_reopen(
                task,
                target_stage_ids=list(
                    (repair_handoff or {}).get("target_stage_ids") or []
                ),
                candidate_digest=candidate.digest,
            )
            prepared = apply_session_progress(
                prepared, str(session["record_id"]), mode="repair"
            )
        else:
            prepared = apply_session_progress(
                task, str(session["record_id"]), mode=mode
            )
        hook = opts.get("before_repair_reopen_publish") if ready_repair else None
        if not callable(hook):
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
        if ready_repair and isinstance(repair_handoff, dict):
            persist_repair_state(
                self.root,
                {
                    "task_id": str(task["record_id"]),
                    "status": "consumed",
                    "target_stage_ids": list(
                        repair_handoff.get("target_stage_ids") or []
                    ),
                    "target_mapping": "explicit",
                    "candidate_digest": candidate.digest,
                    "consumed_task_revision": expected,
                    "resulting_task_revision": task.get("record_revision"),
                    "session_id": str(session["record_id"]),
                    "blockers": list(repair_handoff.get("blockers") or []),
                    "evidence_refs": list(repair_handoff.get("evidence_refs") or []),
                    "report_id": repair_handoff.get("report_id") or "",
                    "reason": (
                        "explicit Stage-targeted READY repair reopened the "
                        "requested Stage(s)"
                    ),
                },
            )
        if opts.get("execute_approved_migration"):
            mig = execute_task_bound_migration(
                self.root,
                distribution=opts.get("distribution"),
                approval=opts.get("migration_approval") or opts.get("approval"),
                revalidation_distribution=opts.get(
                    "migration_revalidation_distribution"
                ),
                interrupt_after=opts.get("interrupt_after_migration"),
                task_id=str(task["record_id"]),
                task_revision=expected,
                session_id=str(session["record_id"]),
                candidate_digest=str(candidate.digest),
                prepared_plan=(
                    prepared_migration.plan if prepared_migration is not None else None
                ),
            )
            if not mig.ok:
                extras = {
                    "migration": mig.extras,
                    "post_compatibility": (mig.extras or {}).get(
                        "post_compatibility"
                    ),
                    "pre_compatibility": (mig.extras or {}).get(
                        "pre_compatibility"
                    ),
                }
                post_compat = (mig.extras or {}).get("post_compatibility")
                if mig.outcome == "NEEDS_HUMAN":
                    if session.get("status") == "OPEN":
                        session = abort_session(bound.directory, session)
                    payload = self._result_extras(
                        task=task,
                        session=session,
                        candidate=observe_candidate(self.root),
                        project=project,
                        writes_applied=list(mig.writes),
                    )
                    payload.update(extras)
                    payload["human_action"] = (mig.extras or {}).get("human_action")
                    return skill_result(
                        skill_id=SKILL_ID,
                        skill_version=self.skill_version,
                        mode=mode,
                        outcome="NEEDS_HUMAN",
                        baseline=observe_candidate(self.root).data,
                        mutations=_mutation_label(list(mig.writes), task_mutated),
                        artifacts=[],
                        blockers=list(mig.blockers),
                        next_route=mig.route or "human",
                        compatibility=post_compat
                        or (
                            self.preflight.compatibility if self.preflight else None
                        ),
                        extras=payload,
                    )
                return self._blocked(
                    mode,
                    list(mig.blockers),
                    mig.route or "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    writes_applied=list(mig.writes),
                    task_mutated=task_mutated or mig.applied,
                    extras=extras,
                    compatibility=post_compat,
                )
            applied_migration = list(mig.writes)
        else:
            applied_migration = []
            mig = None
        if ready_repair and requested_writes:
            plan = authorize_writes(
                self.root,
                writes=requested_writes,
                task=task,
                project=project or {},
            )
            if not plan.ok:
                return self._blocked(
                    mode,
                    plan.blockers,
                    "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    task_mutated=task_mutated,
                    extras={"project_rules": project_rules},
                )

        applied: list[str] = []
        if applied_migration:
            applied.extend(applied_migration)
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
        if not after.usable:
            return self._blocked(
                mode,
                list(after.data.get("blockers") or [
                    "candidate SCM observation failed after Develop mutation"
                ]),
                "human",
                candidate=after,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
                writes_applied=applied,
                task_mutated=task_mutated,
                extras={
                    "d1_currentness": currentness.public(),
                    "scm_observation": after.data,
                },
            )
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
                test_package=test_package,
            )
        elif published_id:
            test_result = consume_published_test_report(
                self.root,
                report_id=published_id,
                test_package=test_package,
                task=opened_task,
            )
            if getattr(test_result, "outcome", None) != "COMPLETED":
                return self._blocked(
                    mode,
                    list(getattr(test_result, "blockers", None) or [
                        "published Test report cannot be consumed"
                    ]),
                    "test.scoped_verification",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    extras={"consumed_published_report": True},
                )
            loaded_extras = getattr(test_result, "extras", {}) or {}
            if (
                _requests_satisfied_completion(opts)
                and loaded_extras.get("test_pass") is not True
            ):
                return self._blocked(
                    mode,
                    [
                        "published Test report TEST_PASS is false; "
                        "cannot support SATISFIED completion"
                    ],
                    "test.scoped_verification",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    extras={"consumed_published_report": True},
                )
            if (
                opts.get("request_ready_for_review")
                and loaded_extras.get("test_complete") is not True
            ):
                return self._blocked(
                    mode,
                    [
                        "published Test report TEST_COMPLETE is false; "
                        "cannot support READY"
                    ],
                    "test.scoped_verification",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    extras={"consumed_published_report": True},
                )
        if test_result is not None:
            test_to_develop = build_test_to_develop(
                task_id=str(task["record_id"]),
                session_id=str(session["record_id"]),
                candidate_digest=observe_candidate(self.root).digest,
                test_result=test_result,
                task=task,
            )
            after = observe_candidate(self.root)
            if test_to_develop.get("test_pass") is False:
                existing_repair = load_repair_state(
                    self.root, str(task["record_id"])
                )
                persist_repair_state(
                    self.root,
                    {
                        "task_id": str(task["record_id"]),
                        "status": (
                            "consumed"
                            if existing_repair and existing_repair.get("status") == "consumed"
                            else "pending"
                        ),
                        "target_stage_ids": list(
                            test_to_develop.get("target_stage_ids")
                            or (existing_repair or {}).get("target_stage_ids")
                            or []
                        ),
                        "target_mapping": test_to_develop.get("target_mapping")
                        or (existing_repair or {}).get("target_mapping")
                        or "unresolved",
                        "candidate_digest": after.digest,
                        "consumed_task_revision": (
                            (existing_repair or {}).get("consumed_task_revision")
                        ),
                        "resulting_task_revision": (
                            (existing_repair or {}).get("resulting_task_revision")
                        ),
                        "session_id": str(session["record_id"]),
                        "blockers": list(test_to_develop.get("blockers") or []),
                        "evidence_refs": list(
                            test_to_develop.get("evidence_refs") or []
                        ),
                        "fail_ids": list(test_to_develop.get("fail_ids") or []),
                        "report_id": test_to_develop.get("report_id") or "",
                        "reason": (
                            "required Test FAIL/BLOCKED produced a Repair handoff"
                        ),
                    },
                )

        submit_handoff = None
        next_route = "caller"
        lifecycle_task, _life_blockers, life_extras = prepare_lifecycle(
            task,
            root=self.root,
            candidate_digest=after.digest,
            test_result=test_result,
            stage_completion_decision=opts.get("stage_completion_decision"),
            task_completion_decision=opts.get("task_completion_decision"),
            request_stage_complete=bool(opts.get("request_stage_complete")),
            revalidate_complete_stages=bool(opts.get("revalidate_complete_stages")),
            request_ready_for_review=bool(opts.get("request_ready_for_review")),
        )
        if _life_blockers:
            extras = {
                "develop_to_test": develop_to_test,
                "test_to_develop": test_to_develop,
                "writes_applied": applied,
                "lifecycle": life_extras,
            }
            return self._blocked(
                mode,
                list(_life_blockers),
                "stop",
                candidate=after,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
                writes_applied=applied,
                task_mutated=task_mutated,
                extras=extras,
            )
        ready_requested = bool(opts.get("request_ready_for_review"))
        ready_ok = False
        gate_reason = ""
        if ready_requested:
            lifecycle_task, ready_ok, gate_reason = persist_ready_if_legal(
                lifecycle_task,
                candidate_digest=after.digest,
                root=self.root,
            )
        should_publish = lifecycle_progressed(task, lifecycle_task)
        if ready_requested and not ready_ok:
            test_pass = bool((test_to_develop or {}).get("test_pass"))
            reason = (
                ["TEST_PASS alone cannot set READY_FOR_REVIEW", gate_reason]
                if test_pass
                else [gate_reason]
            )
            extras = {
                "develop_to_test": develop_to_test,
                "test_to_develop": test_to_develop,
                "writes_applied": applied,
                "lifecycle": life_extras,
            }
            if should_publish:
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
                        extras=extras,
                    )
                life_hook = opts.get("before_lifecycle_task_publish")
                if callable(life_hook):
                    life_hook()
                progressed = publish_task(
                    resolved.path,
                    lifecycle_task,
                    expected_revision=ready_expected,
                )
                if progressed.ok and progressed.task is not None:
                    task = progressed.task
                    task_mutated = True
                    after = observe_candidate(self.root)
                    extras["task_publication"] = _publication_extras(progressed)
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
                extras=extras,
            )
        if should_publish:
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
            ready_hook = opts.get("before_ready_task_publish")
            life_hook = opts.get("before_lifecycle_task_publish")
            if callable(life_hook):
                life_hook()
            if callable(ready_hook):
                ready_hook()
            second = publish_task(
                resolved.path, lifecycle_task, expected_revision=ready_expected
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
                        "lifecycle": life_extras,
                    },
                )
            task = second.task
            task_mutated = True
            after = observe_candidate(self.root)
            if not after.usable:
                return self._blocked(
                    mode,
                    list(after.data.get("blockers") or [
                        "candidate SCM observation failed after Task publication"
                    ]),
                    "human",
                    candidate=after,
                    project=project,
                    task=task,
                    session=session,
                    session_directory=bound.directory,
                    writes_applied=applied,
                    task_mutated=task_mutated,
                    extras={"scm_observation": after.data},
                )
            if task.get("status") == "READY_FOR_REVIEW":
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
            if test_to_develop.get("target_stage_ids"):
                next_route = "develop.repair"
            else:
                next_route = "human"

        reconcile_session_changes(
            self.root,
            bound.directory,
            task=task,
            session=session,
        )
        reconcile_unexplained_drift(self.root, boundary="seal")
        physical = physical_authority_issues(self.root)
        if physical:
            return self._blocked(
                mode,
                physical,
                "stop",
                candidate=after,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
                writes_applied=applied,
                task_mutated=task_mutated,
            )
        provenance = execution_provenance_issues(
            self.root,
            task=task,
            session=session,
            directory=bound.directory,
            for_seal=True,
        )
        if provenance:
            return self._blocked(
                mode,
                provenance,
                "stop",
                candidate=after,
                project=project,
                task=task,
                session=session,
                session_directory=bound.directory,
                writes_applied=applied,
                task_mutated=task_mutated,
            )
        session = seal_session(self.root, bound.directory, session)
        session["sealed_candidate_digest"] = after.digest
        persist_session(bound.directory, session)
        clear_current_execution(
            self.root, session_id=str(session.get("record_id") or "")
        )
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
        extras["project_rules"] = project_rules
        extras["ownership_authority"] = list(plan.authority)
        extras["lifecycle"] = life_extras
        extras["consumed_published_report"] = bool(published_id)
        extras["repair_reopen"] = ready_repair
        extras["repair_view"] = reconstruct_repair_view(
            self.root, str(task["record_id"])
        )
        if mig is not None:
            extras["migration"] = mig.extras
            extras["post_compatibility"] = (mig.extras or {}).get("post_compatibility")
            extras["pre_compatibility"] = (mig.extras or {}).get("pre_compatibility")
            extras["current_compatibility"] = (mig.extras or {}).get(
                "current_compatibility"
            ) or (mig.extras or {}).get("post_compatibility")
        if test_result is not None:
            report = (getattr(test_result, "extras", {}) or {}).get("report")
            if isinstance(report, dict):
                extras["test_report_usable_for_current"] = report_usable_for(
                    report, after
                )
        if mig is not None:
            result_compatibility = (
                extras.get("current_compatibility")
                or extras.get("post_compatibility")
                or (self.preflight.compatibility if self.preflight else None)
            )
        else:
            result_compatibility = (
                self.preflight.compatibility if self.preflight else None
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
            compatibility=result_compatibility,
            extras=extras,
        )

    def _refresh_ready_authority(
        self,
        *,
        mode: str,
        opts: dict[str, Any],
        task: dict[str, Any],
        resolved,
        candidate,
        project: dict[str, Any] | None,
        published_id: str,
        write_paths: list[str],
        project_rules: dict[str, Any] | None,
    ):
        if write_paths or opts.get("writes"):
            return self._blocked(
                mode,
                ["READY authority refresh cannot request source writes"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"ready_authority_refresh": True},
            )
        if opts.get("invoke_test"):
            return self._blocked(
                mode,
                ["invoke_test and READY authority refresh are mutually exclusive"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"ready_authority_refresh": True},
            )
        if not published_id:
            return self._blocked(
                mode,
                ["READY authority refresh requires published_test_report_id"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"ready_authority_refresh": True},
            )
        if task.get("status") != "READY_FOR_REVIEW":
            return self._blocked(
                mode,
                ["READY authority refresh requires Task status READY_FOR_REVIEW"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"ready_authority_refresh": True},
            )
        test_package = (
            Path(opts["test_package"])
            if opts.get("test_package")
            else default_test_package(self.root)
        )
        test_result = consume_published_test_report(
            self.root,
            report_id=published_id,
            test_package=test_package,
            task=task,
        )
        if getattr(test_result, "outcome", None) != "COMPLETED":
            return self._blocked(
                mode,
                list(getattr(test_result, "blockers", None) or [
                    "published Test report cannot be consumed"
                ]),
                "test.scoped_verification",
                candidate=candidate,
                project=project,
                task=task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                },
            )
        from scaffold_p6.sav import reconstruct_sav_plan, task_contract_digest

        extras_loaded = getattr(test_result, "extras", {}) or {}
        if extras_loaded.get("test_pass") is not True:
            return self._blocked(
                mode,
                ["published Test report TEST_PASS is false; cannot refresh READY authority"],
                "test.scoped_verification",
                candidate=candidate,
                project=project,
                task=task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                },
            )
        if extras_loaded.get("test_complete") is not True:
            return self._blocked(
                mode,
                [
                    "published Test report TEST_COMPLETE is false; "
                    "cannot refresh READY authority"
                ],
                "test.scoped_verification",
                candidate=candidate,
                project=project,
                task=task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                },
            )
        contract = task_contract_digest(task)
        report = extras_loaded.get("report") if isinstance(extras_loaded.get("report"), dict) else {}
        sav_payload = extras_loaded.get("sav") if isinstance(extras_loaded.get("sav"), dict) else {}
        reconstruction = (
            sav_payload.get("reconstruction")
            if isinstance(sav_payload.get("reconstruction"), dict)
            else {}
        )
        plan = reconstruction.get("plan") if isinstance(reconstruction.get("plan"), dict) else None
        requirement_ids: list[str] = []
        explicit = str(opts.get("requirement_id") or reconstruction.get("requirement_id") or "").strip()
        if explicit:
            requirement_ids.append(explicit)
        for item in list(task.get("final_tests") or []):
            if isinstance(item, dict) and str(item.get("requirement_id") or "").strip():
                rid = str(item["requirement_id"]).strip()
                if rid not in requirement_ids:
                    requirement_ids.append(rid)
        for stage in task.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            for item in stage.get("required_tests") or []:
                if isinstance(item, dict) and str(item.get("requirement_id") or "").strip():
                    rid = str(item["requirement_id"]).strip()
                    if rid not in requirement_ids:
                        requirement_ids.append(rid)
        if plan is None:
            for requirement_id in requirement_ids:
                reconstructed = reconstruct_sav_plan(
                    self.root,
                    task_id=str(task.get("record_id") or ""),
                    requirement_id=requirement_id,
                    task=task,
                )
                if reconstructed.get("current") and isinstance(reconstructed.get("plan"), dict):
                    plan = reconstructed.get("plan")
                    break
        if isinstance(plan, dict):
            bound = str(plan.get("task_contract_digest") or "").strip()
            if bound and bound != contract:
                return self._blocked(
                    mode,
                    ["published SAV task_contract_digest does not match the current Task"],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={
                        "consumed_published_report": True,
                        "ready_authority_refresh": True,
                    },
                )
        refreshed, refresh_blockers = apply_ready_authority_refresh(
            task,
            root=self.root,
            candidate_digest=candidate.digest,
            test_result=test_result,
        )
        if refresh_blockers:
            return self._blocked(
                mode,
                refresh_blockers,
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                },
            )
        if task_contract_digest(refreshed) != contract:
            return self._blocked(
                mode,
                ["READY authority refresh cannot change the Task verification contract"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                },
            )
        expected = task_revision(task)
        if expected is None:
            return self._blocked(
                mode,
                ["Task Book record_revision is UNKNOWN"],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"ready_authority_refresh": True},
            )
        progressed = publish_task(
            resolved.path, refreshed, expected_revision=expected
        )
        if not progressed.ok or progressed.task is None:
            return self._blocked(
                mode,
                progressed.blockers,
                "stop",
                candidate=candidate,
                project=project,
                task=progressed.task or task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                    "task_publication": _publication_extras(progressed),
                },
            )
        published_task = progressed.task
        after = observe_candidate(self.root)
        if not after.usable or after.digest != candidate.digest:
            return self._blocked(
                mode,
                [
                    "READY authority refresh publication changed substantive "
                    "candidate authority"
                ],
                "stop",
                candidate=after,
                project=project,
                task=published_task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                    "task_publication": _publication_extras(progressed),
                },
            )
        if task_contract_digest(published_task) != contract:
            return self._blocked(
                mode,
                ["READY authority refresh cannot change the Task verification contract"],
                "stop",
                candidate=after,
                project=project,
                task=published_task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                    "task_publication": _publication_extras(progressed),
                },
            )
        ready_ok, ready_reason = ready_for_review_gates(
            published_task, candidate_digest=after.digest, root=self.root
        )
        if not ready_ok:
            return self._blocked(
                mode,
                [
                    "READY authority refresh did not restore current completion "
                    f"authority: {ready_reason}"
                ],
                "stop",
                candidate=after,
                project=project,
                task=published_task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                    "task_publication": _publication_extras(progressed),
                },
            )
        reloaded = consume_published_test_report(
            self.root,
            report_id=published_id,
            test_package=test_package,
            task=published_task,
        )
        if getattr(reloaded, "outcome", None) != "COMPLETED":
            return self._blocked(
                mode,
                list(getattr(reloaded, "blockers", None) or [
                    "published Test report is not consumable after READY authority refresh"
                ]),
                "test.scoped_verification",
                candidate=after,
                project=project,
                task=published_task,
                extras={
                    "consumed_published_report": True,
                    "ready_authority_refresh": True,
                    "task_publication": _publication_extras(progressed),
                },
            )
        test_to_develop = build_test_to_develop(
            task_id=str(published_task["record_id"]),
            session_id="",
            candidate_digest=after.digest,
            test_result=reloaded,
            task=published_task,
        )
        extras = self._result_extras(
            task=published_task,
            session=None,
            candidate=after,
            project=project,
            test_to_develop=test_to_develop,
        )
        extras["consumed_published_report"] = True
        extras["ready_authority_refresh"] = True
        extras["ready_revalidation"] = False
        extras["task_contract_digest"] = contract
        extras["task_publication"] = _publication_extras(progressed)
        extras["project_rules"] = project_rules
        extras["submit_handoff"] = build_submit_route(
            task_id=str(published_task["record_id"]),
            candidate_digest=after.digest,
        )
        extras["session"] = None
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="COMPLETED",
            baseline=after.data,
            mutations=_mutation_label([], True),
            artifacts=[str(resolved.path.as_posix())] if resolved.path else [],
            evidence=list(getattr(reloaded, "evidence", None) or []),
            next_route="submit",
            compatibility=(
                self.preflight.compatibility if self.preflight else None
            ),
            extras=extras,
        )

    def _intake_result(
        self,
        *,
        outcome: str,
        blockers: list[str],
        route: str,
        candidate,
        project: dict[str, Any] | None,
        human_gate: dict[str, Any],
        decision: IntakeDecision | None = None,
        proposal: dict[str, Any] | None = None,
        grounding: dict[str, Any] | None = None,
        project_rules: dict[str, Any] | None = None,
    ):
        task = decision.task if decision else None
        mutation = decision.mutation if decision else "none"
        task_path = decision.task_path if decision else ""
        extras = {
            "operation": "task_intake",
            "package": {
                "skill_id": SKILL_ID,
                "skill_version": self.skill_version,
                "modes": list(DEVELOP_MODES),
                "provides": list(PROVIDES),
                "requires": list(REQUIRES),
            },
            "project_reference": {
                "name": (project or {}).get("name"),
                "lifecycle": (project or {}).get("lifecycle"),
            },
            "candidate": {
                "candidate_digest": candidate.digest,
                "kind": candidate.kind,
                "observation_state": candidate.data.get("observation_state"),
                "observation_ok": candidate.data.get("observation_ok"),
            },
            "proposal": proposal,
            "proposal_digest": decision.proposal_digest if decision else "",
            "grounding": grounding,
            "project_rules": project_rules,
            "d1_currentness": self.d1_currentness,
            "task": (
                {
                    "record_id": task.get("record_id"),
                    "record_revision": task.get("record_revision"),
                    "status": task.get("status"),
                }
                if task
                else None
            ),
            "task_reused": bool(decision and decision.reused),
            "human_gate": human_gate,
            "submit_authorized": False,
            "capabilities": {
                "source_write": False,
                "commit": False,
                "push": False,
                "submit_authorized": False,
                "test_source_write": False,
                "understand_source_write": False,
            },
        }
        if self.preflight is not None:
            extras.update(self.preflight.extras())
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode="normal_task",
            outcome=outcome,
            baseline=candidate.data,
            mutations=mutation,
            artifacts=[task_path] if task_path else [],
            blockers=blockers,
            next_route=route,
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
        compatibility: str | None = None,
    ):
        if (
            session is not None
            and session_directory is not None
            and session.get("status") == "OPEN"
        ):
            reconcile_unexplained_drift(self.root, boundary="abort")
            session = abort_session(session_directory, session)
            clear_current_execution(
                self.root, session_id=str(session.get("record_id") or "")
            )
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
            compatibility=compatibility
            if compatibility is not None
            else (self.preflight.compatibility if self.preflight else None),
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
        if self.d1_currentness is not None:
            extras["d1_currentness"] = self.d1_currentness
        if task is not None:
            extras["task"] = {
                "record_id": task.get("record_id"),
                "status": task.get("status"),
                "record_revision": task.get("record_revision"),
                "task_complete": task_complete(task),
                "stages": [
                    {
                        "stage_id": row.get("stage_id"),
                        "status": row.get("status"),
                        "completion_decision": row.get("completion_decision"),
                    }
                    for row in (task.get("stages") or [])
                    if isinstance(row, dict)
                ],
                "task_completion_decision": task.get("task_completion_decision"),
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
                "observation_state": candidate.data.get("observation_state"),
                "observation_ok": candidate.data.get("observation_ok"),
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


def default_develop_package(host: str | Path | None = None) -> Path:
    return resolve_skill_package("develop", host=host, runtime_file=Path(__file__))


def _intake_scope_issues(
    root: Path,
    project: dict[str, Any],
    proposal: dict[str, Any],
) -> list[str]:
    issues = ownership_registry_issues(project.get("ownership"))
    scope = proposal.get("scope") or {}
    source_areas = list(project.get("source_areas") or [])
    for raw in scope.get("paths") or []:
        path = normalize_project_path(raw, area=False)
        if not path:
            issues.append(f"Task proposal path is invalid: {raw!r}")
            continue
        if path in CORE_MACHINE_ARTIFACTS or path.startswith(".scaffold/"):
            issues.append(f"Task proposal cannot directly scope core authority: {path}")
            continue
        ownership = resolve_ownership(project.get("ownership"), path)
        if ownership.status != "RESOLVED":
            issues.append(
                ownership.reason
                or f"Task proposal ownership is unresolved for {path}"
            )
        physical = root / path
        parent_known = physical.parent != root and physical.parent.exists()
        area_known = any(path_covered(path, area) for area in source_areas)
        if not physical.exists() and not parent_known and not area_known:
            issues.append(
                f"Task proposal path is not grounded in current project knowledge: {path}"
            )

    supporting = [
        normalize_project_path(raw, area=False)
        for raw in (scope.get("supporting_paths") or [])
    ]
    issues.extend(
        supporting_path_declaration_issues(
            [item for item in supporting if item],
            list(scope.get("paths") or []),
            root,
        )
    )
    tests = _read_rows(root / ".scaffold/tests.yaml", "profiles", issues)
    commands = _optional_index_rows(root / ".scaffold/commands.yaml", "commands")
    issues.extend(
        supporting_path_grounding_issues(
            root,
            [item for item in supporting if item],
            tests_rows=tests,
            commands_rows=commands,
        )
    )

    modules = _read_rows(root / ".scaffold/modules.yaml", "modules", issues)
    known_modules = {
        str(row.get("id") or row.get("name") or "")
        for row in modules
        if isinstance(row, dict)
    }
    for module in scope.get("modules") or []:
        if module not in known_modules:
            issues.append(
                f"Task proposal module is not grounded in modules.yaml: {module}"
            )

    known_tests = {
        str(row.get("id") or "")
        for row in tests
        if isinstance(row, dict) and row.get("id")
    }
    for profile_id in _proposal_bound_profile_ids(proposal):
        if profile_id not in known_tests:
            issues.append(
                "Task proposal execution_binding.profile_id is not "
                f"grounded in tests.yaml: {profile_id}"
            )
    return sorted(set(issues))


def _read_rows(
    path: Path,
    field: str,
    issues: list[str],
) -> list[dict[str, Any]]:
    if not path.is_file():
        issues.append(f"required project knowledge is missing: {path.name}")
        return []
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        issues.append(f"required project knowledge is unreadable: {path.name}")
        return []
    rows = data.get(field) if isinstance(data, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        issues.append(f"required project knowledge is malformed: {path.name}#{field}")
        return []
    return list(rows)


def _optional_index_rows(path: Path, field: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return []
    rows = data.get(field) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _requests_satisfied_completion(opts: dict[str, Any]) -> bool:
    if opts.get("request_stage_complete"):
        return True
    for key in ("stage_completion_decision", "task_completion_decision"):
        spec = opts.get(key)
        if isinstance(spec, dict) and spec.get("outcome") == "SATISFIED":
            return True
    return False


def _proposal_bound_profile_ids(proposal: dict[str, Any]) -> list[str]:
    """Return explicit test_profile bindings only. Unbound requirement_ids are not profiles."""
    ids: set[str] = set()
    for item in _proposal_test_refs(proposal):
        binding = item.get("execution_binding")
        if not isinstance(binding, dict):
            continue
        if binding.get("kind") != "test_profile":
            continue
        profile_id = str(binding.get("profile_id") or "").strip()
        if profile_id:
            ids.add(profile_id)
    return sorted(ids)


def _proposal_test_refs(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in proposal.get("final_tests") or []:
        if isinstance(item, dict):
            refs.append(item)
    for stage in proposal.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        for item in stage.get("required_tests") or []:
            if isinstance(item, dict):
                refs.append(item)
    return refs


def _intake_gate(
    observed: str,
    stopped: str,
    action: str,
    approved: str,
) -> dict[str, str]:
    return {
        "observed": observed,
        "why_stopped": stopped,
        "human_action_required": action,
        "if_approved": approved,
        "remains_unchanged": (
            "No source, Commit, Push, Submit authorization, or project governance "
            "is changed by this Task Intake result."
        ),
    }


def default_test_package(host: str | Path | None = None) -> Path:
    return resolve_skill_package("test", host=host, runtime_file=Path(__file__))


def _candidate_after_publication(root: Path, publication, previous):
    return observe_candidate(root)


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

"""Submit Skill orchestration. Reviews the real candidate. Does not become Develop."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import threading

from scaffold_p5.packages import load_package, resolve_skill_package
from scaffold_p5.result import skill_result
from scaffold_p5.rules import resolve_project_rules, rule_test_ids
from scaffold_p5.scm import DIVERGED, STALE, observe_upstream_currentness
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.engine import TestEngine
from scaffold_p7.tasks import ready_for_review_gates, resolve_task, task_complete
from scaffold_p7.unexplained import (
    STATE_AUTHORITY_UNUSABLE,
    inspect_drift_authority,
    reconcile_unexplained_drift,
)

from scaffold_p8.cleanup import cleanup_sessions
from scaffold_p8.completeness import evaluate_completeness
from scaffold_p8.delta import classify_delta, load_sealed_sessions, observe_real_diff
from scaffold_p8.finalize import finalize_s10, reconcile_index_transactions
from scaffold_p8.handoff import executable_repair_route, nonrepairable_scope_paths
from scaffold_p8.knowledge import evaluate_knowledge
from scaffold_p8.lock_review import evaluate_skills_lock_review_authority
from scaffold_p8.models import PROVIDES, REQUIRES, SKILL_ID
from scaffold_p8.orphan_recovery import (
    apply_abandon_pre_durable_change,
    build_abandon_pre_durable_plan,
)
from scaffold_p8.preflight import (
    SubmitPreflight,
    evaluate_submit_preflight,
    inspect_host_project,
)
from scaffold_p8.push import push_if_authorized
from scaffold_p8.records import (
    build_change_record,
    durability_state,
    frozen_cleanup_session_ids,
    is_durable,
    load_change_record,
    load_durable_change_record,
    new_change_id,
    persist_candidate_change,
    remove_non_durable_change_record,
    scm_base_value,
)
from scaffold_p8.structural import missing_scoped_source, review_structure
from scaffold_p8.task_authority import resolve_submit_task_authority


class SubmitEngine:
    def __init__(
        self,
        host_root: str | Path,
        package_root: str | Path | None = None,
    ):
        self.root = Path(host_root)
        self.package_root = (
            Path(package_root) if package_root else default_submit_package(self.root)
        )
        self.skill_version = ""
        self.preflight: SubmitPreflight | None = None
        self.project_rules: dict[str, Any] | None = None
        self.s7_currentness: dict[str, Any] | None = None
        if self.package_root.exists():
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version

    def run(self, mode: str = "", **opts: Any):
        self.project_rules = None
        self.s7_currentness = None
        opts.pop("authorization_provider", None)
        opts.pop("approval_origin", None)
        opts.pop("submit_authorization_ref", None)
        opts.pop("submit_authorization_attempt_id", None)
        opts.pop("push_authorization_ref", None)
        opts.pop("push_authorization_attempt_id", None)
        opts.pop("knowledge_assessment", None)
        if opts.get("cleanup_retry") or mode == "cleanup_retry":
            return self._cleanup_retry(mode=mode or "cleanup_retry", **opts)
        if opts.get("abandon_pre_durable_change") or mode == "abandon_pre_durable_change":
            return self._abandon_pre_durable_change(
                mode=mode or "abandon_pre_durable_change",
                **opts,
            )
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
        test_package = (
            Path(opts["test_package"])
            if opts.get("test_package")
            else default_test_package(self.root)
        )
        test_engine = TestEngine(self.root, test_package)
        candidate = observe_candidate(self.root)
        if not self.preflight.allowed:
            return self._blocked(
                list(self.preflight.blockers),
                self.preflight.route or "understand.compatibility",
                candidate=candidate,
                project=project,
            )
        reconciliation = self._reconcile_materializations(test_engine)
        if reconciliation:
            return self._blocked(
                reconciliation,
                "understand.refresh",
                project=project,
                extras={"stage": "S1", "materialization_recovery": "required"},
            )
        candidate = observe_candidate(self.root)
        if not candidate.usable:
            return self._blocked(
                list(candidate.data.get("blockers") or [
                    "candidate SCM observation is unresolved"
                ]),
                "stop",
                candidate=candidate,
                project=project,
                extras={"stage": "S1", "scm_observation": candidate.data},
            )

        caller_prose = opts.get("task_text", opts.get("goal_override"))
        real_diff = observe_real_diff(self.root)
        if not real_diff.get("ok"):
            return self._blocked(
                list(real_diff.get("blockers") or ["real Diff is UNKNOWN"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                extras={"stage": "S2", "real_diff": real_diff},
            )
        real_paths = list(real_diff.get("paths") or [])
        inspected = inspect_drift_authority(self.root)
        if inspected.get("state") == STATE_AUTHORITY_UNUSABLE:
            return self._blocked(
                list(inspected.get("blockers") or ["durable drift authority is unusable"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                extras={"stage": "S2", "drift_authority": inspected},
            )
        reconciled = reconcile_unexplained_drift(self.root, boundary="submit_s2")
        if not reconciled.get("ok"):
            return self._blocked(
                list(reconciled.get("blockers") or ["durable drift authority is unusable"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                extras={"stage": "S2", "drift_authority": reconciled},
            )
        authority = resolve_submit_task_authority(
            self.root,
            task_id=opts.get("task_id"),
            caller_prose=caller_prose,
            real_paths=real_paths,
        )
        if not authority.ok:
            return self._blocked(
                authority.blockers,
                authority.route or "stop",
                candidate=candidate,
                project=project,
                extras={"stage": "S1", "no_task": authority.no_task},
            )
        task = authority.task
        if task is not None and task.get("status") != "READY_FOR_REVIEW":
            return self._blocked(
                [
                    f"Task Book status {task.get('status')!r} is incompatible with "
                    "Submit; READY_FOR_REVIEW is required"
                ],
                "stop",
                candidate=candidate,
                project=project,
                task=task,
                extras={"stage": "S1", "no_task": False, "ready_authority": False},
            )
        if task is not None:
            ready_ok, ready_reason = ready_for_review_gates(
                task, candidate_digest=candidate.digest, root=self.root
            )
            if not ready_ok:
                return self._blocked(
                    [
                        "Task Book READY_FOR_REVIEW is not current completion "
                        f"authority: {ready_reason}"
                    ],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={"stage": "S1", "no_task": False, "ready_authority": False},
                )

        linked_session_ids = {
            str(item) for item in ((task or {}).get("develop_session_ids") or [])
        }
        sessions = load_sealed_sessions(
            self.root, linked_ids=linked_session_ids
        )
        delta = classify_delta(
            self.root,
            real_paths=real_paths,
            sessions=sessions,
            entries=list(real_diff.get("entries") or []),
            task=task,
        )
        task_scope = (
            task.get("scope")
            if task is not None and isinstance(task.get("scope"), dict)
            else {}
        )
        self.project_rules = resolve_project_rules(
            self.root,
            project=project,
            skill_id="submit",
            paths=real_paths,
            modules=list(task_scope.get("modules") or []),
            test_ids=rule_test_ids(task=task, selected=opts.get("selected")),
            operation="source_write",
        )
        if not self.project_rules.get("ok"):
            return self._blocked(
                list(self.project_rules.get("blockers") or []),
                self.project_rules.get("route") or "understand.refresh",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S3",
                    "delta": delta,
                    "project_rules": self.project_rules,
                },
            )

        missing_source = missing_scoped_source(self.root, task)
        lock_review_authority = evaluate_skills_lock_review_authority(
            self.root,
            real_diff=real_diff,
            project=project,
            preflight=self.preflight,
        )
        structural = review_structure(
            root=self.root,
            task=task,
            real_diff=real_diff,
            project=project,
            lock_review_authority=lock_review_authority,
        )
        if missing_source:
            structural = dict(structural)
            structural["structural_review_pass"] = False
            structural["repair_required"] = list(missing_source)
            candidate = observe_candidate(self.root)
            if task is None:
                return self._blocked(
                    [
                        "substantive repair required; scoped source is missing: "
                        + ", ".join(missing_source)
                    ],
                    "human",
                    candidate=candidate,
                    project=project,
                    extras={
                        "stage": "S3",
                        "repair_handoff": None,
                        "delta": delta,
                        "structural": structural,
                    },
                )
            structural_blockers = [
                blocker
                for blocker in structural.get("blockers") or []
                if isinstance(blocker, str) and blocker
            ]
            undeclared_paths = [
                path
                for path in structural.get("undeclared") or []
                if isinstance(path, str) and path
            ]
            governance_paths = nonrepairable_scope_paths(
                self.root, project, undeclared_paths
            )
            other_blockers = [
                blocker
                for blocker in structural_blockers
                if "undeclared Task Book paths" not in blocker
            ]
            missing_blocker = (
                "substantive repair required; scoped source is missing: "
                + ", ".join(missing_source)
            )
            # A missing-source handoff is executable only when every other
            # structural finding is also repairable by that same handoff.
            # Governance paths and unrelated blockers stay on the stop route
            # with their text intact.
            if governance_paths or other_blockers:
                return self._blocked(
                    [missing_blocker, *structural_blockers],
                    "stop",
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={
                        "stage": "S3",
                        "repair_handoff": None,
                        "delta": delta,
                        "structural": structural,
                    },
                )
            route, handoff, blockers = executable_repair_route(
                task,
                candidate_digest=candidate.digest,
                blockers=[missing_blocker, *structural_blockers],
                missing_source=missing_source,
            )
            return self._blocked(
                blockers,
                route,
                candidate=candidate,
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
            undeclared_paths = [
                path
                for path in structural.get("undeclared") or []
                if isinstance(path, str) and path
            ]
            structural_blockers = [
                blocker
                for blocker in structural.get("blockers") or []
                if isinstance(blocker, str) and blocker
            ]
            governance_paths = nonrepairable_scope_paths(
                self.root, project, undeclared_paths
            )
            scope_escape_only = (
                task is not None
                and bool(undeclared_paths)
                and not governance_paths
                and len(structural_blockers) == 1
                and "undeclared Task Book paths" in structural_blockers[0]
            )
            if scope_escape_only:
                candidate = observe_candidate(self.root)
                route, handoff, blockers = executable_repair_route(
                    task,
                    candidate_digest=candidate.digest,
                    blockers=structural_blockers,
                    undeclared=undeclared_paths,
                )
                return self._blocked(
                    blockers,
                    route,
                    candidate=candidate,
                    project=project,
                    task=task,
                    extras={
                        "stage": "S3",
                        "repair_handoff": handoff,
                        "delta": delta,
                        "structural": structural,
                    },
                )
            return self._blocked(
                list(structural.get("blockers") or ["structural review blocked"]),
                "stop",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={"stage": "S3", "delta": delta, "structural": structural},
            )

        knowledge = evaluate_knowledge(
            root=self.root,
            project=project,
            maintenance=list(self.preflight.maintenance),
            structural=structural,
            real_diff=real_diff,
            real_paths=real_paths,
            caller_flags={
                "maintenance_required": opts.get("maintenance_required"),
                "knowledge_assessment_ref": opts.get("knowledge_assessment_ref"),
            },
        )
        if knowledge.get("route") == "understand.compatibility":
            return self._blocked(
                list(knowledge.get("blockers") or [
                    "knowledge/compatibility is stale or conflicting"
                ]),
                "understand.compatibility",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S4",
                    "delta": delta,
                    "structural": structural,
                    "knowledge": knowledge,
                },
            )
        if knowledge.get("needs_human") or knowledge.get("route") == "human":
            return self._blocked(
                list(knowledge.get("blockers") or [
                    "Knowledge Assessment requires human action"
                ]),
                "human",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S4",
                    "delta": delta,
                    "structural": structural,
                    "knowledge": knowledge,
                },
            )
        if knowledge.get("stale"):
            return self._blocked(
                list(knowledge.get("blockers") or [
                    "stale project knowledge requires Understand refresh"
                ]),
                "understand.refresh",
                candidate=observe_candidate(self.root),
                project=project,
                task=task,
                extras={
                    "stage": "S4",
                    "delta": delta,
                    "structural": structural,
                    "knowledge": knowledge,
                },
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
        completeness = evaluate_completeness(
            self.root,
            task=task,
            report=report if isinstance(report, dict) else None,
            invoke=bool(opts.get("invoke_test")),
            selected=list(opts.get("selected") or []),
            test_package=test_package,
            report_id=str(opts["report_id"]) if opts.get("report_id") else None,
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
        s5_candidate = observe_candidate(self.root)
        if completeness.get("required_fail"):
            if task is None:
                return self._blocked(
                    ["required FAIL cannot yield TEST_COMPLETE"],
                    "test.scoped_verification",
                    candidate=s5_candidate,
                    project=project,
                    extras={
                        "stage": "S5",
                        "completeness": _public_completeness(completeness),
                        "repair_handoff": None,
                    },
                )
            route, handoff, blockers = executable_repair_route(
                task,
                candidate_digest=s5_candidate.digest,
                blockers=["required FAIL cannot yield TEST_COMPLETE"],
                fail_ids=list(completeness.get("required_fail_profile_ids") or []),
            )
            return self._blocked(
                blockers,
                route,
                candidate=s5_candidate,
                project=project,
                task=task,
                extras={
                    "stage": "S5",
                    "completeness": _public_completeness(completeness),
                    "repair_handoff": handoff,
                },
            )
        if not completeness.get("test_complete"):
            s5_route = str(completeness.get("route") or "")
            if not s5_route or s5_route == "develop.repair":
                s5_route = "test.scoped_verification"
            authority_guidance = [
                blocker
                for blocker in completeness.get("authority_blockers") or []
                if isinstance(blocker, str) and blocker
            ]
            message = "TEST_COMPLETE does not hold; Submit stops at S5"
            if authority_guidance:
                message += "; " + " | ".join(authority_guidance)
            extras: dict[str, Any] = {
                "stage": "S5",
                "completeness": _public_completeness(completeness),
            }
            if authority_guidance:
                extras["authority_blockers"] = authority_guidance
            return self._blocked(
                [message],
                s5_route,
                candidate=s5_candidate,
                project=project,
                task=task,
                extras=extras,
            )

        want_s10 = bool(opts.get("request_s10") or opts.get("finalize"))
        reviewed = observe_candidate(self.root)
        if not reviewed.usable:
            return self._blocked(
                list(reviewed.data.get("blockers") or [
                    "reviewed candidate SCM observation is unresolved"
                ]),
                "human",
                candidate=reviewed,
                project=project,
                task=task,
                extras={"stage": "S6", "scm_observation": reviewed.data},
            )
        reviewed_currentness = observe_upstream_currentness(self.root)
        authorized = bool(want_s10)

        sync_hook = opts.get("before_s7") or opts.get("repository_sync")
        if callable(sync_hook):
            sync_hook()
        synced = observe_candidate(self.root)
        if not synced.usable:
            return self._blocked(
                list(synced.data.get("blockers") or [
                    "S7 candidate SCM observation is unresolved"
                ]),
                "human",
                candidate=synced,
                project=project,
                task=task,
                extras={
                    "stage": "S7",
                    "scm_observation": synced.data,
                    "submit_authorized": False,
                },
            )
        if synced.digest != reviewed.digest:
            return self._blocked(
                [
                    "material Repository Sync candidate change invalidates "
                    "the reviewed candidate; return to S3"
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
        currentness = observe_upstream_currentness(self.root)
        self.s7_currentness = currentness.public()
        if not currentness.ok:
            return self._blocked(
                list(currentness.blockers)
                or ["S7 repository currentness is UNKNOWN"],
                "human",
                candidate=synced,
                project=project,
                task=task,
                extras={
                    "stage": "S7",
                    "s7_currentness": self.s7_currentness,
                    "submit_authorized": False,
                },
            )
        basis_changed = (
            reviewed_currentness.ok
            and reviewed_currentness.basis_digest
            and currentness.basis_digest != reviewed_currentness.basis_digest
        )
        if currentness.state in {STALE, DIVERGED} or basis_changed:
            return self._blocked(
                [
                    "S7 repository basis changed or is not current; "
                    "the reviewed candidate is invalidated and review must return to S3"
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
                    "prior_currentness": reviewed_currentness.public(),
                    "s7_currentness": self.s7_currentness,
                    "submit_authorized": False,
                    "repair_handoff": None,
                },
            )

        if not want_s10:
            next_route = "caller"
            if completeness.get("required_fail"):
                if task is None:
                    next_route = "test.scoped_verification"
                else:
                    next_route, _handoff, _blockers = executable_repair_route(
                        task,
                        candidate_digest=synced.digest,
                        blockers=["required FAIL cannot yield TEST_COMPLETE"],
                        fail_ids=list(completeness.get("required_fail_profile_ids") or []),
                    )
            elif not completeness.get("test_complete"):
                next_route = "test.scoped_verification"
            extras = self._result_extras(
                task=task,
                candidate=synced,
                project=project,
                delta=delta,
                structural=structural,
                knowledge=knowledge,
                completeness=completeness,
                authorized=False,
                stage="S6",
            )
            extras["ready_for_human_approval"] = False
            extras["review_ready"] = True
            extras["s10_requested"] = False
            extras["s10_apply_intent"] = False
            extras["commit_requires_explicit_user_instruction"] = True
            extras["push_requires_explicit_user_instruction"] = True
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="COMPLETED",
                baseline=synced.data,
                mutations="none",
                next_route=next_route,
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=extras,
            )

        if task is not None and not task_complete(task):
            return self._blocked(
                ["TASK_COMPLETE does not hold; S10 is blocked"],
                "stop",
                candidate=synced,
                project=project,
                task=task,
            )

        record_id = str(opts.get("change_id") or new_change_id(self.root))
        kind, base_value = scm_base_value(self.root)
        frozen_session_ids = sorted(linked_session_ids)
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
            cleanup_session_ids=frozen_session_ids,
        )
        s10_gate = _finalization_lock(self.root)
        s10_gate.acquire()
        try:
            materialization: dict[str, Any] | None = None
            change_path: Path | None = None
            evidence_refs = list(
                (record.get("verification") or {}).get("evidence_refs") or []
            )
            before_s9 = opts.get("before_s9_materialization")
            if callable(before_s9):
                before_s9()
            if evidence_refs:
                materialization, materialize_blockers = test_engine.materialize_evidence(
                    evidence_refs,
                    coordination_id=record_id,
                )
                if materialization is None:
                    recovery = self._abort_pre_durable_s9(
                        test_engine,
                        record_id=record_id,
                        change_path=None,
                        materialized=True,
                    )
                    return self._pre_durable_blocked(
                        materialize_blockers,
                        "understand.refresh",
                        candidate=observe_candidate(self.root),
                        project=project,
                        task=task,
                        record=record,
                        recovery=recovery,
                        extras={"materialization": {"ok": False}},
                    )
            if opts.get("fail_change_record_persist"):
                recovery = self._abort_pre_durable_s9(
                    test_engine,
                    record_id=record_id,
                    change_path=None,
                    materialized=materialization is not None,
                )
                return self._pre_durable_blocked(
                    ["Change Record persistence failed"],
                    "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    record=record,
                    recovery=recovery,
                )
            persisted, persist_blockers, change_path = persist_candidate_change(
                self.root, record
            )
            if not persisted or change_path is None:
                recovery = self._abort_pre_durable_s9(
                    test_engine,
                    record_id=record_id,
                    change_path=None,
                    materialized=materialization is not None,
                )
                return self._pre_durable_blocked(
                    persist_blockers,
                    "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    record=record,
                    recovery=recovery,
                )
            after_s9 = observe_candidate(self.root)
            if not after_s9.usable:
                recovery = self._abort_pre_durable_s9(
                    test_engine,
                    record_id=record_id,
                    change_path=change_path,
                    materialized=materialization is not None,
                )
                return self._pre_durable_blocked(
                    list(after_s9.data.get("blockers") or [
                        "S9 candidate SCM observation is unresolved"
                    ]),
                    "human",
                    candidate=after_s9,
                    project=project,
                    task=task,
                    record=record,
                    recovery=recovery,
                    extras={"scm_observation": after_s9.data},
                )
            finalization_digest = after_s9.digest
            support_artifacts = [
                {"path": str(row.get("path")), "digest": str(row.get("digest"))}
                for row in (materialization or {}).get("artifacts") or []
                if isinstance(row, dict) and row.get("path") and row.get("digest")
            ]
            before_s10 = opts.get("before_s10")
            if callable(before_s10):
                before_s10()
            if opts.get("fail_pre_s10_authorization"):
                recovery = self._abort_pre_durable_s9(
                    test_engine,
                    record_id=record_id,
                    change_path=change_path,
                    materialized=materialization is not None,
                )
                return self._pre_durable_blocked(
                    ["S10 finalization was interrupted before durable apply"],
                    "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    record=record,
                    recovery=recovery,
                    stage="S10",
                    extras={
                        "s10": {"ok": False, "durable": False},
                        "s10_durable": False,
                        "durable_finalization_occurred": False,
                    },
                )
            if opts.get("fail_s10"):
                recovery = (
                    test_engine.abort_materialization(record_id)
                    if materialization is not None
                    else {"ok": True, "blockers": []}
                )
                return self._blocked(
                    ["S10 failed; Finalization Bundle remains non-durable"]
                    + list(recovery.get("blockers") or []),
                    "stop",
                    candidate=observe_candidate(self.root),
                    project=project,
                    task=task,
                    extras={
                        "stage": "S10",
                        "change_record": record,
                        "s9_durable": False,
                        "s10": {
                            "ok": False,
                            "durable": False,
                            "reviewed_candidate_digest": reviewed.digest,
                            "finalization_candidate_digest": finalization_digest,
                        },
                        "materialization": recovery,
                        "mutations": "change_record",
                    },
                    mutations="change_record",
                )
            s10 = finalize_s10(
                self.root,
                record_id=record_id,
                change_rel=change_path.relative_to(self.root).as_posix(),
                reviewed_paths=real_paths,
                expected_digest=finalization_digest,
                scm_kind=kind,
                expected_parent=base_value if kind == "git" else None,
                reviewed_entries=list(real_diff.get("entries") or []),
                support_artifacts=support_artifacts,
                after_commit=opts.get("after_s10_commit"),
                during_s10=opts.get("during_s10"),
                fail_before_complete=bool(opts.get("fail_before_complete")),
                fail_baseline_cache=bool(opts.get("fail_baseline_cache")),
            )
            s10["reviewed_candidate_digest"] = reviewed.digest
            s10["finalization_candidate_digest"] = finalization_digest
            s10["support_artifacts"] = support_artifacts
            materialization_transition = {"ok": True, "blockers": []}
            if materialization is not None:
                rollback = s10.get("index_rollback")
                rollback_blocks_abort = (
                    s10.get("index_mutated") is True
                    and (
                        not isinstance(rollback, dict)
                        or rollback.get("ok") is not True
                    )
                )
                if s10.get("durable"):
                    materialization_transition = test_engine.release_materialization(
                        record_id
                    )
                elif rollback_blocks_abort:
                    materialization_transition = {
                        "ok": False,
                        "aborted": False,
                        "preserved": True,
                        "blockers": [
                            "P6 PREPARED materialization is preserved until "
                            "P8 index recovery reconciliation succeeds"
                        ],
                    }
                else:
                    materialization_transition = test_engine.abort_materialization(
                        record_id
                    )
                if not materialization_transition.get("ok"):
                    s10["blockers"] = list(s10.get("blockers") or []) + list(
                        materialization_transition.get("blockers") or []
                    )
                    if s10.get("durable"):
                        s10["ok"] = False
            if s10.get("durable"):
                reconcile_unexplained_drift(self.root, boundary="s10")
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
                        "materialization": materialization_transition,
                    },
                    mutations="change_record",
                )

        finally:
            s10_gate.release()
        push_requested = bool(opts.get("request_push"))
        before_s11 = opts.get("before_s11")
        if callable(before_s11):
            before_s11()
        push = push_if_authorized(
            self.root,
            authorized=push_requested,
            scm_kind=s10.get("kind") or "none",
            s10_ok=True,
            expected_commit=s10.get("commit"),
            expected_branch=s10.get("branch"),
            simulate_failure=bool(opts.get("fail_push")),
        )
        fail_cleanup_sessions = opts.get("fail_cleanup_sessions")
        fail_cleanup = bool(opts.get("fail_cleanup"))
        cleanup_targets = frozen_cleanup_session_ids(record)
        if cleanup_targets is None:
            cleanup_targets = list(frozen_session_ids)
        cleanup = cleanup_sessions(
            self.root,
            task=task,
            s10_ok=True,
            target_session_ids=cleanup_targets,
            fail_session_ids=fail_cleanup_sessions,
            fail_all=fail_cleanup,
        )
        final_candidate = observe_candidate(self.root)
        s11_unresolved = bool(push_requested) and not push.get("ok")
        cleanup_failed = bool(cleanup.get("performed")) and not cleanup.get("ok", True)
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
                "S12"
                if cleanup_failed
                else (
                    "S11"
                    if s11_unresolved
                    else ("S12" if cleanup.get("performed") else "S10")
                )
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
                "materialization": {
                    **materialization_transition,
                    "support_artifacts": support_artifacts,
                },
                "submit_authorized": True,
            }
        )
        extras["review_ready"] = True
        extras["s10_requested"] = True
        extras["s10_apply_intent"] = True
        extras["commit_requires_explicit_user_instruction"] = True
        extras["push_requires_explicit_user_instruction"] = True
        extras["durable_finalization_occurred"] = True
        durable_artifacts = [change_path.as_posix()] + [
            (self.root / item["path"]).as_posix()
            for item in support_artifacts
        ]
        if not final_candidate.usable:
            extras["submit_authorized"] = False
            extras["post_finalization_verification"] = "unresolved"
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="BLOCKED",
                baseline=final_candidate.data,
                mutations="durable_finalization",
                artifacts=durable_artifacts,
                blockers=list(final_candidate.data.get("blockers") or [
                    "post-finalization candidate SCM observation is unresolved"
                ]),
                next_route="human",
                compatibility=self.preflight.compatibility
                if self.preflight
                else None,
                extras=extras,
            )
        if cleanup_failed:
            extras["cleanup_retry_required"] = True
            extras["cleanup_retry"] = {
                "operation": "cleanup_retry",
                "change_id": record_id,
            }
            extras["s10_durable"] = True
            extras["durable_finalization_occurred"] = True
            extras["stage"] = "S12"
            blockers = list(cleanup.get("blockers") or ["S12 cleanup failed"])
            if s11_unresolved:
                blockers.append(
                    str(
                        push.get("reason")
                        or "authorized S11 could not publish the exact S10 target"
                    )
                )
            outcome = (
                "NEEDS_HUMAN" if cleanup.get("needs_human") else "BLOCKED"
            )
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome=outcome,
                baseline=final_candidate.data,
                mutations="durable_finalization",
                artifacts=durable_artifacts,
                blockers=blockers,
                next_route="submit",
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=extras,
            )
        if s11_unresolved:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="BLOCKED",
                baseline=final_candidate.data,
                mutations="durable_finalization",
                artifacts=durable_artifacts,
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
            mutations="durable_finalization",
            artifacts=durable_artifacts,
            next_route="caller",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _abandon_pre_durable_change(self, *, mode: str, **opts: Any):
        spec = opts.get("abandon_pre_durable_change")
        if spec is True:
            spec = {}
        if not isinstance(spec, dict):
            spec = {}
        change_id = str(spec.get("change_id") or opts.get("change_id") or "")
        project_status, _reasons, project = inspect_host_project(self.root)
        plan = build_abandon_pre_durable_plan(self.root, change_id=change_id)
        extras = {
            "stage": "pre_durable_recovery",
            "abandon_pre_durable_plan": plan,
            "plan_digest": plan.get("digest"),
            "s10_durable": bool((plan.get("durability") or {}).get("s10_durable")),
            "durable_finalization_occurred": False,
        }
        if not plan.get("valid"):
            return self._blocked(
                list(plan.get("blockers") or ["orphan recovery is blocked"]),
                "human",
                project=project,
                extras=extras,
            )
        approval = spec.get("approval") or opts.get("approval")
        if not approval or not approval.get("approved"):
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="NEEDS_HUMAN",
                mutations="none",
                blockers=["explicit pre-durable Change Record recovery approval is required"],
                next_route="review orphan recovery plan",
                extras=extras,
            )
        if (approval.get("plan_digest") or approval.get("digest")) != plan["digest"]:
            return self._blocked(
                ["approved orphan recovery Plan does not match the current host"],
                "human",
                project=project,
                extras=extras,
            )
        applied = apply_abandon_pre_durable_change(self.root, plan)
        extras["abandon_pre_durable"] = {
            "ok": applied.get("ok"),
            "applied": applied.get("applied"),
            "plan_digest": (applied.get("plan") or {}).get("digest"),
            "current_candidate_digest": applied.get("current_candidate_digest"),
        }
        extras["abandon_pre_durable_plan"] = applied.get("plan") or plan
        if not applied.get("ok"):
            return self._blocked(
                list(applied.get("blockers") or ["orphan recovery could not be applied"]),
                "human",
                project=project,
                extras=extras,
                mutations="partial" if applied.get("applied") else "none",
            )
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="COMPLETED",
            mutations="bounded",
            artifacts=list(applied.get("artifacts") or []),
            next_route="submit",
            extras=extras,
        )

    def _cleanup_retry(self, *, mode: str, **opts: Any):
        spec = opts.get("cleanup_retry")
        if spec is True:
            spec = {}
        if not isinstance(spec, dict):
            spec = {}
        change_id = str(spec.get("change_id") or opts.get("change_id") or "")
        project_status, _reasons, project = inspect_host_project(self.root)
        self.preflight = evaluate_submit_preflight(
            self.root,
            package_root=self.package_root,
            project=project,
            project_status=project_status,
        )
        if not self.preflight.allowed:
            return self._blocked(
                list(self.preflight.blockers),
                "stop",
                project=project,
                extras={"stage": "S12"},
            )
        if not change_id:
            return self._blocked(
                ["cleanup retry requires a durable Change Record identity"],
                "human",
                project=project,
                extras={"stage": "S12", "cleanup_retry_required": True},
            )
        if not is_durable(self.root, change_id):
            state = durability_state(self.root, change_id)
            return self._blocked(
                list(state.get("blockers") or [
                    "cleanup retry cannot prove durable S10"
                ]),
                "human",
                project=project,
                extras={
                    "stage": "S12",
                    "s10_durable": False,
                    "durable_finalization_occurred": False,
                    "cleanup": {"performed": False, "ok": False},
                },
            )
        record = load_durable_change_record(self.root, change_id)
        if not isinstance(record, dict):
            return self._blocked(
                ["cleanup retry cannot load the durable Change Record"],
                "human",
                project=project,
                extras={
                    "stage": "S12",
                    "s10_durable": True,
                    "durable_finalization_occurred": True,
                },
            )
        frozen = frozen_cleanup_session_ids(record)
        if frozen is None:
            return self._blocked(
                ["cleanup retry cannot resolve the frozen S12 cleanup target set"],
                "human",
                project=project,
                extras={
                    "stage": "S12",
                    "s10_durable": True,
                    "durable_finalization_occurred": True,
                    "cleanup_retry_required": True,
                    "cleanup_retry": {
                        "operation": "cleanup_retry",
                        "change_id": change_id,
                    },
                },
            )
        task_ids = [
            str(item)
            for item in (record.get("task_book_ids") or [])
            if isinstance(item, str)
        ]
        cleanup_task = {"record_id": task_ids[0]} if task_ids else None
        if task_ids:
            resolved = resolve_task(self.root, task_id=task_ids[0])
            if resolved.ok and resolved.task is not None:
                if str(resolved.task.get("record_id") or "") != task_ids[0]:
                    return self._blocked(
                        ["cleanup retry Task Book identity conflicts with the Change Record"],
                        "human",
                        project=project,
                        extras={
                            "stage": "S12",
                            "s10_durable": True,
                            "durable_finalization_occurred": True,
                            "cleanup_retry_required": True,
                            "cleanup_retry": {
                                "operation": "cleanup_retry",
                                "change_id": change_id,
                            },
                        },
                    )
            elif any(
                "malformed" in item or "unreadable" in item
                for item in (resolved.blockers or [])
            ):
                return self._blocked(
                    list(resolved.blockers)
                    or ["cleanup retry cannot validate Task Book identity"],
                    "human",
                    project=project,
                    extras={
                        "stage": "S12",
                        "s10_durable": True,
                        "durable_finalization_occurred": True,
                        "cleanup_retry_required": True,
                        "cleanup_retry": {
                            "operation": "cleanup_retry",
                            "change_id": change_id,
                        },
                    },
                )
        cleanup = cleanup_sessions(
            self.root,
            task=cleanup_task,
            s10_ok=True,
            target_session_ids=frozen,
            fail_session_ids=opts.get("fail_cleanup_sessions"),
            fail_all=bool(opts.get("fail_cleanup")),
        )
        extras = {
            "stage": "S12",
            "s10_durable": True,
            "durable_finalization_occurred": True,
            "cleanup": cleanup,
            "cleanup_retry": {
                "operation": "cleanup_retry",
                "change_id": change_id,
            },
            "change_record": record,
            "submit_authorized": False,
            "submit_authorized_persisted": False,
        }
        if not cleanup.get("ok", True):
            extras["cleanup_retry_required"] = True
            outcome = "NEEDS_HUMAN" if cleanup.get("needs_human") else "BLOCKED"
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome=outcome,
                mutations="none",
                blockers=list(cleanup.get("blockers") or ["S12 cleanup failed"]),
                next_route="submit",
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=extras,
            )
        extras["cleanup_retry_required"] = False
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="COMPLETED",
            mutations="none",
            next_route="caller",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _reconcile_materializations(self, engine: TestEngine) -> list[str]:
        blockers = reconcile_index_transactions(self.root)
        if blockers:
            return blockers
        for prepared in engine.prepared_materializations():
            if prepared.get("malformed"):
                blockers.extend(
                    list(prepared.get("issues") or [])
                    or [
                        "P6 PREPARED materialization is malformed; "
                        "manual reconciliation is required"
                    ]
                )
                continue
            coordination_id = str(prepared.get("coordination_id") or "")
            state = durability_state(self.root, coordination_id)
            if state.get("state") == "durable":
                result = engine.release_materialization(coordination_id)
            elif state.get("state") == "absent":
                result = engine.abort_materialization(coordination_id)
            else:
                blockers.extend(
                    list(state.get("blockers") or [])
                    or [
                        f"materialization durability for {coordination_id!r} "
                        "requires reconciliation"
                    ]
                )
                continue
            if not result.get("ok"):
                blockers.extend(list(result.get("blockers") or []))
        return sorted(set(blockers))

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
        durable_artifacts = [change_path.as_posix()] + [
            (self.root / str(item.get("path"))).as_posix()
            for item in s10.get("support_artifacts") or []
            if isinstance(item, dict) and item.get("path")
        ]
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode="",
            outcome="BLOCKED",
            baseline=candidate.data if candidate is not None else None,
            mutations="durable_finalization",
            artifacts=durable_artifacts,
            blockers=list(s10.get("blockers") or ["S10 post-Commit verification is unresolved"]),
            next_route="human",
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def _abort_pre_durable_s9(
        self,
        test_engine: TestEngine,
        *,
        record_id: str,
        change_path: Path | None,
        materialized: bool,
    ) -> dict[str, Any]:
        materialization = {"ok": True, "aborted": False, "blockers": []}
        if materialized:
            materialization = test_engine.abort_materialization(record_id)
        change_rollback = {"ok": True, "removed": False, "blockers": []}
        if change_path is not None and change_path.is_file():
            change_rollback = remove_non_durable_change_record(
                self.root,
                record_id,
            )
        remaining = bool(change_path is not None and change_path.is_file())
        proven = (
            materialization.get("ok") is True
            and change_rollback.get("ok") is True
            and not remaining
        )
        blockers = list(materialization.get("blockers") or []) + list(
            change_rollback.get("blockers") or []
        )
        if remaining:
            blockers.append(
                "pre-durable Change Record remains after bounded rollback"
            )
        return {
            "ok": proven,
            "proven": proven,
            "blockers": blockers,
            "materialization": materialization,
            "change_record": change_rollback,
            "finalization_recovery_required": not proven,
        }

    def _pre_durable_blocked(
        self,
        blockers: list[str],
        route: str,
        *,
        candidate=None,
        project: dict[str, Any] | None = None,
        task: dict[str, Any] | None = None,
        record: dict[str, Any] | None = None,
        recovery: dict[str, Any] | None = None,
        extras: dict[str, Any] | None = None,
        stage: str = "S9",
    ):
        recovery = recovery or {"ok": True, "blockers": [], "proven": True}
        payload = {
            "stage": stage,
            "s9_durable": False,
            "s10": {"ok": False, "durable": False},
            "pre_durable_abort": recovery,
            "finalization_recovery_required": bool(
                recovery.get("finalization_recovery_required")
            ),
            "materialization": recovery.get("materialization") or {"ok": True},
        }
        if record is not None:
            payload["change_record"] = record
        if extras:
            payload.update(extras)
        payload["mutations"] = "none" if recovery.get("ok") else "partial"
        return self._blocked(
            list(blockers) + list(recovery.get("blockers") or []),
            route,
            candidate=candidate,
            project=project,
            task=task,
            extras=payload,
            mutations="none" if recovery.get("ok") else "partial",
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
            "task_complete": (
                "NOT_APPLICABLE" if task is None else task_complete(task)
            ),
            "ready_for_review": (
                "NOT_APPLICABLE"
                if task is None
                else bool(task.get("status") == "READY_FOR_REVIEW")
            ),
            "task_book_ids": (
                []
                if task is None or not task.get("record_id")
                else [str(task.get("record_id"))]
            ),
            "task_identity": "none" if task is None else "task",
            "no_task": task is None,
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
        if self.project_rules is not None:
            extras["project_rules"] = self.project_rules
        if candidate is not None:
            extras["candidate"] = {
                "candidate_digest": candidate.digest,
                "kind": candidate.kind,
                "observation_state": candidate.data.get("observation_state"),
                "observation_ok": candidate.data.get("observation_ok"),
            }
        if self.s7_currentness is not None:
            extras["s7_currentness"] = self.s7_currentness
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
                "unknown_ownership": structural.get("unknown_ownership"),
                "conflicting_ownership": structural.get("conflicting_ownership"),
                "ownership_authority": structural.get("ownership_authority"),
                "impacts": structural.get("impacts") or [],
                "impact_classes": structural.get("impact_classes") or [],
                "reviewed_paths": structural.get("reviewed_paths") or [],
                "structural_unknown": structural.get("structural_unknown"),
                "skills_lock_review_authority": structural.get(
                    "skills_lock_review_authority"
                )
                or {},
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


def default_submit_package(host: str | Path | None = None) -> Path:
    return resolve_skill_package("submit", host=host, runtime_file=Path(__file__))


_FINALIZATION_LOCKS: dict[str, threading.Lock] = {}
_FINALIZATION_LOCKS_GUARD = threading.Lock()


def _finalization_lock(root: Path) -> threading.Lock:
    key = str(Path(root).resolve())
    with _FINALIZATION_LOCKS_GUARD:
        lock = _FINALIZATION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FINALIZATION_LOCKS[key] = lock
        return lock


def default_test_package(host: str | Path | None = None) -> Path:
    return resolve_skill_package("test", host=host, runtime_file=Path(__file__))


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
        "evidence_refs": completeness.get("evidence_refs"),
        "task_required_ids": completeness.get("task_required_ids"),
        "project_required_ids": completeness.get("project_required_ids"),
        "proven_required_ids": completeness.get("proven_required_ids"),
        "uncovered_required_ids": completeness.get("uncovered_required_ids"),
        "required_fail_ids": completeness.get("required_fail_ids"),
        "required_fail_profile_ids": completeness.get("required_fail_profile_ids"),
        "blockers": completeness.get("blockers"),
        "authority_blockers": completeness.get("authority_blockers"),
        "route": completeness.get("route"),
    }

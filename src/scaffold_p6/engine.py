"""Test Skill orchestration. Consumes Understand knowledge. Does not refresh it."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.packages import load_package
from scaffold_p5.io_util import read_yaml
from scaffold_p5.ownership import normalize_project_path
from scaffold_p5.result import skill_result
from scaffold_p5.rules import resolve_project_rules

from scaffold_p6.adapter import resolve_adapter
from scaffold_p6.analysis import analyze, failure_summary, route
from scaffold_p6.candidate import candidates_match, observe_candidate, report_usable_for
from scaffold_p6.contract import (
    adapter_supported,
    command_execution_allowed,
    inspect_host_project,
    project_blocks_execution,
    resolve_contract,
    resolve_project_working_directory,
    validate_selected,
)
from scaffold_p6.evidence import (
    compile_local_evidence,
    compile_supplied_bundle,
    compile_supplied_sav_item,
    local_execution_permitted,
    observation_dict,
    preserve_verification_truth,
    scenario_from_observation,
)
from scaffold_p6.models import (
    PROVIDES,
    RECORD_CLASS,
    REPORT_SCHEMA_VERSION,
    REQUIRES,
    SKILL_ID,
    SUPPORT_KIND,
    TEST_MODES,
    CandidateIdentity,
    ContractResolution,
    Profile,
    ScenarioResult,
)
from scaffold_p6.preflight import TestPreflight, evaluate_test_preflight
from scaffold_p6.sav import (
    evaluate_sav_coverage,
    reconstruct_sav_plan,
)
from scaffold_p6.schemas import yaml_safe
from scaffold_p6.sufficiency import sav_blocks_test_complete
from scaffold_p6.storage import (
    abort_materialization,
    build_published_evidence_refs,
    cleanup_test_run_result,
    list_prepared_materializations,
    load_completed_report,
    materialize_published_evidence,
    new_run_id,
    prepare_run,
    publish_completed_report,
    release_materialization,
    resolve_published_evidence,
    write_evidence_blobs,
)


class TestEngine:
    def __init__(self, host_root: str | Path, package_root: str | Path | None = None):
        self.root = Path(host_root)
        self.package_root = Path(package_root) if package_root else None
        self.skill_version = ""
        self.package_validity = "UNRESOLVED"
        self.adapter_invocations = 0
        self.preflight: TestPreflight | None = None
        self.project_rules: dict[str, Any] | None = None
        self._evidence_task: dict[str, Any] | None = None
        self._report_task_id = ""
        if self.package_root:
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version
            self.package_validity = loaded.validity

    def run(self, mode: str = "scoped_verification", **opts: Any):
        self.project_rules = None
        task_id = str(opts.get("task_id") or "").strip()
        task_book = opts.get("task_book")
        if isinstance(task_book, dict):
            self._evidence_task = task_book
            if not task_id:
                task_id = str(task_book.get("record_id") or "").strip()
        elif task_id:
            from scaffold_p6.sav import load_task_book

            self._evidence_task = load_task_book(self.root, task_id)
        else:
            self._evidence_task = None
        self._report_task_id = task_id
        if not self._report_task_id and isinstance(self._evidence_task, dict):
            self._report_task_id = str(
                self._evidence_task.get("record_id") or ""
            ).strip()
        if mode not in TEST_MODES:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="FAILED",
                blockers=[f"unsupported Test mode: {mode}"],
                next_route="stop",
            )

        pre = observe_candidate(self.root)
        run_id = new_run_id()
        project_status, project_reasons, project = inspect_host_project(self.root)
        self.preflight = evaluate_test_preflight(
            self.root,
            package_root=self.package_root,
            project=project,
            project_status=project_status,
        )
        self.skill_version = self.preflight.skill_version
        dest = prepare_run(
            self.root,
            run_id,
            {
                "run_id": run_id,
                "status": "PREPARING",
                "candidate_digest": pre.digest,
            },
        )
        supplied = list(opts.get("supplied_evidence") or [])
        selected = opts.get("selected")
        contract = resolve_contract(
            self.root,
            project_status=project_status,
            project=project,
        )
        project_blockers = project_blocks_execution(
            project_status, project_reasons, project
        )

        if not self.preflight.allowed:
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                observe_candidate(self.root),
                [],
                contract,
                list(self.preflight.blockers),
                project,
                opts,
                route_to=self.preflight.route or "understand.compatibility",
                selected_ids=[],
            )
        if not pre.usable:
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                pre,
                [],
                contract,
                list(pre.data.get("blockers") or [
                    "candidate SCM observation is unresolved"
                ]),
                project,
                opts,
                route_to="stop",
                selected_ids=[],
            )
        if project_blockers:
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                pre,
                [],
                contract,
                project_blockers,
                project,
                opts,
                route_to="understand.refresh",
                selected_ids=[],
            )
        if contract.status not in {"RESOLVED", "VERIFIED_NONE"} or contract.blockers:
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                observe_candidate(self.root),
                [],
                contract,
                list(contract.blockers),
                project,
                opts,
                route_to=contract.route or "understand.refresh",
                selected_ids=[],
            )
        known_ids = {p.profile_id for p in contract.profiles}
        selected_ids, selected_blockers = validate_selected(selected, known_ids)
        if selected_blockers:
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                observe_candidate(self.root),
                [],
                contract,
                selected_blockers,
                project,
                opts,
                route_to="understand.refresh",
                selected_ids=[],
            )
        if selected_ids is None:
            selected_ids = [p.profile_id for p in contract.required]
            selected_ids.extend(
                p.profile_id for p in contract.optional if p.data.get("auto") is True
            )

        self.project_rules = resolve_project_rules(
            self.root,
            project=project,
            skill_id="test",
            paths=list(opts.get("scope_paths") or []),
            modules=list(opts.get("scope_modules") or []),
            test_ids=selected_ids,
            operation="test_execute",
        )
        if not self.project_rules.get("ok"):
            return self._blocked(
                mode,
                run_id,
                dest,
                pre,
                observe_candidate(self.root),
                [],
                contract,
                list(self.project_rules.get("blockers") or []),
                project,
                opts,
                route_to=self.project_rules.get("route") or "understand.refresh",
                selected_ids=selected_ids,
            )

        results, evidence, refs, artifacts, human_required, authority_route = (
            self._execute_profiles(run_id, pre, contract, selected_ids, supplied)
        )
        default_profile = (selected_ids or [""])[0]
        sav_blockers: list[str] = []
        for index, item in enumerate(opts.get("sav_evidence") or []):
            if not isinstance(item, dict):
                continue
            compiled, item_refs, item_blockers = compile_supplied_sav_item(
                run_id=run_id,
                profile_id=str(item.get("profile_id") or default_profile),
                candidate=pre,
                supplied=item,
                index=index,
                host_root=self.root,
                task=self._evidence_task,
            )
            refs.extend(item_refs)
            sav_blockers.extend(item_blockers)
            if compiled is not None and not item_blockers:
                evidence.append(compiled)
        if sav_blockers:
            for row in results:
                row.blockers.extend(sav_blockers)
                row.result = "BLOCKED"
                row.evidence_complete = False
        post = observe_candidate(self.root)
        match = candidates_match(pre, post)
        if not match:
            for row in results:
                if row.result in {"PASS", "FAIL"}:
                    row.blockers.append(
                        "candidate changed during verification; result is stale for the current candidate"
                    )
                    row.result = "BLOCKED"
                    row.evidence_complete = False

        completeness = analyze(
            required_ids=[p.profile_id for p in contract.required],
            optional_ids=[p.profile_id for p in contract.optional],
            results=results,
            candidate_match=match,
            verified_no_required=contract.verified_no_required,
            contract_blockers=list(contract.blockers),
            selected_ids=selected_ids,
            required_set_authoritative=contract.required_set_authoritative,
        )
        sav = self._evaluate_sav(
            opts, evidence, results, completeness, candidate_digest=pre.digest
        )
        if sav.get("applied"):
            completeness = dict(completeness)
            completeness["test_pass"] = bool(completeness.get("test_pass")) and bool(
                sav.get("requirement_pass")
            )
            completeness["requirement_pass"] = sav.get("requirement_pass")
            completeness["sav"] = sav
            adequacy = sav.get("adequacy") if isinstance(sav.get("adequacy"), dict) else {}
            if adequacy:
                completeness["adequacy"] = {
                    "status": adequacy.get("status"),
                    "derived": True,
                    "authority": "engine",
                    "reasons": list(adequacy.get("reasons") or []),
                }
            if sav_blocks_test_complete(sav) or not sav.get("current"):
                completeness["test_complete"] = False
        report = self._build_report(
            run_id=run_id,
            mode=mode,
            pre=pre,
            post=post,
            match=match,
            project=project,
            contract=contract,
            results=results,
            evidence=evidence,
            refs=refs,
            completeness=completeness,
            opts=opts,
        )
        write_evidence_blobs(dest, artifacts)
        published, publish_issues = publish_completed_report(
            dest, report, _human_summary(report)
        )
        if not published:
            return skill_result(
                skill_id=SKILL_ID,
                skill_version=self.skill_version,
                mode=mode,
                outcome="BLOCKED",
                baseline=pre.data,
                mutations="none",
                artifacts=[],
                blockers=publish_issues or ["completed Test Report failed schema validation"],
                next_route="understand.refresh",
                compatibility=self.preflight.compatibility if self.preflight else None,
                extras=self._extras(run_id, completeness, None, opts),
            )
        verification_failed = completeness["required_fail"] > 0 or bool(
            sav.get("failed")
        )
        next_route = authority_route or route(
            completeness=completeness,
            contract_route=contract.route,
            candidate_match=match,
            human_required=human_required,
            verification_failed=verification_failed,
        )
        outcome = "COMPLETED"
        if sav.get("insufficient_observability"):
            outcome = "BLOCKED"
            next_route = "develop_or_human"
        elif completeness["required_blocked"] or not match or sav.get("blockers"):
            outcome = "BLOCKED"
            if sav.get("blockers") and next_route == (authority_route or "caller"):
                next_route = "develop_or_human" if sav.get("insufficient_observability") else next_route
        elif human_required:
            outcome = "NEEDS_HUMAN"
        elif contract.blockers:
            outcome = "BLOCKED"
        extras = self._extras(run_id, completeness, report, opts)
        if sav:
            extras["sav"] = sav
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome=outcome,
            baseline=pre.data,
            mutations="none",
            artifacts=[_artifact_ref(dest)],
            evidence=[item["evidence_id"] for item in evidence],
            blockers=_collect_blockers(
                results,
                ([] if match else ["candidate changed during verification"])
                + list(sav.get("blockers") or []),
            ),
            next_route=next_route,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=extras,
        )

    def load_report(self, run_id: str) -> dict[str, Any] | None:
        return load_completed_report(self.root, run_id)

    def consume_published_report(
        self,
        report_id: str,
        *,
        task: dict[str, Any] | None = None,
        requirement_id: str = "",
    ) -> dict[str, Any]:
        from scaffold_p6.published import consume_published_report

        return consume_published_report(
            self.root,
            report_id,
            task=task,
            skill_version=self.skill_version,
            requirement_id=requirement_id,
        )

    def reconstruct_scenario_plan(self, task_id: str, requirement_id: str) -> dict[str, Any]:
        return reconstruct_sav_plan(
            self.root, task_id=task_id, requirement_id=requirement_id
        )

    def _evaluate_sav(
        self,
        opts: dict[str, Any],
        evidence: list[dict[str, Any]],
        results: list[ScenarioResult],
        completeness: dict[str, Any],
        *,
        candidate_digest: str = "",
    ) -> dict[str, Any]:
        task_id = str(opts.get("task_id") or "").strip()
        requirement_id = str(opts.get("requirement_id") or "").strip()
        if not task_id or not requirement_id:
            return {}
        reconstructed = reconstruct_sav_plan(
            self.root, task_id=task_id, requirement_id=requirement_id
        )
        if not reconstructed.get("current"):
            return {
                "applied": True,
                "required": True,
                "ok": False,
                "current": False,
                "requirement_pass": False,
                "failed": True,
                "adequacy": {
                    "status": "UNKNOWN",
                    "derived": True,
                    "authority": "engine",
                    "reasons": ["SAV plan is not current applicable Test authority"],
                },
                "blockers": list(
                    reconstructed.get("blockers")
                    or ["SAV plan is not current applicable Test authority"]
                ),
                "reconstruction": reconstructed,
            }
        profile_results = {row.profile_id: row.result for row in results}
        coverage = evaluate_sav_coverage(
            reconstructed.get("plan") or {},
            evidence=evidence,
            profile_results=profile_results,
            candidate_digest=candidate_digest,
            caller_adequacy=opts.get("adequacy"),
        )
        return {
            "applied": True,
            "required": True,
            "ok": True,
            "current": True,
            "requirement_pass": bool(coverage.get("requirement_pass")),
            "profile_pass": bool(coverage.get("profile_pass"))
            or bool(completeness.get("test_pass")),
            "failed": bool(coverage.get("failed")),
            "insufficient_observability": bool(coverage.get("insufficient_observability")),
            "unknown": bool(coverage.get("unknown")),
            "adequacy": coverage.get("adequacy") or {},
            "blockers": []
            if coverage.get("requirement_pass")
            else [
                str(row.get("reason") or "")
                for row in coverage.get("proof_obligations") or []
                if row.get("required")
                and row.get("status") != "SATISFIED"
                and row.get("reason")
            ],
            "proof_obligations": coverage.get("proof_obligations") or [],
            "handoff": coverage.get("handoff"),
            "reconstruction": {
                "scenario": reconstructed.get("scenario"),
                "proof_obligations": reconstructed.get("proof_obligations"),
                "profile_id": reconstructed.get("profile_id"),
                "locator": reconstructed.get("locator"),
                "current": True,
                "task_id": reconstructed.get("task_id") or task_id,
                "requirement_id": reconstructed.get("requirement_id") or requirement_id,
            },
            "task_id": reconstructed.get("task_id") or task_id,
            "requirement_id": reconstructed.get("requirement_id") or requirement_id,
        }

    def report_usable_for_current(self, report: dict[str, Any]) -> bool:
        return report_usable_for(report, observe_candidate(self.root))

    def build_evidence_refs(self, run_id: str) -> list[dict[str, str]]:
        return build_published_evidence_refs(self.root, run_id)

    def resolve_evidence(
        self, locator: Any
    ) -> tuple[dict[str, Any] | None, list[str]]:
        return resolve_published_evidence(self.root, locator)

    def materialize_evidence(
        self,
        locators: list[Any],
        *,
        coordination_id: str,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        return materialize_published_evidence(
            self.root,
            locators,
            coordination_id=coordination_id,
        )

    def prepared_materializations(self) -> list[dict[str, Any]]:
        return list_prepared_materializations(self.root)

    def release_materialization(self, coordination_id: str) -> dict[str, Any]:
        return release_materialization(self.root, coordination_id)

    def abort_materialization(self, coordination_id: str) -> dict[str, Any]:
        return abort_materialization(self.root, coordination_id)

    def cleanup_run(self, run_id: str) -> dict[str, Any]:
        return cleanup_test_run_result(self.root, run_id)

    def _optional_refs(self, opts: dict[str, Any]) -> dict[str, Any]:
        """Durable report identity. task_book here is the Task id, not the mapping."""
        task_ref = str(getattr(self, "_report_task_id", "") or "").strip()
        if not task_ref and isinstance(opts.get("task_book"), dict):
            task_ref = str(opts["task_book"].get("record_id") or "").strip()
        if not task_ref:
            task_ref = str(opts.get("task_id") or "").strip()
        return {
            "task_book": task_ref or None,
            "develop_session": opts.get("develop_session"),
        }

    def _extras(
        self,
        run_id: str,
        completeness: dict[str, Any],
        report: dict[str, Any] | None,
        opts: dict[str, Any],
    ) -> dict[str, Any]:
        extras: dict[str, Any] = {
            "test_pass": completeness["test_pass"],
            "test_complete": completeness["test_complete"],
            "coverage_complete": completeness.get("coverage_complete"),
            "completeness": completeness,
            "report_id": run_id,
            "package": {
                "skill_id": SKILL_ID,
                "skill_version": self.skill_version,
                "modes": list(TEST_MODES),
                "provides": list(PROVIDES),
                "requires": list(REQUIRES),
            },
            "optional_refs": self._optional_refs(opts),
        }
        if report is not None:
            extras["report"] = report
        if self.preflight is not None:
            extras.update(self.preflight.extras())
        if self.project_rules is not None:
            extras["project_rules"] = self.project_rules
        return extras

    def _execute_profiles(
        self,
        run_id: str,
        candidate: CandidateIdentity,
        contract: ContractResolution,
        selected: list[str],
        supplied: list[dict[str, Any]],
    ) -> tuple[
        list[ScenarioResult],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, str],
        bool,
        str,
    ]:
        results: list[ScenarioResult] = []
        evidence: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        artifacts: dict[str, str] = {}
        human_required = False
        authority_route = ""
        supplied_by_profile: dict[str, list[dict[str, Any]]] = {}
        for item in supplied:
            if isinstance(item, dict):
                supplied_by_profile.setdefault(str(item.get("profile_id") or ""), []).append(item)
        wanted = set(selected)

        for profile in contract.profiles:
            if profile.profile_id not in wanted:
                results.append(
                    ScenarioResult(
                        profile_id=profile.profile_id,
                        required=profile.required,
                        result="NOT_RUN",
                        provenance="",
                        adapter=profile.adapter,
                        command_ref=profile.command_ref,
                        evidence_complete=not profile.required,
                        not_run_reason="not_selected",
                    )
                )
                continue

            required_kinds = _required_evidence(profile)
            supplied_items = supplied_by_profile.get(profile.profile_id) or []
            declared_prov = profile.provenance
            profile_app = profile.applicability or contract.applicability
            profile_conf = str(profile.data.get("confidence") or contract.confidence)
            if profile_app == "NOT_APPLICABLE":
                results.append(
                    ScenarioResult(
                        profile_id=profile.profile_id,
                        required=profile.required,
                        result="NOT_RUN",
                        provenance="",
                        adapter=profile.adapter,
                        command_ref=profile.command_ref,
                        evidence_complete=not profile.required,
                        not_run_reason="not_applicable",
                    )
                )
                continue
            required_authority_verified = (
                profile.required
                and profile.data.get("required_authority") == "VERIFIED"
            )
            # CONFLICTING discovery confidence cannot be consumed as required
            # authority. UNKNOWN and INFERRED keep the existing contract:
            # UNKNOWN blocks unless this required profile is separately
            # VERIFIED; INFERRED remains executable.
            if profile_app in {"UNKNOWN", "CONFLICTING"} or profile_conf == "CONFLICTING" or (
                profile_conf == "UNKNOWN" and not required_authority_verified
            ):
                results.append(
                    ScenarioResult(
                        profile_id=profile.profile_id,
                        required=profile.required,
                        result="BLOCKED",
                        provenance=declared_prov,
                        adapter=profile.adapter,
                        command_ref=profile.command_ref,
                        blockers=[
                            f"profile {profile.profile_id} authority is "
                            f"{profile_app or profile_conf} and cannot be executed by guessing"
                        ],
                        evidence_complete=False,
                    )
                )
                authority_route = "understand.refresh"
                continue
            if supplied_items:
                row, items, item_refs, _complete = self._from_supplied(
                    run_id, profile, candidate, supplied_items, required_kinds
                )
                results.append(row)
                evidence.extend(items)
                refs.extend(item_refs)
                if declared_prov == "HUMAN_OBSERVATION" and row.result in {
                    "BLOCKED",
                    "NOT_RUN",
                }:
                    human_required = True
                continue

            if not local_execution_permitted(declared_prov):
                if declared_prov == "HUMAN_OBSERVATION":
                    human_required = True
                    message = "required human observation is not supplied"
                else:
                    message = (
                        f"profile requires {declared_prov}; LocalTargetAdapter was not invoked"
                    )
                results.append(
                    ScenarioResult(
                        profile_id=profile.profile_id,
                        required=profile.required,
                        result="BLOCKED",
                        provenance=declared_prov,
                        adapter=profile.adapter,
                        command_ref=profile.command_ref,
                        blockers=[message],
                        evidence_complete=False,
                    )
                )
                continue

            row, items, item_refs, refresh = self._from_local(
                run_id, profile, candidate, contract, required_kinds, artifacts
            )
            if refresh:
                authority_route = "understand.refresh"
            results.append(row)
            evidence.extend(items)
            refs.extend(item_refs)
        return results, evidence, refs, artifacts, human_required, authority_route

    def _from_local(
        self,
        run_id: str,
        profile: Profile,
        candidate: CandidateIdentity,
        contract: ContractResolution,
        required_kinds: list[str],
        artifacts: dict[str, str],
    ) -> tuple[ScenarioResult, list[dict[str, Any]], list[dict[str, Any]], bool]:
        if not adapter_supported(profile.adapter):
            return (
                ScenarioResult(
                    profile_id=profile.profile_id,
                    required=profile.required,
                    result="BLOCKED",
                    provenance="",
                    adapter=profile.adapter,
                    command_ref=profile.command_ref,
                    blockers=[f"unsupported target adapter: {profile.adapter or '(missing)'}"]
                    if profile.adapter
                    else ["target adapter is missing or unsupported"],
                    evidence_complete=False,
                ),
                [],
                [],
                False,
            )
        command = contract.commands.get(profile.command_ref)
        if not profile.command_ref:
            return (
                ScenarioResult(
                    profile_id=profile.profile_id,
                    required=profile.required,
                    result="BLOCKED",
                    provenance="",
                    adapter=profile.adapter,
                    command_ref=profile.command_ref,
                    blockers=["required command authority is UNKNOWN; route Understand Refresh"],
                    evidence_complete=False,
                ),
                [],
                [],
                True,
            )
        allowed, reason = command_execution_allowed(command)
        if not allowed:
            return (
                ScenarioResult(
                    profile_id=profile.profile_id,
                    required=profile.required,
                    result="BLOCKED",
                    provenance="LOCAL_EXECUTION",
                    adapter=profile.adapter,
                    command_ref=profile.command_ref,
                    blockers=[
                        f"{reason}: {profile.command_ref}"
                        if reason
                        else f"declared command missing or not executable: {profile.command_ref}"
                    ],
                    evidence_complete=False,
                ),
                [],
                [],
                True,
            )
        cwd_ok, cwd_reason, cwd = resolve_project_working_directory(
            self.root,
            profile.data.get("working_directory"),
        )
        if not cwd_ok or cwd is None:
            return (
                ScenarioResult(
                    profile_id=profile.profile_id,
                    required=profile.required,
                    result="BLOCKED",
                    provenance="LOCAL_EXECUTION",
                    adapter=profile.adapter,
                    command_ref=profile.command_ref,
                    blockers=[cwd_reason],
                    evidence_complete=False,
                ),
                [],
                [],
                False,
            )
        adapter = resolve_adapter(profile.adapter)
        assert adapter is not None
        timeout = profile.data.get("timeout_seconds")
        self.adapter_invocations += 1
        observation = adapter.execute(
            command=list(command["argv"]),
            working_directory=cwd,
            timeout_seconds=float(timeout) if timeout is not None else None,
        )
        raw = scenario_from_observation(profile.data, observation)
        result = preserve_verification_truth(raw)
        items, item_refs, complete = compile_local_evidence(
            run_id=run_id,
            profile_id=profile.profile_id,
            candidate=candidate,
            observation=observation,
            result=result,
            required_kinds=required_kinds,
            artifacts=artifacts,
        )
        if required_kinds and not complete:
            blockers = [f"required evidence missing: {', '.join(required_kinds)}"]
        else:
            blockers = []
        return (
            ScenarioResult(
                profile_id=profile.profile_id,
                required=profile.required,
                result=result,
                provenance="LOCAL_EXECUTION",
                adapter=profile.adapter,
                command_ref=profile.command_ref,
                blockers=blockers,
                evidence_ids=[item["evidence_id"] for item in items],
                evidence_complete=complete,
                observation=observation_dict(observation),
            ),
            items,
            item_refs,
            False,
        )

    def _from_supplied(
        self,
        run_id: str,
        profile: Profile,
        candidate: CandidateIdentity,
        supplied_items: list[dict[str, Any]],
        required_kinds: list[str],
    ) -> tuple[ScenarioResult, list[dict[str, Any]], list[dict[str, Any]], bool]:
        items, item_refs, complete, blockers, raw = compile_supplied_bundle(
            run_id=run_id,
            profile_id=profile.profile_id,
            candidate=candidate,
            supplied_items=supplied_items,
            required_kinds=required_kinds,
            declared_provenance=profile.provenance,
            host_root=self.root,
            task=self._evidence_task,
        )
        result = preserve_verification_truth(raw)
        if blockers and result != "FAIL":
            result = "BLOCKED"
            complete = False
        provenance = next((item["provenance"] for item in items if item.get("usable")), "")
        return (
            ScenarioResult(
                profile_id=profile.profile_id,
                required=profile.required,
                result=result,
                provenance=provenance,
                adapter=profile.adapter or "none",
                command_ref=profile.command_ref,
                blockers=blockers,
                evidence_ids=[item["evidence_id"] for item in items],
                evidence_complete=complete,
            ),
            items,
            item_refs,
            complete,
        )

    def _blocked(
        self,
        mode: str,
        run_id: str,
        dest: Path,
        pre: CandidateIdentity,
        post: CandidateIdentity,
        results: list[ScenarioResult],
        contract: ContractResolution,
        blockers: list[str],
        project: dict[str, Any] | None,
        opts: dict[str, Any],
        *,
        route_to: str,
        selected_ids: list[str] | None = None,
    ):
        match = candidates_match(pre, post)
        effective = _effective_blocked_results(results, contract, blockers)
        completeness = analyze(
            required_ids=[p.profile_id for p in contract.required],
            optional_ids=[p.profile_id for p in contract.optional],
            results=effective,
            candidate_match=match,
            verified_no_required=False,
            contract_blockers=blockers,
            selected_ids=selected_ids or [],
            required_set_authoritative=False,
        )
        report = self._build_report(
            run_id=run_id,
            mode=mode,
            pre=pre,
            post=post,
            match=match,
            project=project,
            contract=contract,
            results=effective,
            evidence=[],
            refs=[],
            completeness=completeness,
            opts=opts,
            extra_blockers=blockers,
        )
        publish_completed_report(dest, report, _human_summary(report))
        return skill_result(
            skill_id=SKILL_ID,
            skill_version=self.skill_version,
            mode=mode,
            outcome="BLOCKED",
            baseline=pre.data,
            mutations="none",
            artifacts=[_artifact_ref(dest)],
            blockers=blockers,
            next_route=route_to,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=self._extras(run_id, completeness, report, opts),
        )

    def _build_report(
        self,
        *,
        run_id: str,
        mode: str,
        pre: CandidateIdentity,
        post: CandidateIdentity,
        match: bool,
        project: dict[str, Any] | None,
        contract: ContractResolution,
        results: list[ScenarioResult],
        evidence: list[dict[str, Any]],
        refs: list[dict[str, Any]],
        completeness: dict[str, Any],
        opts: dict[str, Any],
        extra_blockers: list[str] | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        blockers = list(extra_blockers or [])
        for row in results:
            blockers.extend(row.blockers)
        profiles = []
        for row in results:
            entry = {
                "id": row.profile_id,
                "required": row.required,
                "result": row.result,
                "provenance": row.provenance,
                "adapter": row.adapter,
                "command_ref": row.command_ref,
                "timing": row.observation,
                "evidence_ids": row.evidence_ids,
                "evidence_complete": row.evidence_complete,
                "blockers": row.blockers,
            }
            if row.result == "NOT_RUN":
                entry["not_run_reason"] = row.not_run_reason or "outside_scope"
            profiles.append(entry)
        preflight = self.preflight
        area_scope = _report_area_scope(opts, self.project_rules)
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "kind": SUPPORT_KIND,
            "record_class": RECORD_CLASS,
            "report_id": run_id,
            "report_status": "COMPLETED",
            "skill_id": SKILL_ID,
            "skill_version": self.skill_version,
            "mode": mode,
            "candidate": pre.data,
            "candidate_after": post.data,
            "candidate_match": match,
            "expected_package": preflight.expected if preflight else None,
            "actual_package": preflight.actual if preflight else None,
            "package_validity": preflight.validity if preflight else self.package_validity,
            "compatibility": preflight.compatibility if preflight else None,
            "project_reference": {
                "name": (project or {}).get("name"),
                "lifecycle": (project or {}).get("lifecycle"),
            },
            "optional_refs": self._optional_refs(opts),
            "selected": completeness.get("selected") or [],
            "required": completeness.get("required") or [],
            "optional": completeness.get("optional") or [],
            "scope": {
                "candidate_digest": pre.digest,
                "paths": area_scope["paths"],
                "modules": area_scope["modules"],
                "selected": completeness.get("selected") or [],
                "required": completeness.get("required") or [],
                "optional": completeness.get("optional") or [],
                "not_selected": completeness.get("not_selected") or [],
                "required_policy": completeness.get("required_policy"),
                "required_set_authoritative": completeness.get(
                    "required_set_authoritative"
                ),
                "verified_no_required_tests": completeness.get(
                    "verified_no_required_tests", False
                ),
            },
            "profiles": profiles,
            "execution_provenance": sorted({
                row.provenance for row in results if row.provenance
            }),
            "evidence": evidence,
            "evidence_refs": refs,
            "blockers": sorted(set(blockers)),
            "completeness": completeness,
            "verification": {
                "test_pass": completeness["test_pass"],
                "test_complete": completeness["test_complete"],
                "verified_no_required_tests": completeness.get(
                    "verified_no_required_tests", False
                ),
                "failure_summary": failure_summary(results),
            },
            "structural_review": None,
            "change_record": None,
            "created_at": now,
            "updated_at": now,
        }
        return yaml_safe(report)


def _effective_blocked_results(
    results: list[ScenarioResult],
    contract: ContractResolution,
    blockers: list[str],
) -> list[ScenarioResult]:
    if results:
        return list(results)
    if contract.status not in {"RESOLVED", "VERIFIED_NONE"}:
        accounting = "BLOCKED"
        reason = ""
    else:
        accounting = "NOT_RUN"
        reason = "prerequisite_blocked"
    return [
        ScenarioResult(
            profile_id=p.profile_id,
            required=p.required,
            result=accounting,
            provenance="",
            adapter=p.adapter,
            command_ref=p.command_ref,
            blockers=list(blockers),
            evidence_complete=False,
            not_run_reason=reason,
        )
        for p in contract.profiles
    ]


def _required_evidence(profile: Profile) -> list[str]:
    value = profile.data.get("evidence_required")
    if value is None:
        expected = profile.data.get("evidence")
        if isinstance(expected, dict):
            value = expected.get("required")
    if isinstance(value, list):
        return [str(item) for item in value]
    if profile.command_ref:
        return ["command_result"]
    return []


def _artifact_ref(dest: Path) -> str:
    text = dest.as_posix()
    marker = ".scaffold/"
    if marker in text:
        return marker + text.split(marker, 1)[1] + "/report.yaml"
    return dest.name + "/report.yaml"


def _collect_blockers(results: list[ScenarioResult], extra: list[str]) -> list[str]:
    out = list(extra)
    for row in results:
        out.extend(row.blockers)
    return sorted(set(out))


def _report_area_scope(
    opts: dict[str, Any],
    project_rules: dict[str, Any] | None,
) -> dict[str, list[str]]:
    resolved = (
        project_rules.get("scope")
        if isinstance(project_rules, dict)
        and isinstance(project_rules.get("scope"), dict)
        else {}
    )
    raw_paths = resolved.get("paths", opts.get("scope_paths") or [])
    raw_modules = resolved.get("modules", opts.get("scope_modules") or [])
    return {
        "paths": _portable_scope_values(raw_paths),
        "modules": _portable_scope_values(raw_modules),
    }


def _portable_scope_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({
        normalized
        for value in values
        if (normalized := normalize_project_path(value, area=False))
    })


def _human_summary(report: dict[str, Any]) -> str:
    completeness = report.get("completeness") or {}
    scope = report.get("scope") or {}
    lines = [
        "# Test Report",
        "",
        f"report_id: {report.get('report_id')}",
        f"TEST_PASS: {completeness.get('test_pass')}",
        f"test_complete: {completeness.get('test_complete')}",
        f"coverage_complete: {completeness.get('coverage_complete')}",
        f"required_policy: {completeness.get('required_policy')}",
        f"candidate_match: {completeness.get('candidate_match')}",
        f"selected: {', '.join(scope.get('selected') or completeness.get('selected') or []) or '(none)'}",
        "",
        "This markdown is a rendering. The YAML report is authoritative.",
        "",
    ]
    for row in report.get("profiles") or []:
        extra = ""
        if row.get("result") == "NOT_RUN" and row.get("not_run_reason"):
            extra = f" ({row.get('not_run_reason')})"
        lines.append(f"- {row.get('id')}: {row.get('result')}{extra}")
    return "\n".join(lines) + "\n"

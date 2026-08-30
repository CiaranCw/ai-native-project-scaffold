"""Test Skill orchestration. Consumes Understand knowledge. Does not refresh it."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.packages import load_package
from scaffold_p5.result import skill_result

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
from scaffold_p6.schemas import yaml_safe
from scaffold_p6.storage import (
    load_completed_report,
    new_run_id,
    prepare_run,
    publish_completed_report,
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
        if self.package_root:
            loaded = load_package(self.package_root)
            self.skill_version = loaded.ref.skill_version
            self.package_validity = loaded.validity

    def run(self, mode: str = "scoped_verification", **opts: Any):
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

        results, evidence, refs, artifacts, human_required, authority_route = (
            self._execute_profiles(run_id, pre, contract, selected_ids, supplied)
        )
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
        verification_failed = completeness["required_fail"] > 0
        next_route = authority_route or route(
            completeness=completeness,
            contract_route=contract.route,
            candidate_match=match,
            human_required=human_required,
            verification_failed=verification_failed,
        )
        outcome = "COMPLETED"
        if completeness["required_blocked"] or not match:
            outcome = "BLOCKED"
        elif human_required:
            outcome = "NEEDS_HUMAN"
        elif contract.blockers:
            outcome = "BLOCKED"
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
                results, [] if match else ["candidate changed during verification"]
            ),
            next_route=next_route,
            compatibility=self.preflight.compatibility if self.preflight else None,
            extras=self._extras(run_id, completeness, report, opts),
        )

    def load_report(self, run_id: str) -> dict[str, Any] | None:
        return load_completed_report(self.root, run_id)

    def report_usable_for_current(self, report: dict[str, Any]) -> bool:
        return report_usable_for(report, observe_candidate(self.root))

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
            "completeness": completeness,
            "report_id": run_id,
            "package": {
                "skill_id": SKILL_ID,
                "skill_version": self.skill_version,
                "modes": list(TEST_MODES),
                "provides": list(PROVIDES),
                "requires": list(REQUIRES),
            },
            "optional_refs": {
                "task_book": opts.get("task_book"),
                "develop_session": opts.get("develop_session"),
            },
        }
        if report is not None:
            extras["report"] = report
        if self.preflight is not None:
            extras.update(self.preflight.extras())
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
                    )
                )
                continue
            if profile_app in {"UNKNOWN", "CONFLICTING"} or profile_conf in {
                "UNKNOWN",
                "CONFLICTING",
                "INFERRED",
            }:
                if profile_conf == "INFERRED" and profile_app == "APPLICABLE" and declared_prov:
                    pass
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
            profiles.append(
                {
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
            )
        preflight = self.preflight
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
            "optional_refs": {
                "task_book": opts.get("task_book"),
                "develop_session": opts.get("develop_session"),
            },
            "selected": completeness.get("selected") or [],
            "required": completeness.get("required") or [],
            "optional": completeness.get("optional") or [],
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
    return [
        ScenarioResult(
            profile_id=p.profile_id,
            required=p.required,
            result="NOT_RUN",
            provenance="",
            adapter=p.adapter,
            command_ref=p.command_ref,
            blockers=list(blockers),
            evidence_complete=False,
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


def _human_summary(report: dict[str, Any]) -> str:
    completeness = report.get("completeness") or {}
    lines = [
        "# Test Report",
        "",
        f"report_id: {report.get('report_id')}",
        f"TEST_PASS: {completeness.get('test_pass')}",
        f"test_complete: {completeness.get('test_complete')}",
        f"candidate_match: {completeness.get('candidate_match')}",
        "",
        "This markdown is a rendering. The YAML report is authoritative.",
        "",
    ]
    for row in report.get("profiles") or []:
        lines.append(f"- {row.get('id')}: {row.get('result')}")
    return "\n".join(lines) + "\n"

"""Gate-1B-C01 authority closure regressions.

Closes G1B-T1-001/002, G1B-T2-001/002/003, G1B-T3-001.
Does not repair G1B-T2-SHOULD-001.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from p6_support import passing_profile, test_engine, write_host
from p7_support import TASK_A, write_task
from scaffold_p5.adoption import _preserve_human_paths, build_adoption_plan
from scaffold_p5.discovery import discover, resolve_existing
from scaffold_p5.host_state import _nested_workspaces, scm_baseline, snapshot_host
from scaffold_p5.inventory import InventoryBudget, bounded_metadata_walk
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.preflight import run_preflight
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.published import consume_published_report
from scaffold_p6.sav import evaluate_sav_coverage, publish_sav_plan
from scaffold_p6.storage import build_published_evidence_refs
from scaffold_p6.sufficiency import evaluate_sav_coverage as evaluate_from_module
from support import REPO, distribution, engine, write


PROFILE = "unit"
DIGEST = "ab" * 32
STALE = "cd" * 32
REQ_A = "REQ-A"
REQ_B = "REQ-B"


def _po(po_id: str, *, strategy: str = "structured_assertion", evidence=None, extra=None):
    row = {
        "po_id": po_id,
        "obligation": po_id,
        "required": True,
        "observable_signals": [po_id],
        "execution_strategy": strategy,
        "assertions": [f"{po_id} holds"],
        "evidence_requirements": evidence or ["structured_assertion"],
        "observability_status": "SUFFICIENT",
    }
    if extra:
        row.update(extra)
    return row


def _plan(*obligations, requirement_id=REQ_A, plan_id="sav-20260909T190000Z-c01aaa0a"):
    return {
        "record_type": "test_scenario_aware_plan",
        "schema_version": "1",
        "supporting": True,
        "canonical": False,
        "plan_id": plan_id,
        "task_id": TASK_A,
        "task_revision": 1,
        "requirement_id": requirement_id,
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "scenario": {"initial_state": "ready", "action": "verify", "expected_result": "pass"},
        "proof_obligations": list(obligations),
    }


def _assertion(po_id: str, **extra):
    item = {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": po_id,
        "assertion": {"po_id": po_id, "pass": True},
        "pass": True,
        "result": "PASS",
        "provenance": "HUMAN_OBSERVATION",
        "usable": True,
        "candidate_digest": DIGEST,
    }
    item.update(extra)
    return item


def _engine_assertion(host: Path, po_id: str):
    item = _assertion(po_id, candidate_digest=observe_candidate(host).digest)
    return item


def _command_result(**extra):
    item = {
        "kind": "command_result",
        "result": "PASS",
        "provenance": "LOCAL_EXECUTION",
        "usable": True,
        "command": ["python", "-m", "unittest"],
        "exit_code": 0,
    }
    item.update(extra)
    return item


def _try_dir_link(dest: Path, target: Path) -> bool:
    try:
        dest.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        try:
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest), str(target)],
                capture_output=True,
                text=True,
            )
            return completed.returncode == 0 and dest.exists()
        except OSError:
            return False


def _try_file_link(dest: Path, target: Path) -> bool:
    try:
        dest.symlink_to(target)
        return dest.exists()
    except OSError:
        try:
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", str(dest), str(target)],
                capture_output=True,
                text=True,
            )
            return completed.returncode == 0 and dest.exists()
        except OSError:
            return False


class C1BoundedTraversalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# web-monorepo / backend / native / ml / interactive host\n")
        write(self.host, "src/app.py", "print('ok')\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_C1_01_large_source_tree_cannot_unbounded_test_walk(self):
        for index in range(40):
            write(self.host, f"src/pkg_{index}/__tests__/spec.py", "assert True\n")
        budget = InventoryBudget(max_entries=15, max_files=15)
        walked = bounded_metadata_walk(
            self.host, start="src", budget=budget, skip_dir_names=()
        )
        self.assertTrue(walked.truncated)
        self.assertLessEqual(walked.entries_enumerated, budget.max_entries + 1)
        facts = discover(self.host, budget=budget)
        tests = next(row for row in facts if row.name == "test_tree")
        self.assertNotEqual(tests.confidence, "VERIFIED")
        source = (REPO / "src" / "scaffold_p5" / "discovery.py").read_text(encoding="utf-8")
        self.assertNotIn("os.walk(area_path)", source)

    def test_C1_02_large_docs_tree_cannot_unbounded_preserve_discovery(self):
        for index in range(40):
            write(self.host, f"docs/notes/n_{index}.md", f"note {index}\n")
        budget = InventoryBudget(max_entries=12)
        _paths, walked = _preserve_human_paths(self.host, budget=budget)
        self.assertTrue(walked.truncated)
        self.assertLessEqual(walked.entries_enumerated, budget.max_entries + 1)
        source = (REPO / "src" / "scaffold_p5" / "adoption.py").read_text(encoding="utf-8")
        self.assertNotIn("docs.rglob", source)

    def test_C1_03_large_tree_cannot_unbounded_nested_workspace_discovery(self):
        for index in range(40):
            (self.host / f"pkg_{index}" / "src").mkdir(parents=True)
        budget = InventoryBudget(max_entries=10)
        scan = _nested_workspaces(self.host, budget=budget)
        self.assertTrue(scan["truncated"])
        self.assertNotEqual(scan["status"], "absent")
        source = (REPO / "src" / "scaffold_p5" / "host_state.py").read_text(encoding="utf-8")
        self.assertNotIn("os.walk(root)", source)

    def test_C1_04_truncated_test_discovery_is_not_verified(self):
        write(self.host, "src/__tests__/a.py", "assert True\n")
        for index in range(30):
            write(self.host, f"src/mod_{index}/x.py", "x\n")
        facts = discover(self.host, budget=InventoryBudget(max_entries=8))
        tests = next(row for row in facts if row.name == "test_tree")
        self.assertNotEqual(tests.confidence, "VERIFIED")

    def test_C1_05_truncated_preserve_discovery_blocks_apply(self):
        for index in range(40):
            write(self.host, f"docs/human/n_{index}.md", f"doc {index}\n")
        budget = InventoryBudget(max_entries=8)
        facts = discover(self.host, budget=budget)
        snap = snapshot_host(self.host)
        dist = distribution()
        decision = run_preflight(snap, dist)
        self.assertTrue(decision.allowed)
        plan = build_adoption_plan(
            self.host,
            facts=facts,
            distribution=dist,
            preflight=decision,
            budget=budget,
        )
        self.assertTrue(
            any(item.startswith("human_owned_preservation:") for item in plan.activation_blockers),
            plan.activation_blockers,
        )
        result = engine(self.host)._apply_adoption(plan, None, {}, {}, None)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("preservation" in item for item in result.blockers))

    def test_C1_06_truncated_nested_workspace_is_not_verified_absence(self):
        for index in range(30):
            (self.host / f"tree_{index}").mkdir()
        scan = _nested_workspaces(self.host, budget=InventoryBudget(max_entries=6))
        self.assertEqual(scan["status"], "truncated")
        self.assertNotEqual(scan["status"], "absent")
        baseline = scm_baseline(self.host, budget=InventoryBudget(max_entries=6))
        self.assertEqual(baseline["nested_workspace"], "truncated")
        self.assertNotEqual(baseline["nested_workspace"], "absent")

    def test_C1_07_index_fast_path_rejects_out_of_root_indirection(self):
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "package.json").write_text('{"name": "escaped-pkg"}\n', encoding="utf-8")
        index = {"package.json": "../outside/package.json"}
        self.assertIsNone(resolve_existing(self.host, "package.json", index))
        facts = discover(self.host)
        pkg_facts = [row for row in facts if row.name == "declared_package_identity"]
        self.assertFalse(pkg_facts)

    def test_C1_08_case_insensitive_walk_does_not_follow_out_of_root_dir(self):
        outside = Path(self._tmp.name) / "outside-docs"
        outside.mkdir()
        (outside / "README.md").write_text("# Escaped title\n", encoding="utf-8")
        linked = self.host / "docs"
        created = _try_dir_link(linked, outside)
        self.assertTrue(created)
        self.assertIsNone(resolve_existing(self.host, "docs/README.md", {}))
        self.assertIsNone(resolve_existing(self.host, "Docs/Readme.md", {}))

    def test_C1_09_linked_manifest_outside_root_cannot_contribute_facts(self):
        outside = Path(self._tmp.name) / "ext"
        outside.mkdir()
        (outside / "package.json").write_text('{"name": "not-project-authority"}\n', encoding="utf-8")
        (outside / "README.md").write_text("# External Title\n", encoding="utf-8")
        index = {
            "package.json": "../ext/package.json",
            "readme.md": "../ext/README.md",
        }
        self.assertIsNone(resolve_existing(self.host, "package.json", index))
        self.assertIsNone(resolve_existing(self.host, "README.md", index))
        linked_pkg = self.host / "package.json"
        if _try_file_link(linked_pkg, outside / "package.json"):
            facts = discover(self.host)
            pkg_facts = [row for row in facts if row.name == "declared_package_identity"]
            self.assertFalse(
                any(
                    row.value == "not-project-authority" and row.confidence == "VERIFIED"
                    for row in pkg_facts
                )
            )
        readme_facts = [row for row in discover(self.host) if row.name == "declared_product_title"]
        self.assertFalse(
            any(row.value == "External Title" and row.confidence == "VERIFIED" for row in readme_facts)
        )

    def test_C1_10_in_root_case_insensitive_resolution_still_works(self):
        write(self.host, "Package.JSON", '{"name": "in-root-app"}\n')
        actual = resolve_existing(self.host, "package.json", {})
        self.assertEqual(actual, "Package.JSON")
        facts = discover(self.host)
        pkg = next(row for row in facts if row.name == "declared_package_identity")
        self.assertEqual(pkg.value, "in-root-app")
        self.assertEqual(pkg.confidence, "VERIFIED")


class C2ExactAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _sav_host(self):
        write_host(self.host, [passing_profile(PROFILE)])
        write_task(
            self.host,
            title="c01",
            final_tests=[
                {
                    "requirement_id": REQ_A,
                    "execution_binding": {"kind": "test_profile", "profile_id": PROFILE},
                },
                {
                    "requirement_id": REQ_B,
                    "execution_binding": {"kind": "test_profile", "profile_id": PROFILE},
                },
            ],
        )
        write(self.host, "src/app.py", "print('ok')\n")
        return self.host

    def test_C2_01_req_a_report_with_req_a_head_consumes(self):
        host = self._sav_host()
        publish_sav_plan(host, _plan(_po("PO-1"), requirement_id=REQ_A))
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id=REQ_A,
            selected=[PROFILE],
            sav_evidence=[_engine_assertion(host, "PO-1")],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        loaded = consume_published_report(
            host,
            result.extras["report_id"],
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            requirement_id=REQ_A,
        )
        self.assertTrue(loaded.get("ok"), loaded)

    def test_C2_02_req_a_report_cannot_consume_via_req_b(self):
        host = self._sav_host()
        publish_sav_plan(host, _plan(_po("PO-1"), requirement_id=REQ_A))
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id=REQ_A,
            selected=[PROFILE],
            sav_evidence=[_engine_assertion(host, "PO-1")],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        head_a = host / ".scaffold/runtime/test-plans/heads" / TASK_A / REQ_A / "head.yaml"
        self.assertTrue(head_a.is_file())
        head_a.unlink()
        publish_sav_plan(
            host,
            _plan(
                _po("PO-1"),
                requirement_id=REQ_B,
                plan_id="sav-20260909T190000Z-c01aaa0b",
            ),
        )
        loaded = consume_published_report(
            host,
            result.extras["report_id"],
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertFalse(loaded.get("ok"), loaded)
        self.assertTrue(loaded.get("blockers"))

    def test_C2_03_requested_requirement_mismatch_is_blocked(self):
        host = self._sav_host()
        publish_sav_plan(host, _plan(_po("PO-1"), requirement_id=REQ_A))
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id=REQ_A,
            selected=[PROFILE],
            sav_evidence=[_engine_assertion(host, "PO-1")],
        )
        loaded = consume_published_report(
            host,
            result.extras["report_id"],
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            requirement_id=REQ_B,
        )
        self.assertFalse(loaded.get("ok"), loaded)
        self.assertTrue(any("Requirement" in item for item in loaded.get("blockers") or []))

    def test_C2_04_legacy_report_without_requirement_identity_fails_closed(self):
        host = self._sav_host()
        publish_sav_plan(host, _plan(_po("PO-1"), requirement_id=REQ_A))
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id=REQ_A,
            selected=[PROFILE],
            sav_evidence=[_engine_assertion(host, "PO-1")],
        )
        report_id = result.extras["report_id"]
        path = host / ".scaffold/runtime/test-runs" / report_id / "report.yaml"
        report = read_yaml(path)
        sav = ((report.get("completeness") or {}).get("sav") or {})
        sav.pop("requirement_id", None)
        recon = sav.get("reconstruction") if isinstance(sav.get("reconstruction"), dict) else {}
        recon.pop("requirement_id", None)
        sav["reconstruction"] = recon
        (report.setdefault("completeness", {}))["sav"] = sav
        write_yaml_atomic(path, report)
        loaded = consume_published_report(
            host,
            report_id,
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
        )
        self.assertFalse(loaded.get("ok"), loaded)

    def test_C2_05_task_contract_currentness_still_applies_to_bound_requirement(self):
        host = self._sav_host()
        publish_sav_plan(host, _plan(_po("PO-1"), requirement_id=REQ_A))
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id=REQ_A,
            selected=[PROFILE],
            sav_evidence=[_engine_assertion(host, "PO-1")],
        )
        task_path = host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        task["final_tests"] = [
            item
            for item in task.get("final_tests") or []
            if item.get("requirement_id") != REQ_A
        ]
        write_yaml_atomic(task_path, task)
        loaded = consume_published_report(host, result.extras["report_id"], task=task)
        self.assertFalse(loaded.get("ok"), loaded)

    def test_C2_06_event_trace_required_structured_assertion_not_satisfied(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_C2_07_event_trace_required_valid_event_trace_satisfied(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-1",
                    "trace": {
                        "scenario_id": "web-checkout",
                        "candidate": DIGEST,
                        "assertions": [{"po_id": "PO-1", "pass": True, "result": "PASS"}],
                    },
                    "pass": True,
                    "result": "PASS",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_C2_08_command_result_required_profile_pass_without_evidence_fails(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[_assertion("PO-S")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_C2_09_command_result_required_with_eligible_command_result_passes(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[_command_result()],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_C2_10_supporting_log_cannot_substitute_for_required_kind(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "log_text",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "content": "ok",
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")

    def test_C2_11_human_visual_external_restrictions_still_work(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["structured_assertion"])),
            evidence=[
                {
                    "kind": "human_observation",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")

    def test_C2_12_matching_po_candidate_is_normal(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", extra={"candidate_digest": DIGEST})),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")

    def test_C2_13_stale_po_candidate_cannot_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", extra={"candidate_digest": STALE})),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_C2_14_matching_trace_candidate_is_normal(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-1",
                    "trace": {
                        "candidate": {"candidate_digest": DIGEST},
                        "assertions": [{"po_id": "PO-1", "pass": True, "result": "PASS"}],
                    },
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")

    def test_C2_15_stale_trace_candidate_cannot_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-1",
                    "trace": {
                        "candidate": STALE,
                        "assertions": [{"po_id": "PO-1", "pass": True, "result": "PASS"}],
                    },
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_C2_16_absent_legacy_trace_candidate_remains_compatible(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-1",
                    "trace": {
                        "assertions": [{"po_id": "PO-1", "pass": True, "result": "PASS"}],
                    },
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")

    def test_C2_17_outer_evidence_candidate_conflict_still_blocked(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1")),
            evidence=[_assertion("PO-1", candidate_digest=STALE)],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")


class C3DurableSelectionTests(unittest.TestCase):
    def _published(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir()
        write_host(host, [passing_profile(PROFILE)])
        write(host, "src/app.py", "print('ok')\n")
        published = test_engine(host).run(selected=[PROFILE])
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        return host, published.extras["report_id"]

    def _patch_kinds(self, host: Path, report_id: str, *, result_retention: str | None, log_retention=None):
        path = host / ".scaffold/runtime/test-runs" / report_id / "report.yaml"
        report = read_yaml(path)
        for item in report.get("evidence") or []:
            kind = item.get("kind")
            if kind == "command_result":
                if result_retention is None:
                    item.pop("retention_class", None)
                else:
                    item["retention_class"] = result_retention
            elif kind == "log_text":
                if log_retention is None:
                    item.pop("retention_class", None)
                else:
                    item["retention_class"] = log_retention
        write_yaml_atomic(path, report)
        return report

    def test_C3_01_debug_result_cannot_be_replaced_by_stdout_log(self):
        host, report_id = self._published()
        report = self._patch_kinds(host, report_id, result_retention="DEBUG")
        kinds = {item.get("kind") for item in report.get("evidence") or []}
        self.assertIn("command_result", kinds)
        self.assertIn("log_text", kinds)
        refs = build_published_evidence_refs(host, report_id)
        self.assertEqual(refs, [])
        materialization, issues = test_engine(host).materialize_evidence(
            [], coordination_id="change-20260909T120000Z-c3debug"
        )
        self.assertTrue(materialization is None or issues or refs == [])

    def test_C3_02_temporary_runtime_result_cannot_be_replaced_by_support_log(self):
        host, report_id = self._published()
        self._patch_kinds(host, report_id, result_retention="TEMPORARY_RUNTIME")
        refs = build_published_evidence_refs(host, report_id)
        self.assertEqual(refs, [])

    def test_C3_03_durable_result_selected_not_debug_support_log(self):
        host, report_id = self._published()
        self._patch_kinds(
            host, report_id, result_retention="DURABLE_FINALIZATION", log_retention="DEBUG"
        )
        refs = build_published_evidence_refs(host, report_id)
        self.assertTrue(refs)
        locator = refs[0]["locator"]
        self.assertTrue("command" in locator or "#evidence/" in locator)
        self.assertNotIn("stdout", locator)

    def test_C3_04_profile_associated_log_without_result_yields_no_ref(self):
        host, report_id = self._published()
        path = host / ".scaffold/runtime/test-runs" / report_id / "report.yaml"
        report = read_yaml(path)
        report["evidence"] = [
            item
            for item in report.get("evidence") or []
            if item.get("kind") != "command_result"
        ]
        write_yaml_atomic(path, report)
        refs = build_published_evidence_refs(host, report_id)
        self.assertEqual(refs, [])

    def test_C3_05_embedded_fallback_requires_result_bearing_usable_evidence(self):
        host, report_id = self._published()
        path = host / ".scaffold/runtime/test-runs" / report_id / "report.yaml"
        report = read_yaml(path)
        for item in report.get("evidence") or []:
            if item.get("kind") == "command_result":
                item["usable"] = False
            if item.get("kind") == "log_text":
                item["result"] = "PASS"
                item["usable"] = True
        for ref in report.get("evidence_refs") or []:
            ref["resolvable"] = False
        write_yaml_atomic(path, report)
        refs = build_published_evidence_refs(host, report_id)
        self.assertEqual(refs, [])

    def test_C3_06_optional_visual_remains_justification_gated(self):
        from scaffold_p6.trace import retention_allows_s9

        allowed, reason = retention_allows_s9({"retention_class": "OPTIONAL_VISUAL"})
        self.assertFalse(allowed)
        self.assertIn("justification", reason)
        allowed, _reason = retention_allows_s9(
            {
                "retention_class": "OPTIONAL_VISUAL",
                "retention_justification": "inherently_visual",
            }
        )
        self.assertTrue(allowed)

    def test_C3_07_correction04_materialize_before_change_record(self):
        text = (REPO / "src" / "scaffold_p8" / "engine.py").read_text(encoding="utf-8")
        start = text.find("s10_gate.acquire")
        self.assertGreater(start, 0)
        block = text[start : start + 2500]
        self.assertLess(block.find("materialize_evidence"), block.find("persist_candidate_change"))


class OriginalBypassReplayTests(unittest.TestCase):
    """Independently recreate FOLLOWUP_AUTHORITY_PROBES.json blocker cases."""

    def test_G1B_T1_001(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir()
        write(host, "README.md", "# replay host\n")
        write(host, "src/app.py", "print('ok')\n")
        for index in range(40):
            write(host, f"src/pkg_{index}/__tests__/spec.py", "assert True\n")
            write(host, f"docs/notes/n_{index}.md", f"note {index}\n")
            (host / f"tree_{index}").mkdir()
        budget = InventoryBudget(max_entries=12)
        tests = next(row for row in discover(host, budget=budget) if row.name == "test_tree")
        self.assertNotEqual(tests.confidence, "VERIFIED")
        _paths, preserve = _preserve_human_paths(host, budget=budget)
        self.assertTrue(preserve.truncated)
        nested = _nested_workspaces(host, budget=budget)
        self.assertEqual(nested["status"], "truncated")
        self.assertNotEqual(nested["status"], "absent")

    def test_G1B_T1_002(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir()
        write(host, "README.md", "# replay host\n")
        self.assertIsNone(
            resolve_existing(
                host,
                "package.json",
                {"package.json": "../outside/package.json"},
            )
        )
        self.assertIsNone(resolve_existing(host, "../outside/README.md", {}))

    def test_G1B_T2_001(self):
        case = C2ExactAuthorityTests()
        case.setUp()
        self.addCleanup(case.tearDown)
        case.test_C2_02_req_a_report_cannot_consume_via_req_b()

    def test_G1B_T2_002a(self):
        coverage = evaluate_from_module(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertNotEqual(coverage["adequacy"]["status"], "SATISFIED")

    def test_G1B_T2_002b(self):
        coverage = evaluate_from_module(
            _plan(_po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[
                {
                    "kind": "human_observation",
                    "po_id": "PO-S",
                    "pass": True,
                    "result": "PASS",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")

    def test_G1B_T2_003a(self):
        coverage = evaluate_from_module(
            _plan(_po("PO-1", extra={"candidate_digest": STALE})),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertNotEqual(coverage["adequacy"]["status"], "SATISFIED")

    def test_G1B_T2_003b(self):
        coverage = evaluate_from_module(
            _plan(_po("PO-1", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-1",
                    "trace": {
                        "candidate": STALE,
                        "assertions": [{"po_id": "PO-1", "pass": True, "result": "PASS"}],
                    },
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")

    def test_G1B_T3_001(self):
        case = C3DurableSelectionTests()
        case._published = C3DurableSelectionTests._published.__get__(case, C3DurableSelectionTests)
        case.addCleanup = self.addCleanup
        host, report_id = case._published()
        case._patch_kinds(host, report_id, result_retention="DEBUG")
        refs = build_published_evidence_refs(host, report_id)
        self.assertEqual(refs, [])


class GeneralityAndShouldTests(unittest.TestCase):
    def test_no_project_city_paths_in_c01_core(self):
        forbidden = ("project-city", "babylon", "game_tick", "src/mvp")
        hits = []
        for rel in (
            "src/scaffold_p5/inventory.py",
            "src/scaffold_p5/discovery.py",
            "src/scaffold_p5/adoption.py",
            "src/scaffold_p5/host_state.py",
            "src/scaffold_p6/sufficiency.py",
            "src/scaffold_p6/published.py",
            "src/scaffold_p6/storage.py",
            "src/scaffold_p6/trace.py",
        ):
            text = (REPO / rel).read_text(encoding="utf-8").lower()
            for token in forbidden:
                if token in text:
                    hits.append(f"{rel}:{token}")
        self.assertEqual(hits, [])

    def test_G1B_T2_SHOULD_001_remains_fail_closed_unrepaired(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1")),
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "assertion": {"po_id": "PO-1", "verdict": "UNKNOWN"},
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertFalse(coverage["requirement_pass"])
        self.assertNotEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")


if __name__ == "__main__":
    unittest.main()

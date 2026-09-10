import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from p6_support import passing_profile, test_engine, write_host
from p7_support import TASK_A, write_task
from p10_support import (
    install_abc_modules,
    persist_understanding,
    resume,
    snapshot_dirs,
)
from scaffold_p5.currentness import (
    evaluate_understanding_currentness,
    observe_physical_understanding,
)
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.refresh_completion import (
    load_refresh_completions,
    referenced_completion_targets,
    review_package_missing_targets,
)
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.sav import publish_sav_plan, reconstruct_sav_plan
from support import engine, files_under, write


KNOWLEDGE = {
    "mod_a": "# Module A\n\nFinal understood payload for A.\n",
    "mod_b": "# Module B\n\nFinal understood payload for B.\n",
    "mod_c": "# Module C\n\nFinal understood payload for C.\n",
}
REQUIREMENT = "inspect-step-distance"
PROFILE = "npm-test"
PLAN_ID = "sav-20260906T120000Z-abcdef01"


def _knowledge_path(host: Path, module_id: str) -> Path:
    return host / "docs/project/modules/src" / f"{module_id}.md"


def _latest_completion(host: Path) -> dict:
    rows = load_refresh_completions(host)
    assert rows, "expected at least one valid refresh completion"
    return rows[-1]["completion"]


def _inspect_plan(
    *,
    task_revision: int = 1,
    po2_status: str = "INSUFFICIENT_OBSERVABILITY",
    candidate_digest: str | None = None,
) -> dict:
    plan = {
        "record_type": "test_scenario_aware_plan",
        "schema_version": "1",
        "supporting": True,
        "canonical": False,
        "plan_id": PLAN_ID,
        "task_id": TASK_A,
        "task_revision": task_revision,
        "requirement_id": REQUIREMENT,
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "scenario": {
            "initial_state": "inspect tile is available on the board",
            "action": "inspect a tile",
            "expected_result": "player tile shows distance 0; other tiles show Manhattan distance",
        },
        "proof_obligations": [
            {
                "po_id": "PO-1",
                "obligation": "player tile distance 0",
                "required": True,
                "observable_signals": ["inspect overlay on player tile"],
                "execution_strategy": "structured_assertion",
                "assertions": ["player tile distance is 0"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            },
            {
                "po_id": "PO-2",
                "obligation": "non-player exact Manhattan distance",
                "required": True,
                "observable_signals": ["inspect overlay on non-player tiles"],
                "execution_strategy": "structured_assertion",
                "assertions": ["non-player Manhattan distance is exact"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": po2_status,
            },
            {
                "po_id": "PO-3",
                "obligation": "existing inspect rows preserved",
                "required": True,
                "observable_signals": ["inspect row labels"],
                "execution_strategy": "structured_assertion",
                "assertions": ["existing inspect rows remain"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            },
            {
                "po_id": "PO-4",
                "obligation": "adjacent suite remains green",
                "required": True,
                "observable_signals": ["bound profile command_result"],
                "execution_strategy": "regression",
                "assertions": ["bound profile PASS"],
                "evidence_requirements": ["command_result"],
                "observability_status": "SUFFICIENT",
            },
        ],
    }
    if candidate_digest:
        plan["candidate_digest"] = candidate_digest
    return plan


def _assertion(po_id: str, *, passed: bool = True) -> dict:
    return {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": f"{po_id} structured assertion",
        "assertion": {"po_id": po_id, "pass": passed},
        "pass": passed,
        "result": "PASS" if passed else "FAIL",
    }


def _external_assertion(host: Path, po_id: str, *, passed: bool = True, **overrides) -> dict:
    payload = {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": f"{po_id} structured assertion",
        "assertion": {"po_id": po_id, "pass": passed},
        "pass": passed,
        "result": "PASS" if passed else "FAIL",
        "provenance": "EXTERNAL_RESULT",
        "mechanism": "verifier_execution",
        "candidate_digest": observe_candidate(host).digest,
        "locator": f"ext/sav/{po_id}.json",
        "digest": "ab" * 32,
    }
    payload.update(overrides)
    return payload


def _human_assertion(po_id: str, *, passed: bool = True) -> dict:
    return {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": f"{po_id} structured assertion",
        "assertion": {"po_id": po_id, "pass": passed},
        "pass": passed,
        "result": "PASS" if passed else "FAIL",
        "provenance": "HUMAN_OBSERVATION",
        "mechanism": "synchronous_invocation",
    }


def _sav_head_path(host: Path) -> Path:
    return host / ".scaffold/runtime/test-plans/heads" / TASK_A / REQUIREMENT / "head.yaml"


def _subprocess_reconstruct(host: Path) -> dict:
    from support import REPO

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO / "tests")])
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from scaffold_p6.sav import reconstruct_sav_plan\n"
        "host = Path(sys.argv[1])\n"
        "result = reconstruct_sav_plan(host, task_id=sys.argv[2], requirement_id=sys.argv[3])\n"
        "print(json.dumps({'ok': result.get('ok'), 'current': result.get('current'), "
        "'blockers': result.get('blockers') or []}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(host), TASK_A, REQUIREMENT],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def _bound_task(**overrides) -> dict:
    data = {
        "title": "inspect-step-distance",
        "final_tests": [
            {
                "requirement_id": REQUIREMENT,
                "execution_binding": {"kind": "test_profile", "profile_id": PROFILE},
            }
        ],
    }
    data.update(overrides)
    return data


class KnowledgeCurrentnessCorrectionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")
        from support import adopt

        adopt(self.host)
        install_abc_modules(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP_K01_final_knowledge_completion_resume_is_current(self):
        first = persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        self.assertEqual(first.extras["understanding"]["currentness"], "CURRENT")
        for module_id, payload in KNOWLEDGE.items():
            self.assertEqual(_knowledge_path(self.host, module_id).read_text(encoding="utf-8"), payload)
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "CURRENT")
        self.assertEqual(result.mutations, "none")

    def test_RP_K02_knowledge_edit_without_new_completion_is_not_current(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        write(self.host, "docs/project/modules/src/mod_b.md", "# Module B\n\nDrifted bytes.\n")
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K03_completion_knowledge_digest_mismatch_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        path = self.host / ".scaffold/runtime/understand-currentness/completions" / completion["record_id"] / "completion.yaml"
        for row in completion.get("modules") or []:
            if row.get("id") == "mod_b":
                row["knowledge_digest"] = "ab" * 32
        write_yaml_atomic(path, completion)
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K04_missing_output_locator_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        path = self.host / ".scaffold/runtime/understand-currentness/completions" / completion["record_id"] / "completion.yaml"
        completion.pop("output_locator", None)
        write_yaml_atomic(path, completion)
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "UNKNOWN")

    def test_RP_K05_output_digest_mismatch_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        result_path = self.host / ".scaffold/runtime" / completion["output_locator"]
        result_path.write_text("# drifted output\n", encoding="utf-8")
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "UNKNOWN")

    def test_RP_K06_source_unchanged_knowledge_changed_is_stale(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        before = observe_physical_understanding(self.host)
        write(self.host, "docs/project/modules/src/mod_a.md", "# Module A\n\nChanged knowledge only.\n")
        after = observe_physical_understanding(self.host)
        self.assertEqual(before.get("physical_digest"), after.get("physical_digest"))
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K07_enriched_knowledge_published_before_receipt_stays_current(self):
        for module_id, payload in KNOWLEDGE.items():
            write(self.host, f"docs/project/modules/src/{module_id}.md", payload)
        first = persist_understanding(self.host)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        completion = _latest_completion(self.host)
        bound = {
            row["id"]: row["knowledge_digest"]
            for row in completion.get("modules") or []
        }
        for module_id, payload in KNOWLEDGE.items():
            self.assertEqual(bound[module_id], file_digest(_knowledge_path(self.host, module_id)))
            self.assertIn("Final understood payload", payload)
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K08_repeated_resume_is_observational_noop(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        first = resume(self.host)
        snapshots = snapshot_dirs(self.host)
        repeated = persist_understanding(self.host)
        self.assertTrue(repeated.extras["understanding"].get("noop"))
        second = resume(self.host)
        self.assertEqual(second.extras["understanding"]["currentness"], "CURRENT")
        self.assertEqual(second.mutations, "none")
        self.assertEqual(snapshot_dirs(self.host), snapshots)
        self.assertEqual(second.extras["understanding"]["locator"], first.extras["understanding"]["locator"])

    def test_RP_K09_partial_module_refresh_reuses_unaffected_authority(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        write(self.host, "docs/project/modules/src/mod_b.md", "# Module B\n\nPartial refresh payload.\n")
        observed = resume(self.host)
        self.assertEqual(observed.extras["understanding"]["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(observed.extras["understanding"]["affected_module_ids"], ["mod_b"])
        refreshed = persist_understanding(
            self.host,
            incremental=True,
            knowledge_payloads={"mod_b": "# Module B\n\nPartial refresh payload.\n"},
        )
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        self.assertEqual(refreshed.extras["understanding"]["currentness"], "CURRENT")
        self.assertEqual(refreshed.extras["understanding"]["refreshed_module_ids"], ["mod_b"])
        self.assertEqual(set(refreshed.extras["understanding"].get("reused_module_ids") or []), {"mod_a", "mod_c"})
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K10_knowledge_drift_cannot_hide_behind_source_equality(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        snapshot = evaluate_understanding_currentness(self.host)
        write(self.host, "docs/project/modules/src/mod_c.md", "# Module C\n\nHidden enrichment.\n")
        physical = observe_physical_understanding(self.host)
        self.assertEqual(snapshot.get("physical_digest"), physical.get("physical_digest"))
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K11_output_record_identity_tamper_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        result_path = self.host / ".scaffold/runtime" / completion["output_locator"]
        payload = read_yaml(result_path)
        payload["record_id"] = "rc-20990101T000000Z-deadbeef"
        write_yaml_atomic(result_path, payload)
        completion["output_digest"] = file_digest(result_path)
        write_yaml_atomic(
            self.host
            / ".scaffold/runtime/understand-currentness/completions"
            / completion["record_id"]
            / "completion.yaml",
            completion,
        )
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K13_module_path_rebind_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        completion["modules"][0]["path"] = "rebound/elsewhere"
        write_yaml_atomic(
            self.host
            / ".scaffold/runtime/understand-currentness/completions"
            / completion["record_id"]
            / "completion.yaml",
            completion,
        )
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K14_output_module_path_tamper_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        result_path = self.host / ".scaffold/runtime" / completion["output_locator"]
        payload = read_yaml(result_path)
        payload["modules"][0]["path"] = "rebound/elsewhere"
        write_yaml_atomic(result_path, payload)
        completion["output_digest"] = file_digest(result_path)
        write_yaml_atomic(
            self.host
            / ".scaffold/runtime/understand-currentness/completions"
            / completion["record_id"]
            / "completion.yaml",
            completion,
        )
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")

    def test_RP_K12_module_knowledge_entry_rebind_fails_closed(self):
        persist_understanding(self.host, knowledge_payloads=KNOWLEDGE)
        completion = _latest_completion(self.host)
        by_id = {row["id"]: row for row in completion.get("modules") or []}
        by_id["mod_b"]["knowledge_entry"] = by_id["mod_a"]["knowledge_entry"]
        by_id["mod_b"]["knowledge_digest"] = by_id["mod_a"]["knowledge_digest"]
        write_yaml_atomic(
            self.host
            / ".scaffold/runtime/understand-currentness/completions"
            / completion["record_id"]
            / "completion.yaml",
            completion,
        )
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")


class ScenarioAwareVerificationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [passing_profile(PROFILE)])
        write_task(self.host, **_bound_task())

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP_S01_fresh_reconstruction_returns_exact_scenario_and_pos(self):
        published = publish_sav_plan(self.host, _inspect_plan())
        self.assertTrue(published.get("ok"), published)
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("ok"), reconstructed)
        self.assertEqual(reconstructed["scenario"]["action"], "inspect a tile")
        self.assertEqual(
            [row["po_id"] for row in reconstructed["proof_obligations"]],
            ["PO-1", "PO-2", "PO-3", "PO-4"],
        )
        self.assertEqual(reconstructed["profile_id"], PROFILE)

    def test_RP_S02_missing_sav_plan_cannot_treat_profile_exit_as_requirement_pass(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("applied"))
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))
        self.assertNotEqual(result.outcome, "COMPLETED")

    def test_RP_S03_broad_suite_pass_without_feature_assertion_is_not_requirement_pass(self):
        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("profile_pass") or result.extras["completeness"]["required_pass"])
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))

    def test_RP_S03b_assertion_without_explicit_pass_is_not_satisfied(self):
        from scaffold_p6.sav import evaluate_sav_coverage

        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        coverage = evaluate_sav_coverage(
            reconstructed.get("plan") or {},
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "summary": "player tile distance 0",
                }
            ],
            profile_results={PROFILE: "PASS"},
        )
        statuses = {row["po_id"]: row["status"] for row in coverage.get("proof_obligations") or []}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")
        self.assertFalse(coverage.get("requirement_pass"))

    def test_RP_S04_insufficient_observability_returns_test_to_develop_handoff(self):
        publish_sav_plan(self.host, _inspect_plan())
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion("PO-1"), _assertion("PO-3")],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("insufficient_observability"))
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "develop_or_human")
        self.assertEqual((sav.get("handoff") or {}).get("kind"), "test_to_develop")
        self.assertEqual((sav.get("handoff") or {}).get("reason"), "INSUFFICIENT_OBSERVABILITY")
        self.assertIn("PO-2", (sav.get("handoff") or {}).get("po_ids") or [])

    def test_RP_S05_revised_plan_after_instrumentation_can_become_executable(self):
        publish_sav_plan(self.host, _inspect_plan())
        blocked = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion("PO-1"), _assertion("PO-3")],
        )
        self.assertTrue(blocked.extras["sav"].get("insufficient_observability"))
        revised = dict(_inspect_plan(po2_status="SUFFICIENT"))
        revised["plan_id"] = "sav-20260906T130000Z-abcdef02"
        published = publish_sav_plan(self.host, revised)
        self.assertTrue(published.get("ok"), published)
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("insufficient_observability"))
        self.assertTrue(sav.get("requirement_pass"), sav)

    def test_RP_S06_required_assertions_and_regression_suite_satisfy_pos(self):
        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("requirement_pass"), sav)
        self.assertTrue(result.extras.get("test_pass"))
        statuses = {row["po_id"]: row["status"] for row in sav.get("proof_obligations") or []}
        self.assertEqual(statuses["PO-1"], "SATISFIED")
        self.assertEqual(statuses["PO-2"], "SATISFIED")
        self.assertEqual(statuses["PO-4"], "SATISFIED")

    def test_RP_S07_one_required_po_fail_forbids_requirement_pass(self):
        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2", passed=False),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("failed"))
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))

    def test_RP_S08_task_revision_change_makes_plan_not_silently_current(self):
        publish_sav_plan(
            self.host, _inspect_plan(task_revision=1), bind_task_contract=False
        )
        write_task(self.host, record_revision=2, **_bound_task())
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("ok"))
        self.assertFalse(sav.get("requirement_pass"))
        self.assertTrue(any("revision" in item for item in sav.get("blockers") or []))

    def test_RP_S09_candidate_change_requires_plan_revalidation(self):
        candidate = observe_candidate(self.host)
        publish_sav_plan(
            self.host,
            _inspect_plan(po2_status="SUFFICIENT", candidate_digest=candidate.digest),
        )
        write(self.host, "README.md", "# candidate changed\n")
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("ok"))
        self.assertTrue(any("candidate" in item for item in sav.get("blockers") or []))

    def test_RP_S10_fresh_process_reconstructs_current_plan_without_chat(self):
        publish_sav_plan(self.host, _inspect_plan())
        reconstructed = test_engine(self.host).reconstruct_scenario_plan(TASK_A, REQUIREMENT)
        self.assertTrue(reconstructed.get("ok"), reconstructed)
        self.assertEqual(reconstructed["task_id"], TASK_A)
        self.assertEqual(reconstructed["requirement_id"], REQUIREMENT)
        self.assertEqual(reconstructed["scenario"]["initial_state"], "inspect tile is available on the board")
        self.assertFalse(reconstructed.get("chat_memory"))

    def test_RP_dive_shaped_inspect_step_distance_fixture(self):
        publish_sav_plan(self.host, _inspect_plan())
        broad = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion("PO-1"), _assertion("PO-3")],
        )
        self.assertFalse(broad.extras["sav"].get("requirement_pass"))
        self.assertTrue(broad.extras["sav"].get("insufficient_observability"))
        revised = dict(_inspect_plan(po2_status="SUFFICIENT"))
        revised["plan_id"] = "sav-20260906T140000Z-abcdef03"
        publish_sav_plan(self.host, revised)
        executable = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        self.assertTrue(executable.extras["sav"].get("requirement_pass"), executable.extras["sav"])

    def test_RP_S11_incomplete_plan_is_not_valid_authority(self):
        from scaffold_p6.sav import validate_sav_plan

        plan = _inspect_plan(po2_status="SUFFICIENT")
        for po in plan["proof_obligations"]:
            po.pop("observable_signals", None)
            po.pop("execution_strategy", None)
            po.pop("assertions", None)
            po.pop("evidence_requirements", None)
        issues = validate_sav_plan(plan)
        self.assertTrue(issues)
        self.assertFalse(publish_sav_plan(self.host, plan).get("ok"))

    def test_RP_S12_missing_task_book_cannot_pass_sav_requirement(self):
        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").unlink()
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("applied"))
        self.assertFalse(sav.get("requirement_pass"))
        self.assertNotEqual(result.outcome, "COMPLETED")

    def test_RP_S13_develop_invoke_test_applies_existing_sav_plan(self):
        from scaffold_p7.handoff import invoke_test
        from support import REPO

        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))
        payload = {
            "kind": "develop_to_test",
            "task_id": TASK_A,
            "session_id": "dev-20260906T000000Z-abcdef01",
            "candidate_digest": "x",
            "test_requirement": {
                "requirement_ids": [REQUIREMENT],
                "requirement_bindings": [
                    {"requirement_id": REQUIREMENT, "profile_id": PROFILE}
                ],
                "selected": [PROFILE],
            },
            "scope": {"paths": [], "modules": []},
        }
        result = invoke_test(self.host, payload, test_package=REPO / "skills" / "test")
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("applied"), sav)
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))

    def test_RP_S14_head_plan_id_mismatch_is_not_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        head_path = (
            self.host / ".scaffold/runtime/test-plans/heads" / TASK_A / REQUIREMENT / "head.yaml"
        )
        head = read_yaml(head_path)
        head["plan_id"] = "sav-20990101T000000Z-deadbeef"
        write_yaml_atomic(head_path, head)
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("ok"))
        self.assertFalse(reconstructed.get("current"))


class SavReconstructionCurrentnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [passing_profile(PROFILE)])
        write_task(self.host, **_bound_task())

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP_R01_current_task_revision_binding_reconstructs_current(self):
        self.assertTrue(publish_sav_plan(self.host, _inspect_plan()).get("ok"))
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertTrue(reconstructed.get("ok"), reconstructed)
        self.assertTrue(reconstructed.get("current"), reconstructed)

    def test_RP_R02_task_revision_change_is_not_current(self):
        publish_sav_plan(
            self.host, _inspect_plan(task_revision=1), bind_task_contract=False
        )
        write_task(self.host, record_revision=2, **_bound_task())
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("ok"))
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(any("revision" in item for item in reconstructed.get("blockers") or []))

    def test_RP_R03_missing_task_book_is_not_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").unlink()
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(any("Task Book" in item for item in reconstructed.get("blockers") or []))

    def test_RP_R04_removed_requirement_is_not_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(self.host, title="inspect-step-distance", final_tests=[])
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(any("requirement" in item for item in reconstructed.get("blockers") or []))

    def test_RP_R05_profile_binding_change_is_not_current(self):
        publish_sav_plan(self.host, _inspect_plan())
        write_task(
            self.host,
            **_bound_task(
                final_tests=[
                    {
                        "requirement_id": REQUIREMENT,
                        "execution_binding": {
                            "kind": "test_profile",
                            "profile_id": "other-profile",
                        },
                    }
                ]
            ),
        )
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(any("profile" in item for item in reconstructed.get("blockers") or []))

    def test_RP_R06_candidate_bound_plan_is_not_current_after_candidate_change(self):
        candidate = observe_candidate(self.host)
        publish_sav_plan(
            self.host,
            _inspect_plan(candidate_digest=candidate.digest),
        )
        write(self.host, "README.md", "# candidate changed\n")
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        self.assertFalse(reconstructed.get("current"))
        self.assertTrue(any("candidate" in item for item in reconstructed.get("blockers") or []))

    def test_RP_R07_publish_without_task_cannot_install_current_head(self):
        (self.host / ".scaffold/tasks" / f"{TASK_A}.yaml").unlink()
        published = publish_sav_plan(self.host, _inspect_plan())
        self.assertFalse(published.get("ok"), published)
        self.assertFalse(published.get("current"))
        self.assertIsNone(published.get("head"))
        self.assertFalse(_sav_head_path(self.host).is_file())

    def test_RP_R08_publish_against_stale_revision_cannot_install_current_head(self):
        first = publish_sav_plan(
            self.host, _inspect_plan(task_revision=1), bind_task_contract=False
        )
        self.assertTrue(first.get("ok"), first)
        before = read_yaml(_sav_head_path(self.host))
        write_task(self.host, record_revision=2, **_bound_task())
        stale = dict(_inspect_plan(task_revision=1))
        stale["plan_id"] = "sav-20260906T150000Z-stale001"
        published = publish_sav_plan(self.host, stale, bind_task_contract=False)
        self.assertFalse(published.get("ok"), published)
        self.assertIsNone(published.get("head"))
        after = read_yaml(_sav_head_path(self.host))
        self.assertEqual(after.get("plan_id"), before.get("plan_id"))
        self.assertEqual(after.get("plan_digest"), before.get("plan_digest"))

    def test_RP_R09_fresh_process_sees_the_same_current_or_stale_decision(self):
        publish_sav_plan(self.host, _inspect_plan(task_revision=1))
        fresh_current = _subprocess_reconstruct(self.host)
        self.assertTrue(fresh_current.get("current"), fresh_current)
        write_task(self.host, record_revision=2, **_bound_task())
        local = reconstruct_sav_plan(self.host, task_id=TASK_A, requirement_id=REQUIREMENT)
        fresh_after = _subprocess_reconstruct(self.host)
        self.assertEqual(local.get("current"), fresh_after.get("current"))
        self.assertTrue(fresh_after.get("current"), fresh_after)

    def test_RP_R10_test_engine_reuses_the_same_currentness_decision(self):
        publish_sav_plan(self.host, _inspect_plan(task_revision=1))
        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
        )
        sav = result.extras.get("sav") or {}
        self.assertEqual(reconstructed.get("current"), sav.get("current"))
        self.assertTrue(sav.get("current"))
        write_task(self.host, record_revision=2, **_bound_task())
        after_revision = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        executed = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
        )
        executed_sav = executed.extras.get("sav") or {}
        self.assertEqual(after_revision.get("current"), executed_sav.get("current"))
        self.assertTrue(executed_sav.get("current"), executed_sav)
        stale = [
            item
            for item in (executed_sav.get("blockers") or [])
            if "Task revision" in item or "verification contract" in item
        ]
        self.assertEqual(stale, [])


class SavEvidenceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [passing_profile(PROFILE)])
        write_task(self.host, **_bound_task())
        publish_sav_plan(self.host, _inspect_plan(po2_status="SUFFICIENT"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP_E01_caller_local_execution_claim_cannot_satisfy_po(self):
        forged = [
            {**_assertion(po), "provenance": "LOCAL_EXECUTION"}
            for po in ("PO-1", "PO-2", "PO-3")
        ]
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=forged,
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))

    def test_RP_E02_omitted_provenance_does_not_become_human_observation(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[_assertion("PO-1"), _assertion("PO-2"), _assertion("PO-3")],
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("requirement_pass"))
        report = result.extras.get("report") or {}
        for item in report.get("evidence") or []:
            if item.get("kind") == "structured_assertion":
                self.assertNotEqual(item.get("provenance"), "HUMAN_OBSERVATION")

    def test_RP_E03_raw_pass_without_lawful_provenance_cannot_satisfy_feature_po(self):
        from scaffold_p6.sav import evaluate_sav_coverage

        reconstructed = reconstruct_sav_plan(
            self.host, task_id=TASK_A, requirement_id=REQUIREMENT
        )
        coverage = evaluate_sav_coverage(
            reconstructed.get("plan") or {},
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "summary": "player tile distance 0",
                }
            ],
            profile_results={PROFILE: "PASS"},
        )
        statuses = {row["po_id"]: row["status"] for row in coverage.get("proof_obligations") or []}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")
        self.assertFalse(coverage.get("requirement_pass"))

    def test_RP_E04_lawful_external_result_can_satisfy_its_po(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("requirement_pass"), sav)
        self.assertTrue(result.extras.get("test_pass"))

    def test_RP_E05_stale_candidate_external_assertion_cannot_satisfy_po(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1", candidate_digest="ab" * 32),
                _external_assertion(self.host, "PO-2", candidate_digest="ab" * 32),
                _external_assertion(self.host, "PO-3", candidate_digest="ab" * 32),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertFalse(sav.get("requirement_pass"))
        self.assertFalse(result.extras.get("test_pass"))

    def test_RP_E06_human_observation_requires_explicit_existing_rules(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _human_assertion("PO-1"),
                _human_assertion("PO-2"),
                _human_assertion("PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("requirement_pass"), sav)
        report = result.extras.get("report") or {}
        human = [
            item
            for item in report.get("evidence") or []
            if item.get("kind") == "structured_assertion"
        ]
        self.assertTrue(human)
        for item in human:
            self.assertEqual(item.get("provenance"), "HUMAN_OBSERVATION")
            self.assertEqual(item.get("binding_mechanism"), "synchronous_invocation")

    def test_RP_E07_broad_profile_pass_plus_forged_assertions_is_not_test_pass(self):
        forged = [
            {
                **_assertion(po),
                "provenance": "LOCAL_EXECUTION",
                "pass": True,
                "result": "PASS",
            }
            for po in ("PO-1", "PO-2", "PO-3")
        ]
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=forged,
        )
        self.assertFalse(result.extras.get("test_pass"))
        self.assertFalse((result.extras.get("sav") or {}).get("requirement_pass"))

    def test_RP_E08_lawful_assertion_plus_regression_profile_may_pass_requirement(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        statuses = {row["po_id"]: row["status"] for row in sav.get("proof_obligations") or []}
        self.assertEqual(statuses["PO-4"], "SATISFIED")
        self.assertTrue(sav.get("requirement_pass"), sav)

    def test_RP_E09_published_report_retains_truthful_provenance_and_binding(self):
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-2"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        report = result.extras.get("report") or {}
        assertions = [
            item
            for item in report.get("evidence") or []
            if item.get("kind") == "structured_assertion"
        ]
        self.assertTrue(assertions)
        for item in assertions:
            self.assertEqual(item.get("provenance"), "EXTERNAL_RESULT")
            self.assertEqual(item.get("mechanism"), "verifier_execution")
            self.assertEqual(item.get("binding_mechanism"), "explicit_candidate_digest")
            self.assertEqual(item.get("candidate_digest"), observe_candidate(self.host).digest)

    def test_RP_E10_insufficient_observability_handoff_remains(self):
        publish_sav_plan(self.host, _inspect_plan())
        result = test_engine(self.host).run(
            task_id=TASK_A,
            requirement_id=REQUIREMENT,
            selected=[PROFILE],
            sav_evidence=[
                _external_assertion(self.host, "PO-1"),
                _external_assertion(self.host, "PO-3"),
            ],
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("insufficient_observability"))
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "develop_or_human")
        self.assertEqual((sav.get("handoff") or {}).get("reason"), "INSUFFICIENT_OBSERVABILITY")


class BootstrapHumanGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_RP_B01_generic_adopt_intent_permits_preview_not_apply(self):
        before = files_under(self.host)
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(files_under(self.host), before)
        self.assertTrue(result.extras.get("preview_is_not_approval"))
        self.assertTrue(result.extras.get("generic_adoption_intent_is_not_plan_approval"))
        approved_without_digest = engine(self.host).run(
            "bootstrap",
            approval={"approved": True},
        )
        self.assertEqual(approved_without_digest.outcome, "NEEDS_HUMAN")
        self.assertEqual(approved_without_digest.mutations, "none")
        self.assertEqual(files_under(self.host), before)

    def test_RP_B02_preview_returns_needs_human_and_exact_plan_identity(self):
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        plan = result.extras["plan"]
        gate = result.extras["human_gate"]
        self.assertEqual(gate["plan_id"], plan["plan_id"])
        self.assertEqual(gate["plan_digest"], plan["digest"])
        self.assertTrue(gate["plan_id"])
        self.assertTrue(gate["plan_digest"])
        self.assertNotEqual(gate["mutation_envelope"], "")
        self.assertIn("ownership_changes", gate)
        self.assertIn("managed_regions", gate)
        self.assertIn("preserved_surfaces", gate)

    def test_RP_B03_no_explicit_post_preview_approval_does_not_mutate(self):
        preview = engine(self.host).run("bootstrap")
        before = files_under(self.host)
        skipped = engine(self.host).run("bootstrap")
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        self.assertEqual(skipped.outcome, "NEEDS_HUMAN")
        self.assertEqual(skipped.mutations, "none")
        self.assertEqual(files_under(self.host), before)
        self.assertFalse((self.host / ".scaffold").exists())

    def test_RP_B04_explicit_exact_approval_for_current_plan_allows_apply(self):
        preview = engine(self.host).run("bootstrap")
        plan = preview.extras["plan"]
        applied = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(applied.outcome, "COMPLETED", applied.blockers)
        self.assertNotEqual(applied.mutations, "none")
        self.assertTrue((self.host / ".scaffold/project.yaml").is_file())

    def test_RP_B05_approval_for_different_digest_is_blocked(self):
        preview = engine(self.host).run("bootstrap")
        before = files_under(self.host)
        blocked = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": "0" * 64},
        )
        self.assertEqual(blocked.outcome, "NEEDS_HUMAN")
        self.assertEqual(blocked.mutations, "none")
        self.assertEqual(files_under(self.host), before)
        self.assertNotEqual(preview.extras["plan"]["digest"], "0" * 64)


class ReviewPackageLocatorTests(unittest.TestCase):
    def test_RP_review_package_requires_referenced_result_yaml(self):
        completion = {
            "record_id": "rc-20260906T142946Z-ba8b4513",
            "output_locator": "understand-currentness/completions/rc-20260906T142946Z-ba8b4513/result.yaml",
        }
        packaged = [
            ".scaffold/runtime/understand-currentness/completions/rc-20260906T142946Z-ba8b4513/completion.yaml"
        ]
        missing = review_package_missing_targets(packaged, [completion])
        self.assertEqual(
            missing,
            ["understand-currentness/completions/rc-20260906T142946Z-ba8b4513/result.yaml"],
        )
        self.assertEqual(
            review_package_missing_targets(packaged, []),
            ["understand-currentness/completions/rc-20260906T142946Z-ba8b4513/result.yaml"],
        )
        packaged.append(
            ".scaffold/runtime/understand-currentness/completions/rc-20260906T142946Z-ba8b4513/result.yaml"
        )
        self.assertEqual(review_package_missing_targets(packaged, [completion]), [])
        self.assertEqual(
            referenced_completion_targets(completion),
            ["understand-currentness/completions/rc-20260906T142946Z-ba8b4513/result.yaml"],
        )


class PackageImportCorrectionTests(unittest.TestCase):
    def test_RP_fresh_scaffold_p6_import_resolves_test_engine(self):
        from scaffold_p6 import TestEngine

        self.assertEqual(TestEngine.__name__, "TestEngine")


if __name__ == "__main__":
    unittest.main()

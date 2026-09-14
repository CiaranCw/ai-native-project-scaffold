from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, write_host
from p7_support import TASK_A, write_task
from support import write

from scaffold_p6.analysis import analyze
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.evidence import compile_supplied_bundle
from scaffold_p6.models import ScenarioResult
from scaffold_p6.sav import revalidate_sav_plan


class P6SupportingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_host(self.host, [], ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"})
        write(self.host, "src/mvp/vault.js", "export const vault = true\n")
        write(self.host, "artifacts/evidence/mvp-vault/run.log", "observed\n")
        self.task = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope={
                "paths": ["src/mvp"],
                "modules": [],
                "exclude": [],
                "supporting_paths": ["artifacts/evidence/mvp-vault"],
            },
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Keep evidence supporting.",
                    "acceptance": "Evidence remains supporting.",
                    "status": "IN_PROGRESS",
                    "required_tests": [
                        {"requirement_id": "req-vault"},
                    ],
                }
            ],
            final_tests=[{"requirement_id": "req-vault"}],
        )
        self.candidate = observe_candidate(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_supporting_file_artifact_ingests_without_manufacturing_pass(self):
        items, refs, complete, blockers, result = compile_supplied_bundle(
            run_id="tr-fixture",
            profile_id="unit",
            candidate=self.candidate,
            supplied_items=[
                {
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "file_artifact",
                    "locator": "artifacts/evidence/mvp-vault/run.log",
                    "candidate_digest": self.candidate.digest,
                    "summary": "supporting evidence log",
                }
            ],
            required_kinds=["file_artifact"],
            declared_provenance="HUMAN_OBSERVATION",
            host_root=self.host,
            task=self.task,
        )
        self.assertFalse(blockers, blockers)
        self.assertTrue(items)
        self.assertEqual(items[0]["candidate_digest"], self.candidate.digest)
        self.assertNotEqual(result, "PASS")
        analysis = analyze(
            required_ids=["unit"],
            optional_ids=[],
            results=[
                ScenarioResult(
                    profile_id="unit",
                    required=True,
                    result=result,
                    provenance="HUMAN_OBSERVATION",
                    adapter="none",
                    command_ref="",
                    blockers=blockers,
                    evidence_ids=[item["evidence_id"] for item in items],
                    evidence_complete=complete,
                )
            ],
            candidate_match=True,
            verified_no_required=False,
            contract_blockers=[],
            required_set_authoritative=True,
        )
        self.assertFalse(analysis["test_complete"])
        self.assertFalse(analysis.get("test_pass"))

    def test_out_of_scope_and_mismatched_candidate_fail_closed(self):
        write(self.host, "lib/other/secret.log", "nope\n")
        _items, _refs, _complete, blockers, result = compile_supplied_bundle(
            run_id="tr-fixture",
            profile_id="unit",
            candidate=self.candidate,
            supplied_items=[
                {
                    "provenance": "HUMAN_OBSERVATION",
                    "kind": "file_artifact",
                    "locator": "lib/other/secret.log",
                    "candidate_digest": self.candidate.digest,
                    "summary": "out of supporting scope",
                }
            ],
            required_kinds=["file_artifact"],
            declared_provenance="HUMAN_OBSERVATION",
            host_root=self.host,
            task=self.task,
        )
        self.assertTrue(blockers)
        self.assertEqual(result, "BLOCKED")
        _items, _refs, _complete, mismatch, mismatch_result = compile_supplied_bundle(
            run_id="tr-fixture",
            profile_id="unit",
            candidate=self.candidate,
            supplied_items=[
                {
                    "provenance": "EXTERNAL_RESULT",
                    "kind": "file_artifact",
                    "locator": "artifacts/evidence/mvp-vault/run.log",
                    "candidate_digest": "sha256:" + ("0" * 64),
                    "summary": "stale candidate",
                    "result": "PASS",
                }
            ],
            required_kinds=["file_artifact"],
            declared_provenance="EXTERNAL_RESULT",
            host_root=self.host,
            task=self.task,
        )
        self.assertTrue(mismatch)
        self.assertNotEqual(mismatch_result, "PASS")

    def test_supporting_membership_does_not_create_execution_binding(self):
        revalidated = revalidate_sav_plan(
            self.host,
            {
                "task_id": TASK_A,
                "requirement_id": "req-vault",
                "binding": {},
            },
            task=self.task,
        )
        self.assertFalse(revalidated.get("ok"))
        self.assertTrue(
            any("execution_binding" in item for item in revalidated.get("blockers") or []),
            revalidated,
        )

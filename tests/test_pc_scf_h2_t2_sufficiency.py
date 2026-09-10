from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import passing_profile, test_engine, write_host
from p7_support import TASK_A, write_task
from scaffold_p6.sav import evaluate_sav_coverage, publish_sav_plan
from scaffold_p6.sufficiency import derive_adequacy
from support import write


PROFILE = "unit"
DIGEST = "ab" * 32


def _po(
    po_id: str,
    *,
    strategy: str = "structured_assertion",
    required: bool = True,
    observability: str = "SUFFICIENT",
    evidence: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    row = {
        "po_id": po_id,
        "obligation": po_id,
        "required": required,
        "observable_signals": [po_id],
        "execution_strategy": strategy,
        "assertions": [f"{po_id} holds"],
        "evidence_requirements": evidence or ["structured_assertion"],
        "observability_status": observability,
    }
    if extra:
        row.update(extra)
    return row


def _plan(*obligations: dict) -> dict:
    return {
        "record_type": "test_scenario_aware_plan",
        "schema_version": "1",
        "supporting": True,
        "canonical": False,
        "plan_id": "sav-20260909T000000Z-abcdef01",
        "task_id": TASK_A,
        "task_revision": 1,
        "requirement_id": "req-h2",
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "scenario": {
            "initial_state": "ready",
            "action": "verify",
            "expected_result": "pass",
        },
        "proof_obligations": list(obligations),
    }


def _assertion(po_id: str, *, passed: bool = True, **extra) -> dict:
    item = {
        "kind": "structured_assertion",
        "po_id": po_id,
        "profile_id": PROFILE,
        "summary": po_id,
        "assertion": {"po_id": po_id, "pass": passed},
        "pass": passed,
        "result": "PASS" if passed else "FAIL",
        "provenance": "HUMAN_OBSERVATION",
        "usable": True,
        "candidate_digest": DIGEST,
    }
    item.update(extra)
    if not item.get("candidate_digest"):
        item.pop("candidate_digest", None)
    return item


class EvidenceSufficiencyTests(unittest.TestCase):
    def test_T2_01_legacy_structured_assertion_still_satisfies_po(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1"), _po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[
                _assertion("PO-1"),
                {
                    "kind": "command_result",
                    "result": "PASS",
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                },
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_T2_02_suite_command_result_pass_satisfies_suite_po(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[{"kind": "command_result", "result": "PASS", "provenance": "LOCAL_EXECUTION"}],
            profile_results={PROFILE: "PASS"},
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-S"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_T2_03_command_result_pass_cannot_satisfy_state_transition_po(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-ST", strategy="state_transition", evidence=["structured_state"])),
            evidence=[
                {
                    "kind": "command_result",
                    "po_id": "PO-ST",
                    "result": "PASS",
                    "pass": True,
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                    "command": ["true"],
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-ST"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_T2_04_structured_state_without_assertion_cannot_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-ST", strategy="state_transition", evidence=["structured_state"])),
            evidence=[
                {
                    "kind": "structured_state",
                    "po_id": "PO-ST",
                    "state": {"phase": "ready"},
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-ST"], "UNSATISFIED")

    def test_T2_05_structured_state_with_explicit_pass_can_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-ST", strategy="state_transition", evidence=["structured_state"])),
            evidence=[
                {
                    "kind": "structured_state",
                    "po_id": "PO-ST",
                    "state": {"phase": "ready"},
                    "assertions": [{"po_id": "PO-ST", "pass": True, "result": "PASS"}],
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-ST"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_T2_06_event_trace_existence_alone_cannot_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-T", strategy="event_trace", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-T",
                    "trace": {"scenario_id": "s1", "actions": ["click"]},
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-T"], "UNSATISFIED")

    def test_T2_07_event_trace_with_po_bound_pass_can_satisfy(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-T", strategy="event_trace", evidence=["event_trace"])),
            evidence=[
                {
                    "kind": "event_trace",
                    "po_id": "PO-T",
                    "trace": {
                        "scenario_id": "s1",
                        "actions": ["click"],
                        "assertions": [{"po_id": "PO-T", "pass": True}],
                    },
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-T"], "SATISFIED")

    def test_T2_08_one_trace_can_independently_satisfy_two_pos(self):
        coverage = evaluate_sav_coverage(
            _plan(
                _po("PO-A", strategy="event_trace", evidence=["event_trace"]),
                _po("PO-B", strategy="event_trace", evidence=["event_trace"]),
            ),
            evidence=[
                {
                    "kind": "event_trace",
                    "covers": ["PO-A", "PO-B"],
                    "trace": {
                        "scenario_id": "s1",
                        "assertions": [
                            {"po_id": "PO-A", "pass": True},
                            {"po_id": "PO-B", "pass": True},
                        ],
                    },
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-A"], "SATISFIED")
        self.assertEqual(statuses["PO-B"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_T2_09_covers_list_without_verdict_cannot_fake_coverage(self):
        coverage = evaluate_sav_coverage(
            _plan(
                _po("PO-A"),
                _po("PO-B"),
            ),
            evidence=[
                {
                    "kind": "structured_assertion",
                    "covers": ["PO-A", "PO-B"],
                    "pass": True,
                    "result": "PASS",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                    "summary": "blanket pass",
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-A"], "UNSATISFIED")
        self.assertEqual(statuses["PO-B"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_T2_10_visual_checkpoint_cannot_satisfy_structural_po(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1")),
            evidence=[
                {
                    "kind": "visual_checkpoint",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "locator": "shots/one.png",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")

    def test_T2_11_stale_candidate_evidence_blocks(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1"), _po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[_assertion("PO-1", candidate_digest="cd" * 32)],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_T2_12_incorrect_provenance_blocks(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1"), _po("PO-S", strategy="regression", evidence=["command_result"])),
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "assertion": {"po_id": "PO-1", "pass": True},
                    "provenance": "LOCAL_EXECUTION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")

    def test_T2_13_required_primary_missing_makes_test_complete_false(self):
        host = self._host()
        publish_sav_plan(
            host,
            _plan(_po("PO-1"), _po("PO-S", strategy="regression", evidence=["command_result"])),
        )
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id="req-h2",
            selected=[PROFILE],
        )
        self.assertFalse(result.extras["test_complete"])
        self.assertFalse((result.extras.get("sav") or {}).get("requirement_pass"))

    def test_T2_14_engine_derived_adequacy_unsatisfied_makes_test_complete_false(self):
        host = self._host()
        published = publish_sav_plan(
            host,
            _plan(_po("PO-1"), _po("PO-S", strategy="regression", evidence=["command_result"])),
        )
        self.assertTrue(published.get("ok"), published)
        result = test_engine(host).run(
            task_id=TASK_A,
            requirement_id="req-h2",
            selected=[PROFILE],
            sav_evidence=[_assertion("PO-1", role="SECONDARY", candidate_digest="")],
            adequacy={"status": "SATISFIED"},
        )
        sav = result.extras.get("sav") or {}
        self.assertTrue(sav.get("current"), sav)
        adequacy = (result.extras.get("completeness") or {}).get("adequacy") or sav.get("adequacy")
        self.assertEqual((adequacy or {}).get("status"), "UNSATISFIED", sav)
        self.assertEqual((adequacy or {}).get("authority"), "engine")
        self.assertFalse(result.extras["test_complete"])

    def test_T2_15_required_unknown_adequacy_cannot_pass(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", observability="UNKNOWN")),
            evidence=[_assertion("PO-1")],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
            caller_adequacy={"status": "SATISFIED"},
        )
        self.assertEqual(coverage["adequacy"]["status"], "UNKNOWN")
        self.assertFalse(coverage["requirement_pass"])
        derived = derive_adequacy(
            _plan(_po("PO-1", observability="UNKNOWN")),
            coverage["proof_obligations"],
            [_assertion("PO-1")],
            profile_pass=True,
            candidate_digest=DIGEST,
            caller_adequacy={"status": "SATISFIED"},
        )
        self.assertEqual(derived["status"], "UNKNOWN")

    def test_T2_secondary_role_survives_supplied_compiler(self):
        from scaffold_p6.evidence import compile_supplied_bundle
        from scaffold_p6.models import CandidateIdentity

        candidate = CandidateIdentity(
            {"candidate_digest": DIGEST, "observation_ok": True, "kind": "none"}
        )
        items, _refs, _complete, blockers, _result = compile_supplied_bundle(
            run_id="testrun-20260909T000000Z-abcd1234",
            profile_id=PROFILE,
            candidate=candidate,
            supplied_items=[_assertion("PO-1", role="SECONDARY")],
            required_kinds=["structured_assertion"],
            declared_provenance="HUMAN_OBSERVATION",
        )
        self.assertEqual(blockers, [])
        self.assertEqual(items[0].get("role"), "SECONDARY")
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1")),
            evidence=items,
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")

    def test_T2_supporting_artifact_cannot_prove_negative_control(self):
        coverage = evaluate_sav_coverage(
            _plan(_po("PO-1", extra={"negative_control": True})),
            evidence=[
                _assertion("PO-1"),
                {
                    "kind": "file_artifact",
                    "po_id": "PO-1",
                    "negative_control": True,
                    "pass": True,
                    "result": "PASS",
                    "locator": "out/rejected.log",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                },
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertEqual(coverage["proof_obligations"][0]["status"], "SATISFIED")
        self.assertEqual(coverage["adequacy"]["status"], "UNSATISFIED")

    def _host(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir()
        write_host(host, [passing_profile(PROFILE)])
        write_task(host, title="h2", final_tests=[{"requirement_id": "req-h2", "execution_binding": {"kind": "test_profile", "profile_id": PROFILE}}])
        write(host, "src/app.py", "print('ok')\n")
        return host


if __name__ == "__main__":
    unittest.main()

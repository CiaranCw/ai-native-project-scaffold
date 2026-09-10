from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import passing_profile, test_engine, write_host
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p6.sav import evaluate_sav_coverage
from scaffold_p6.trace import (
    retention_allows_s9,
    validate_role,
    validate_trace_envelope,
    visual_is_required_by_default,
)
from support import REPO, write


PROFILE = "unit"
DIGEST = "ab" * 32


def _structural_plan() -> dict:
    return {
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "proof_obligations": [
            {
                "po_id": "PO-1",
                "obligation": "structural fact",
                "required": True,
                "observable_signals": ["value"],
                "execution_strategy": "structured_assertion",
                "assertions": ["value is 1"],
                "evidence_requirements": ["structured_assertion"],
                "observability_status": "SUFFICIENT",
            }
        ],
    }


class TraceRoleRetentionTests(unittest.TestCase):
    def test_T3_01_valid_generic_event_trace_schema(self):
        issues = validate_trace_envelope(
            {
                "scenario_id": "web-login",
                "candidate": DIGEST,
                "requirement_ids": ["REQ-1"],
                "obligation_ids": ["PO-1"],
                "initial_state": {"route": "/login"},
                "actions": [{"type": "submit"}],
                "observations": [{"status": 200}],
                "assertions": [{"po_id": "PO-1", "pass": True}],
                "artifacts": ["trace.json"],
                "result": "PASS",
            }
        )
        self.assertEqual(issues, [])

    def test_T3_02_game_like_opaque_payload_accepted_without_game_core_fields(self):
        issues = validate_trace_envelope(
            {
                "scenario_id": "interactive-session",
                "actions": [{"type": "move"}],
                "assertions": [{"po_id": "PO-1", "pass": True}],
                "domain": {
                    "actor_id": "a1",
                    "view": "third_person",
                    "clip": "idle",
                },
            }
        )
        self.assertEqual(issues, [])

    def test_T3_03_web_api_like_opaque_payload_accepted(self):
        issues = validate_trace_envelope(
            {
                "scenario_id": "api-create",
                "actions": [{"method": "POST", "path": "/items"}],
                "observations": [{"status": 201}],
                "assertions": [{"po_id": "PO-1", "pass": True}],
                "payload": {"request_id": "r1", "json": {"name": "item"}},
            }
        )
        self.assertEqual(issues, [])

    def test_T3_04_role_validation(self):
        self.assertEqual(validate_role("PRIMARY"), [])
        self.assertEqual(validate_role("SECONDARY"), [])
        self.assertEqual(validate_role("ESCALATION"), [])
        self.assertEqual(validate_role(None), [])
        self.assertTrue(validate_role("OWNER"))

    def test_T3_05_required_po_with_only_secondary_lacks_primary(self):
        coverage = evaluate_sav_coverage(
            _structural_plan(),
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "role": "SECONDARY",
                    "pass": True,
                    "result": "PASS",
                    "assertion": {"po_id": "PO-1", "pass": True},
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
        self.assertIn("PRIMARY", coverage["proof_obligations"][0]["reason"])
        self.assertEqual(coverage["adequacy"]["status"], "UNSATISFIED")

    def test_T3_06_legacy_assertion_without_role_remains_compatible(self):
        coverage = evaluate_sav_coverage(
            _structural_plan(),
            evidence=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "assertion": {"po_id": "PO-1", "pass": True},
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_T3_supplied_compiler_preserves_debug_retention(self):
        from scaffold_p6.evidence import compile_supplied_bundle
        from scaffold_p6.models import CandidateIdentity

        candidate = CandidateIdentity(
            {"candidate_digest": DIGEST, "observation_ok": True, "kind": "none"}
        )
        items, _refs, _complete, blockers, _result = compile_supplied_bundle(
            run_id="testrun-20260909T000000Z-abcd1234",
            profile_id=PROFILE,
            candidate=candidate,
            supplied_items=[
                {
                    "kind": "structured_assertion",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "assertion": {"po_id": "PO-1", "pass": True},
                    "provenance": "HUMAN_OBSERVATION",
                    "retention_class": "DEBUG",
                    "summary": "debug assertion",
                }
            ],
            required_kinds=["structured_assertion"],
            declared_provenance="HUMAN_OBSERVATION",
        )
        self.assertEqual(blockers, [])
        self.assertEqual(items[0].get("retention_class"), "DEBUG")
        allowed, reason = retention_allows_s9(items[0])
        self.assertFalse(allowed)
        self.assertIn("DEBUG", reason)

    def test_T3_07_debug_locator_rejected_from_durable_cr_support(self):
        host, refs = self._published_refs()
        self._patch_retention(host, refs, "DEBUG")
        materialization, issues = test_engine(host).materialize_evidence(
            refs, coordination_id="change-20260909T120000Z-debug001"
        )
        self.assertIsNone(materialization)
        self.assertTrue(any("DEBUG" in item for item in issues), issues)

    def test_T3_08_temporary_runtime_locator_rejected_from_durable_cr_support(self):
        host, refs = self._published_refs()
        self._patch_retention(host, refs, "TEMPORARY_RUNTIME")
        materialization, issues = test_engine(host).materialize_evidence(
            refs, coordination_id="change-20260909T120000Z-tmp00001"
        )
        self.assertIsNone(materialization)
        self.assertTrue(any("TEMPORARY_RUNTIME" in item for item in issues), issues)

    def test_T3_09_durable_finalization_locator_follows_normal_s9_materialization(self):
        host, refs = self._published_refs()
        self._patch_retention(host, refs, "DURABLE_FINALIZATION")
        materialization, issues = test_engine(host).materialize_evidence(
            refs, coordination_id="change-20260909T120000Z-dur00001"
        )
        self.assertEqual(issues, [])
        self.assertIsNotNone(materialization)
        self.assertTrue((host / ".scaffold/ext/test/evidence").exists())

    def test_T3_10_optional_visual_does_not_become_required_merely_because_it_exists(self):
        self.assertFalse(visual_is_required_by_default())
        coverage = evaluate_sav_coverage(
            _structural_plan(),
            evidence=[
                {
                    "kind": "visual_checkpoint",
                    "po_id": "PO-1",
                    "role": "ESCALATION",
                    "retention_class": "OPTIONAL_VISUAL",
                    "pass": True,
                    "result": "PASS",
                    "locator": "shots/ui.png",
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
        ok, reason = retention_allows_s9(
            {"retention_class": "OPTIONAL_VISUAL"}
        )
        self.assertFalse(ok)
        self.assertIn("justification", reason)

    def test_T3_11_visual_checkpoint_alone_does_not_make_structural_po_complete(self):
        coverage = evaluate_sav_coverage(
            _structural_plan(),
            evidence=[
                {
                    "kind": "visual_checkpoint",
                    "po_id": "PO-1",
                    "pass": True,
                    "result": "PASS",
                    "locator": "shots/ui.png",
                    "provenance": "HUMAN_OBSERVATION",
                    "usable": True,
                    "candidate_digest": DIGEST,
                }
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        self.assertFalse(coverage["requirement_pass"])
        self.assertEqual(coverage["proof_obligations"][0]["status"], "UNSATISFIED")

    def test_T3_12_correction04_s9_materialize_before_cr_ordering_remains_intact(self):
        text = (REPO / "src" / "scaffold_p8" / "engine.py").read_text(encoding="utf-8")
        start = text.find("s10_gate.acquire")
        self.assertGreater(start, 0)
        block = text[start:start + 2500]
        self.assertLess(
            block.find("materialize_evidence"),
            block.find("persist_candidate_change"),
        )
        self.assertGreater(block.find("persist_candidate_change"), 0)

    def _published_refs(self) -> tuple[Path, list[dict]]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        host.mkdir()
        write_host(host, [passing_profile(PROFILE)])
        write(host, "src/app.py", "print('ok')\n")
        published = test_engine(host).run(selected=[PROFILE])
        self.assertEqual(published.outcome, "COMPLETED", published.blockers)
        refs = test_engine(host).build_evidence_refs(published.extras["report_id"])
        self.assertTrue(refs)
        return host, refs

    def _patch_retention(self, host: Path, refs: list[dict], retention: str) -> None:
        from urllib.parse import unquote

        locator = str(refs[0]["locator"])
        path_part, marker, encoded = locator.partition("#evidence/")
        run_id = path_part.split("/")[1]
        report_path = host / ".scaffold/runtime/test-runs" / run_id / "report.yaml"
        from scaffold_p5.io_util import read_yaml

        report = read_yaml(report_path)
        if marker:
            evidence_id = unquote(encoded)
            for item in report.get("evidence") or []:
                if item.get("evidence_id") == evidence_id:
                    item["retention_class"] = retention
        else:
            for item in report.get("evidence") or []:
                item["retention_class"] = retention
        write_yaml_atomic(report_path, report)


if __name__ == "__main__":
    unittest.main()

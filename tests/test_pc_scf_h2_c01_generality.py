from __future__ import annotations

import unittest

from scaffold_p6.sav import evaluate_sav_coverage
from scaffold_p6.trace import (
    TRACE_ENVELOPE_FIELDS,
    OPAQUE_PAYLOAD_KEYS,
    retention_allows_s9,
    validate_role,
    validate_trace_envelope,
    visual_is_required_by_default,
)
from support import REPO


PROFILE = "unit"
DIGEST = "ab" * 32
TRACE_PY = REPO / "src" / "scaffold_p6" / "trace.py"
DOMAIN_BLACKLIST_TOKENS = (
    "project-city",
    "src/mvp",
    "vault",
    "babylon",
    "player",
    "camera",
    "animation",
    "game_tick",
)


def _trace_plan() -> dict:
    return {
        "binding": {"kind": "test_profile", "profile_id": PROFILE},
        "proof_obligations": [
            {
                "po_id": "PO-1",
                "obligation": "structural fact",
                "required": True,
                "observable_signals": ["value"],
                "execution_strategy": "event_trace",
                "assertions": ["value is 1"],
                "evidence_requirements": ["event_trace"],
                "observability_status": "SUFFICIENT",
            }
        ],
    }


def _trace_evidence(trace: dict, **extra) -> dict:
    item = {
        "kind": "event_trace",
        "po_id": "PO-1",
        "trace": trace,
        "provenance": "LOCAL_EXECUTION",
        "usable": True,
        "candidate_digest": DIGEST,
    }
    item.update(extra)
    return item


class GeneralityClosureTests(unittest.TestCase):
    def test_G01_core_trace_source_has_no_consumer_domain_blacklist(self):
        text = TRACE_PY.read_text(encoding="utf-8")
        self.assertNotIn("CORE_FORBIDDEN_REQUIRED_FIELDS", text)
        lowered = text.lower()
        hits = [token for token in DOMAIN_BLACKLIST_TOKENS if token in lowered]
        self.assertEqual(hits, [])
        known = set(TRACE_ENVELOPE_FIELDS) | set(OPAQUE_PAYLOAD_KEYS)
        self.assertTrue({"scenario_id", "assertions", "domain", "payload"} <= known)
        self.assertNotIn("foo", known)
        self.assertNotIn("tensor", known)

    def test_G02_opaque_domain_payload_accepted_identically_across_domains(self):
        traces = (
            {
                "scenario_id": "web-create",
                "actions": [{"method": "POST", "path": "/items"}],
                "observations": [{"status": 201}],
                "domain": {"request_id": "r1", "json": {"name": "item"}},
            },
            {
                "scenario_id": "ml-eval",
                "initial_state": {"split": "val"},
                "observations": [{"metric": "f1", "value": 0.9}],
                "domain": {"checkpoint": "epoch-12", "tensor_stats": {"mean": 0.1}},
            },
            {
                "scenario_id": "interactive-session",
                "actions": [{"type": "move"}],
                "domain": {"actor_id": "a1", "view": "third_person", "clip": "idle"},
            },
        )
        results = [validate_trace_envelope(item) for item in traces]
        self.assertEqual(results[0], [])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_G03_unknown_top_level_payload_is_not_rejected_by_domain_name(self):
        issues = validate_trace_envelope(
            {
                "scenario_id": "legacy-unknown",
                "foo": {"ok": True},
                "database": {"rows": 1},
                "tensor": [0.1, 0.2],
                "player": {"id": "ignored-as-name"},
            }
        )
        self.assertEqual(issues, [])

    def test_G04_unknown_top_level_payload_cannot_satisfy_required_po(self):
        coverage = evaluate_sav_coverage(
            _trace_plan(),
            evidence=[
                _trace_evidence(
                    {
                        "scenario_id": "legacy-unknown",
                        "foo": {"pass": True, "po_id": "PO-1"},
                        "database": {"pass": True},
                        "tensor": {"result": "PASS"},
                        "player": {"po_id": "PO-1", "pass": True},
                    }
                )
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_G04b_opaque_namespace_assertions_cannot_satisfy_required_po(self):
        coverage = evaluate_sav_coverage(
            _trace_plan(),
            evidence=[
                _trace_evidence(
                    {
                        "scenario_id": "opaque-nested",
                        "domain": {
                            "assertions": [{"po_id": "PO-1", "pass": True}]
                        },
                        "payload": {
                            "assertions": [{"po_id": "PO-1", "pass": True}]
                        },
                    }
                )
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "UNSATISFIED")
        self.assertFalse(coverage["requirement_pass"])

    def test_G05_generic_envelope_assertion_still_satisfies_po(self):
        coverage = evaluate_sav_coverage(
            _trace_plan(),
            evidence=[
                _trace_evidence(
                    {
                        "scenario_id": "web-create",
                        "actions": [{"method": "POST"}],
                        "assertions": [{"po_id": "PO-1", "pass": True}],
                        "domain": {"request_id": "r1"},
                    }
                )
            ],
            profile_results={PROFILE: "PASS"},
            candidate_digest=DIGEST,
        )
        statuses = {row["po_id"]: row["status"] for row in coverage["proof_obligations"]}
        self.assertEqual(statuses["PO-1"], "SATISFIED")
        self.assertTrue(coverage["requirement_pass"])

    def test_G06_existing_t3_generic_trace_tests_remain_pass(self):
        from test_pc_scf_h2_t3_evidence import TraceRoleRetentionTests

        case = TraceRoleRetentionTests("test_T3_01_valid_generic_event_trace_schema")
        case.test_T3_01_valid_generic_event_trace_schema()
        case = TraceRoleRetentionTests(
            "test_T3_02_game_like_opaque_payload_accepted_without_game_core_fields"
        )
        case.test_T3_02_game_like_opaque_payload_accepted_without_game_core_fields()
        case = TraceRoleRetentionTests("test_T3_03_web_api_like_opaque_payload_accepted")
        case.test_T3_03_web_api_like_opaque_payload_accepted()

    def test_G07_visual_role_retention_behavior_unchanged(self):
        self.assertFalse(visual_is_required_by_default())
        self.assertEqual(validate_role("PRIMARY"), [])
        self.assertEqual(validate_role("SECONDARY"), [])
        self.assertEqual(validate_role("ESCALATION"), [])
        allowed, reason = retention_allows_s9({"retention_class": "DEBUG"})
        self.assertFalse(allowed)
        self.assertIn("DEBUG", reason)
        allowed, reason = retention_allows_s9({"retention_class": "OPTIONAL_VISUAL"})
        self.assertFalse(allowed)
        self.assertIn("justification", reason)
        coverage = evaluate_sav_coverage(
            {
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
            },
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


if __name__ == "__main__":
    unittest.main()

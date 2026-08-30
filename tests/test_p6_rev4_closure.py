from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import failing_profile, passing_profile, test_engine, write_host
from scaffold_p6.schemas import validate_report
from scaffold_p6.storage import load_completed_report


class P6Rev4ClosureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _pass_report(self) -> dict:
        write_host(self.host, [passing_profile()])
        return test_engine(self.host).run().extras["report"]

    def _fail_complete_report(self) -> tuple[dict, str]:
        write_host(self.host, [failing_profile()])
        result = test_engine(self.host).run()
        return result.extras["report"], result.extras["report_id"]

    def _validate(self, report: dict) -> str:
        try:
            status, _issues = validate_report(report)
        except Exception as exc:  # noqa: BLE001 - validator must fail closed
            self.fail(f"validate_report raised {exc!r}")
        return status

    def _empty_required_counters(self, completeness: dict) -> None:
        completeness["required"] = []
        completeness["required_total"] = 0
        completeness["required_pass"] = 0
        completeness["required_fail"] = 0
        completeness["required_blocked"] = 0
        completeness["required_not_run"] = 0
        completeness["required_terminal_usable"] = 0
        completeness["missing_required"] = []
        completeness["blocked_required"] = []

    def test_Y01_missing_required_total_invalid(self):
        report = self._pass_report()
        del report["completeness"]["required_total"]
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y02_missing_required_pass_invalid(self):
        report = self._pass_report()
        del report["completeness"]["required_pass"]
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y03_missing_required_set_authoritative_invalid(self):
        report, _run_id = self._fail_complete_report()
        self.assertTrue(report["completeness"]["test_complete"])
        self.assertFalse(report["completeness"]["test_pass"])
        del report["completeness"]["required_set_authoritative"]
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y04_optional_profile_flagged_required_invalid(self):
        report = self._pass_report()
        report["profiles"][0]["required"] = False
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y05_required_profile_listed_optional_invalid(self):
        report = self._pass_report()
        profile_id = report["profiles"][0]["id"]
        self._empty_required_counters(report["completeness"])
        report["completeness"]["optional"] = [profile_id]
        report["completeness"]["optional_total"] = 1
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y06_required_removed_from_required_set_still_invalid(self):
        report = self._pass_report()
        self.assertTrue(report["profiles"][0]["required"])
        self._empty_required_counters(report["completeness"])
        report["completeness"]["optional"] = []
        report["completeness"]["optional_total"] = 0
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y07_profile_in_neither_set_invalid(self):
        report = self._pass_report()
        report["completeness"]["required"] = []
        report["completeness"]["optional"] = []
        report["completeness"]["required_total"] = 0
        report["completeness"]["optional_total"] = 0
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y08_false_batch_evidence_complete_with_test_pass_invalid(self):
        report = self._pass_report()
        self.assertTrue(report["completeness"]["test_pass"])
        self.assertTrue(report["profiles"][0]["evidence_complete"])
        report["completeness"]["batch_evidence_complete"] = False
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y09_false_coverage_evidence_complete_with_test_complete_invalid(self):
        report = self._pass_report()
        self.assertTrue(report["completeness"]["test_complete"])
        self.assertTrue(report["profiles"][0]["evidence_complete"])
        report["completeness"]["evidence_complete"] = False
        self.assertNotEqual(self._validate(report), "VALID")

    def test_Y10_generated_pass_and_required_fail_complete_remain_valid(self):
        write_host(self.host, [passing_profile()])
        passed = test_engine(self.host).run()
        self.assertEqual(self._validate(passed.extras["report"]), "VALID")
        loaded_pass = load_completed_report(self.host, passed.extras["report_id"])
        self.assertIsNotNone(loaded_pass)
        self.assertTrue(loaded_pass["verification"]["test_pass"])
        self.assertTrue(loaded_pass["verification"]["test_complete"])

        fail_host = Path(self._tmp.name) / "fail-host"
        fail_host.mkdir()
        write_host(fail_host, [failing_profile()])
        failed = test_engine(fail_host).run()
        self.assertEqual(failed.extras["report"]["profiles"][0]["result"], "FAIL")
        self.assertEqual(self._validate(failed.extras["report"]), "VALID")
        loaded_fail = load_completed_report(fail_host, failed.extras["report_id"])
        self.assertIsNotNone(loaded_fail)
        self.assertFalse(loaded_fail["verification"]["test_pass"])
        self.assertTrue(loaded_fail["verification"]["test_complete"])


if __name__ == "__main__":
    unittest.main()

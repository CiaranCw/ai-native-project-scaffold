from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import failing_profile, passing_profile, test_engine, write_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.schemas import validate_report
from scaffold_p6.storage import load_completed_report, run_dir


class P6Rev4Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _pass_report(self) -> dict:
        write_host(self.host, [passing_profile()])
        return test_engine(self.host).run().extras["report"]

    def _validate(self, report: dict) -> str:
        try:
            status, _issues = validate_report(report)
        except Exception as exc:  # noqa: BLE001 - test must prove fail-closed
            self.fail(f"validate_report raised {exc!r}")
        return status

    def test_X01_required_scalar_is_non_valid_without_exception(self):
        report = self._pass_report()
        report["completeness"]["required"] = 1
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X02_optional_non_list_is_non_valid_without_exception(self):
        report = self._pass_report()
        report["completeness"]["optional"] = "unit"
        self.assertNotEqual(self._validate(report), "VALID")
        report["completeness"]["optional"] = {"id": "unit"}
        self.assertNotEqual(self._validate(report), "VALID")
        report["completeness"]["optional"] = 0
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X03_persisted_malformed_report_load_is_none_without_exception(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        report = read_yaml(dest / "report.yaml")
        report["completeness"]["required"] = 1
        write_yaml_atomic(dest / "report.yaml", report)
        try:
            loaded = load_completed_report(self.host, run_id)
        except Exception as exc:  # noqa: BLE001 - test must prove fail-closed
            self.fail(f"load_completed_report raised {exc!r}")
        self.assertIsNone(loaded)

    def test_X04_required_total_mismatch_invalid(self):
        report = self._pass_report()
        report["completeness"]["required_total"] = 999
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X05_optional_total_mismatch_invalid(self):
        report = self._pass_report()
        report["completeness"]["optional_total"] = 5
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X06_required_counter_mismatch_invalid(self):
        report = self._pass_report()
        report["completeness"]["required_terminal_usable"] = 0
        self.assertNotEqual(self._validate(report), "VALID")
        report = self._pass_report()
        report["completeness"]["required_pass"] = True
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X07_candidate_match_fields_must_agree(self):
        report = self._pass_report()
        report["candidate_match"] = True
        report["completeness"]["candidate_match"] = False
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X08_pass_without_evidence_cannot_be_test_pass(self):
        report = self._pass_report()
        report["profiles"][0]["evidence_complete"] = False
        report["completeness"]["test_pass"] = True
        report["verification"]["test_pass"] = True
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X09_non_boolean_profile_evidence_complete_invalid(self):
        report = self._pass_report()
        report["profiles"][0]["evidence_complete"] = "true"
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X10_non_authoritative_required_cannot_be_complete(self):
        report = self._pass_report()
        report["completeness"]["required_set_authoritative"] = False
        report["completeness"]["test_complete"] = True
        report["verification"]["test_complete"] = True
        self.assertNotEqual(self._validate(report), "VALID")

    def test_X11_required_fail_may_still_be_test_complete(self):
        write_host(self.host, [failing_profile()])
        result = test_engine(self.host).run()
        report = result.extras["report"]
        completeness = result.extras["completeness"]
        self.assertEqual(report["profiles"][0]["result"], "FAIL")
        self.assertTrue(completeness["required_set_authoritative"])
        self.assertTrue(completeness["test_complete"])
        self.assertFalse(completeness["test_pass"])
        self.assertEqual(self._validate(report), "VALID")
        loaded = load_completed_report(self.host, result.extras["report_id"])
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["verification"]["test_complete"])
        self.assertFalse(loaded["verification"]["test_pass"])

    def test_X12_normal_completed_pass_report_still_usable(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        report = result.extras["report"]
        self.assertEqual(self._validate(report), "VALID")
        loaded = load_completed_report(self.host, result.extras["report_id"])
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["verification"]["test_pass"])


if __name__ == "__main__":
    unittest.main()

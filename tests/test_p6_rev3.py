from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    passing_profile,
    py_command,
    test_engine,
    write_commands,
    write_host,
    write_modules,
    write_skill_package,
    write_tests,
)
from support import write
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p6.engine import TestEngine
from scaffold_p6.schemas import validate_report
from scaffold_p6.storage import cleanup_test_run, load_completed_report, run_dir


class P6Rev3Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _invalid_package(self) -> Path:
        return write_skill_package(
            Path(self._tmp.name) / "invalid-test",
            skill_version="not-a-version",
        )

    def test_W01_not_adopted_invalid_package_routes_bootstrap(self):
        profile, command = passing_profile()
        write(self.host, "README.md", "# raw\n")
        write_commands(self.host, [command])
        write_tests(self.host, [profile])
        engine = TestEngine(self.host, self._invalid_package())
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.bootstrap")

    def test_W02_adopting_invalid_package_routes_bootstrap(self):
        write_host(self.host, [passing_profile()], lifecycle="ADOPTING")
        engine = TestEngine(self.host, self._invalid_package())
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.bootstrap")

    def test_W03_needs_refresh_invalid_package_routes_refresh(self):
        write_host(self.host, [passing_profile()], maintenance=["NEEDS_REFRESH"])
        engine = TestEngine(self.host, self._invalid_package())
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.refresh")

    def test_W04_needs_migration_invalid_package_routes_compatibility(self):
        write_host(self.host, [passing_profile()], maintenance=["NEEDS_MIGRATION"])
        project_before = file_digest(self.host / ".scaffold/project.yaml")
        lock_before = file_digest(self.host / ".scaffold/skills.lock")
        engine = TestEngine(self.host, self._invalid_package())
        result = engine.run()
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertEqual(result.next_route, "understand.compatibility")
        self.assertEqual(file_digest(self.host / ".scaffold/project.yaml"), project_before)
        self.assertEqual(file_digest(self.host / ".scaffold/skills.lock"), lock_before)
        self.assertIn(
            "NEEDS_MIGRATION",
            read_yaml(self.host / ".scaffold/project.yaml")["maintenance"],
        )

    def test_W05_parent_generated_outputs_cannot_use_narrow_authority(self):
        profile, command = passing_profile("gen")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('build/source.txt'); p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('source\\n', encoding='utf-8'); print('P6_PASS')"
        )
        write_host(self.host, [(profile, command)], generated_outputs=["build"])
        write_modules(
            self.host,
            [
                {
                    "id": "generated",
                    "path": "build/generated",
                    "kind": "generated",
                    "confidence": "VERIFIED",
                }
            ],
        )
        result = test_engine(self.host).run()
        self.assertTrue((self.host / "build/source.txt").exists())
        self.assertFalse(result.extras["completeness"]["candidate_match"])

    def test_W06_descendant_generated_exclusion_remains_supported(self):
        profile, command = passing_profile("gen")
        command["argv"] = py_command(
            "from pathlib import Path; "
            "p=Path('build/generated/out.txt'); p.parent.mkdir(parents=True, exist_ok=True); "
            "p.write_text('built\\n', encoding='utf-8'); print('P6_PASS')"
        )
        write_host(self.host, [(profile, command)], generated_outputs=["build/generated"])
        write_modules(
            self.host,
            [{"id": "build", "path": "build", "kind": "generated", "confidence": "VERIFIED"}],
        )
        result = test_engine(self.host).run()
        self.assertTrue((self.host / "build/generated/out.txt").exists())
        self.assertTrue(result.extras["completeness"]["candidate_match"])
        self.assertTrue(result.extras["test_pass"])

    def test_W07_blocked_known_required_profile_is_in_report(self):
        write_host(self.host, [passing_profile()], lifecycle="ADOPTING")
        result = test_engine(self.host).run()
        report = result.extras["report"]
        completeness = result.extras["completeness"]
        self.assertEqual(completeness["required"], ["unit"])
        ids = [row["id"] for row in report["profiles"]]
        self.assertEqual(ids.count("unit"), 1)
        self.assertEqual(report["profiles"][0]["result"], "NOT_RUN")

    def test_W08_missing_required_profile_row_invalid(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["profiles"] = []
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_W09_duplicate_profile_id_invalid(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["profiles"].append(dict(report["profiles"][0]))
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_W10_non_mapping_completeness_invalid(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["completeness"] = ["not", "a", "mapping"]
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_W11_non_mapping_verification_invalid(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["verification"] = "PASS"
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_W12_non_boolean_pass_complete_match_invalid(self):
        write_host(self.host, [passing_profile()])
        report = test_engine(self.host).run().extras["report"]
        report["candidate_match"] = "true"
        report["completeness"]["test_pass"] = 1
        report["completeness"]["test_complete"] = "true"
        report["verification"]["test_pass"] = 1
        report["verification"]["test_complete"] = "true"
        self.assertNotEqual(validate_report(report)[0], "VALID")

    def test_W13_resolvable_ref_missing_digest_unusable(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        report = read_yaml(dest / "report.yaml")
        report["evidence_refs"][0]["digest"] = ""
        write_yaml_atomic(dest / "report.yaml", report)
        self.assertNotEqual(validate_report(report)[0], "VALID")
        self.assertIsNone(load_completed_report(self.host, run_id))

    def test_W14_evidence_ref_missing_binding_invalid(self):
        write_host(self.host, [passing_profile()])
        result = test_engine(self.host).run()
        run_id = result.extras["report_id"]
        dest = run_dir(self.host, run_id)
        missing_report = read_yaml(dest / "report.yaml")
        missing_report["evidence_refs"][0].pop("report_id", None)
        self.assertNotEqual(validate_report(missing_report)[0], "VALID")
        write_yaml_atomic(dest / "report.yaml", missing_report)
        self.assertIsNone(load_completed_report(self.host, run_id))
        missing_candidate = test_engine(self.host).run().extras["report"]
        missing_candidate["evidence_refs"][0].pop("candidate_digest", None)
        self.assertNotEqual(validate_report(missing_candidate)[0], "VALID")

    def test_W15_invalid_run_identity_refuses_cleanup(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        second = test_engine(self.host).run()
        self.assertFalse(cleanup_test_run(self.host, "."))
        self.assertTrue(run_dir(self.host, first.extras["report_id"]).exists())
        self.assertTrue(run_dir(self.host, second.extras["report_id"]).exists())
        self.assertIsNotNone(load_completed_report(self.host, first.extras["report_id"]))
        self.assertIsNotNone(load_completed_report(self.host, second.extras["report_id"]))

    def test_W16_valid_exact_run_cleanup_leaves_sibling(self):
        write_host(self.host, [passing_profile()])
        first = test_engine(self.host).run()
        second = test_engine(self.host).run()
        self.assertTrue(cleanup_test_run(self.host, first.extras["report_id"]))
        self.assertFalse(run_dir(self.host, first.extras["report_id"]).exists())
        self.assertTrue(run_dir(self.host, second.extras["report_id"]).exists())
        self.assertIsNotNone(load_completed_report(self.host, second.extras["report_id"]))


if __name__ == "__main__":
    unittest.main()

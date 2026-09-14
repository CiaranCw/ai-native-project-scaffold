from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from p8_support import write_submit_host
from support import REPO

from scaffold_p5.consumer_install import CURSOR_ADAPTERS
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.models import EXECUTABLE_COMPAT
from scaffold_p8.preflight import (
    _applicable_packages,
    evaluate_submit_preflight,
    inspect_host_project,
)


def _publish_packages(host: Path) -> Path:
    packages = host / ".scaffold" / "install" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    for skill_id in CORE_SKILLS:
        dest = packages / skill_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            REPO / "skills" / skill_id,
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return packages


class PcConsumer004Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_submit_host(self.host)
        self.packages = _publish_packages(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_C004_01_capabilities_resolve_from_published_packages(self):
        submit = self.packages / "submit"
        actual = load_package(submit)
        applicable = _applicable_packages(
            actual,
            root=self.host,
            package_root=submit,
        )
        self.assertIn("understand", applicable)
        self.assertIn("test", applicable)
        self.assertIn("develop", applicable)
        self.assertEqual(
            Path(applicable["understand"].path).resolve(),
            (self.packages / "understand").resolve(),
        )
        self.assertEqual(
            Path(applicable["test"].path).resolve(),
            (self.packages / "test").resolve(),
        )
        self.assertFalse((self.host / ".scaffold" / "install" / "skills").exists())

    def test_C004_02_s1_not_false_incompatible_without_install_skills(self):
        status, _reasons, project = inspect_host_project(self.host)
        preflight = evaluate_submit_preflight(
            self.host,
            package_root=self.packages / "submit",
            project=project,
            project_status=status,
        )
        reasons = " ".join(preflight.blockers + preflight.reasons)
        self.assertNotIn("required capability is unavailable", reasons)
        self.assertNotIn("test.scoped_verification", reasons)
        self.assertNotIn("understand.refresh", reasons)
        self.assertNotIn("understand.compatibility", reasons)
        self.assertTrue(preflight.allowed, preflight)
        self.assertIn(preflight.compatibility, EXECUTABLE_COMPAT)

    def test_C004_03_four_skills_and_candidate_unchanged(self):
        self.assertEqual(CORE_SKILLS, ("understand", "develop", "test", "submit"))
        self.assertEqual(len(CURSOR_ADAPTERS), 4)
        self.assertNotIn("repair", CORE_SKILLS)
        self.assertTrue(observe_candidate(self.host).usable)


if __name__ == "__main__":
    unittest.main()

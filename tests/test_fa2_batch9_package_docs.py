from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import (
    FIXTURE_DIST,
    REPO,
    REPO_UNDERSTAND,
    adopt,
    distribution,
    engine,
    files_under,
    write,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.compatibility import evaluate_host, evaluate_package
from scaffold_p5.distribution import load_distribution
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_text, read_yaml
from scaffold_p5.packages import load_package
from scaffold_p5.preflight import run_preflight


CANONICAL = {
    "understand": REPO / "skills" / "understand",
    "develop": REPO / "skills" / "develop",
    "test": REPO / "skills" / "test",
    "submit": REPO / "skills" / "submit",
}
STATUS_DOCS = (
    REPO / "README.md",
    REPO / "docs" / "implementation" / "P5_UNDERSTAND.md",
    REPO / "docs" / "implementation" / "P6_TEST.md",
    REPO / "docs" / "implementation" / "P7_DEVELOP.md",
    REPO / "docs" / "implementation" / "P8_SUBMIT.md",
    REPO / "docs" / "implementation" / "FA2_BATCH9_PACKAGE_DOCS.md",
)


class FA2Batch9PackageDocsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _copy_package(self, source: Path, name: str) -> Path:
        target = self.root / name
        shutil.copytree(source, target)
        return target

    def _rewrite_manifest(self, package_dir: Path, **updates) -> dict:
        manifest = yaml_lite.load(read_text(package_dir / "skill.yaml"))
        manifest.update(updates)
        (package_dir / "skill.yaml").write_text(
            yaml_lite.dump(manifest),
            encoding="utf-8",
        )
        skill_md = package_dir / "SKILL.md"
        if skill_md.is_file() and (
            "skill_version" in updates or "skill_id" in updates
        ):
            text = skill_md.read_text(encoding="utf-8")
            if "skill_version" in updates:
                text = re.sub(
                    r"(-\s*`skill_version`\s*:\s*`)[0-9]+\.[0-9]+\.[0-9]+(`)",
                    rf"\g<1>{updates['skill_version']}\2",
                    text,
                    count=1,
                )
            if "skill_id" in updates:
                text = re.sub(
                    r"(-\s*`skill_id`\s*:\s*`)[a-z][a-z0-9_-]*(`)",
                    rf"\g<1>{updates['skill_id']}\2",
                    text,
                    count=1,
                )
            skill_md.write_text(text, encoding="utf-8")
        return manifest

    def _custom_distribution(self, *, omit=(), extra_dirs=()):
        packages_root = FIXTURE_DIST / "packages"
        package_dirs = [
            path
            for path in packages_root.iterdir()
            if path.is_dir() and path.name not in set(omit)
        ]
        package_dirs.append(REPO_UNDERSTAND)
        package_dirs.extend(extra_dirs)
        releases: dict[str, dict] = {}
        for rel_file in (FIXTURE_DIST / "releases").glob("*.yaml"):
            data = yaml_lite.load(read_text(rel_file))
            releases[str(data["release_id"])] = dict(data.get("core") or {})
        return load_distribution(
            package_dirs=package_dirs,
            releases=releases,
            selected_release_id="rel-r1",
            actual_understand_dir=REPO_UNDERSTAND,
        )

    def _assert_invalid_modes(self, source: Path, modes: list[str], name: str):
        copied = self._copy_package(source, name)
        self._rewrite_manifest(copied, modes=modes)
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "INVALID", loaded.validity_reasons)
        pinned = load_package(source).ref
        row = evaluate_package(
            pinned,
            loaded,
            project={"project_contract_generation": "1"},
            distribution=distribution(),
        )
        self.assertEqual(row["validity"], "INVALID")
        self.assertIsNone(row["result"])
        self.assertNotIn(row.get("result"), {"EXACT", "COMPATIBLE"})

    def test_B9V01_test_cannot_declare_repair(self):
        self._assert_invalid_modes(
            CANONICAL["test"],
            ["repair"],
            "test-repair",
        )

    def test_B9V02_develop_cannot_declare_understand_mode(self):
        self._assert_invalid_modes(
            CANONICAL["develop"],
            ["normal_task", "bootstrap"],
            "develop-bootstrap",
        )
        self._assert_invalid_modes(
            CANONICAL["develop"],
            ["compatibility"],
            "develop-compatibility",
        )

    def test_B9V03_submit_cannot_declare_cross_skill_mode(self):
        self._assert_invalid_modes(CANONICAL["submit"], ["repair"], "submit-repair")
        self._assert_invalid_modes(CANONICAL["submit"], ["full"], "submit-full")
        self._assert_invalid_modes(
            CANONICAL["submit"],
            ["bootstrap"],
            "submit-bootstrap",
        )
        self._assert_invalid_modes(CANONICAL["submit"], ["S1"], "submit-s1")

    def test_B9V04_understand_cannot_declare_develop_repair(self):
        self._assert_invalid_modes(
            CANONICAL["understand"],
            ["bootstrap", "full", "refresh", "repair"],
            "understand-repair",
        )

    def test_B9V05_current_legal_four_packages_remain_valid(self):
        for skill_id, path in CANONICAL.items():
            loaded = load_package(path)
            self.assertEqual(loaded.validity, "VALID", (skill_id, loaded.validity_reasons))
            self.assertEqual(loaded.ref.skill_id, skill_id)

    def test_B9V06_capability_miss_is_not_package_invalidity(self):
        copied = self._copy_package(CANONICAL["develop"], "develop-requires-test")
        self._rewrite_manifest(copied, requires=["test.scoped_verification"])
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "VALID", loaded.validity_reasons)
        row = evaluate_package(
            loaded.ref,
            loaded,
            project={"project_contract_generation": "1"},
            distribution=distribution(),
            applicable_packages={},
        )
        self.assertEqual(row["validity"], "VALID")
        self.assertIn(row["result"], {"INCOMPATIBLE", "UNKNOWN"})
        self.assertNotEqual(row["result"], "EXACT")

    def _run_non_exact(self, skill_id: str, omit: str, extra: Path):
        adopt(self.host)
        lock_path = self.host / ".scaffold/skills.lock"
        before = lock_path.read_bytes()
        expected = read_yaml(lock_path)["skills"][skill_id]["skill_version"]
        dist = self._custom_distribution(omit=(omit,), extra_dirs=[extra])
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        result = UnderstandEngine(self.host, dist).run("compatibility")
        after = read_yaml(lock_path)
        self.assertEqual(lock_path.read_bytes(), before)
        self.assertEqual(after["skills"][skill_id]["skill_version"], expected)
        return evaluation, result, expected, load_package(extra)

    def test_B9C01_test_non_exact_compatible_substitution(self):
        evaluation, result, expected, actual = self._run_non_exact(
            "test",
            "test-2.0.0",
            CANONICAL["test"],
        )
        row = evaluation["results"]["test"]
        self.assertEqual(evaluation["ok"], True, evaluation["blockers"])
        self.assertEqual(evaluation["overall"], "COMPATIBLE")
        self.assertEqual(row["validity"], "VALID")
        self.assertEqual(row["result"], "COMPATIBLE")
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(row["actual_version"], actual.ref.skill_version)
        self.assertEqual(row["expected_version"], expected)
        self.assertNotEqual(row["actual_version"], expected)

    def test_B9C02_develop_non_exact_compatible_substitution(self):
        evaluation, result, expected, actual = self._run_non_exact(
            "develop",
            "develop-2.0.0",
            CANONICAL["develop"],
        )
        row = evaluation["results"]["develop"]
        self.assertEqual(evaluation["overall"], "COMPATIBLE")
        self.assertEqual(row["result"], "COMPATIBLE")
        self.assertEqual(row["actual_version"], actual.ref.skill_version)
        self.assertNotEqual(row["actual_version"], expected)
        self.assertEqual(result.compatibility, "COMPATIBLE")

    def test_B9C03_submit_non_exact_compatible_substitution(self):
        evaluation, result, expected, actual = self._run_non_exact(
            "submit",
            "submit-2.0.0",
            CANONICAL["submit"],
        )
        row = evaluation["results"]["submit"]
        self.assertEqual(evaluation["overall"], "COMPATIBLE")
        self.assertEqual(row["result"], "COMPATIBLE")
        self.assertEqual(row["actual_version"], actual.ref.skill_version)
        self.assertNotEqual(row["actual_version"], expected)
        self.assertEqual(result.compatibility, "COMPATIBLE")

    def test_B9C04_actual_version_surfaced(self):
        evaluation, _, expected, actual = self._run_non_exact(
            "test",
            "test-2.0.0",
            CANONICAL["test"],
        )
        row = evaluation["results"]["test"]
        self.assertEqual(row["actual_version"], actual.ref.skill_version)
        self.assertEqual(row["expected_version"], expected)
        self.assertNotEqual(row["actual_version"], expected)
        self.assertNotEqual(row["result"], "EXACT")

    def test_B9C05_lock_not_auto_rewritten(self):
        self._run_non_exact("test", "test-2.0.0", CANONICAL["test"])

    def test_B9C06_version_difference_is_not_migration(self):
        evaluation, result, _, _ = self._run_non_exact(
            "test",
            "test-2.0.0",
            CANONICAL["test"],
        )
        self.assertEqual(evaluation["results"]["test"]["result"], "COMPATIBLE")
        self.assertNotEqual(evaluation["overall"], "MIGRATION_REQUIRED")
        self.assertNotEqual(result.compatibility, "MIGRATION_REQUIRED")

    def test_B9C07_ambiguous_compatible_candidates(self):
        adopt(self.host)
        first = self._copy_package(CANONICAL["test"], "test-a")
        second = self._copy_package(CANONICAL["test"], "test-b")
        self._rewrite_manifest(second, skill_version="2.0.2")
        dist = self._custom_distribution(
            omit=("test-2.0.0",),
            extra_dirs=[first, second],
        )
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["test"]
        self.assertFalse(evaluation["ok"])
        self.assertEqual(row["result"], "UNKNOWN")
        self.assertNotEqual(row["result"], "COMPATIBLE")
        self.assertEqual(evaluation["overall"], "UNKNOWN")
        self.assertTrue(
            any("MUST NOT guess" in blocker for blocker in evaluation["blockers"])
        )
        engine_result = UnderstandEngine(self.host, dist).run("compatibility")
        self.assertEqual(engine_result.outcome, "BLOCKED")
        self.assertNotEqual(engine_result.compatibility, "COMPATIBLE")

    def test_B9C08_invalid_non_exact_package_cannot_substitute(self):
        adopt(self.host)
        invalid = self._copy_package(CANONICAL["test"], "test-invalid")
        self._rewrite_manifest(invalid, modes=["repair"])
        self.assertEqual(load_package(invalid).validity, "INVALID")
        dist = self._custom_distribution(
            omit=("test-2.0.0",),
            extra_dirs=[invalid],
        )
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["test"]
        self.assertNotEqual(row.get("result"), "COMPATIBLE")
        self.assertEqual(row["validity"], "INVALID")
        self.assertFalse(evaluation["ok"])

    def test_B9C09_exact_package_regression(self):
        adopt(self.host)
        evaluation = evaluate_host(snapshot_host(self.host), distribution())
        self.assertTrue(evaluation["ok"], evaluation["blockers"])
        self.assertEqual(evaluation["overall"], "EXACT")
        for skill_id in ("understand", "develop", "test", "submit"):
            row = evaluation["results"][skill_id]
            self.assertEqual(row["validity"], "VALID")
            self.assertEqual(row["result"], "EXACT")
            self.assertEqual(row["expected_version"], row["actual_version"])
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.compatibility, "EXACT")

    def test_B9C10_pre_adoption_understand_exact_binding(self):
        before = files_under(self.host)
        snap = snapshot_host(self.host)
        decision = run_preflight(snap, distribution("2.0.1"))
        self.assertEqual(decision.context, "PRE_ADOPTION_BOOTSTRAP")
        self.assertFalse(decision.allowed)
        result = engine(self.host, "2.0.1").run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("identity mismatch" in blocker for blocker in result.blockers))
        self.assertNotEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(files_under(self.host), before)

    def test_B9C11_valid_non_exact_unknown_must_not_become_invalid(self):
        adopt(self.host)
        copied = self._copy_package(CANONICAL["test"], "test-unknown")
        self._rewrite_manifest(copied, may_substitute_for=[])
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "VALID", loaded.validity_reasons)
        dist = self._custom_distribution(
            omit=("test-2.0.0",),
            extra_dirs=[copied],
        )
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["test"]
        self.assertEqual(row["validity"], "VALID", row)
        self.assertEqual(row["result"], "UNKNOWN")
        self.assertNotIn(row["result"], {"EXACT", "COMPATIBLE"})
        self.assertIsNot(row["result"], None)
        self.assertEqual(row["actual_version"], loaded.ref.skill_version)
        self.assertNotEqual(row["actual_version"], row["expected_version"])

    def test_B9C12_legal_develop_requires_test_is_not_invalid_by_order(self):
        adopt(self.host)
        copied = self._copy_package(CANONICAL["develop"], "develop-requires-test")
        self._rewrite_manifest(copied, requires=["test.scoped_verification"])
        loaded = load_package(copied)
        self.assertEqual(loaded.validity, "VALID", loaded.validity_reasons)
        dist = self._custom_distribution(
            omit=("develop-2.0.0",),
            extra_dirs=[copied],
        )
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        self.assertEqual(lock["skills"]["test"]["skill_version"], "2.0.0")
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["develop"]
        self.assertEqual(row["validity"], "VALID", row)
        self.assertNotEqual(row.get("result"), None)
        self.assertEqual(row["result"], "COMPATIBLE", evaluation)
        self.assertEqual(row["actual_version"], loaded.ref.skill_version)
        self.assertEqual(evaluation["results"]["test"]["result"], "EXACT")

    def test_B9C13_multiple_valid_non_resolvable_candidates(self):
        adopt(self.host)
        first = self._copy_package(CANONICAL["test"], "test-unknown-a")
        second = self._copy_package(CANONICAL["test"], "test-unknown-b")
        self._rewrite_manifest(first, may_substitute_for=[])
        self._rewrite_manifest(second, skill_version="2.0.2", may_substitute_for=[])
        dist = self._custom_distribution(
            omit=("test-2.0.0",),
            extra_dirs=[first, second],
        )
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["test"]
        self.assertEqual(row["validity"], "VALID", row)
        self.assertEqual(row["result"], "UNKNOWN")
        self.assertNotEqual(row["result"], "COMPATIBLE")
        self.assertFalse(evaluation["ok"])
        self.assertEqual(evaluation["overall"], "UNKNOWN")
        self.assertTrue(
            any("MUST NOT guess" in blocker for blocker in evaluation["blockers"])
        )

    def test_B9C14_non_exact_develop_to_non_exact_test_is_order_independent(self):
        adopt(self.host)
        lock_path = self.host / ".scaffold/skills.lock"
        before = lock_path.read_bytes()
        develop_compatible = self._copy_package(
            CANONICAL["develop"],
            "develop-2.1.0-requires-test",
        )
        self._rewrite_manifest(
            develop_compatible,
            requires=["test.scoped_verification"],
        )
        develop_unknown = self._copy_package(
            CANONICAL["develop"],
            "develop-2.2.0-requires-test",
        )
        self._rewrite_manifest(
            develop_unknown,
            skill_version="2.2.0",
            requires=["test.scoped_verification"],
            may_substitute_for=[],
        )
        self.assertEqual(load_package(develop_compatible).validity, "VALID")
        self.assertEqual(load_package(develop_unknown).validity, "VALID")
        self.assertEqual(load_package(CANONICAL["test"]).validity, "VALID")
        dist = self._custom_distribution(
            omit=("develop-2.0.0", "test-2.0.0"),
            extra_dirs=[develop_compatible, develop_unknown, CANONICAL["test"]],
        )
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        joined_blockers = " ".join(evaluation["blockers"])
        self.assertNotIn(
            "develop has multiple valid non-exact packages; MUST NOT guess",
            joined_blockers,
        )
        test_row = evaluation["results"]["test"]
        develop_row = evaluation["results"]["develop"]
        self.assertEqual(test_row["validity"], "VALID", test_row)
        self.assertEqual(test_row["result"], "COMPATIBLE", test_row)
        self.assertEqual(test_row["actual_version"], "2.0.1")
        self.assertEqual(develop_row["validity"], "VALID", develop_row)
        self.assertEqual(develop_row["result"], "COMPATIBLE", evaluation)
        self.assertEqual(develop_row["actual_version"], "2.1.0")
        self.assertNotEqual(develop_row["actual_version"], "2.2.0")
        self.assertEqual(evaluation["overall"], "COMPATIBLE")
        self.assertTrue(evaluation["ok"], evaluation["blockers"])
        self.assertEqual(lock_path.read_bytes(), before)

    def _status_header(self, path: Path, lines: int = 8) -> str:
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[:lines])

    def test_B9D01_p5_status_truth(self):
        header = self._status_header(REPO / "docs" / "implementation" / "P5_UNDERSTAND.md")
        self.assertNotIn("ACTIVE / IMPLEMENTATION", header)
        self.assertIn("CLOSED / BASELINED / REMOTELY PUBLISHED", header)

    def test_B9D02_p6_status_truth(self):
        header = self._status_header(REPO / "docs" / "implementation" / "P6_TEST.md")
        self.assertNotIn("ACTIVE / IMPLEMENTATION", header)
        self.assertIn("CLOSED / BASELINED / REMOTELY PUBLISHED", header)

    def test_B9D03_p7_status_truth(self):
        header = self._status_header(REPO / "docs" / "implementation" / "P7_DEVELOP.md")
        self.assertNotIn("ACTIVE / IMPLEMENTATION", header)
        self.assertIn("CLOSED / BASELINED / REMOTELY PUBLISHED", header)

    def test_B9D04_p8_status_truth(self):
        header = self._status_header(REPO / "docs" / "implementation" / "P8_SUBMIT.md")
        self.assertNotIn("ACTIVE / IMPLEMENTATION", header)
        self.assertIn("CLOSED / BASELINED / REMOTELY PUBLISHED", header)

    def test_B9D05_fa2_not_prematurely_closed(self):
        texts = [path.read_text(encoding="utf-8") for path in STATUS_DOCS]
        joined = "\n".join(texts)
        self.assertNotIn("FA-2 — PASS / CLOSED", joined)
        self.assertNotIn("FA-2 PASS / CLOSED", joined)
        self.assertNotIn("FA-2 is CLOSED", joined)
        batch9 = (REPO / "docs" / "implementation" / "FA2_BATCH9_PACKAGE_DOCS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("does not claim FA-2 PASS", batch9)

    def test_B9D06_p9_not_started(self):
        for path in STATUS_DOCS:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("P9 STARTED", text)
            self.assertNotIn("P9 implementation has started", text)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("P9 Repair/Migration is PASS / CLOSED", readme)
        self.assertIn(
            "P10 Incremental Understanding / Multi-Agent is PASS / CLOSED",
            readme,
        )
        self.assertIn("DIVE Day-1 is not closed", readme)
        self.assertNotIn("DIVE is not started", readme)
        self.assertNotIn("DIVE Day-1 is closed", readme)
        self.assertIn("does **not** claim v2.0 release", readme)
        self.assertNotIn("v2.0 RELEASED", readme)

    def test_B9D07_v20_not_released(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("does **not** claim v2.0 release", readme)
        self.assertNotIn("v2.0 RELEASED", readme)
        for path in STATUS_DOCS:
            header = self._status_header(path, 20)
            self.assertNotIn("v2.0 RELEASED", header)

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scaffold_p5.host_state import compare_adoption_state, durable_inventory
from scaffold_p5.inventory import (
    CLASS_EXCLUDED,
    EXCLUDED_BY_POLICY,
    EXCLUDED_DIR_NAMES,
    FULLY_OBSERVED,
    InventoryBudget,
    TRUNCATED_BY_BUDGET,
    hashed_inventory,
    observe_inventory,
    resolved_inside_root,
)
from scaffold_p5.io_util import file_digest, list_files
from support import write


CORE_ROOTS = (
    Path(__file__).resolve().parents[1] / "src" / "scaffold_p5",
    Path(__file__).resolve().parents[1] / "src" / "scaffold_p6",
    Path(__file__).resolve().parents[1] / "src" / "scaffold_p7",
    Path(__file__).resolve().parents[1] / "src" / "scaffold_p8",
)


class BoundedInventoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# ordinary host\n")
        write(self.host, "src/app.py", "print('ok')\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_T1_01_huge_dependency_root_is_excluded_from_recursive_hashing(self):
        for index in range(40):
            write(self.host, f"node_modules/pkg/file-{index}.js", "x" * 256)
        observation = observe_inventory(self.host)
        hashed = hashed_inventory(observation)
        self.assertNotIn("node_modules/pkg/file-0.js", hashed)
        self.assertTrue(
            any(
                row.path == "node_modules" and row.observation == EXCLUDED_BY_POLICY
                for row in observation.roots
            )
        )
        self.assertLess(observation.files_hashed, 10)

    def test_T1_02_normal_source_file_is_fully_inventoried(self):
        observation = observe_inventory(self.host)
        hashed = hashed_inventory(observation)
        self.assertEqual(hashed["src/app.py"]["observation"], FULLY_OBSERVED)
        self.assertEqual(hashed["src/app.py"]["digest"], file_digest(self.host / "src/app.py"))
        self.assertIn("src/app.py", list_files(self.host))

    def test_T1_03_excluded_root_is_reported_as_present_not_absent(self):
        write(self.host, "vendor/lib.bin", "payload\n")
        observation = observe_inventory(self.host)
        vendor = next(row for row in observation.roots if row.path == "vendor")
        self.assertEqual(vendor.classification, CLASS_EXCLUDED)
        self.assertTrue(vendor.present)
        self.assertEqual(vendor.observation, EXCLUDED_BY_POLICY)
        self.assertNotIn("vendor/lib.bin", hashed_inventory(observation))
        self.assertNotEqual(vendor.observation, "ABSENT")

    def test_T1_04_budget_overflow_reports_truncated_partial_truth(self):
        for index in range(8):
            write(self.host, f"src/mod_{index}.py", f"value={index}\n")
        observation = observe_inventory(
            self.host, budget=InventoryBudget(max_files=3, max_hash_bytes=10**9)
        )
        self.assertTrue(observation.truncated)
        self.assertEqual(observation.in_scope_status, TRUNCATED_BY_BUDGET)
        self.assertFalse(observation.verified_complete)

    def test_T1_05_budget_overflow_cannot_become_verified_completeness(self):
        for index in range(8):
            write(self.host, f"src/mod_{index}.py", f"value={index}\n")
        coverage: dict = {}
        durable_inventory(
            self.host,
            budget=InventoryBudget(max_files=2, max_hash_bytes=10**9),
            coverage_out=coverage,
        )
        self.assertFalse(coverage["verified_complete"])
        self.assertEqual(coverage["status"], TRUNCATED_BY_BUDGET)
        forged = {
            "inventory": {"README.md": {"type": "file", "digest": "aa"}},
            "inventory_coverage": {
                "status": TRUNCATED_BY_BUDGET,
                "verified_complete": True,
                "exact_observed": [],
                "roots": [],
            },
        }
        issues = compare_adoption_state(self.host, forged, [])
        self.assertTrue(
            any("VERIFIED completeness" in item for item in issues),
            issues,
        )

    def test_T1_06_dirty_tracked_in_scope_bytes_remain_baseline_protected(self):
        write(self.host, "src/tracked.py", "original\n")
        self._git(["init"])
        self._git(["add", "src/tracked.py", "README.md", "src/app.py"])
        self._git(["-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-m", "init"])
        write(self.host, "src/tracked.py", "dirty bytes\n")
        hashed = durable_inventory(self.host)
        self.assertEqual(hashed["src/tracked.py"]["digest"], file_digest(self.host / "src/tracked.py"))
        self.assertNotEqual(hashed["src/tracked.py"]["digest"], file_digest(self.host / "src/app.py"))

    def test_T1_07_planned_mutation_target_under_excluded_root_is_exact_observed(self):
        target = "node_modules/tooling/managed.json"
        write(self.host, target, '{"managed": true}\n')
        observation = observe_inventory(self.host, exact_observe=[target])
        self.assertIn(target, observation.exact_observed)
        hashed = hashed_inventory(observation)
        self.assertEqual(hashed[target]["observation"], FULLY_OBSERVED)
        self.assertEqual(hashed[target]["digest"], file_digest(self.host / target))
        self.assertNotIn("node_modules/tooling/other.js", hashed)

    def test_T1_08_mutation_envelope_cannot_touch_an_unobserved_target(self):
        write(self.host, "src/app.py", "print('ok')\n")
        coverage: dict = {}
        inventory = durable_inventory(self.host, coverage_out=coverage)
        baseline = {"inventory": inventory, "inventory_coverage": coverage}
        issues = compare_adoption_state(
            self.host,
            baseline,
            ["node_modules/secret/config.json"],
        )
        self.assertTrue(
            any("unobserved" in item for item in issues),
            issues,
        )

    def test_T1_09_filesystem_indirection_cannot_escape_project_root(self):
        outside = Path(self._tmp.name) / "outside.txt"
        outside.write_text("escaped\n", encoding="utf-8")
        inside, reason = resolved_inside_root(self.host, outside)
        self.assertFalse(inside)
        self.assertIn("escapes", reason)
        linked = self.host / "escape-link"
        created = _try_dir_link(linked, Path(self._tmp.name))
        if created:
            observation = observe_inventory(self.host)
            self.assertTrue(
                observation.unknown
                or any(row.observation == "UNKNOWN" for row in observation.roots)
            )
            self.assertNotIn("escape-link/outside.txt", hashed_inventory(observation))
        observation = observe_inventory(self.host, exact_observe=["../secret.txt"])
        self.assertNotIn("../secret.txt", observation.exact_observed)
        self.assertTrue(
            observation.unknown
            or any(row.get("observation") == "UNKNOWN" for row in observation.files.values())
        )
        issues = compare_adoption_state(
            self.host,
            {
                "inventory": durable_inventory(self.host),
                "inventory_coverage": observe_inventory(self.host).coverage_dict(),
            },
            ["../secret.txt"],
        )
        self.assertTrue(any("unobserved" in item for item in issues), issues)

    def test_T1_10_no_project_city_specific_root_names_in_core(self):
        forbidden = (
            "project-city",
            "src/mvp",
            "public/polygon",
            "synty",
        )
        hits: list[str] = []
        for root in CORE_ROOTS:
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8").lower()
                for token in forbidden:
                    if token in text:
                        hits.append(f"{path.as_posix()}: {token}")
        self.assertEqual(hits, [])
        self.assertNotIn("assets/vendor", EXCLUDED_DIR_NAMES)
        self.assertNotIn("public", EXCLUDED_DIR_NAMES)

    def _git(self, args: list[str]) -> None:
        import subprocess

        subprocess.run(
            ["git", *args],
            cwd=self.host,
            check=True,
            capture_output=True,
            text=True,
        )


def _try_dir_link(dest: Path, target: Path) -> bool:
    try:
        dest.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        try:
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(dest), str(target)],
                capture_output=True,
                text=True,
            )
            return completed.returncode == 0 and dest.exists()
        except OSError:
            return False


if __name__ == "__main__":
    unittest.main()

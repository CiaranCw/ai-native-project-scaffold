"""Gate-1B-C02 operational enumeration bound.

Closes G1B-T1-001. Does not reopen T1-002 / T2 / T3. Does not repair
G1B-T2-SHOULD-001.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scaffold_p5.inventory as inventory
from scaffold_p5.adoption import _preserve_human_paths, build_adoption_plan
from scaffold_p5.discovery import discover, resolve_existing
from scaffold_p5.host_state import _nested_workspaces, scm_baseline, snapshot_host
from scaffold_p5.inventory import (
    ENUMERATION_OVERFLOW_PROBE,
    InventoryBudget,
    bounded_metadata_walk,
)
from scaffold_p5.preflight import run_preflight
from support import REPO, distribution, engine, write
from test_pc_scf_gate1b_c01 import _try_dir_link


WIDE = 2048


def _counting_scandir(yielded: list[str]):
    real = inventory._directory_scandir

    def wrapped(path):
        inner = real(path)

        class CountingScanner:
            def __enter__(self):
                self._it = inner.__enter__() if hasattr(inner, "__enter__") else inner
                return self

            def __exit__(self, *exc):
                if hasattr(inner, "__exit__"):
                    return inner.__exit__(*exc)
                closer = getattr(inner, "close", None)
                if closer:
                    closer()
                return False

            def __iter__(self):
                for entry in self._it:
                    yielded.append(entry.name)
                    yield entry

            def close(self):
                closer = getattr(self._it, "close", None)
                if closer:
                    closer()

        return CountingScanner()

    return wrapped


def _tracking_listdir(seen: list[str]):
    real = inventory.os.listdir

    def wrapped(path):
        names = real(path)
        seen.extend(names)
        return names

    return wrapped


class C02OperationalEnumerationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_G1B_T1_001_wide_directory_does_not_materialize_all_names(self):
        for index in range(WIDE):
            (self.host / f"d{index:04d}").mkdir()
        yielded: list[str] = []
        listdir_names: list[str] = []
        with (
            patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)),
            patch.object(inventory.os, "listdir", _tracking_listdir(listdir_names)),
        ):
            walked = bounded_metadata_walk(
                self.host, budget=InventoryBudget(max_entries=1)
            )
        self.assertTrue(walked.truncated)
        self.assertLessEqual(len(yielded), 1 + ENUMERATION_OVERFLOW_PROBE)
        self.assertGreater(len(yielded), 0)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertEqual(listdir_names, [])
        self.assertEqual(walked.directories, [])
        self.assertEqual(walked.files, [])

    def test_C02_01_empty_directory_with_budget_is_complete(self):
        empty = self.host / "empty"
        empty.mkdir()
        walked = bounded_metadata_walk(
            self.host, start="empty", budget=InventoryBudget(max_entries=8)
        )
        self.assertFalse(walked.truncated)
        self.assertEqual(walked.observation, "FULLY_OBSERVED")
        self.assertEqual(walked.files, [])
        self.assertEqual(walked.directories, [])

    def test_C02_02_exact_budget_exhaustion_is_complete(self):
        for name in ("a.md", "b.md", "c.md"):
            write(self.host, f"docs/{name}", name)
        walked = bounded_metadata_walk(
            self.host, start="docs", budget=InventoryBudget(max_entries=3)
        )
        self.assertFalse(walked.truncated)
        self.assertEqual(walked.observation, "FULLY_OBSERVED")
        self.assertEqual(walked.files, ["docs/a.md", "docs/b.md", "docs/c.md"])

    def test_C02_03_budget_plus_one_truncates_without_rest(self):
        for name in ("a.md", "b.md", "c.md", "d.md"):
            write(self.host, f"docs/{name}", name)
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            walked = bounded_metadata_walk(
                self.host, start="docs", budget=InventoryBudget(max_entries=3)
            )
        self.assertTrue(walked.truncated)
        self.assertLessEqual(len(yielded), 3 + ENUMERATION_OVERFLOW_PROBE)
        self.assertEqual(walked.files, [])
        self.assertEqual(walked.directories, [])

    def test_C02_04_very_wide_flat_directory_enumeration_is_bounded(self):
        for index in range(WIDE):
            (self.host / f"pkg_{index:04d}").mkdir()
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            walked = bounded_metadata_walk(
                self.host, budget=InventoryBudget(max_entries=1)
            )
        self.assertTrue(walked.truncated)
        self.assertLessEqual(len(yielded), 1 + ENUMERATION_OVERFLOW_PROBE)

    def test_C02_05_directory_only_explosion_ignores_byte_budget(self):
        for index in range(64):
            (self.host / f"native_{index:02d}").mkdir()
        walked = bounded_metadata_walk(
            self.host,
            budget=InventoryBudget(max_entries=1, max_hash_bytes=1),
        )
        self.assertTrue(walked.truncated)
        self.assertLessEqual(walked.entries_enumerated, 1 + ENUMERATION_OVERFLOW_PROBE)

    def test_C02_06_fully_enumerated_directory_is_sorted(self):
        write(self.host, "docs/z.md", "z")
        write(self.host, "docs/a.md", "a")
        write(self.host, "docs/m.md", "m")
        walked = bounded_metadata_walk(
            self.host, start="docs", budget=InventoryBudget(max_entries=8)
        )
        self.assertFalse(walked.truncated)
        self.assertEqual(walked.files, ["docs/a.md", "docs/m.md", "docs/z.md"])

    def test_C02_07_overflow_prefix_is_not_verified_complete(self):
        for index in range(40):
            write(self.host, f"src/mod_{index}/x.py", "x\n")
        facts = discover(self.host, budget=InventoryBudget(max_entries=1))
        tests = next(row for row in facts if row.name == "test_tree")
        self.assertNotEqual(tests.confidence, "VERIFIED")
        walked = bounded_metadata_walk(
            self.host, start="src", budget=InventoryBudget(max_entries=1)
        )
        self.assertTrue(walked.truncated)
        self.assertEqual(walked.observation, "TRUNCATED_BY_BUDGET")

    def test_C02_08_truncated_test_discovery_remains_unknown(self):
        write(self.host, "src/__tests__/a.py", "assert True\n")
        for index in range(30):
            write(self.host, f"src/mod_{index}/x.py", "x\n")
        facts = discover(self.host, budget=InventoryBudget(max_entries=8))
        tests = next(row for row in facts if row.name == "test_tree")
        self.assertEqual(tests.confidence, "UNKNOWN")

    def test_C02_09_truncated_preservation_still_blocks_apply(self):
        write(self.host, "README.md", "# host\n")
        for index in range(40):
            write(self.host, f"docs/human/n_{index}.md", f"doc {index}\n")
        budget = InventoryBudget(max_entries=8)
        facts = discover(self.host, budget=budget)
        snap = snapshot_host(self.host)
        dist = distribution()
        decision = run_preflight(snap, dist)
        self.assertTrue(decision.allowed)
        plan = build_adoption_plan(
            self.host,
            facts=facts,
            distribution=dist,
            preflight=decision,
            budget=budget,
        )
        self.assertTrue(
            any(item.startswith("human_owned_preservation:") for item in plan.activation_blockers),
            plan.activation_blockers,
        )
        result = engine(self.host)._apply_adoption(plan, None, {}, {}, None)
        self.assertEqual(result.outcome, "BLOCKED")

    def test_C02_10_truncated_nested_workspace_remains_truncated(self):
        for index in range(30):
            (self.host / f"tree_{index}").mkdir()
        scan = _nested_workspaces(self.host, budget=InventoryBudget(max_entries=6))
        self.assertEqual(scan["status"], "truncated")
        self.assertNotEqual(scan["status"], "absent")
        baseline = scm_baseline(self.host, budget=InventoryBudget(max_entries=6))
        self.assertEqual(baseline["nested_workspace"], "truncated")

    def test_C02_11_out_of_root_indirection_protection_remains(self):
        write(self.host, "README.md", "# host\n")
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "package.json").write_text('{"name": "escaped"}\n', encoding="utf-8")
        self.assertIsNone(
            resolve_existing(
                self.host, "package.json", {"package.json": "../outside/package.json"}
            )
        )
        (outside / "README.md").write_text("# Escaped\n", encoding="utf-8")
        linked = self.host / "docs"
        created = _try_dir_link(linked, outside)
        self.assertTrue(created)
        self.assertIsNone(resolve_existing(self.host, "docs/README.md", {}))

    def test_C02_12_ordinary_small_project_discovery_still_works(self):
        write(self.host, "README.md", "# small-app\n")
        write(self.host, "src/app.py", "print('ok')\n")
        write(self.host, "Package.JSON", '{"name": "small-app"}\n')
        facts = discover(self.host)
        pkg = next(row for row in facts if row.name == "declared_package_identity")
        self.assertEqual(pkg.value, "small-app")
        self.assertEqual(pkg.confidence, "VERIFIED")
        source = next(row for row in facts if row.name == "source_tree")
        self.assertEqual(source.confidence, "VERIFIED")

    def test_shared_primitive_is_the_only_walker(self):
        for rel in (
            "src/scaffold_p5/discovery.py",
            "src/scaffold_p5/adoption.py",
            "src/scaffold_p5/host_state.py",
        ):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn("bounded_metadata_walk", text)
        stream = (REPO / "src" / "scaffold_p5" / "inventory.py").read_text(encoding="utf-8")
        fn = stream[stream.find("def bounded_metadata_walk") : stream.find("def _stream_directory_names")]
        self.assertNotIn("os.listdir", fn)
        self.assertNotIn("sorted(os.scandir", fn)
        self.assertNotIn("list(os.scandir", fn)
        helper = stream[stream.find("def _stream_directory_names") : stream.find("def observe_inventory")]
        self.assertIn("_directory_scandir", helper)
        self.assertNotIn("os.listdir", helper)
        self.assertNotIn("sorted(os.scandir", helper)
        self.assertNotIn("list(os.scandir", helper)


class GeneralityReviewTests(unittest.TestCase):
    def test_no_consumer_domain_in_walker(self):
        text = (REPO / "src" / "scaffold_p5" / "inventory.py").read_text(encoding="utf-8").lower()
        for token in ("project-city", "babylon", "src/mvp", "vault"):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()

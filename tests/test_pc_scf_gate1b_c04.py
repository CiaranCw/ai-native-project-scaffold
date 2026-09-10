"""Gate-1B-C04 operation-scoped discovery resolution.

Closes remaining G1B-T1-001: resolve_existing must share one discover()
enumeration budget and must not rescan truncated directories. Does not
reopen T1-002 / T2 / T3. Does not repair G1B-T2-SHOULD-001.
"""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import scaffold_p5.inventory as inventory
from scaffold_p5.discovery import discover, path_identity_index, resolve_existing
from scaffold_p5.discovery_context import (
    DIR_COMPLETE,
    DiscoverySession,
    RESOLVE_ABSENT,
    RESOLVE_AMBIGUOUS,
    RESOLVE_FOUND,
    RESOLVE_UNKNOWN,
    RESOLVE_UNSAFE,
    observe_directory,
    resolve_outcome,
)
from scaffold_p5.inventory import (
    ENUMERATION_OVERFLOW_PROBE,
    InventoryBudget,
    bounded_metadata_walk,
    observe_inventory,
)
from scaffold_p5.io_util import list_files
from support import REPO, write
from test_pc_scf_gate1b_c01 import _try_dir_link
from test_pc_scf_gate1b_c02 import _counting_scandir, _tracking_listdir
from test_pc_scf_gate1b_c03 import _opening_scandir, _wide_children


WIDE = 2048
OVERFLOW_BOUND = 1 + ENUMERATION_OVERFLOW_PROBE

MISSING_HINTS = (
    ".scaffold/project.yaml",
    "package.json",
    "README.md",
    "README.markdown",
    "README.txt",
    "src",
    "lib",
    "app",
    "pkg",
    "docs",
    "CONTRIBUTING.md",
    "pyproject.toml",
    "setup.py",
    "tests",
    "test",
    "spec",
    "docs/testing.md",
    "TESTING.md",
    "Makefile",
    "docs/architecture.md",
    "architecture.md",
    "docs/project/architecture.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CODEX.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)


class C04DiscoverBudgetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_C04_01_full_discover_high_fanout_root_obeys_global_budget(self):
        _wide_children(self.host)
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            facts = discover(self.host, budget=InventoryBudget(max_entries=1))
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertGreater(len(yielded), 0)
        self.assertFalse(
            any(
                row.name == "source_tree" and row.confidence == "VERIFIED"
                for row in facts
            )
        )

    def test_C04_02_root_scanner_opened_once_for_fallback(self):
        _wide_children(self.host)
        opened: list[Path] = []
        yielded: list[str] = []
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            discover(self.host, budget=InventoryBudget(max_entries=1))
        root_opens = [item for item in opened if item == self.host.resolve()]
        self.assertLessEqual(len(root_opens), 1)
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)

    def test_C04_03_truncated_root_is_not_rescanned_for_later_hints(self):
        _wide_children(self.host)
        opened: list[Path] = []
        yielded: list[str] = []
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        outcomes = []
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            for hint in MISSING_HINTS:
                outcomes.append(
                    resolve_outcome(self.host, hint, session.index, session=session)
                )
        root_opens = [item for item in opened if item == self.host.resolve()]
        self.assertEqual(root_opens, [])
        self.assertEqual(yielded, [])
        self.assertGreaterEqual(len(MISSING_HINTS), 20)
        self.assertTrue(all(row.status == RESOLVE_UNKNOWN for row in outcomes))
        self.assertFalse(any(row.status == RESOLVE_ABSENT for row in outcomes))

    def test_C04_04_partial_root_missing_readme_is_unknown(self):
        _wide_children(self.host)
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        outcome = resolve_outcome(self.host, "README.md", session.index, session=session)
        self.assertEqual(outcome.status, RESOLVE_UNKNOWN)
        self.assertNotEqual(outcome.status, RESOLVE_ABSENT)
        docs = next(
            row
            for row in discover(self.host, budget=InventoryBudget(max_entries=1))
            if row.name == "documentation"
        )
        self.assertEqual(docs.confidence, "UNKNOWN")

    def test_C04_05_partial_root_missing_manifest_is_unknown(self):
        _wide_children(self.host)
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        outcome = resolve_outcome(self.host, "package.json", session.index, session=session)
        self.assertEqual(outcome.status, RESOLVE_UNKNOWN)
        self.assertNotEqual(outcome.status, RESOLVE_ABSENT)

    def test_complete_inventory_does_not_rescan_root(self):
        _wide_children(self.host)
        opened: list[Path] = []
        yielded: list[str] = []
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            discover(self.host, budget=InventoryBudget(max_entries=20000))
        root_opens = [item for item in opened if item == self.host.resolve()]
        self.assertEqual(len(root_opens), 1)
        self.assertLessEqual(len(yielded), WIDE + 8)
        opened_counts = Counter(opened)
        repeats = {str(path): count for path, count in opened_counts.items() if count > 1}
        self.assertEqual(repeats, {})

    def test_C04_06_unknown_resolution_is_not_verified_source_tree(self):
        _wide_children(self.host)
        facts = discover(self.host, budget=InventoryBudget(max_entries=1))
        source = next(row for row in facts if row.name == "source_tree")
        self.assertEqual(source.confidence, "UNKNOWN")
        self.assertIsNone(source.value)
        pkg = next(row for row in facts if row.name == "declared_javascript_manifest")
        self.assertEqual(pkg.confidence, "UNKNOWN")
        self.assertNotEqual(pkg.confidence, "VERIFIED")


class C04ResolutionMatrixTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_C04_07_complete_small_root_reuses_scan_and_proves_absence(self):
        write(self.host, "a.md", "a")
        write(self.host, "b.md", "b")
        opened: list[Path] = []
        yielded: list[str] = []
        session = DiscoverySession.ephemeral(self.host, index={})
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            first = resolve_outcome(self.host, "missing.md", {}, session=session)
            second = resolve_outcome(self.host, "other.md", {}, session=session)
            third = resolve_outcome(self.host, "a.md", {}, session=session)
        self.assertEqual(first.status, RESOLVE_ABSENT)
        self.assertEqual(second.status, RESOLVE_ABSENT)
        self.assertEqual(third.status, RESOLVE_FOUND)
        self.assertEqual(third.path, "a.md")
        self.assertEqual(len([item for item in opened if item == self.host.resolve()]), 1)
        record = observe_directory(session, self.host)
        self.assertEqual(record.status, DIR_COMPLETE)

    def test_C04_08_wrong_case_readme_resolves(self):
        write(self.host, "Readme.md", "# Title\n")
        actual = resolve_existing(self.host, "README.md", {})
        self.assertEqual(actual.lower(), "readme.md")
        facts = discover(self.host)
        docs = next(row for row in facts if row.name == "documentation")
        self.assertEqual(docs.confidence, "VERIFIED")

    def test_C04_09_exact_existing_path_does_not_scan(self):
        write(self.host, "README.md", "# Title\n")
        opened: list[Path] = []
        yielded: list[str] = []
        session = DiscoverySession.ephemeral(self.host, index={})
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            actual = resolve_existing(self.host, "README.md", {}, session=session)
        self.assertEqual(actual, "README.md")
        self.assertEqual(opened, [])
        self.assertEqual(yielded, [])

    def test_C04_10_exact_path_out_of_root_is_rejected(self):
        self.assertIsNone(resolve_existing(self.host, "../secret.txt", {}))
        outcome = resolve_outcome(self.host, "../secret.txt", {})
        self.assertEqual(outcome.status, RESOLVE_UNSAFE)

    def test_C04_11_case_insensitive_out_of_root_indirection_is_rejected(self):
        write(self.host, "README.md", "# host\n")
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "README.md").write_text("# Escaped\n", encoding="utf-8")
        linked = self.host / "docs"
        created = _try_dir_link(linked, outside)
        self.assertTrue(created)
        self.assertIsNone(resolve_existing(self.host, "docs/README.md", {}))
        self.assertIsNone(resolve_existing(self.host, "Docs/Readme.md", {}))

    def test_C04_12_case_fold_collision_is_ambiguous(self):
        (self.host / "README.md").write_text("A\n", encoding="utf-8")
        try:
            (self.host / "Readme.md").write_text("B\n", encoding="utf-8")
        except OSError:
            self.skipTest("filesystem cannot store colliding names")
        names = {path.name for path in self.host.iterdir()}
        if len(names) < 2:
            self.skipTest("filesystem is case-insensitive")
        session = DiscoverySession.ephemeral(self.host, index={})
        outcome = resolve_outcome(self.host, "readme.md", {}, session=session)
        self.assertEqual(outcome.status, RESOLVE_AMBIGUOUS)
        self.assertIsNone(resolve_existing(self.host, "readme.md", {}, session=session))

    def test_C04_13_multi_component_complete_parents_resolve(self):
        write(self.host, "docs/architecture.md", "# arch\n")
        actual = resolve_existing(self.host, "docs/architecture.md", {})
        self.assertEqual(actual, "docs/architecture.md")
        mixed = resolve_existing(self.host, "Docs/Architecture.md", {})
        self.assertEqual(mixed.lower(), "docs/architecture.md")

    def test_C04_14_truncated_parent_makes_downstream_unknown(self):
        _wide_children(self.host)
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        outcome = resolve_outcome(
            self.host, "docs/architecture/system.md", session.index, session=session
        )
        self.assertEqual(outcome.status, RESOLVE_UNKNOWN)
        self.assertNotEqual(outcome.status, RESOLVE_ABSENT)

    def test_C04_15_incomplete_index_does_not_prove_absence(self):
        write(self.host, "README.md", "# Title\n")
        _wide_children(self.host)
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        self.assertNotIn("readme.md", session.index)
        outcome = resolve_outcome(self.host, "README.md", session.index, session=session)
        self.assertEqual(outcome.status, RESOLVE_FOUND)
        self.assertEqual(outcome.path, "README.md")
        missing = resolve_outcome(
            self.host, "CONTRIBUTING.md", session.index, session=session
        )
        self.assertEqual(missing.status, RESOLVE_UNKNOWN)
        self.assertNotEqual(missing.status, RESOLVE_ABSENT)

    def test_C04_16_incomplete_index_fallback_uses_shared_budget(self):
        _wide_children(self.host)
        session = DiscoverySession.start(self.host, InventoryBudget(max_entries=1))
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            resolve_outcome(self.host, "README.md", session.index, session=session)
            resolve_outcome(self.host, "package.json", session.index, session=session)
        self.assertEqual(yielded, [])

    def test_C04_17_indexed_lookup_does_not_enumerate(self):
        write(self.host, "README.md", "# Title\n")
        index = path_identity_index(self.host)
        opened: list[Path] = []
        yielded: list[str] = []
        session = DiscoverySession.ephemeral(self.host, index=index)
        with patch.object(
            inventory, "_directory_scandir", _opening_scandir(opened, yielded)
        ):
            actual = resolve_existing(self.host, "readme.md", index, session=session)
        self.assertEqual(actual, "README.md")
        self.assertEqual(opened, [])

    def test_C04_18_ordinary_small_project_discover_still_works(self):
        write(self.host, "README.md", "# small-app\n")
        write(self.host, "src/app.py", "print('ok')\n")
        write(self.host, "Package.JSON", '{"name": "small-app"}\n')
        facts = discover(self.host)
        pkg = next(row for row in facts if row.name == "declared_package_identity")
        self.assertEqual(pkg.value, "small-app")
        self.assertEqual(pkg.confidence, "VERIFIED")
        source = next(row for row in facts if row.name == "source_tree")
        self.assertEqual(source.confidence, "VERIFIED")
        self.assertIn("src", source.value)

    def test_C04_19_c03_inventory_streaming_remains_bounded(self):
        _wide_children(self.host)
        yielded: list[str] = []
        listdir_names: list[str] = []
        with (
            patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)),
            patch.object(inventory.os, "listdir", _tracking_listdir(listdir_names)),
        ):
            observation = observe_inventory(
                self.host, budget=InventoryBudget(max_entries=1)
            )
            walked = bounded_metadata_walk(
                self.host, budget=InventoryBudget(max_entries=1)
            )
        self.assertTrue(observation.truncated)
        self.assertTrue(walked.truncated)
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND * 2)
        self.assertEqual(listdir_names, [])
        self.assertEqual(list_files(self.host, budget=InventoryBudget(max_entries=1)), [])

    def test_C04_20_out_of_root_containment_remains(self):
        write(self.host, "README.md", "# host\n")
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "package.json").write_text('{"name": "escaped"}\n', encoding="utf-8")
        self.assertIsNone(
            resolve_existing(
                self.host, "package.json", {"package.json": "../outside/package.json"}
            )
        )
        linked = self.host / "docs"
        created = _try_dir_link(linked, outside)
        self.assertTrue(created)
        self.assertIsNone(resolve_existing(self.host, "docs/README.md", {}))


class C04SourceAndGeneralityTests(unittest.TestCase):
    def test_discovery_has_no_listdir_resolver(self):
        text = (REPO / "src" / "scaffold_p5" / "discovery.py").read_text(encoding="utf-8")
        self.assertNotIn("os.listdir", text)
        context = (REPO / "src" / "scaffold_p5" / "discovery_context.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("os.listdir", context)
        self.assertNotIn("sorted(os.scandir", context)
        self.assertNotIn("list(os.scandir", context)
        self.assertIn("DiscoverySession", text)

    def test_no_consumer_domain(self):
        for rel in (
            "src/scaffold_p5/discovery.py",
            "src/scaffold_p5/discovery_context.py",
        ):
            text = (REPO / rel).read_text(encoding="utf-8").lower()
            for token in ("project-city", "babylon", "src/mvp", "vault", "player"):
                self.assertNotIn(token, text)

    def test_web_backend_native_data_interactive_fanout(self):
        for root_name, prefix in (
            ("packages", "pkg_"),
            ("src", "mod_"),
            ("include", "hdr_"),
            ("datasets", "shard_"),
            ("assets", "mesh_"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                host = Path(tmp) / "host"
                host.mkdir()
                base = host / root_name
                base.mkdir()
                for index in range(WIDE):
                    (base / f"{prefix}{index:04d}").mkdir()
                yielded: list[str] = []
                with patch.object(
                    inventory, "_directory_scandir", _counting_scandir(yielded)
                ):
                    discover(host, budget=InventoryBudget(max_entries=1))
                self.assertLessEqual(len(yielded), OVERFLOW_BOUND, root_name)
                self.assertNotEqual(len(yielded), WIDE, root_name)


if __name__ == "__main__":
    unittest.main()

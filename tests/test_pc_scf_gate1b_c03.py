"""Gate-1B-C03 complete inventory enumeration closure.

Residual G1B-T1-001: observe_inventory / durable_inventory / list_files
must share the streaming bound with bounded_metadata_walk. Does not
reopen T1-002 / T2 / T3. Does not repair G1B-T2-SHOULD-001.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scaffold_p5.inventory as inventory
from scaffold_p5.discovery import path_identity_index, resolve_existing
from scaffold_p5.host_state import durable_inventory, snapshot_host
from scaffold_p5.inventory import (
    CLASS_EXCLUDED,
    ENUMERATION_OVERFLOW_PROBE,
    EXCLUDED_BY_POLICY,
    FULLY_OBSERVED,
    InventoryBudget,
    TRUNCATED_BY_BUDGET,
    bounded_metadata_walk,
    hashed_inventory,
    observe_inventory,
)
from scaffold_p5.io_util import list_files
from support import REPO, write
from test_pc_scf_gate1b_c01 import _try_dir_link
from test_pc_scf_gate1b_c02 import _counting_scandir, _tracking_listdir


WIDE = 2048
OVERFLOW_BOUND = 1 + ENUMERATION_OVERFLOW_PROBE


def _wide_children(host: Path, prefix: str = "d") -> None:
    for index in range(WIDE):
        (host / f"{prefix}{index:04d}").mkdir()


def _opening_scandir(opened: list[Path], yielded: list[str]):
    real = inventory._directory_scandir

    def wrapped(path):
        opened.append(Path(path).resolve())
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

        return CountingScanner()

    return wrapped


class C03InventoryEnumerationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_C03_01_observe_inventory_wide_directory_enumeration_is_bounded(self):
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
        self.assertTrue(observation.truncated)
        self.assertEqual(observation.in_scope_status, TRUNCATED_BY_BUDGET)
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertGreater(len(yielded), 0)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertEqual(listdir_names, [])
        self.assertFalse(observation.verified_complete)

    def test_C03_02_durable_inventory_same_wide_host_is_bounded(self):
        _wide_children(self.host)
        yielded: list[str] = []
        coverage: dict = {}
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            hashed = durable_inventory(
                self.host,
                budget=InventoryBudget(max_entries=1),
                coverage_out=coverage,
            )
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertEqual(coverage["status"], TRUNCATED_BY_BUDGET)
        self.assertFalse(coverage["verified_complete"])
        self.assertEqual(hashed, {})

    def test_C03_03_list_files_does_not_materialize_wide_directory(self):
        _wide_children(self.host)
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            names = list_files(self.host, budget=InventoryBudget(max_entries=1))
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertEqual(names, [])

    def test_C03_04_excluded_root_does_not_listdir_for_cosmetic_count(self):
        write(self.host, "README.md", "# host\n")
        write(self.host, "src/app.py", "print('ok')\n")
        excluded = self.host / "node_modules"
        excluded.mkdir()
        _wide_children(excluded, prefix="pkg_")
        opened: list[Path] = []
        yielded: list[str] = []
        listdir_names: list[str] = []
        with (
            patch.object(inventory, "_directory_scandir", _opening_scandir(opened, yielded)),
            patch.object(inventory.os, "listdir", _tracking_listdir(listdir_names)),
        ):
            observation = observe_inventory(self.host)
        excluded_resolved = excluded.resolve()
        self.assertNotIn(excluded_resolved, opened)
        self.assertFalse(any(_is_under(item, excluded_resolved) for item in opened))
        self.assertEqual(listdir_names, [])
        vendor = next(row for row in observation.roots if row.path == "node_modules")
        self.assertEqual(vendor.classification, CLASS_EXCLUDED)
        self.assertEqual(vendor.observation, EXCLUDED_BY_POLICY)
        self.assertTrue(vendor.present)
        self.assertIsNone(vendor.bounded_file_count)
        self.assertNotEqual(len(yielded), WIDE)

    def test_C03_05_bounded_root_huge_fanout_obeys_max_entries(self):
        datasets = self.host / "datasets"
        datasets.mkdir()
        _wide_children(datasets, prefix="shard_")
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            observation = observe_inventory(
                self.host, budget=InventoryBudget(max_entries=1)
            )
        self.assertTrue(observation.truncated)
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertFalse(observation.verified_complete)

    def test_C03_06_exact_budget_small_directory_is_complete(self):
        write(self.host, "a.md", "a")
        write(self.host, "b.md", "b")
        write(self.host, "c.md", "c")
        observation = observe_inventory(
            self.host, budget=InventoryBudget(max_entries=3)
        )
        self.assertFalse(observation.truncated)
        self.assertEqual(observation.in_scope_status, FULLY_OBSERVED)
        hashed = hashed_inventory(observation)
        self.assertEqual(sorted(hashed), ["a.md", "b.md", "c.md"])
        self.assertTrue(all(row["observation"] == FULLY_OBSERVED for row in hashed.values()))

    def test_C03_07_budget_plus_one_has_no_authoritative_partial_prefix(self):
        for name in ("a.md", "b.md", "c.md", "d.md"):
            write(self.host, name, name)
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            observation = observe_inventory(
                self.host, budget=InventoryBudget(max_entries=3)
            )
        self.assertTrue(observation.truncated)
        self.assertLessEqual(len(yielded), 3 + ENUMERATION_OVERFLOW_PROBE)
        hashed = hashed_inventory(observation)
        self.assertEqual(hashed, {})
        self.assertFalse(observation.verified_complete)

    def test_C03_08_bounded_metadata_walk_2048_child_remains_bounded(self):
        _wide_children(self.host)
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
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)
        self.assertEqual(listdir_names, [])
        self.assertEqual(walked.directories, [])
        self.assertEqual(walked.files, [])

    def test_C03_09_out_of_root_containment_remains(self):
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

    def test_C03_10_ordinary_small_repository_remains_compatible(self):
        write(self.host, "README.md", "# small-app\n")
        write(self.host, "src/app.py", "print('ok')\n")
        observation = observe_inventory(self.host)
        hashed = hashed_inventory(observation)
        self.assertEqual(hashed["README.md"]["observation"], FULLY_OBSERVED)
        self.assertEqual(hashed["src/app.py"]["observation"], FULLY_OBSERVED)
        self.assertIn("README.md", list_files(self.host))
        self.assertIn("src/app.py", list_files(self.host))
        index = path_identity_index(self.host)
        self.assertEqual(index["readme.md"], "README.md")
        snap = snapshot_host(self.host)
        self.assertIn("README.md", snap.files)
        self.assertIn("src/app.py", snap.files)


class C03IntegrationAndSourceTests(unittest.TestCase):
    def test_production_consumers_still_use_list_files(self):
        host_state = (REPO / "src" / "scaffold_p5" / "host_state.py").read_text(encoding="utf-8")
        discovery = (REPO / "src" / "scaffold_p5" / "discovery.py").read_text(encoding="utf-8")
        io_util = (REPO / "src" / "scaffold_p5" / "io_util.py").read_text(encoding="utf-8")
        self.assertIn("files = list_files(host)", host_state)
        self.assertIn("observation = observe_inventory(", host_state)
        self.assertIn("for rel in list_files(root", discovery)
        self.assertIn("observe_inventory(", io_util)

    def test_walk_uses_shared_stream_primitive_not_listdir(self):
        stream = (REPO / "src" / "scaffold_p5" / "inventory.py").read_text(encoding="utf-8")
        walk = stream[stream.find("def _walk(") :]
        self.assertIn("_stream_directory_names", walk)
        self.assertNotIn("os.listdir", walk)
        self.assertNotIn("sorted(os.scandir", walk)
        self.assertNotIn("list(os.scandir", walk)
        self.assertNotIn("cheap_count", stream)
        self.assertNotIn("os.listdir", stream)

    def test_modules_fact_uses_shared_stream_primitive(self):
        text = (REPO / "src" / "scaffold_p5" / "discovery.py").read_text(encoding="utf-8")
        fn = text[text.find("def _modules_fact") : text.find("def _module_corroborated")]
        self.assertIn("_stream_directory_names", fn)
        self.assertNotIn("os.listdir", fn)


class C03GeneralityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _bounded_observe(self, root_name: str, child_prefix: str) -> None:
        root = self.host / root_name
        root.mkdir()
        for index in range(WIDE):
            (root / f"{child_prefix}{index:04d}").mkdir()
        yielded: list[str] = []
        with patch.object(inventory, "_directory_scandir", _counting_scandir(yielded)):
            observation = observe_inventory(
                self.host, budget=InventoryBudget(max_entries=1)
            )
        self.assertTrue(observation.truncated)
        self.assertLessEqual(len(yielded), OVERFLOW_BOUND)
        self.assertNotEqual(len(yielded), WIDE)

    def test_web_monorepo_packages_fanout(self):
        self._bounded_observe("packages", "pkg_")

    def test_backend_cli_src_fanout(self):
        self._bounded_observe("src", "mod_")

    def test_native_include_fanout(self):
        self._bounded_observe("include", "hdr_")

    def test_data_ml_datasets_fanout(self):
        self._bounded_observe("datasets", "shard_")

    def test_interactive_assets_fanout(self):
        self._bounded_observe("assets", "mesh_")

    def test_no_consumer_domain_in_inventory(self):
        text = (REPO / "src" / "scaffold_p5" / "inventory.py").read_text(encoding="utf-8").lower()
        for token in ("project-city", "babylon", "src/mvp", "vault"):
            self.assertNotIn(token, text)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from p6_support import git, write_modules
from p7_support import TASK_A
from p8_support import (
    run_submit,
    rebind_noscms_baseline,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.scm import observe_scm
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.delta import observe_real_diff
from scaffold_p8.finalize import finalize_s10
from scaffold_p8.models import FORBIDDEN_FINALIZATIONS_DIR, NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import (
    BASELINE_REL,
    COMPLETE_NAME,
    SUBMIT_EXT_PREFIX,
    initialize_noscms_baseline,
    load_noscms_baseline,
    publish_noscms_finalization,
    submit_namespace_write_allowed,
    verify_noscms_publication,
)
from scaffold_p8.records import durability_state, is_durable
from scaffold_p8.structural import IMPACT_MODULE_STRUCTURE
from support import write


class FA2Batch7NoScmPublicationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B7D01_baseline_initialization_required(self):
        write_submit_host(self.host, noscms_baseline=False)
        observed = observe_real_diff(self.host)
        self.assertFalse(observed["ok"])
        self.assertEqual(observed.get("observation_state"), "UNKNOWN")
        self.assertTrue(observed.get("baseline_required"))
        self.assertTrue(
            any("baseline" in item.lower() for item in observed.get("blockers") or [])
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S2")
        self.assertTrue(result.extras.get("real_diff", {}).get("baseline_required"))
        self.assertFalse(observed.get("ok"))

    def test_B7D02_initialized_unchanged_workspace(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "same.txt", "A\n")
        rebind_noscms_baseline(self.host)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])
        self.assertNotIn("same.txt", observed["paths"])
        self.assertFalse(
            any(
                row.get("path") == "same.txt" and row.get("change") == "modified"
                for row in observed["entries"]
            )
        )

    def test_B7D03_add(self):
        self._baseline_host()
        write(self.host, "added.txt", "new\n")
        row = self._entry("added.txt")
        self.assertEqual(row["change"], "added")

    def test_B7D04_modify(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "same.txt", "A\n")
        rebind_noscms_baseline(self.host)
        write(self.host, "same.txt", "B\n")
        row = self._entry("same.txt")
        self.assertEqual(row["change"], "modified")

    def test_B7D05_delete(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "delete-me.txt", "gone soon\n")
        rebind_noscms_baseline(self.host)
        (self.host / "delete-me.txt").unlink()
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        row = self._entry("delete-me.txt")
        self.assertEqual(row["change"], "deleted")
        self.assertIn("delete-me.txt", observed["paths"])
        self.assertFalse((self.host / "delete-me.txt").exists())

    def test_B7D06_type_change(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "was-file.txt", "file bytes\n")
        rebind_noscms_baseline(self.host)
        (self.host / "was-file.txt").unlink()
        (self.host / "was-file.txt").mkdir()
        row = self._entry("was-file.txt")
        self.assertEqual(row["change"], "type_changed")

    def test_B7D07_mixed_real_change_set(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "unchanged.txt", "keep\n")
        write(self.host, "modify-me.txt", "old\n")
        write(self.host, "delete-me.txt", "remove\n")
        rebind_noscms_baseline(self.host)
        write(self.host, "added.txt", "new\n")
        write(self.host, "modify-me.txt", "new\n")
        (self.host / "delete-me.txt").unlink()
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        kinds = {row["path"]: row["change"] for row in observed["entries"]}
        self.assertEqual(kinds["added.txt"], "added")
        self.assertEqual(kinds["modify-me.txt"], "modified")
        self.assertEqual(kinds["delete-me.txt"], "deleted")
        self.assertNotIn("unchanged.txt", kinds)
        self.assertNotIn("unchanged.txt", observed["paths"])

    def test_B7D08_support_does_not_self_diff(self):
        self._baseline_host()
        write(
            self.host,
            ".scaffold/ext/submit/noscms/scratch.yaml",
            "kind: support\n",
        )
        initialize_noscms_baseline(self.host)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertFalse(
            any(
                str(row.get("path") or "").startswith(".scaffold/ext/submit/")
                for row in observed["entries"]
            )
        )

    def test_B7D09_relevant_core_change_remains_visible(self):
        self._baseline_host()
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["name"] = "batch7-core-visible"
        from scaffold_p5.io_util import write_yaml_atomic

        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertIn(".scaffold/project.yaml", observed["paths"])
        self.assertEqual(self._entry(".scaffold/project.yaml")["change"], "modified")

    def test_B7N01_no_forbidden_finalizations_root(self):
        result = self._finalize_success()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse((self.host / FORBIDDEN_FINALIZATIONS_DIR).exists())
        self.assertFalse((self.host / ".scaffold/finalizations").exists())

    def test_B7N02_authorized_support_location(self):
        result = self._finalize_success()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record_id = result.extras["change_record"]["record_id"]
        pub = self.host / NOSCMS_PUBLICATIONS_DIR / record_id
        self.assertTrue((self.host / BASELINE_REL).is_file())
        self.assertTrue((pub / COMPLETE_NAME).is_file())
        self.assertTrue((pub / "manifest.yaml").is_file())
        self.assertTrue((pub / "objects").is_dir())
        project = read_yaml(self.host / ".scaffold/project.yaml")
        resolved = resolve_ownership(project["ownership"], SUBMIT_EXT_PREFIX)
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertIn(resolved.mode, {"GENERATED", "MANAGED"})
        self.assertTrue(str(pub.relative_to(self.host)).replace("\\", "/").startswith(
            SUBMIT_EXT_PREFIX
        ))

    def test_B7N03_namespace_boundary(self):
        self.assertFalse(
            submit_namespace_write_allowed(".scaffold/ext/other/file.yaml")
        )
        self.assertFalse(
            submit_namespace_write_allowed(".scaffold/ext/test/report.yaml")
        )
        self.assertTrue(
            submit_namespace_write_allowed(".scaffold/ext/submit/noscms/baseline.yaml")
        )
        ownership = {
            ".scaffold/project.yaml": "GENERATED",
            ".scaffold/modules.yaml": "GENERATED",
            ".scaffold/commands.yaml": "GENERATED",
            ".scaffold/tests.yaml": "GENERATED",
            ".scaffold/skills.lock": "GENERATED",
            ".scaffold/ext/test/": "GENERATED",
            "src/": "HUMAN_OWNED",
        }
        write_submit_host(
            self.host,
            noscms_baseline=False,
            ownership=ownership,
        )
        initialized = initialize_noscms_baseline(self.host)
        self.assertFalse(initialized.get("ok"))
        self.assertTrue(
            any("ext/submit" in item for item in initialized.get("blockers") or [])
        )
        result = self._finalize_success()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse((self.host / ".scaffold/ext/other").exists())
        test_ns = self.host / ".scaffold/ext/test"
        if test_ns.exists():
            self.assertTrue(test_ns.is_dir())

    def test_B7P01_exact_immutable_publication(self):
        result = self._finalize_success()
        record_id = result.extras["change_record"]["record_id"]
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        digest = result.extras["s10"]["finalization_candidate_digest"]
        self.assertEqual(verified.get("candidate_digest"), digest)
        self.assertEqual(
            verified.get("representation_digest"),
            result.extras["s10"].get("representation_digest"),
        )
        objects = self.host / NOSCMS_PUBLICATIONS_DIR / record_id / "objects"
        self.assertTrue(any(objects.iterdir()))

    def test_B7P02_restart_verification(self):
        result = self._finalize_success()
        record_id = result.extras["change_record"]["record_id"]
        expected = result.extras["s10"]["finalization_candidate_digest"]
        restarted = submit_engine(self.host)
        self.assertIsNot(restarted, submit_engine(self.host))
        self.assertTrue(is_durable(self.host, record_id))
        state = durability_state(self.host, record_id)
        self.assertEqual(state["state"], "durable")
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertEqual(verified.get("candidate_digest"), expected)

    def test_B7P03_workspace_mutation_does_not_alter_history(self):
        result = self._finalize_success()
        record_id = result.extras["change_record"]["record_id"]
        expected = result.extras["s10"]["finalization_candidate_digest"]
        representation = result.extras["s10"]["representation_digest"]
        write(self.host, "src/app.py", "value = 99\n")
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertEqual(verified.get("candidate_digest"), expected)
        self.assertEqual(verified.get("representation_digest"), representation)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(self._entry("src/app.py")["change"], "modified")

    def test_B7P04_mutation_during_publication_blocks(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest

        def mutate():
            write(self.host, "src/app.py", "value = 7\n")

        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            during_s10=mutate,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertFalse(result.extras["s10"].get("durable"))
        records = list((self.host / ".scaffold/changes").glob("*.yaml"))
        self.assertTrue(records)
        record_id = records[0].stem
        self.assertFalse(
            (self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME).exists()
        )
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertIn("src/app.py", observed["paths"])

    def test_B7P05_partial_preparation_is_not_durable(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_before_complete=True,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        records = list((self.host / ".scaffold/changes").glob("*.yaml"))
        self.assertTrue(records)
        record_id = records[0].stem
        self.assertFalse(is_durable(self.host, record_id))
        self.assertEqual(durability_state(self.host, record_id)["state"], "absent")
        restarted = submit_engine(self.host)
        self.assertFalse(is_durable(self.host, record_id))
        self.assertIsNotNone(restarted)

    def test_B7P06_publication_support_does_not_change_candidate(self):
        write_submit_host(self.host)
        before = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = observe_candidate(self.host)
        self.assertEqual(
            after.digest,
            result.extras["s10"]["finalization_candidate_digest"],
        )
        self.assertTrue((self.host / BASELINE_REL).is_file())

    def test_B7P07_success_advances_no_scm_baseline(self):
        result = self._finalize_success()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])

    def test_B7P08_failed_s10_does_not_advance_baseline(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        before = observe_real_diff(self.host)
        self.assertIn("src/app.py", before["paths"])
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_s10=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"].get("durable"))
        after = observe_real_diff(self.host)
        self.assertTrue(after["ok"], after.get("blockers"))
        self.assertIn("src/app.py", after["paths"])
        self.assertEqual(self._entry("src/app.py")["change"], "modified")

    def test_B7P09_finalization_identity_conflict(self):
        result = self._finalize_success()
        record_id = result.extras["change_record"]["record_id"]
        rel = f".scaffold/changes/{record_id}.yaml"
        second = finalize_s10(
            self.host,
            record_id=record_id,
            change_rel=rel,
            reviewed_paths=["src/app.py"],
            expected_digest="f" * 64,
            scm_kind="none",
        )
        self.assertFalse(second["ok"])
        self.assertTrue(second.get("conflict"))
        self.assertTrue(is_durable(self.host, record_id))

    def test_B7P10_complete_without_cache_cannot_contradict_restart(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_baseline_cache=True,
        )
        records = list((self.host / ".scaffold/changes").glob("*.yaml"))
        self.assertTrue(records)
        record_id = records[0].stem
        call_durable = bool(result.extras.get("s10", {}).get("durable"))
        restart_durable = is_durable(self.host, record_id)
        self.assertEqual(call_durable, restart_durable)
        self.assertTrue(call_durable)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "publication")

    def test_B7P11_restart_at_commit_boundary_resolves_f_baseline(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_baseline_cache=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record_id = result.extras["change_record"]["record_id"]
        expected = result.extras["s10"]["finalization_candidate_digest"]
        cache = self.host / BASELINE_REL
        if cache.is_file():
            cache.unlink()
        restarted = submit_engine(self.host)
        self.assertIsNotNone(restarted)
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertEqual(verified.get("candidate_digest"), expected)
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "publication")
        self.assertEqual(resolved.get("change_id"), record_id)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])

    def test_B7P12_interruption_before_commit_retains_b(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        before = observe_real_diff(self.host)
        self.assertIn("src/app.py", before["paths"])
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_before_complete=True,
        )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertFalse(result.extras["s10"].get("durable"))
        records = list((self.host / ".scaffold/changes").glob("*.yaml"))
        self.assertTrue(records)
        record_id = records[0].stem
        self.assertFalse(
            (self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME).exists()
        )
        restarted = submit_engine(self.host)
        self.assertFalse(is_durable(self.host, record_id))
        self.assertIsNotNone(restarted)
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "file")
        after = observe_real_diff(self.host)
        self.assertTrue(after["ok"], after.get("blockers"))
        self.assertIn("src/app.py", after["paths"])
        self.assertEqual(self._entry("src/app.py")["change"], "modified")

    def test_B7P13_baseline_cache_loss_recovery(self):
        result = self._finalize_success()
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record_id = result.extras["change_record"]["record_id"]
        expected = result.extras["s10"]["finalization_candidate_digest"]
        cache = self.host / BASELINE_REL
        self.assertTrue(cache.is_file())
        cache.unlink()
        self.assertFalse(cache.is_file())
        verified = verify_noscms_publication(self.host, record_id)
        self.assertTrue(verified.get("ok"), verified.get("blockers"))
        self.assertEqual(verified.get("candidate_digest"), expected)
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "publication")
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])

    def test_B7P14_same_second_reverse_lex_ids_do_not_revert_baseline(self):
        f1 = "change-20300101T000000Z-ffffffff"
        f2 = "change-20300101T000000Z-00000000"
        self.assertGreater(f1, f2)
        write_submit_host(self.host)
        first = self._publish_named(f1)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        self.assertTrue(first.extras["s10"].get("durable"))
        write(self.host, "src/app.py", "value = 2\n")
        second = self._publish_named(f2)
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        self.assertTrue(second.extras["s10"].get("durable"))
        verified_f2 = verify_noscms_publication(self.host, f2)
        self.assertTrue(verified_f2.get("ok"), verified_f2.get("blockers"))
        self.assertTrue(verified_f2.get("durable"))
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "publication")
        self.assertEqual(resolved.get("change_id"), f2)
        self.assertEqual(resolved.get("baseline_generation"), 2)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])
        verified_f1 = verify_noscms_publication(self.host, f1)
        self.assertTrue(verified_f1.get("ok"), verified_f1.get("blockers"))
        self.assertTrue(verified_f1.get("durable"))

    def test_B7P15_change_id_order_is_not_head_authority(self):
        f1 = "change-20300101T000000Z-cccccccc"
        f2 = "change-20300101T000000Z-bbbbbbbb"
        f3 = "change-20300101T000000Z-00000000"
        self.assertGreater(f1, f2)
        self.assertGreater(f2, f3)
        write_submit_host(self.host)
        first = self._publish_named(f1)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        write(self.host, "src/app.py", "value = 2\n")
        second = self._publish_named(f2)
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        write(self.host, "src/app.py", "value = 3\n")
        third = self._publish_named(f3)
        self.assertEqual(third.outcome, "COMPLETED", third.blockers)
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("change_id"), f3)
        self.assertEqual(resolved.get("baseline_generation"), 3)
        self.assertNotEqual(resolved.get("change_id"), max([f1, f2, f3]))
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        for record_id in (f1, f2, f3):
            verified = verify_noscms_publication(self.host, record_id)
            self.assertTrue(verified.get("ok"), verified.get("blockers"))

    def test_B7P16_baseline_cache_cannot_override_newer_publication(self):
        f1 = "change-20300101T000000Z-aaaaaaa1"
        f2 = "change-20300101T000000Z-aaaaaaa2"
        write_submit_host(self.host)
        first = self._publish_named(f1)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        f1_inventory = read_yaml(
            self.host / NOSCMS_PUBLICATIONS_DIR / f1 / "manifest.yaml"
        )["inventory"]
        write(self.host, "src/app.py", "value = 2\n")
        second = self._publish_named(f2)
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        write_yaml_atomic(
            self.host / BASELINE_REL,
            {
                "kind": "noscms_baseline",
                "record_class": "support_artifact",
                "schema_version": "1",
                "source": "publication_cache",
                "change_id": f1,
                "inventory": f1_inventory,
            },
        )
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("source"), "publication")
        self.assertEqual(resolved.get("change_id"), f2)
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        self.assertEqual(observed["entries"], [])
        self.assertEqual(observed["paths"], [])

    def test_B7P17_ambiguous_lineage_fails_closed(self):
        f1 = "change-20300101T000000Z-aaaaaaa1"
        duplicate = "change-20300101T000000Z-eeeeeeee"
        write_submit_host(self.host)
        first = self._publish_named(f1)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        src = self.host / NOSCMS_PUBLICATIONS_DIR / f1
        dst = self.host / NOSCMS_PUBLICATIONS_DIR / duplicate
        shutil.copytree(src, dst)
        for name in (COMPLETE_NAME, "manifest.yaml"):
            payload = read_yaml(dst / name)
            payload["change_id"] = duplicate
            write_yaml_atomic(dst / name, payload)
        verified_f1 = verify_noscms_publication(self.host, f1)
        verified_dup = verify_noscms_publication(self.host, duplicate)
        self.assertTrue(verified_f1.get("ok"), verified_f1.get("blockers"))
        self.assertTrue(verified_dup.get("ok"), verified_dup.get("blockers"))
        resolved = load_noscms_baseline(self.host)
        self.assertFalse(resolved.get("ok"))
        self.assertEqual(resolved.get("observation_state"), "UNKNOWN")
        self.assertFalse(resolved.get("baseline_required"))
        self.assertTrue(
            any("UNKNOWN" in item for item in resolved.get("blockers") or [])
        )
        observed = observe_real_diff(self.host)
        self.assertFalse(observed.get("ok"))
        self.assertEqual(observed.get("observation_state"), "UNKNOWN")
        self.assertNotEqual(resolved.get("change_id"), f1)
        self.assertNotEqual(resolved.get("change_id"), duplicate)

    def test_B7P18_distinct_record_ids_cannot_claim_same_generation(self):
        from scaffold_p8.finalize import build_finalization_marker

        write_submit_host(self.host, noscms_working_diff=False)
        digest = observe_candidate(self.host).digest
        first_id = "change-20300101T000000Z-11111111"
        second_id = "change-20300101T000000Z-22222222"
        barrier = threading.Barrier(2)
        results: list[dict | None] = [None, None]

        def worker(index: int, record_id: str) -> None:
            barrier.wait(timeout=10)
            marker = build_finalization_marker(
                record_id=record_id,
                candidate_digest=digest,
                change_record_digest="a" * 64,
            )
            results[index] = publish_noscms_finalization(
                self.host,
                record_id=record_id,
                candidate_digest=digest,
                change_record_digest="a" * 64,
                support_artifacts=[],
                marker=marker,
            )

        threads = [
            threading.Thread(target=worker, args=(0, first_id)),
            threading.Thread(target=worker, args=(1, second_id)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            self.assertFalse(thread.is_alive())
        self.assertIsNotNone(results[0])
        self.assertIsNotNone(results[1])
        self.assertTrue(results[0].get("ok"), results[0])
        self.assertTrue(results[1].get("ok"), results[1])
        generations = {
            read_yaml(
                self.host / NOSCMS_PUBLICATIONS_DIR / first_id / COMPLETE_NAME
            )["baseline_generation"],
            read_yaml(
                self.host / NOSCMS_PUBLICATIONS_DIR / second_id / COMPLETE_NAME
            )["baseline_generation"],
        }
        self.assertEqual(generations, {1, 2})
        resolved = load_noscms_baseline(self.host)
        self.assertTrue(resolved.get("ok"), resolved.get("blockers"))
        self.assertEqual(resolved.get("baseline_generation"), 2)
        self.assertIn(resolved.get("change_id"), {first_id, second_id})

    def test_B7X01_real_diff_feeds_batch6_s3_s4(self):
        write_submit_host(self.host)
        write_modules(
            self.host,
            [
                {
                    "id": "save",
                    "path": "src/save/",
                    "interfaces": ["src/save/api.py"],
                }
            ],
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertIn(result.extras.get("stage"), {"S3", "S4"})
        self.assertIn("structural", result.extras)
        self.assertIn("knowledge", result.extras)
        self.assertIn(
            IMPACT_MODULE_STRUCTURE,
            (result.extras.get("structural") or {}).get("impact_classes") or [],
        )
        self.assertIn(".scaffold/modules.yaml", result.extras.get("delta", {}).get("paths") or [])

    def test_B7X02_no_task_plus_no_scm(self):
        write_submit_host(self.host, noscms_working_diff=False)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        if task_path.is_file():
            task_path.unlink()
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        result = run_submit(self.host, 
            invoke_test=True,
            selected=["unit"],
        )
        self.assertTrue(result.extras.get("no_task"))
        self.assertEqual(result.extras["task_book_ids"], [])
        self.assertIn("src/app.py", result.extras.get("delta", {}).get("paths") or [])
        self.assertIn("structural", result.extras)
        self.assertIn("knowledge", result.extras)
        self.assertNotIn(
            "missing Task Book identity",
            " ".join(result.blockers),
        )

    def test_B7X03_task_scope_plus_deleted_path(self):
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "src/gone.py", "delete me\n")
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        (self.host / "src/gone.py").unlink()
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        paths = result.extras.get("delta", {}).get("paths") or []
        self.assertIn("src/gone.py", paths)
        entries = {
            row["path"]: row["change"]
            for row in result.extras.get("delta", {}).get("entries") or []
        }
        self.assertEqual(entries.get("src/gone.py"), "deleted")
        self.assertIn(
            "src/gone.py",
            (result.extras.get("structural") or {}).get("reviewed_paths") or [],
        )

    def test_B7X04_scm_detection_regression(self):
        parent = self.root / "parent"
        project = parent / "project"
        project.mkdir(parents=True)
        write(parent, "outside.txt", "outside baseline\n")
        git(parent, "init")
        git(parent, "branch", "-M", "main")
        git(parent, "add", "-A")
        git(
            parent,
            "-c",
            "user.name=Batch 7 Fixture",
            "-c",
            "user.email=batch7@example.invalid",
            "commit",
            "-m",
            "parent baseline",
        )
        write_submit_host(project)
        observed = observe_scm(project)
        self.assertEqual(observed.kind, "git")
        diff = observe_real_diff(project)
        self.assertEqual(diff.get("kind"), "git")
        self.assertFalse(
            (project / ".scaffold/ext/submit/noscms").exists()
        )
        initialized = initialize_noscms_baseline(project)
        self.assertFalse(initialized.get("ok"))
        self.assertFalse(
            (project / ".scaffold/ext/submit/noscms").exists()
        )

    def _baseline_host(self) -> None:
        write_submit_host(self.host, noscms_working_diff=False)

    def _entry(self, path: str) -> dict:
        observed = observe_real_diff(self.host)
        self.assertTrue(observed["ok"], observed.get("blockers"))
        return next(row for row in observed["entries"] if row["path"] == path)

    def _finalize_success(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        return run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )

    def _publish_named(self, change_id: str):
        digest = observe_candidate(self.host).digest
        return run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            change_id=change_id,
        )


if __name__ == "__main__":
    unittest.main()

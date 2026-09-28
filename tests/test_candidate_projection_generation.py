"""P6 candidate projection generation and migration currentness."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from support import REPO

from scaffold_p5 import yaml_lite
from scaffold_p5.consumer_install import (
    apply_consumer_install,
    distribution_cli,
    plan_consumer_install,
)
from scaffold_p6.candidate import (
    observe_candidate,
    report_usable_for,
    semantic_body,
)
from scaffold_p6.models import (
    PROJECTION_GENERATION_CURRENT,
    PROJECTION_GENERATION_LEGACY,
)
from scaffold_p6.projection import (
    digest_is_current,
    establish_projection_migration,
    migration_dir,
)
from scaffold_p7.lifecycle import (
    decision_is_satisfied_current,
    evaluate_ready_for_review,
)


AGENTS = (
    "human rule\n"
    "<!-- scaffold:managed:scaffold-consumer:start -->\n"
    "managed body\n"
    "<!-- scaffold:managed:scaffold-consumer:end -->\n"
)
GITATTRIBUTES = (
    "*.txt text\n"
    "# scaffold:managed:scaffold-consumer-git:start\n"
    ".scaffold/install/** -text\n"
    "# scaffold:managed:scaffold-consumer-git:end\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.check_call(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=T", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _replace(path: Path, old: str, new: str) -> None:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if old not in text:
        raise AssertionError(f"{old!r} missing from {path}")
    path.write_bytes(text.replace(old, new, 1).encode("utf-8"))


class ProjectionGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "host"
        self.root.mkdir()
        _git(self.root, "init")
        _write(self.root / "src" / "app.py", "value = 1\n")
        _write(self.root / "AGENTS.md", AGENTS)
        _write(self.root / ".gitattributes", GITATTRIBUTES)
        _write(
            self.root / ".scaffold" / "project.yaml",
            yaml_lite.dump({"name": "sample", "clients": [{"path": ".cursor/"}]}),
        )
        _write(
            self.root / ".scaffold" / "tasks" / "task-alpha.yaml",
            yaml_lite.dump(
                {
                    "record_type": "task_book",
                    "record_id": "task-alpha",
                    "goal": "ship the sample",
                    "status": "IN_PROGRESS",
                }
            ),
        )
        _write(self.root / ".scaffold" / "install" / "run.py", "print('v1')\n")
        _git(self.root, "add", "src/app.py", "AGENTS.md", ".gitattributes", ".scaffold/project.yaml")
        _git(self.root, "commit", "-m", "base")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _decision(self, digest: str) -> dict:
        return {
            "outcome": "SATISFIED",
            "candidate_digest": digest,
            "basis": [{"kind": "task_fact", "summary": "held"}],
            "rationale": "held",
        }

    def _task(self, digest: str) -> dict:
        return {
            "status": "READY_FOR_REVIEW",
            "acceptance": "the sample holds",
            "stages": [
                {
                    "stage_id": "s1",
                    "status": "COMPLETE",
                    "required_tests": [],
                    "completion_decision": {
                        **self._decision(digest),
                        "stage_id": "s1",
                    },
                }
            ],
            "final_tests": [],
            "task_completion_decision": self._decision(digest),
        }

    def test_generation_1_is_legacy_and_generation_2_is_maintenance_neutral(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        current = observe_candidate(self.root)
        self.assertEqual(legacy.projection_generation, PROJECTION_GENERATION_LEGACY)
        self.assertEqual(current.projection_generation, PROJECTION_GENERATION_CURRENT)
        self.assertNotIn("projection_generation", semantic_body(legacy.data))
        self.assertEqual(
            semantic_body(current.data).get("projection_generation"),
            PROJECTION_GENERATION_CURRENT,
        )
        legacy_paths = [
            row["path"] for row in semantic_body(legacy.data)["untracked_paths"]
        ]
        current_paths = [
            row["path"] for row in semantic_body(current.data)["untracked_paths"]
        ]
        self.assertIn(".scaffold/install/run.py", legacy_paths)
        self.assertNotIn(".scaffold/install/run.py", current_paths)
        self.assertNotEqual(legacy.digest, current.digest)

        _write(self.root / ".scaffold" / "install" / "run.py", "print('v2')\n")
        _replace(self.root / "AGENTS.md", "managed body", "managed body refreshed")
        _replace(
            self.root / ".gitattributes",
            ".scaffold/install/** -text",
            "*.bin binary",
        )
        _write(self.root / ".cursor" / "rules" / "example.mdc", "client rule\n")
        after = observe_candidate(self.root)
        self.assertEqual(after.digest, current.digest)

        _write(self.root / "src" / "app.py", "value = 2\n")
        self.assertNotEqual(observe_candidate(self.root).digest, current.digest)

    def test_human_agents_and_authority_remain_significant(self) -> None:
        baseline = observe_candidate(self.root).digest
        _replace(self.root / "AGENTS.md", "human rule", "human rule edited")
        self.assertNotEqual(observe_candidate(self.root).digest, baseline)
        _replace(self.root / "AGENTS.md", "human rule edited", "human rule")
        _replace(self.root / ".gitattributes", "*.txt text", "*.md text")
        self.assertNotEqual(observe_candidate(self.root).digest, baseline)
        _replace(self.root / ".gitattributes", "*.md text", "*.txt text")
        project = yaml_lite.load(
            (self.root / ".scaffold" / "project.yaml").read_text(encoding="utf-8")
        )
        project["name"] = "renamed"
        _write(self.root / ".scaffold" / "project.yaml", yaml_lite.dump(project))
        self.assertNotEqual(observe_candidate(self.root).digest, baseline)

    def test_task_substance_rotates_and_status_does_not(self) -> None:
        baseline = observe_candidate(self.root).digest
        task_path = self.root / ".scaffold" / "tasks" / "task-alpha.yaml"
        task = yaml_lite.load(task_path.read_text(encoding="utf-8"))
        task["status"] = "READY_FOR_REVIEW"
        _write(task_path, yaml_lite.dump(task))
        self.assertEqual(observe_candidate(self.root).digest, baseline)
        task["goal"] = "ship a different sample"
        _write(task_path, yaml_lite.dump(task))
        self.assertNotEqual(observe_candidate(self.root).digest, baseline)

    def test_migration_keeps_legacy_completion_and_evidence_current(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        before = observe_candidate(self.root)
        migration = establish_projection_migration(self.root)
        self.assertTrue(migration["ok"])
        self.assertEqual(migration["source_digest"], legacy.digest)
        self.assertEqual(migration["target_digest"], before.digest)
        self.assertNotEqual(legacy.digest, before.digest)
        again = establish_projection_migration(self.root)
        self.assertTrue(again["resumed"])
        self.assertEqual(again["source_digest"], migration["source_digest"])

        _write(self.root / ".scaffold" / "install" / "run.py", "print('v2')\n")
        _replace(self.root / "AGENTS.md", "managed body", "managed body refreshed")
        _replace(
            self.root / ".gitattributes",
            ".scaffold/install/** -text",
            "*.bin binary",
        )
        live = observe_candidate(self.root)
        self.assertEqual(live.digest, before.digest)
        decision = self._decision(legacy.digest)
        self.assertTrue(
            decision_is_satisfied_current(decision, live.digest, root=self.root)
        )
        report = {"candidate": {"candidate_digest": legacy.digest}}
        self.assertTrue(report_usable_for(report, live))
        ready, reason = evaluate_ready_for_review(
            self._task(legacy.digest),
            candidate_digest=live.digest,
            root=self.root,
        )
        self.assertTrue(ready, reason)

    def test_product_and_authority_edits_are_not_equivalent(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        migration = establish_projection_migration(self.root)
        self.assertTrue(migration["ok"])
        _write(self.root / "src" / "app.py", "value = 9\n")
        live = observe_candidate(self.root)
        self.assertFalse(
            digest_is_current(self.root, legacy.digest, live.digest)
        )
        self.assertFalse(
            decision_is_satisfied_current(
                self._decision(legacy.digest), live.digest, root=self.root
            )
        )

    def test_human_agents_edit_is_not_equivalent(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        self.assertTrue(establish_projection_migration(self.root)["ok"])
        _replace(self.root / "AGENTS.md", "human rule", "other human rule")
        live = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))

    def test_task_and_core_artifact_edits_are_not_equivalent(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        self.assertTrue(establish_projection_migration(self.root)["ok"])
        task_path = self.root / ".scaffold" / "tasks" / "task-alpha.yaml"
        task = yaml_lite.load(task_path.read_text(encoding="utf-8"))
        task["goal"] = "changed goal"
        _write(task_path, yaml_lite.dump(task))
        live = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))
        task["goal"] = "ship the sample"
        _write(task_path, yaml_lite.dump(task))
        project = yaml_lite.load(
            (self.root / ".scaffold" / "project.yaml").read_text(encoding="utf-8")
        )
        project["name"] = "changed"
        _write(self.root / ".scaffold" / "project.yaml", yaml_lite.dump(project))
        live = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))

    def test_forged_digest_pair_and_cross_candidate_reuse_are_rejected(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        live = observe_candidate(self.root)
        migration = establish_projection_migration(self.root)
        self.assertTrue(migration["ok"])
        forged = migration_dir(self.root) / ("ab" * 32 + ".yaml")
        _write(
            forged,
            yaml_lite.dump(
                {
                    "record_type": "candidate_projection_migration",
                    "source_generation": "1",
                    "target_generation": "2",
                    "source_digest": "c" * 64,
                    "target_digest": live.digest,
                }
            ),
        )
        self.assertFalse(digest_is_current(self.root, "c" * 64, live.digest))
        self.assertTrue(digest_is_current(self.root, legacy.digest, live.digest))

        other = Path(self._tmp.name) / "other"
        shutil.copytree(self.root, other)
        _write(other / "src" / "app.py", "value = other\n")
        other_live = observe_candidate(other)
        self.assertFalse(
            digest_is_current(other, legacy.digest, other_live.digest)
        )

    def test_public_projection_migration_is_resumable(self) -> None:
        code = distribution_cli(
            ["projection-migration", "--host", str(self.root)]
        )
        self.assertEqual(code, 0)
        code = distribution_cli(
            ["projection-migration", "--host", str(self.root)]
        )
        self.assertEqual(code, 0)

    def test_noscms_shares_projection_and_migration(self) -> None:
        host = Path(self._tmp.name) / "noscms"
        host.mkdir()
        _write(host / "src" / "app.py", "value = 1\n")
        _write(host / "AGENTS.md", AGENTS)
        _write(host / ".scaffold" / "install" / "run.py", "print('v1')\n")
        legacy = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
        current = observe_candidate(host)
        self.assertEqual(legacy.data.get("kind"), "none")
        self.assertNotEqual(legacy.digest, current.digest)
        migration = establish_projection_migration(host)
        self.assertTrue(migration["ok"], migration.get("blockers"))
        _write(host / ".scaffold" / "install" / "run.py", "print('v2')\n")
        _write(host / "AGENTS.md", AGENTS.replace("managed body", "refreshed"))
        live = observe_candidate(host)
        self.assertEqual(live.digest, current.digest)
        self.assertTrue(digest_is_current(host, legacy.digest, live.digest))
        _write(host / "src" / "app.py", "value = 2\n")
        changed = observe_candidate(host)
        self.assertFalse(digest_is_current(host, legacy.digest, changed.digest))

    def test_exact_gen1_is_current_without_a_migration_record(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        live = observe_candidate(self.root)
        self.assertNotEqual(legacy.digest, live.digest)
        self.assertFalse(migration_dir(self.root).exists())
        self.assertTrue(digest_is_current(self.root, legacy.digest, live.digest))
        self.assertTrue(
            decision_is_satisfied_current(
                self._decision(legacy.digest), live.digest, root=self.root
            )
        )
        ready, reason = evaluate_ready_for_review(
            self._task(legacy.digest),
            candidate_digest=live.digest,
            root=self.root,
        )
        self.assertTrue(ready, reason)
        _write(self.root / "src" / "app.py", "value = 9\n")
        changed = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, changed.digest))
        self.assertFalse(
            decision_is_satisfied_current(
                self._decision(legacy.digest), changed.digest, root=self.root
            )
        )

    def test_managed_region_edits_stay_current_and_human_edits_do_not(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        self.assertTrue(establish_projection_migration(self.root)["ok"])
        _replace(self.root / "AGENTS.md", "managed body", "managed body refreshed")
        live = observe_candidate(self.root)
        self.assertTrue(digest_is_current(self.root, legacy.digest, live.digest))
        _replace(self.root / ".gitattributes", ".scaffold/install/** -text", "*.bin binary")
        live = observe_candidate(self.root)
        self.assertTrue(digest_is_current(self.root, legacy.digest, live.digest))
        _replace(self.root / "AGENTS.md", "human rule", "other human rule")
        live = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))
        _replace(self.root / "AGENTS.md", "other human rule", "human rule")
        _replace(self.root / ".gitattributes", "*.txt text", "*.md text")
        live = observe_candidate(self.root)
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))

    def test_forged_mixed_bytes_are_rejected(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        migration = establish_projection_migration(self.root)
        self.assertTrue(migration["ok"])
        record_path = migration_dir(self.root) / f"{legacy.digest}.yaml"
        record = yaml_lite.load(record_path.read_text(encoding="utf-8"))
        self.assertIn("AGENTS.md", record["mixed_source_bytes"])
        self.assertIn(".gitattributes", record["mixed_source_bytes"])
        _replace(self.root / "AGENTS.md", "human rule", "hidden human rule")
        live = observe_candidate(self.root)
        forged = dict(record)
        forged["target_digest"] = live.digest
        forged["target_body_canonical"] = yaml_lite.dump(semantic_body(live.data))
        _write(record_path, yaml_lite.dump(forged))
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))
        record = yaml_lite.load(record_path.read_text(encoding="utf-8"))
        record["mixed_source_bytes"]["AGENTS.md"] = record["mixed_source_bytes"][
            "AGENTS.md"
        ][:-4] + "AAAA"
        _write(record_path, yaml_lite.dump(record))
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))

    def test_bytes_that_do_not_hash_to_the_source_row_are_rejected(self) -> None:
        legacy = observe_candidate(self.root, generation=PROJECTION_GENERATION_LEGACY)
        self.assertTrue(establish_projection_migration(self.root)["ok"])
        record_path = migration_dir(self.root) / f"{legacy.digest}.yaml"
        record = yaml_lite.load(record_path.read_text(encoding="utf-8"))
        _replace(self.root / "AGENTS.md", "human rule", "hidden human rule")
        live = observe_candidate(self.root)
        import base64

        raw = (self.root / "AGENTS.md").read_bytes()
        record["mixed_source_bytes"]["AGENTS.md"] = base64.b64encode(raw).decode("ascii")
        record["target_digest"] = live.digest
        record["target_body_canonical"] = yaml_lite.dump(semantic_body(live.data))
        _write(record_path, yaml_lite.dump(record))
        self.assertFalse(digest_is_current(self.root, legacy.digest, live.digest))

    def test_noscms_forged_mixed_record_is_rejected(self) -> None:
        host = Path(self._tmp.name) / "noscms-forge"
        host.mkdir()
        _write(host / "src" / "app.py", "value = 1\n")
        _write(host / "AGENTS.md", AGENTS)
        legacy = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
        migration = establish_projection_migration(host)
        self.assertTrue(migration["ok"], migration.get("blockers"))
        _replace(host / "AGENTS.md", "human rule", "forged human rule")
        live = observe_candidate(host)
        record_path = migration_dir(host) / f"{legacy.digest}.yaml"
        record = yaml_lite.load(record_path.read_text(encoding="utf-8"))
        record["target_digest"] = live.digest
        record["target_body_canonical"] = yaml_lite.dump(semantic_body(live.data))
        record["target_inventory_canonical"] = yaml_lite.dump(live.inventory)
        _write(record_path, yaml_lite.dump(record))
        self.assertFalse(digest_is_current(host, legacy.digest, live.digest))
        _replace(host / "AGENTS.md", "forged human rule", "human rule")
        _write(host / "src" / "app.py", "value = 3\n")
        changed = observe_candidate(host)
        self.assertFalse(digest_is_current(host, legacy.digest, changed.digest))

    def test_automatic_install_does_not_churn_migration_records(self) -> None:
        host = Path(self._tmp.name) / "installed"
        host.mkdir()
        _git(host, "init")
        _write(host / "README.md", "product\n")
        _git(host, "add", "README.md")
        _git(host, "commit", "-m", "product")
        plan, result = _apply(host, "install")
        self.assertEqual(result["outcome"], "COMPLETED", result.get("blockers"))
        self.assertFalse(migration_dir(host).exists())
        plan, again = _apply(host, "update")
        self.assertEqual(again["outcome"], "COMPLETED", again.get("blockers"))
        self.assertFalse(migration_dir(host).exists())
        task = host / ".scaffold" / "tasks" / "bound.yaml"
        _write(
            task,
            yaml_lite.dump(
                {
                    "record_type": "task_book",
                    "record_id": "bound",
                    "goal": "hold",
                    "task_completion_decision": {
                        "candidate_digest": "0" * 64,
                        "outcome": "SATISFIED",
                    },
                }
            ),
        )
        legacy = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
        book = yaml_lite.load(task.read_text(encoding="utf-8"))
        book["task_completion_decision"]["candidate_digest"] = legacy.digest
        _write(task, yaml_lite.dump(book))
        _plan, crossed = _apply(host, "update")
        self.assertEqual(crossed["outcome"], "COMPLETED", crossed.get("blockers"))
        records = list(migration_dir(host).glob("*.yaml"))
        self.assertEqual(len(records), 1)
        live = observe_candidate(host)
        self.assertTrue(digest_is_current(host, legacy.digest, live.digest))
        _plan, second = _apply(host, "update")
        self.assertEqual(second["outcome"], "COMPLETED", second.get("blockers"))
        self.assertEqual(list(migration_dir(host).glob("*.yaml")), records)
        self.assertTrue(
            decision_is_satisfied_current(
                {
                    "outcome": "SATISFIED",
                    "candidate_digest": legacy.digest,
                    "basis": [{"kind": "task_fact", "summary": "held"}],
                    "rationale": "held",
                },
                live.digest,
                root=host,
            )
        )


class PublishedBoundaryTests(unittest.TestCase):
    def test_distribution_update_from_published_base_keeps_legacy_authority(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "base"
        host = Path(tmp.name) / "host"
        base.mkdir()
        archive = Path(tmp.name) / "base.tar"
        subprocess.check_call(
            [
                "git",
                "archive",
                "--format=tar",
                "-o",
                str(archive),
                "79755b15466155b7fefacfaded3444669eb93450",
            ],
            cwd=REPO,
            stdout=subprocess.DEVNULL,
        )
        subprocess.check_call(["tar", "-xf", str(archive), "-C", str(base)])
        (base / "docs").mkdir(exist_ok=True)
        shutil.copy2(
            REPO / "docs" / "PUBLIC_LIFECYCLE_REFERENCE.md",
            base / "docs" / "PUBLIC_LIFECYCLE_REFERENCE.md",
        )
        host.mkdir()
        _git(host, "init")
        _write(host / "README.md", "product\n")
        _git(host, "add", "README.md")
        _git(host, "commit", "-m", "product")
        plan = plan_consumer_install(host, base, mode="install")
        self.assertTrue(plan.allowed, plan.blockers)
        installed = apply_consumer_install(plan)
        self.assertEqual(installed["outcome"], "COMPLETED", installed.get("blockers"))
        task_path = host / ".scaffold" / "tasks" / "bound.yaml"
        _write(
            task_path,
            yaml_lite.dump(
                {
                    "record_type": "task_book",
                    "record_id": "bound",
                    "goal": "hold",
                    "status": "READY_FOR_REVIEW",
                    "acceptance": "held",
                    "stages": [
                        {
                            "stage_id": "s1",
                            "status": "COMPLETE",
                            "required_tests": [],
                            "completion_decision": {
                                "outcome": "SATISFIED",
                                "candidate_digest": "0" * 64,
                                "stage_id": "s1",
                                "basis": [{"kind": "task_fact", "summary": "held"}],
                                "rationale": "held",
                            },
                        }
                    ],
                    "final_tests": [],
                    "task_completion_decision": {
                        "outcome": "SATISFIED",
                        "candidate_digest": "0" * 64,
                        "basis": [{"kind": "task_fact", "summary": "held"}],
                        "rationale": "held",
                    },
                }
            ),
        )
        legacy = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
        book = yaml_lite.load(task_path.read_text(encoding="utf-8"))
        book["stages"][0]["completion_decision"]["candidate_digest"] = legacy.digest
        book["task_completion_decision"]["candidate_digest"] = legacy.digest
        _write(task_path, yaml_lite.dump(book))
        code = distribution_cli(
            ["update", "--host", str(host), "--distribution", str(REPO)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(list(migration_dir(host).glob("*.yaml"))), 1)
        live = observe_candidate(host)
        self.assertEqual(live.data.get("projection_generation"), PROJECTION_GENERATION_CURRENT)
        report = {"candidate": {"candidate_digest": legacy.digest}}
        self.assertTrue(report_usable_for(report, live))
        self.assertTrue(
            decision_is_satisfied_current(
                {
                    "outcome": "SATISFIED",
                    "candidate_digest": legacy.digest,
                    "basis": [{"kind": "task_fact", "summary": "held"}],
                    "rationale": "held",
                },
                live.digest,
                root=host,
            )
        )
        ready, reason = evaluate_ready_for_review(
            yaml_lite.load(
                (host / ".scaffold" / "tasks" / "bound.yaml").read_text(encoding="utf-8")
            ),
            candidate_digest=live.digest,
            root=host,
        )
        self.assertTrue(ready, reason)
        before = list(migration_dir(host).glob("*.yaml"))
        code = distribution_cli(
            ["update", "--host", str(host), "--distribution", str(REPO)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(list(migration_dir(host).glob("*.yaml")), before)
        self.assertTrue(report_usable_for(report, observe_candidate(host)))


def _apply(host: Path, mode: str):
    plan = plan_consumer_install(host, REPO, mode=mode)
    if not plan.allowed:
        return plan, {"outcome": "BLOCKED", "blockers": list(plan.blockers)}
    return plan, apply_consumer_install(plan)


if __name__ == "__main__":
    unittest.main()

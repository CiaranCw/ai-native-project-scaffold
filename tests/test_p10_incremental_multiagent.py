from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from p7_support import TASK_A, TASK_B, develop_engine, write_task
from p10_support import (
    bound_migration_approval,
    install_abc_modules,
    install_dive_shape,
    persist_currentness_without_completion,
    persist_understanding,
    preview_migration,
    resume,
    snapshot_dirs,
    subprocess_resume,
)
from scaffold_p5.agents import GENERATED_AGENTS
from scaffold_p5.currentness import (
    evaluate_understanding_currentness,
    head_path,
    load_current_snapshot,
    observe_physical_understanding,
    snapshot_locator,
    snapshot_path,
)
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.knowledge_assessment import publish_knowledge_assessment
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.refresh_completion import (
    completions_covering,
    produce_refresh_completion,
    resolve_refresh_completion,
)
from scaffold_p5.understanding import persist_project_understanding
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.repair_state import persist_repair_state
from scaffold_p7.session import create_session
from support import adopt, distribution, live_understand_engine, write


CLIENT_TOKENS = ("cursor", "codebuddy", "claude", "codex", "chatgpt")
TASK_MALFORMED = "task-20260829T120200Z-ccc33333"
TASK_UNREADABLE = "task-20260829T120300Z-ddd44444"
ORPHAN_SESSION = "dev-20260829T120000Z-eeee9999"
FOREIGN_SNAPSHOT = "uc-19990101T000000Z-abcd1234"


class P10UnderstandCurrentnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        install_abc_modules(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_U01_fresh_project_requires_full_understand(self):
        result = resume(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.mutations, "none")
        self.assertEqual(result.extras["understanding"]["currentness"], "FULL_REFRESH_REQUIRED")
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertEqual(snapshot_dirs(self.host), [])

    def test_P10_U02_current_understanding_is_reused(self):
        first = persist_understanding(self.host)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        locator = first.extras["understanding"]["locator"]
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "CURRENT")
        self.assertEqual(result.extras["understanding"]["locator"], locator)
        repeated = persist_understanding(self.host)
        self.assertTrue(repeated.extras["understanding"].get("noop"))
        self.assertEqual(repeated.mutations, "none")
        self.assertEqual(len(snapshot_dirs(self.host)), 1)
        again = resume(self.host)
        self.assertEqual(again.extras["understanding"]["locator"], locator)
        self.assertEqual(again.extras["understanding"]["currentness"], "CURRENT")

    def test_P10_U03_bounded_module_change_is_partial(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-changed'\n")
        result = resume(self.host)
        self.assertEqual(result.extras["understanding"]["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(result.extras["understanding"]["affected_module_ids"], ["mod_b"])
        self.assertEqual(set(result.extras["understanding"]["reusable_module_ids"]), {"mod_a", "mod_c"})
        self.assertEqual(result.next_route, "understand.refresh")

    def test_P10_U04_structural_or_ambiguous_requires_full(self):
        persist_understanding(self.host)
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        modules["modules"].append(
            {
                "id": "mod_d",
                "path": "src/mod_d",
                "knowledge_entry": "docs/project/modules/src/mod_d.md",
                "kind": "source",
                "confidence": "VERIFIED",
            }
        )
        write_yaml_atomic(self.host / ".scaffold/modules.yaml", modules)
        added = resume(self.host)
        self.assertEqual(added.extras["understanding"]["currentness"], "FULL_REFRESH_REQUIRED")
        self.assertTrue(
            added.extras["understanding"]["structural_changed"]
            or added.extras["understanding"]["module_set_changed"]
        )
        install_abc_modules(self.host)
        persist_understanding(self.host)
        write(self.host, "src/orphan.py", "ORPHAN = 1\n")
        unmapped = resume(self.host)
        self.assertEqual(unmapped.extras["understanding"]["currentness"], "FULL_REFRESH_REQUIRED")
        self.assertTrue(unmapped.extras["understanding"]["unmapped_changed"])

    def test_P10_U05_stale_knowledge_assessment_cannot_establish_understanding(self):
        persist_understanding(self.host)
        published = publish_knowledge_assessment(
            self.host,
            mode="refresh",
            impacts=[
                {
                    "class": "MODULE_STRUCTURE",
                    "path": "src/mod_b/core.py",
                    "status": "modified",
                }
            ],
            outcomes=[
                {
                    "class": "MODULE_STRUCTURE",
                    "path": "src/mod_b/core.py",
                    "outcome": "SATISFIED",
                }
            ],
        )
        self.assertTrue(published.get("ok"), published)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-stale-ka'\n")
        result = resume(self.host)
        self.assertNotEqual(result.extras["understanding"]["currentness"], "CURRENT")
        self.assertFalse(result.extras["authority"]["knowledge_assessment"]["establishes_understanding"])
        currentness_root = self.host / ".scaffold/runtime/understand-currentness"
        if currentness_root.exists():
            for child in currentness_root.rglob("*"):
                if child.is_file():
                    child.unlink()
            for child in sorted(currentness_root.rglob("*"), reverse=True):
                if child.is_dir():
                    child.rmdir()
        missing = resume(self.host)
        self.assertEqual(missing.extras["understanding"]["currentness"], "FULL_REFRESH_REQUIRED")
        self.assertFalse(missing.extras["authority"]["knowledge_assessment"]["establishes_understanding"])
        self.assertTrue(
            (self.host / ".scaffold/runtime/understand-assessments").exists()
        )

    def test_P10_U06_incremental_request_cannot_reuse_when_full_required(self):
        persist_understanding(self.host)
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        modules["modules"] = [row for row in modules["modules"] if row.get("id") != "mod_c"]
        write_yaml_atomic(self.host / ".scaffold/modules.yaml", modules)
        result = live_understand_engine(self.host).run(
            "refresh",
            action="understand",
            incremental=True,
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertTrue(result.extras["understanding"].get("rejected_incremental"))
        self.assertEqual(result.mutations, "none")
        self.assertEqual(len(snapshot_dirs(self.host)), 1)
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "FULL_REFRESH_REQUIRED")

    def test_P10_U07_partial_refresh_persists_supersession_and_reuse(self):
        first = persist_understanding(self.host)
        first_id = first.extras["understanding"]["record_id"]
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-refreshed'\n")
        refreshed = persist_understanding(self.host, incremental=True)
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        payload = refreshed.extras["understanding"]
        self.assertEqual(payload["currentness"], "CURRENT")
        self.assertEqual(payload["refreshed_module_ids"], ["mod_b"])
        self.assertEqual(set(payload["reused_module_ids"]), {"mod_a", "mod_c"})
        self.assertEqual(payload["supersedes"], first_id)
        self.assertNotEqual(payload["record_id"], first_id)
        self.assertTrue(payload.get("physical_digest"))
        self.assertEqual(len(snapshot_dirs(self.host)), 2)
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_U08_fresh_process_reconstructs_the_same_currentness(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-process'\n")
        local = resume(self.host)
        remote = subprocess_resume(self.host)
        self.assertEqual(remote["currentness"], local.extras["understanding"]["currentness"])
        self.assertEqual(remote["physical_digest"], local.extras["understanding"]["physical_digest"])
        self.assertEqual(remote["affected_module_ids"], local.extras["understanding"]["affected_module_ids"])
        self.assertEqual(remote["next_route"], local.next_route)


class P10HandoffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        install_abc_modules(self.host)
        persist_understanding(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_H01_active_task_and_session_without_chat(self):
        write_task(self.host)
        create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name="host",
            candidate_digest=observe_candidate(self.host).digest,
        )
        result = resume(self.host)
        tasks = result.extras["work"]["tasks"]
        self.assertEqual(tasks[0]["record_id"], TASK_A)
        self.assertEqual(tasks[0]["status"], "IN_PROGRESS")
        self.assertEqual(tasks[0]["stages"][0]["stage_id"], "stage-1")
        self.assertEqual(result.extras["work"]["sessions"][0]["status"], "OPEN")
        self.assertEqual(result.next_route, "develop.continue")
        self.assertTrue(result.extras["authority"]["candidate_digest"])

    def test_P10_H02_required_test_fail_routes_repair(self):
        write_task(self.host)
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "blockers": ["required verification failed"],
                "fail_ids": ["movement/smoke"],
                "reason": "required Test FAIL",
            },
        )
        result = resume(self.host)
        self.assertEqual(result.next_route, "develop.repair")
        repair = result.extras["work"]["repair"][0]
        self.assertEqual(repair["task_id"], TASK_A)
        self.assertEqual(repair["fail_ids"], ["movement/smoke"])
        self.assertTrue(result.extras["test"]["required_failures"])

    def test_P10_H03_ready_task_routes_submit(self):
        write_task(self.host, status="READY_FOR_REVIEW")
        result = resume(self.host)
        self.assertEqual(result.next_route, "submit")
        self.assertEqual(result.extras["submit"]["ready_task_ids"], [TASK_A])

    def test_P10_H04_repair_surfaces_exact_target_and_blocker(self):
        write_task(self.host)
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "blockers": ["exact current blocker"],
                "reason": "mapped repair target",
            },
        )
        result = resume(self.host)
        repair = result.extras["work"]["repair"][0]
        self.assertEqual(repair["target_stage_ids"], ["stage-1"])
        self.assertEqual(repair["blockers"], ["exact current blocker"])
        self.assertEqual(result.next_route, "develop.repair")

    def test_P10_H05_migration_recovery_outranks_ordinary_work(self):
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        write_task(self.host, TASK_B, status="READY_FOR_REVIEW")
        preview = preview_migration(self.host, task_id=TASK_A)
        plan = preview.extras["migration"]["migration_plan"]
        interrupted = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            execute_approved_migration=True,
            distribution=distribution("2.1.0"),
            migration_approval=bound_migration_approval(self.host, plan),
            interrupt_after_migration="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED", interrupted.blockers)
        result = resume(self.host)
        self.assertEqual(result.next_route, "migration.recovery")
        self.assertNotEqual(result.next_route, "develop.continue")
        self.assertNotEqual(result.next_route, "submit")
        executions = result.extras["work"]["migration"]["executions"]
        self.assertTrue(executions)
        self.assertEqual(executions[0]["status"], "RECOVERY_REQUIRED")

    def test_P10_H06_multiple_active_tasks_are_ambiguous(self):
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        write_task(self.host, TASK_B, status="IN_PROGRESS")
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertEqual(set(result.extras["ambiguous_task_ids"]), {TASK_A, TASK_B})
        selected = resume(self.host, task_id=TASK_A)
        self.assertNotEqual(selected.next_route, "human")

    def test_P10_H07_stale_handoff_summary_is_not_trusted(self):
        write_task(self.host)
        create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name="host",
            candidate_digest=observe_candidate(self.host).digest,
        )
        path = self.host / ".scaffold/runtime/understand-currentness/handoff.yaml"
        write_yaml_atomic(
            path,
            {
                "record_type": "understand_handoff_summary",
                "schema_version": "1",
                "supporting": True,
                "canonical": False,
                "authoritative": False,
                "snapshot_locator": "understand-currentness/uc-19990101T000000Z-deadbeef/snapshot.yaml",
                "snapshot_digest": "0" * 64,
                "physical_digest": "1" * 64,
                "next_route": "submit",
            },
        )
        result = resume(self.host)
        self.assertFalse(result.extras["authority"]["handoff_summary"]["trusted"])
        self.assertEqual(result.next_route, "develop.continue")
        self.assertNotEqual(result.next_route, "submit")

    def test_P10_H08_client_neutral_entry_has_no_client_semantics(self):
        result = resume(self.host)
        payload = json.dumps(result.extras.get("authority"), sort_keys=True).lower()
        for token in CLIENT_TOKENS:
            self.assertNotIn(f'"{token}"', payload)
        agents = GENERATED_AGENTS.lower()
        for token in ("cursor", "claude", "codex", "codebuddy", "chatgpt"):
            self.assertNotIn(token, agents)
        self.assertIn("action=resume", GENERATED_AGENTS)


class P10FreshAgentE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_fresh_agent_bounded_refresh_and_reconstruction(self):
        adopt(self.host)
        install_abc_modules(self.host)
        agent_a = persist_understanding(self.host)
        self.assertEqual(agent_a.outcome, "COMPLETED", agent_a.blockers)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-e2e'\n")
        agent_b = subprocess_resume(self.host)
        self.assertEqual(agent_b["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(agent_b["affected_module_ids"], ["mod_b"])
        self.assertEqual(set(agent_b["reusable_module_ids"]), {"mod_a", "mod_c"})
        refreshed = persist_understanding(self.host, incremental=True)
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        self.assertEqual(refreshed.extras["understanding"]["refreshed_module_ids"], ["mod_b"])
        self.assertEqual(
            set(refreshed.extras["understanding"]["reused_module_ids"]),
            {"mod_a", "mod_c"},
        )
        agent_c = subprocess_resume(self.host)
        self.assertEqual(agent_c["currentness"], "CURRENT")
        self.assertEqual(
            agent_c["physical_digest"],
            refreshed.extras["understanding"]["physical_digest"],
        )
        self.assertEqual(agent_c["locator"], refreshed.extras["understanding"]["locator"])

    def test_P10_dive_prepilot_zero_context_incremental(self):
        write(self.host, "README.md", "# Ordinary app\n")
        adopt(self.host)
        install_dive_shape(self.host)
        persist_understanding(self.host)
        write(self.host, "src/ui/hud.py", "def draw():\n    return 'hud-v2'\n")
        before = resume(self.host)
        self.assertEqual(before.extras["understanding"]["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(before.extras["understanding"]["affected_module_ids"], ["ui"])
        persist_understanding(self.host, incremental=True)
        after = subprocess_resume(self.host)
        self.assertEqual(after["currentness"], "CURRENT")
        self.assertIn(
            after["next_route"],
            {"none", "understand.refresh", "develop.continue", "human"},
        )

    def test_P10_replay_and_cas(self):
        adopt(self.host)
        install_abc_modules(self.host)
        first = persist_understanding(self.host)
        second = persist_understanding(self.host)
        self.assertTrue(second.extras["understanding"].get("noop"))
        self.assertEqual(len(snapshot_dirs(self.host)), 1)
        stale = live_understand_engine(self.host).run(
            "refresh",
            action="understand",
            expected_head_digest="ab" * 32,
        )
        self.assertEqual(stale.outcome, "BLOCKED")
        self.assertTrue(
            any("CAS" in item for item in stale.blockers),
            stale.blockers,
        )
        self.assertEqual(
            first.extras["understanding"]["locator"],
            second.extras["understanding"]["locator"],
        )


class P10DefaultRefreshRegressionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_default_refresh_does_not_persist_understanding(self):
        result = live_understand_engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(snapshot_dirs(self.host), [])
        self.assertEqual(result.next_route, "continue")


def _write_malformed_task(host: Path, task_id: str = TASK_MALFORMED) -> None:
    write_yaml_atomic(
        host / ".scaffold/tasks" / f"{task_id}.yaml",
        {
            "record_type": "task_book",
            "schema_version": "1",
            "record_id": task_id,
        },
    )


def _write_unreadable_task(host: Path, task_id: str = TASK_UNREADABLE) -> None:
    path = host / ".scaffold/tasks" / f"{task_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not: yaml: [", encoding="utf-8")


def _write_malformed_task_filename(host: Path) -> None:
    path = host / ".scaffold/tasks" / "broken-task.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("record_type: task_book\n", encoding="utf-8")


def _write_malformed_session(host: Path, session_id: str = ORPHAN_SESSION) -> None:
    directory = host / SESSIONS_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        directory / "session.yaml",
        {
            "record_type": "develop_session",
            "schema_version": "1",
            "record_id": session_id,
        },
    )


def _write_orphaned_session(host: Path, session_id: str = ORPHAN_SESSION) -> None:
    directory = host / SESSIONS_DIR / session_id
    directory.mkdir(parents=True, exist_ok=True)


class P10RefreshCompletionAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        install_abc_modules(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_X01_observation_cannot_self_certify_refresh(self):
        first = persist_understanding(self.host)
        self.assertEqual(first.outcome, "COMPLETED", first.blockers)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x01'\n")
        observed = resume(self.host)
        self.assertEqual(observed.extras["understanding"]["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(observed.extras["understanding"]["affected_module_ids"], ["mod_b"])
        published = persist_currentness_without_completion(self.host, incremental=True)
        self.assertFalse(published.get("ok"), published)
        self.assertNotEqual(published.get("currentness"), "CURRENT")
        self.assertEqual(len(snapshot_dirs(self.host)), 1)
        self.assertEqual(
            resume(self.host).extras["understanding"]["currentness"],
            "PARTIAL_REFRESH_REQUIRED",
        )
        self.assertEqual(
            resume(self.host).extras["understanding"]["locator"],
            first.extras["understanding"]["locator"],
        )

    def test_P10_X02_valid_completion_publishes_bounded_refresh(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x02'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        published = persist_project_understanding(self.host, incremental=True)
        self.assertTrue(published.get("ok"), published)
        self.assertEqual(published.get("currentness"), "CURRENT")
        self.assertEqual(published.get("refreshed_module_ids"), ["mod_b"])
        self.assertEqual(set(published.get("reused_module_ids") or []), {"mod_a", "mod_c"})
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_X03_stale_completion_cannot_current_after_source_changes(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x03-a'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x03-b'\n")
        published = persist_project_understanding(self.host, incremental=True)
        self.assertFalse(published.get("ok"), published)
        self.assertNotEqual(published.get("currentness"), "CURRENT")
        self.assertEqual(
            resume(self.host).extras["understanding"]["currentness"],
            "PARTIAL_REFRESH_REQUIRED",
        )
        self.assertEqual(len(snapshot_dirs(self.host)), 1)

    def test_P10_X04_wrong_source_digest_is_blocked(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x04'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        locator = produced["locator"]
        path = self.host / ".scaffold/runtime" / locator
        completion = read_yaml(path)
        for row in completion.get("modules") or []:
            if row.get("id") == "mod_b":
                row["source_digest"] = "ab" * 32
        write_yaml_atomic(path, completion)
        published = persist_project_understanding(self.host, incremental=True)
        self.assertFalse(published.get("ok"), published)
        self.assertTrue(
            any("source digest" in item or "missing or stale" in item for item in published.get("blockers") or []),
            published.get("blockers"),
        )
        self.assertNotEqual(
            resume(self.host).extras["understanding"]["currentness"],
            "CURRENT",
        )

    def test_P10_X05_partial_completion_leaves_uncovered_module_required(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x05'\n")
        write(self.host, "src/mod_c/core.py", "VALUE = 'C-x05'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        published = persist_project_understanding(self.host, incremental=True)
        self.assertTrue(published.get("ok"), published)
        self.assertNotEqual(published.get("currentness"), "CURRENT")
        self.assertEqual(published.get("refreshed_module_ids"), ["mod_b"])
        self.assertIn("mod_c", published.get("uncovered_module_ids") or [])
        later = resume(self.host)
        self.assertEqual(later.extras["understanding"]["currentness"], "PARTIAL_REFRESH_REQUIRED")
        self.assertEqual(later.extras["understanding"]["affected_module_ids"], ["mod_c"])

    def test_P10_X06_partial_receipt_cannot_satisfy_full_refresh(self):
        persist_understanding(self.host)
        modules = read_yaml(self.host / ".scaffold/modules.yaml")
        modules["modules"].append(
            {
                "id": "mod_d",
                "path": "src/mod_d",
                "knowledge_entry": "docs/project/modules/src/mod_d.md",
                "kind": "source",
                "confidence": "VERIFIED",
            }
        )
        write_yaml_atomic(self.host / ".scaffold/modules.yaml", modules)
        write(self.host, "src/mod_d/core.py", "VALUE = 'D'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        published = persist_project_understanding(self.host, incremental=False)
        self.assertFalse(published.get("ok"), published)
        self.assertTrue(published.get("uncovered_module_ids"))
        incremental = persist_project_understanding(self.host, incremental=True)
        self.assertTrue(incremental.get("rejected_incremental"))
        self.assertEqual(
            resume(self.host).extras["understanding"]["currentness"],
            "FULL_REFRESH_REQUIRED",
        )
        self.assertEqual(len(snapshot_dirs(self.host)), 1)

    def test_P10_X07_bindings_survive_fresh_process(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-x07'\n")
        refreshed = persist_understanding(self.host, incremental=True)
        self.assertEqual(refreshed.outcome, "COMPLETED", refreshed.blockers)
        payload = refreshed.extras["understanding"]
        locators = list(payload.get("completion_locators") or [])
        self.assertTrue(locators, payload)
        observed = evaluate_understanding_currentness(self.host)
        current_b = next(
            item for item in (observed.get("observed") or {}).get("modules") or []
            if item.get("id") == "mod_b"
        )
        coverage = completions_covering(
            self.host,
            observed=observed.get("observed") or {},
            locators=locators,
        )
        bound_b = (coverage.get("covered") or {}).get("mod_b")
        self.assertIsNotNone(bound_b)
        self.assertEqual(bound_b.get("source_digest"), current_b.get("digest"))
        knowledge_path = self.host / str(current_b.get("knowledge_entry") or "")
        self.assertTrue(knowledge_path.is_file(), current_b)
        self.assertEqual(bound_b.get("knowledge_digest"), file_digest(knowledge_path))
        remote = subprocess_resume(self.host)
        self.assertEqual(remote["currentness"], "CURRENT")
        self.assertEqual(remote["locator"], payload["locator"])
        self.assertEqual(remote["completion_locators"], locators)

    def test_P10_X08_current_publication_is_idempotent(self):
        first = persist_understanding(self.host)
        second = persist_understanding(self.host)
        self.assertTrue(second.extras["understanding"].get("noop"))
        self.assertEqual(second.mutations, "none")
        self.assertEqual(len(snapshot_dirs(self.host)), 1)
        self.assertEqual(
            first.extras["understanding"]["locator"],
            second.extras["understanding"]["locator"],
        )


class P10FailClosedWorkAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        install_abc_modules(self.host)
        persist_understanding(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_Y01_malformed_task_does_not_route_submit(self):
        write_task(self.host, status="READY_FOR_REVIEW")
        _write_malformed_task(self.host)
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "submit")
        self.assertTrue(result.extras["work"]["task_blockers"])

    def test_P10_Y02_malformed_task_does_not_continue_in_progress(self):
        write_task(self.host, status="IN_PROGRESS")
        _write_malformed_task(self.host)
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "develop.continue")

    def test_P10_Y03_malformed_filename_and_unreadable_task_fail_closed(self):
        write_task(self.host, status="READY_FOR_REVIEW")
        _write_malformed_task_filename(self.host)
        named = resume(self.host)
        self.assertEqual(named.next_route, "human")
        self.assertTrue(named.extras["work"]["task_blockers"])
        _write_unreadable_task(self.host)
        unread = resume(self.host)
        self.assertEqual(unread.next_route, "human")
        self.assertNotEqual(unread.next_route, "submit")

    def test_P10_Y04_malformed_session_does_not_continue(self):
        write_task(self.host)
        created = create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name="host",
            candidate_digest=observe_candidate(self.host).digest,
        )
        session_id = created.session["record_id"]
        write_yaml_atomic(
            self.host / SESSIONS_DIR / session_id / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
            },
        )
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "develop.continue")
        self.assertTrue(result.extras["work"]["session_blockers"])

    def test_P10_Y05_orphaned_session_fails_closed(self):
        write_task(self.host)
        _write_orphaned_session(self.host)
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "develop.continue")
        self.assertTrue(
            any("orphan" in item.lower() or "missing session.yaml" in item for item in result.extras["work"]["session_blockers"])
        )

    def test_P10_Y06_malformed_session_does_not_submit_from_ready_task(self):
        write_task(self.host, status="READY_FOR_REVIEW")
        _write_malformed_session(self.host)
        result = resume(self.host)
        self.assertEqual(result.next_route, "human")
        self.assertNotEqual(result.next_route, "submit")
        self.assertTrue(result.extras["work"]["session_blockers"])

    def test_P10_Y07_valid_task_session_routes_are_unchanged(self):
        write_task(self.host)
        create_session(
            self.host,
            task_id=TASK_A,
            mode="normal_task",
            project_name="host",
            candidate_digest=observe_candidate(self.host).digest,
        )
        continue_result = resume(self.host)
        self.assertEqual(continue_result.next_route, "develop.continue")
        write_task(self.host, status="READY_FOR_REVIEW")
        submit_result = resume(self.host)
        self.assertEqual(submit_result.next_route, "submit")
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        write_task(self.host, TASK_B, status="IN_PROGRESS")
        ambiguous = resume(self.host)
        self.assertEqual(ambiguous.next_route, "human")
        self.assertEqual(set(ambiguous.extras["ambiguous_task_ids"]), {TASK_A, TASK_B})

    def test_P10_Y08_fresh_process_reproduces_fail_closed_route(self):
        write_task(self.host, status="READY_FOR_REVIEW")
        _write_malformed_task(self.host)
        local = resume(self.host)
        remote = subprocess_resume(self.host)
        self.assertEqual(local.next_route, "human")
        self.assertEqual(remote["next_route"], "human")
        self.assertTrue(local.extras["work"]["task_blockers"])
        self.assertTrue(remote["task_blockers"])


class P10CurrentHeadIntegrityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)
        install_abc_modules(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_current_head_locator_cannot_alias_a_different_record(self):
        persist_understanding(self.host)
        loaded = load_current_snapshot(self.host)
        self.assertTrue(loaded.get("ok"), loaded)
        other_locator = snapshot_locator(FOREIGN_SNAPSHOT)
        dest = snapshot_path(self.host, other_locator)
        self.assertIsNotNone(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot_path(self.host, loaded["locator"]), dest)
        head = dict(loaded["head"])
        head["record_id"] = FOREIGN_SNAPSHOT
        head["locator"] = other_locator
        head["snapshot_digest"] = file_digest(dest)
        write_yaml_atomic(head_path(self.host), head)
        again = load_current_snapshot(self.host)
        self.assertFalse(again.get("ok"))
        self.assertEqual(again.get("reason"), "identity_mismatch")
        evaluation = evaluate_understanding_currentness(self.host)
        self.assertEqual(evaluation.get("currentness"), "UNKNOWN")

    def test_P10_concurrent_persist_leaves_one_current_head(self):
        persist_understanding(self.host)
        write(self.host, "src/mod_b/core.py", "VALUE = 'B-cas'\n")
        produced = produce_refresh_completion(self.host, module_ids=["mod_b"])
        self.assertTrue(produced.get("ok"), produced)
        results: list[dict] = []

        def worker():
            results.append(persist_project_understanding(self.host, incremental=True))

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 2)
        self.assertTrue(all(row.get("ok") for row in results), results)
        mutated = [row for row in results if row.get("mutations")]
        noops = [row for row in results if row.get("noop")]
        self.assertEqual(len(mutated), 1, results)
        self.assertEqual(len(noops), 1, results)
        self.assertEqual(len(snapshot_dirs(self.host)), 2)
        loaded = load_current_snapshot(self.host)
        self.assertTrue(loaded.get("ok"), loaded)
        self.assertEqual(
            evaluate_understanding_currentness(self.host).get("currentness"),
            "CURRENT",
        )


KNOWLEDGE_A = "docs/project/modules/src/mod_a.md"
KNOWLEDGE_B = "docs/project/modules/src/mod_b.md"
KNOWLEDGE_C = "docs/project/modules/src/mod_c.md"
MODULE_KNOWLEDGE_REGION = "module-knowledge"


def _project(host: Path) -> dict:
    return read_yaml(host / ".scaffold/project.yaml")


def _patch_ownership(host: Path, updates: dict | None = None, *, drop: tuple[str, ...] = ()) -> dict:
    project = _project(host)
    ownership = dict(project.get("ownership") or {})
    for key in drop:
        ownership.pop(key, None)
    if updates:
        ownership.update(updates)
    project["ownership"] = ownership
    write_yaml_atomic(host / ".scaffold/project.yaml", project)
    return ownership


def _drop_module_knowledge_ownership(host: Path) -> None:
    _patch_ownership(host, drop=(KNOWLEDGE_A, KNOWLEDGE_B, KNOWLEDGE_C))


class P10RefreshCompletionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        adopt(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def test_P10_Z01_existing_unknown_knowledge_is_not_mutated(self):
        install_abc_modules(self.host, register_knowledge=False)
        write(self.host, KNOWLEDGE_B, "UNKNOWN EXISTING\n")
        before = (self.host / KNOWLEDGE_B).read_bytes()
        resolved = resolve_ownership(_project(self.host).get("ownership") or {}, KNOWLEDGE_B)
        self.assertEqual(resolved.status, "UNKNOWN")
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        self.assertNotEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")
        self.assertEqual(snapshot_dirs(self.host), [])

    def test_P10_Z02_absent_unknown_registers_generated_before_binding(self):
        install_abc_modules(self.host, register_knowledge=False)
        before = observe_physical_understanding(self.host)
        self.assertFalse((self.host / KNOWLEDGE_B).exists())
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        ownership = _project(self.host).get("ownership") or {}
        self.assertEqual(ownership.get(KNOWLEDGE_B), "GENERATED")
        self.assertEqual(resolve_ownership(ownership, KNOWLEDGE_B).mode, "GENERATED")
        self.assertTrue((self.host / KNOWLEDGE_B).is_file())
        after = observe_physical_understanding(self.host)
        bound = result.extras["understanding"]
        locators = list(bound.get("completion_locators") or [])
        self.assertTrue(locators, bound)
        loaded = resolve_refresh_completion(self.host, locators[0])
        self.assertTrue(loaded.get("ok"), loaded)
        structural = (loaded.get("completion") or {}).get("structural_digest")
        self.assertNotEqual(structural, before.get("structural_digest"))
        self.assertEqual(structural, after.get("structural_digest"))
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z03_exact_human_owned_knowledge_is_preserved(self):
        install_abc_modules(self.host)
        write(self.host, KNOWLEDGE_B, "HUMAN CONTENT\n")
        _patch_ownership(self.host, {KNOWLEDGE_B: "HUMAN_OWNED"})
        before = (self.host / KNOWLEDGE_B).read_bytes()
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        self.assertNotIn("scaffold:understand-refresh-binding", before.decode("utf-8"))
        self.assertNotIn(
            "scaffold:understand-refresh-binding",
            (self.host / KNOWLEDGE_B).read_text(encoding="utf-8"),
        )
        self.assertNotEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z04_area_human_owned_nested_knowledge_is_preserved(self):
        install_abc_modules(self.host)
        write(self.host, KNOWLEDGE_A, "HUMAN A\n")
        write(self.host, KNOWLEDGE_B, "HUMAN B\n")
        write(self.host, KNOWLEDGE_C, "HUMAN C\n")
        _drop_module_knowledge_ownership(self.host)
        _patch_ownership(self.host, {"docs/project/modules/": "HUMAN_OWNED"})
        resolved = resolve_ownership(_project(self.host).get("ownership") or {}, KNOWLEDGE_B)
        self.assertEqual(resolved.mode, "HUMAN_OWNED")
        before = (self.host / KNOWLEDGE_B).read_bytes()
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        self.assertEqual((self.host / KNOWLEDGE_A).read_text(encoding="utf-8"), "HUMAN A\n")
        self.assertNotEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z05_managed_without_region_is_not_whole_file_overwritten(self):
        install_abc_modules(self.host)
        write(self.host, KNOWLEDGE_B, "MANAGED HUMAN PREFIX\nbody\n")
        _patch_ownership(self.host, {KNOWLEDGE_B: "MANAGED"})
        before = (self.host / KNOWLEDGE_B).read_bytes()
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result.blockers)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        self.assertNotEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z06_managed_region_preserves_human_prefix_and_suffix(self):
        install_abc_modules(self.host)
        prefix = "HUMAN PREFIX KEEP\n"
        suffix = "HUMAN SUFFIX KEEP\n"
        write(
            self.host,
            KNOWLEDGE_B,
            prefix
            + f"<!-- scaffold:managed:{MODULE_KNOWLEDGE_REGION}:start -->\n"
            + "old inner\n"
            + f"<!-- scaffold:managed:{MODULE_KNOWLEDGE_REGION}:end -->\n"
            + suffix,
        )
        project = _project(self.host)
        ownership = dict(project.get("ownership") or {})
        ownership[KNOWLEDGE_B] = "MANAGED"
        project["ownership"] = ownership
        regions = dict(project.get("managed_regions") or {})
        regions[KNOWLEDGE_B] = [MODULE_KNOWLEDGE_REGION]
        project["managed_regions"] = regions
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        text = (self.host / KNOWLEDGE_B).read_text(encoding="utf-8")
        self.assertTrue(text.startswith(prefix), text)
        self.assertTrue(text.endswith(suffix), text)
        self.assertNotIn("old inner", text)
        self.assertIn("scaffold:understand-refresh-binding", text)
        self.assertEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z07_exact_generated_may_publish_current(self):
        install_abc_modules(self.host)
        resolved = resolve_ownership(_project(self.host).get("ownership") or {}, KNOWLEDGE_B)
        self.assertEqual(resolved.mode, "GENERATED")
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["understanding"]["currentness"], "CURRENT")
        self.assertTrue((self.host / KNOWLEDGE_B).is_file())

    def test_P10_Z08_area_generated_may_publish_current(self):
        install_abc_modules(self.host)
        _drop_module_knowledge_ownership(self.host)
        _patch_ownership(self.host, {"docs/project/modules/": "GENERATED"})
        resolved = resolve_ownership(_project(self.host).get("ownership") or {}, KNOWLEDGE_B)
        self.assertEqual(resolved.mode, "GENERATED")
        self.assertEqual(resolved.reason, "area ownership")
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["understanding"]["currentness"], "CURRENT")
        ownership = _project(self.host).get("ownership") or {}
        self.assertNotEqual(ownership.get(KNOWLEDGE_B), "GENERATED")
        self.assertEqual(ownership.get("docs/project/modules/"), "GENERATED")

    def test_P10_Z09_conflicting_ownership_fails_closed(self):
        install_abc_modules(self.host)
        write(self.host, KNOWLEDGE_B, "LEAVE ME\n")
        before = (self.host / KNOWLEDGE_B).read_bytes()
        _patch_ownership(
            self.host,
            {
                KNOWLEDGE_B: "GENERATED",
                "./docs/project/modules/src/mod_b.md": "HUMAN_OWNED",
            },
        )
        resolved = resolve_ownership(_project(self.host).get("ownership") or {}, KNOWLEDGE_B)
        self.assertEqual(resolved.status, "CONFLICTING")
        produced = produce_refresh_completion(self.host)
        self.assertFalse(produced.get("ok"), produced)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        result = persist_understanding(self.host)
        self.assertNotEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual((self.host / KNOWLEDGE_B).read_bytes(), before)
        self.assertNotEqual(resume(self.host).extras["understanding"]["currentness"], "CURRENT")

    def test_P10_Z10_registration_binds_post_mutation_structural_digest(self):
        install_abc_modules(self.host, register_knowledge=False)
        before = observe_physical_understanding(self.host)
        result = persist_understanding(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        after = observe_physical_understanding(self.host)
        self.assertNotEqual(after.get("structural_digest"), before.get("structural_digest"))
        locators = list(result.extras["understanding"].get("completion_locators") or [])
        self.assertTrue(locators)
        loaded = resolve_refresh_completion(self.host, locators[0])
        self.assertEqual(
            (loaded.get("completion") or {}).get("structural_digest"),
            after.get("structural_digest"),
        )
        self.assertNotEqual(
            (loaded.get("completion") or {}).get("structural_digest"),
            before.get("structural_digest"),
        )
        snapshot = load_current_snapshot(self.host).get("snapshot") or {}
        self.assertEqual(snapshot.get("structural_digest"), after.get("structural_digest"))


if __name__ == "__main__":
    unittest.main()

"""Focused Develop autonomy / lightweight implementation tests.

Does not run the full suite. Covers physical reconciliation, non-fail-closed
observation, HUMAN_OWNED Task edits, and hot-path cost structure.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from p6_support import CORE_OWNERSHIP, init_git
from p7_support import (
    TASK_A,
    develop_engine,
    ensure_noscms_accepted_anchor,
    write_active_host,
    write_task,
)
from support import write

from scaffold_p5.first_use import (
    GATE_DEVELOP,
    GATE_RECOVERY,
    HOOK_EVENTS,
    OBSERVATION_HOOK_EVENTS,
    canonical_hook_fragment,
    evaluate_cursor_hook,
    expected_hook_fragment_digest,
    first_use_decision,
    hook_main,
    inspect_scaffold_hook_fragment,
    legacy_canonical_hook_fragment,
    legacy_hook_fragment_digest,
    merge_scaffold_hooks,
    scaffold_hook_entry,
)
from scaffold_p5.io_util import read_yaml, sha256_bytes, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.evidence import supporting_evidence_locator_issues
from scaffold_p7.develop_authority import (
    authorize_mutation_paths,
    reconcile_session_changes,
    resolve_current_develop_authority,
)
from scaffold_p7.lifecycle import evaluate_ready_for_review
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.mutation import authorize_path_mutation, hard_mutation_boundary_reason
from scaffold_p7.session import (
    MUTATION_OBSERVED,
    MUTATION_PENDING,
    MUTATION_RECONCILED,
    load_files_yaml,
    load_open_inventory,
)
from scaffold_p8.delta import classify_delta, load_sealed_sessions, observe_real_diff
from scaffold_p8.structural import review_structure


APP = "src/app.py"
TEST_PATH = "tests/test_app.py"
DOC_PATH = "docs/notes.md"
CONFIG_PATH = "pyproject.toml"
DISCOVERED = "lib/helper.py"
MANAGED_PATH = "config/app.yaml"
GENERATED_PATH = "src/generated.py"


def _ownership() -> dict:
    return {
        **CORE_OWNERSHIP,
        "src/": "HUMAN_OWNED",
        "tests/": "HUMAN_OWNED",
        "docs/": "HUMAN_OWNED",
        "pyproject.toml": "HUMAN_OWNED",
        "config/": "MANAGED",
        "src/generated.py": "GENERATED",
        "lib/": "HUMAN_OWNED",
    }


def _task_scope() -> dict:
    return {
        "paths": ["src/app.py"],
        "modules": [],
        "exclude": [],
        "supporting_paths": ["tests/"],
    }


class DevelopAutonomyLightweightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership=_ownership(),
            source_areas=["src"],
        )
        write(self.host, APP, "value = 0\n")
        write(self.host, TEST_PATH, "assert True\n")
        write(self.host, DOC_PATH, "notes\n")
        write(self.host, CONFIG_PATH, "[project]\nname = 'x'\n")
        write(self.host, MANAGED_PATH, "managed: 1\n")
        write(self.host, GENERATED_PATH, "generated = 1\n")
        write(self.host, DISCOVERED, "helper = 0\n")
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=_task_scope(),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Implement the fixture.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        ensure_noscms_accepted_anchor(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _open(self) -> str:
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = str((opened.extras or {}).get("session", {}).get("record_id") or "")
        self.assertTrue(session_id)
        return session_id

    def _session_dir(self, session_id: str) -> Path:
        return self.host / SESSIONS_DIR / session_id

    def _task(self) -> dict:
        return read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")

    def _reconcile(self, session_id: str):
        directory = self._session_dir(session_id)
        session = read_yaml(directory / "session.yaml")
        return reconcile_session_changes(
            self.host, directory, task=self._task(), session=session
        )

    def test_01_multi_file_edit_survives_without_serialization(self):
        self._open()
        payload = {
            "hook_event_name": "preToolUse",
            "tool_name": "MultiEdit",
            "tool_input": {
                "edits": [
                    {"path": APP, "new_string": "value = 1\n"},
                    {"path": TEST_PATH, "new_string": "assert False\n"},
                ]
            },
        }
        result = evaluate_cursor_hook(payload, self.host)
        self.assertEqual(result["permission"], "allow", result)
        allowed, reason = authorize_mutation_paths(self.host, [APP, TEST_PATH])
        self.assertTrue(allowed, reason)

    def test_02_observation_failure_does_not_revert_source(self):
        self._open()
        write(self.host, APP, "value = kept\n")
        stdin = io.StringIO(
            '{"hook_event_name": "afterFileEdit", "tool_name": "Write"'
        )
        stdout = io.StringIO()
        code = hook_main(stdin=stdin, stdout=stdout)
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["permission"], "allow")
        self.assertEqual((self.host / APP).read_text(encoding="utf-8"), "value = kept\n")

    def test_03_observation_events_are_not_fail_closed(self):
        for event in OBSERVATION_HOOK_EVENTS:
            entry = scaffold_hook_entry(event)
            self.assertFalse(entry["failClosed"], event)
        for event in HOOK_EVENTS:
            if event in OBSERVATION_HOOK_EVENTS:
                continue
            self.assertTrue(scaffold_hook_entry(event)["failClosed"], event)
        fragment = canonical_hook_fragment()
        for event in OBSERVATION_HOOK_EVENTS:
            self.assertFalse(fragment["events"][event][0]["failClosed"], event)

    def test_04_hookless_ordinary_develop_reconciles_and_seals(self):
        session_id = self._open()
        write(self.host, APP, "value = 2\n")
        directory = self._session_dir(session_id)
        result = reconcile_session_changes(
            self.host, directory, task=self._task()
        )
        self.assertTrue(result.ok, result.blockers)
        self.assertIn(APP, result.in_scope)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        self.assertFalse((directory / "mutation-attempts.yaml").is_file())

    def test_05_unknown_editor_tool_does_not_block(self):
        self._open()
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "FutureCursorEdit",
                "tool_input": {"path": APP, "contents": "value = 3\n"},
            },
            self.host,
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_06_no_mutation_attempt_durable_record_required(self):
        session_id = self._open()
        write(self.host, APP, "value = 4\n")
        directory = self._session_dir(session_id)
        self.assertFalse((directory / "mutation-attempts.yaml").is_file())
        result = reconcile_session_changes(
            self.host, directory, task=self._task()
        )
        self.assertTrue(result.ok, result.blockers)
        files, issues = load_files_yaml(directory)
        self.assertFalse(issues)
        row = next(item for item in files if item.get("path") == APP)
        self.assertEqual(row.get("mutation_state"), MUTATION_RECONCILED)

    def test_07_legacy_pending_rows_do_not_poison_seal(self):
        session_id = self._open()
        directory = self._session_dir(session_id)
        write(self.host, APP, "value = 5\n")
        write_yaml_atomic(
            directory / "mutation-attempts.yaml",
            {
                "schema_version": "1",
                "record_type": "develop_mutation_attempts",
                "attempts": [
                    {
                        "attempt_id": "legacy",
                        "session_id": session_id,
                        "task_id": TASK_A,
                        "tool_use_id": "stale",
                        "paths": [APP],
                        "state": MUTATION_PENDING,
                    }
                ],
            },
        )
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)

    def test_08_reconcile_writes_correct_files_yaml(self):
        session_id = self._open()
        directory = self._session_dir(session_id)
        s0 = load_open_inventory(directory)
        self.assertIsNotNone(s0)
        write(self.host, APP, "value = 6\n")
        result = reconcile_session_changes(
            self.host, directory, task=self._task()
        )
        self.assertTrue(result.ok, result.blockers)
        files, issues = load_files_yaml(directory)
        self.assertFalse(issues)
        row = next(item for item in files if item.get("path") == APP)
        self.assertEqual(row["before_digest"], s0[APP])
        self.assertNotEqual(row["after_digest"], s0[APP])
        self.assertEqual(row["change_kind"], "modified")
        self.assertEqual(row["scope_role"], "product")
        self.assertFalse(row["was_preexisting_dirty"])

    def test_09_preexisting_dirty_classified_via_s0(self):
        write(self.host, APP, "dirty-before-open\n")
        session_id = self._open()
        directory = self._session_dir(session_id)
        s0 = load_open_inventory(directory)
        result = self._reconcile(session_id)
        self.assertTrue(result.ok, result.blockers)
        self.assertNotIn(APP, [row["path"] for row in result.files])
        write(self.host, APP, "dirty-then-session\n")
        result = self._reconcile(session_id)
        row = next(item for item in result.files if item.get("path") == APP)
        self.assertEqual(row["before_digest"], s0[APP])
        overlay = read_yaml(directory / "session.yaml").get("workspace_overlay_s0") or {}
        overlay_paths = {
            item.get("path")
            for item in (overlay.get("paths") or [])
            if isinstance(item, dict)
        }
        if APP in overlay_paths:
            self.assertTrue(row["was_preexisting_dirty"])

    def test_preexisting_dirty_all_reconcile_api_forms(self):
        git_host = Path(self._tmp.name) / "dirty-api-host"
        git_host.mkdir()
        write_active_host(
            git_host,
            ownership=_ownership(),
            source_areas=["src"],
            capabilities={"scm": "git"},
        )
        write(git_host, APP, "value = 0\n")
        write_task(
            git_host,
            TASK_A,
            status="IN_PROGRESS",
            scope=_task_scope(),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Implement the fixture.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        init_git(git_host)
        write(git_host, APP, "dirty-before-open\n")
        opened = develop_engine(git_host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = str((opened.extras or {}).get("session", {}).get("record_id") or "")
        directory = git_host / SESSIONS_DIR / session_id
        write(git_host, APP, "dirty-then-session\n")
        task = read_yaml(git_host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        explicit = reconcile_session_changes(
            git_host,
            directory,
            task=task,
            session=read_yaml(directory / "session.yaml"),
        )
        omitted = reconcile_session_changes(git_host, directory, task=task)
        self.assertTrue(explicit.ok, explicit.blockers)
        self.assertTrue(omitted.ok, omitted.blockers)
        overlay = read_yaml(directory / "session.yaml").get("workspace_overlay_s0") or {}
        overlay_paths = {
            item.get("path")
            for item in (overlay.get("paths") or [])
            if isinstance(item, dict)
        }
        self.assertIn(APP, overlay_paths)
        for result in (explicit, omitted):
            row = next(item for item in result.files if item.get("path") == APP)
            self.assertTrue(row["was_preexisting_dirty"], result.files)
        missing = reconcile_session_changes(
            git_host,
            Path(self._tmp.name) / "missing-session",
            task=task,
        )
        self.assertFalse(missing.ok)
        self.assertTrue(missing.blockers)

    def test_10_changed_bytes_are_reobserved_after_reconciliation(self):
        session_id = self._open()
        directory = self._session_dir(session_id)
        write(self.host, APP, "value = 7\n")
        first = reconcile_session_changes(self.host, directory, task=self._task())
        after = next(item["after_digest"] for item in first.files if item["path"] == APP)
        write(self.host, APP, "value = 8\n")
        second = reconcile_session_changes(self.host, directory, task=self._task())
        row = next(item for item in second.files if item["path"] == APP)
        self.assertNotEqual(row["after_digest"], after)
        self.assertEqual(row["mutation_state"], MUTATION_RECONCILED)

    def test_11_out_of_scope_discovered_dependency_does_not_block_edit(self):
        self._open()
        allowed, reason = authorize_mutation_paths(self.host, [DISCOVERED])
        self.assertTrue(allowed, reason)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        ok, detail, role = authorize_path_mutation(
            self.host, DISCOVERED, task=self._task(), project=project
        )
        self.assertTrue(ok, detail)
        self.assertEqual(role, "discovered")
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": DISCOVERED, "contents": "helper = 1\n"},
            },
            self.host,
        )
        self.assertEqual(hook["permission"], "allow", hook)

    def test_12_out_of_scope_surfaces_at_reconciliation_and_submit(self):
        session_id = self._open()
        write(self.host, DISCOVERED, "helper = 1\n")
        result = reconcile_session_changes(
            self.host, self._session_dir(session_id), task=self._task()
        )
        self.assertIn(DISCOVERED, result.discovered)
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        real_diff = observe_real_diff(self.host)
        self.assertTrue(real_diff.get("ok"), real_diff)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        structural = review_structure(
            root=self.host,
            task=self._task(),
            real_diff=real_diff,
            project=project,
        )
        self.assertTrue(
            DISCOVERED in structural.get("undeclared", [])
            or any("undeclared" in item for item in structural.get("blockers") or []),
            structural,
        )

    def test_13_human_owned_tests_docs_config_can_change(self):
        session_id = self._open()
        for rel, content in (
            (TEST_PATH, "assert 'task'\n"),
            (DOC_PATH, "updated notes\n"),
            (CONFIG_PATH, "[project]\nname = 'y'\n"),
        ):
            allowed, reason = authorize_mutation_paths(self.host, [rel])
            self.assertTrue(allowed, f"{rel}: {reason}")
            write(self.host, rel, content)
        result = reconcile_session_changes(
            self.host, self._session_dir(session_id), task=self._task()
        )
        self.assertTrue(result.ok, result.blockers)
        self.assertIn(TEST_PATH, result.supporting)
        self.assertIn(DOC_PATH, result.discovered)
        self.assertIn(CONFIG_PATH, result.discovered)
        self.assertEqual(result.ownership.get(TEST_PATH), "HUMAN_OWNED")
        self.assertEqual(result.ownership.get(DOC_PATH), "HUMAN_OWNED")
        self.assertEqual(result.ownership.get(CONFIG_PATH), "HUMAN_OWNED")

    def test_14_managed_and_generated_remain_review_visible(self):
        session_id = self._open()
        write(self.host, MANAGED_PATH, "managed: 2\n")
        write(self.host, GENERATED_PATH, "generated = 2\n")
        result = reconcile_session_changes(
            self.host, self._session_dir(session_id), task=self._task()
        )
        self.assertEqual(result.ownership.get(MANAGED_PATH), "MANAGED")
        self.assertEqual(result.ownership.get(GENERATED_PATH), "GENERATED")
        self.assertIn(MANAGED_PATH, result.discovered)
        self.assertIn(GENERATED_PATH, result.in_scope + result.discovered)

    def test_15_protected_governance_remains_protected(self):
        self._open()
        for rel in (".scaffold/project.yaml", "AGENTS.md", ".gitattributes"):
            reason = hard_mutation_boundary_reason(self.host, rel)
            self.assertIsNotNone(reason, rel)
            hook = evaluate_cursor_hook(
                {
                    "hook_event_name": "preToolUse",
                    "tool_name": "Write",
                    "tool_input": {"path": rel, "contents": "tamper\n"},
                },
                self.host,
            )
            self.assertEqual(hook["permission"], "deny", (rel, hook))

    def test_16_tracked_deletion_is_post_reviewable(self):
        git_host = Path(self._tmp.name) / "git-host"
        git_host.mkdir()
        write_active_host(
            git_host,
            ownership=_ownership(),
            source_areas=["src"],
            capabilities={"scm": "git"},
        )
        write(git_host, APP, "value = 0\n")
        write_task(
            git_host,
            TASK_A,
            status="IN_PROGRESS",
            scope=_task_scope(),
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Implement the fixture.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        init_git(git_host)
        opened = develop_engine(git_host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Delete",
                "tool_input": {"path": APP},
            },
            git_host,
        )
        self.assertEqual(hook["permission"], "allow", hook)

    def test_17_irrecoverable_deletion_protected_where_enforceable(self):
        self._open()
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Delete",
                "tool_input": {"path": APP},
            },
            self.host,
        )
        self.assertEqual(hook["permission"], "deny", hook)
        self.assertIn("irrecoverable", hook.get("reason") or "")
        moved = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Move",
                "tool_input": {"old_path": APP, "new_path": "src/moved.py"},
            },
            self.host,
        )
        self.assertEqual(moved["permission"], "deny", moved)
        self.assertIn("irrecoverable", moved.get("reason") or "")

    def test_18_p6_candidate_currentness_remains(self):
        before = observe_candidate(self.host)
        self.assertTrue(before.usable, before.data)
        write(self.host, APP, "value = candidate\n")
        after = observe_candidate(self.host)
        self.assertTrue(after.usable, after.data)
        self.assertNotEqual(before.digest, after.digest)

    def test_19_p8_s2_s3_physical_diff_remains(self):
        session_id = self._open()
        write(self.host, APP, "value = submit\n")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        real_diff = observe_real_diff(self.host)
        self.assertTrue(real_diff.get("ok"), real_diff)
        self.assertIn(APP, real_diff.get("paths") or [])
        sessions = load_sealed_sessions(self.host)
        self.assertTrue(sessions)
        classified = classify_delta(
            self.host,
            real_paths=list(real_diff.get("paths") or []),
            sessions=sessions,
            entries=list(real_diff.get("entries") or []),
            task=self._task(),
        )
        self.assertIn(APP, classified["classes"])
        self.assertEqual(classified["classes"][APP], "DEVELOP_KNOWN")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        structural = review_structure(
            root=self.host,
            task=self._task(),
            real_diff=real_diff,
            project=project,
        )
        self.assertTrue(structural.get("ownership_authority") or structural.get("structural_review_pass") is not None)

    def test_20_ready_for_review_remains_strict(self):
        ready, reason = evaluate_ready_for_review(
            self._task(),
            candidate_digest=observe_candidate(self.host).digest,
            root=self.host,
        )
        self.assertFalse(ready)
        self.assertTrue(reason)

    def test_21_in_session_reconciled_change_is_not_hostile_drift(self):
        session_id = self._open()
        write(self.host, APP, "value = attributed\n")
        sealed = develop_engine(self.host).seal_develop_execution(task_id=TASK_A)
        self.assertEqual(sealed.outcome, "COMPLETED", sealed.blockers)
        files, issues = load_files_yaml(self._session_dir(session_id))
        self.assertFalse(issues)
        row = next(item for item in files if item.get("path") == APP)
        self.assertIn(row.get("mutation_state"), {MUTATION_RECONCILED, MUTATION_OBSERVED})

    def test_22_repair_still_requires_handoff_for_ready(self):
        write_task(self.host, TASK_A, status="READY_FOR_REVIEW")
        result = develop_engine(self.host).run("normal_task", task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("READY_FOR_REVIEW" in item for item in result.blockers))

    def test_23_old_hook_install_shape_remains_readable(self):
        legacy = {
            "version": 1,
            "hooks": {
                event: [
                    {
                        "command": "python .scaffold/install/cursor_first_use_hook.py",
                        "failClosed": True,
                        "timeout": 60,
                    }
                ]
                for event in HOOK_EVENTS
            },
        }
        fragment, missing, drifted, incompat = inspect_scaffold_hook_fragment(legacy)
        self.assertEqual(missing, [])
        self.assertEqual(drifted, [])
        self.assertEqual(incompat, [])
        self.assertIsNotNone(fragment)
        live = json.dumps(fragment, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(sha256_bytes(live.encode("utf-8")), legacy_hook_fragment_digest())
        self.assertNotEqual(legacy_hook_fragment_digest(), expected_hook_fragment_digest())
        self.assertNotEqual(
            json.dumps(
                legacy_canonical_hook_fragment(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            json.dumps(
                canonical_hook_fragment(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
        )

    def test_24_new_hook_install_shape_verify(self):
        merged = merge_scaffold_hooks(None)
        fragment, missing, drifted, incompat = inspect_scaffold_hook_fragment(merged)
        self.assertEqual(missing, [])
        self.assertEqual(drifted, [])
        self.assertEqual(incompat, [])
        live = json.dumps(fragment, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(sha256_bytes(live.encode("utf-8")), expected_hook_fragment_digest())
        for event in OBSERVATION_HOOK_EVENTS:
            self.assertFalse(merged["hooks"][event][0]["failClosed"], event)

    def test_25_evidence_locator_still_requires_supporting_scope(self):
        issues = supporting_evidence_locator_issues(
            self.host,
            DISCOVERED,
            task=self._task(),
            kind="file_artifact",
        )
        self.assertTrue(issues)
        self.assertTrue(any("supporting scope" in item for item in issues))

    def test_aa_hot_path_does_not_walk_the_project(self):
        self._open()
        with (
            patch("scaffold_p5.first_use.snapshot_host") as snap,
            patch("scaffold_p7.develop_authority.execution_workspace_digests") as digest,
            patch("scaffold_p7.develop_authority.observe_candidate") as candidate,
            patch("scaffold_p7.unexplained.observe_scm") as scm,
        ):
            result = evaluate_cursor_hook(
                {
                    "hook_event_name": "preToolUse",
                    "tool_name": "Write",
                    "tool_input": {"path": APP, "contents": "value = hot\n"},
                },
                self.host,
            )
            after = evaluate_cursor_hook(
                {
                    "hook_event_name": "afterFileEdit",
                    "tool_name": "Write",
                    "tool_input": {"path": APP},
                },
                self.host,
            )
        self.assertEqual(result["permission"], "allow", result)
        self.assertEqual(after["permission"], "allow", after)
        self.assertEqual(snap.call_count, 0)
        self.assertEqual(digest.call_count, 0)
        self.assertEqual(candidate.call_count, 0)
        self.assertEqual(scm.call_count, 0)
        authority = resolve_current_develop_authority(
            self.host, require_provenance=False
        )
        self.assertTrue(authority.ok, authority.reason)

    def test_m1_missing_authoritative_lock_is_recovery(self):
        self._open()
        (self.host / ".scaffold/skills.lock").unlink()
        decision = first_use_decision(self.host, cheap=True)
        self.assertEqual(decision["gate_policy"], GATE_RECOVERY, decision)
        self.assertEqual(decision["host_class"], "ESTABLISHED_HOST_CONSISTENCY")
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": APP, "contents": "value = lock\n"},
            },
            self.host,
        )
        self.assertEqual(hook["permission"], "deny", hook)

    def test_m1_unresolved_adoption_recovery_is_recovery(self):
        self._open()
        orphan = self.host / ".scaffold/runtime/adoption-sessions/orphan"
        orphan.mkdir(parents=True)
        decision = first_use_decision(self.host, cheap=True)
        self.assertEqual(decision["gate_policy"], GATE_RECOVERY, decision)
        self.assertEqual(decision["host_class"], "ESTABLISHED_HOST_CONSISTENCY")
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": APP, "contents": "value = recovery\n"},
            },
            self.host,
        )
        self.assertEqual(hook["permission"], "deny", hook)

    def test_m1_healthy_active_host_allows_ordinary_edit(self):
        self._open()
        decision = first_use_decision(self.host, cheap=True)
        self.assertEqual(decision["gate_policy"], GATE_DEVELOP, decision)
        self.assertEqual(decision["host_class"], "ESTABLISHED_HOST")
        hook = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": APP, "contents": "value = healthy\n"},
            },
            self.host,
        )
        self.assertEqual(hook["permission"], "allow", hook)


if __name__ == "__main__":
    unittest.main()

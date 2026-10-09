"""R10 findings: AGENTS S3, aborted attribution, test dedupe, repair recovery."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from p7_support import TASK_A, TASK_B, write_task
from support import REPO, adopt

from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    CONSUMER_INSTALL_REGION,
    parse_managed_regions,
)
from scaffold_p5.consumer_install import (
    apply_consumer_install,
    plan_consumer_install,
)
from scaffold_p5.io_util import file_digest, write_yaml_atomic
from scaffold_p5.mixed_surface import install_managed_bytes_verified
from scaffold_p6.candidate import observe_candidate
from scaffold_p6.contract import validate_selected
from scaffold_p7.handoff import build_develop_to_test
from scaffold_p7.repair_state import (
    _next_action,
    load_repair_state,
    persist_repair_state,
    reconcile_pending_repair,
    reconstruct_repair_view,
)
from scaffold_p8.delta import classify_delta, load_sealed_sessions
from scaffold_p8.structural import review_structure

FROZEN_R10 = Path(r"F:\NewResearch\Project-City-consumer-pilot-r10")
ADS = "src/ads.py"
OTHER = "src/other.py"
TASK_MAIN = "task-20261008T120000Z-aaa10001"
TASK_OTHER = "task-20261008T120100Z-bbb20002"
ABORTED_ID = "dev-20261008T120000Z-aaaa0001"
SEALED_ID = "dev-20261008T120100Z-aaaa0002"
ABORTED_LATER = "dev-20261008T120030Z-aaaa0003"


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_AUTHOR_NAME"] = "r10-findings"
    env["GIT_AUTHOR_EMAIL"] = "r10-findings@example.invalid"
    env["GIT_COMMITTER_NAME"] = "r10-findings"
    env["GIT_COMMITTER_EMAIL"] = "r10-findings@example.invalid"
    return env


def _git(host: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(host),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _binding(requirement_id: str, profile_id: str) -> dict[str, object]:
    return {
        "requirement_id": requirement_id,
        "execution_binding": {"kind": "test_profile", "profile_id": profile_id},
    }


def _state(host: Path, rel: str) -> tuple[str, str]:
    return "regular_file", "sha256:" + file_digest(host / rel)


def _overlay(path: str, state: tuple[str, str | None]) -> dict[str, object]:
    return {
        "coverage": "complete",
        "paths": [
            {"path": path, "kind": state[0], "digest": state[1]},
        ],
    }


def _write_session(
    host: Path,
    session_id: str,
    *,
    status: str,
    task_id: str,
    created_at: str,
    files: list[dict],
    s0: dict,
    s1: dict,
) -> None:
    directory = host / ".scaffold" / "runtime" / "develop-sessions" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        directory / "session.yaml",
        {
            "record_type": "develop_session",
            "schema_version": "1",
            "record_id": session_id,
            "created_at": created_at,
            "updated_at": created_at,
            "status": status,
            "task_id": task_id,
            "mode": "normal_task",
            "project_name": "r10-findings",
            "baseline": {"kind": "none", "value": None},
            "workspace_overlay_s0": s0,
            "workspace_overlay_s1": s1,
            "observed_candidate_digest": "ab" * 32,
        },
    )
    write_yaml_atomic(directory / "files.yaml", {"files": files})


def _touch(
    path: str,
    *,
    before: tuple[str, str | None],
    after: tuple[str, str | None],
    mutation_state: str = "observed_success",
) -> dict:
    return {
        "path": path,
        "change_kind": "modified",
        "was_preexisting_dirty": False,
        "before_kind": before[0],
        "before_digest": before[1],
        "after_kind": after[0],
        "after_digest": after[1],
        "mutation_state": mutation_state,
        "stage_ids": ["stage-1"],
    }


class AgentsSubmitSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.host = Path(cls._tmp.name) / "host"
        cls.host.mkdir()
        (cls.host / "README.md").write_text("# sample\n", encoding="utf-8")
        _git(cls.host, "init")
        _git(cls.host, "add", "README.md")
        _git(cls.host, "commit", "-m", "readme")
        plan = plan_consumer_install(cls.host, REPO, mode="install")
        if not plan.allowed:
            raise AssertionError(plan.blockers)
        applied = apply_consumer_install(plan)
        if applied.get("outcome") != "COMPLETED":
            raise AssertionError(applied.get("blockers") or applied)
        adopted = adopt(cls.host)
        if adopted.outcome != "COMPLETED":
            raise AssertionError(adopted.blockers)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_install_then_adoption_is_install_managed_at_s3(self) -> None:
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        spans, issues = parse_managed_regions(text)
        self.assertEqual(issues, [])
        self.assertEqual(
            set(spans), {CONSUMER_INSTALL_REGION, AGENTS_ROUTER_REGION}
        )
        self.assertTrue(install_managed_bytes_verified(self.host, "AGENTS.md"))
        reviewed = review_structure(
            root=self.host,
            task=None,
            real_diff={"paths": ["AGENTS.md"], "entries": []},
            project={},
        )
        self.assertEqual(
            [row["path"] for row in reviewed["install_managed_paths"]],
            ["AGENTS.md"],
        )
        self.assertNotIn("AGENTS.md", reviewed["unknown_ownership"])

    def test_human_edit_forged_deleted_and_tampered_regions_fail(self) -> None:
        path = self.host / "AGENTS.md"
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(original + "\nOperator note.\n", encoding="utf-8")
            self.assertFalse(install_managed_bytes_verified(self.host, "AGENTS.md"))
            owned = review_structure(
                root=self.host,
                task=None,
                real_diff={"paths": ["AGENTS.md"], "entries": []},
                project={"ownership": {"AGENTS.md": "MANAGED"}},
            )
            self.assertNotIn(
                "AGENTS.md",
                [row["path"] for row in owned["install_managed_paths"]],
            )
            self.assertIn("AGENTS.md", owned["unknown_ownership"])

            forged = (
                "<!-- scaffold:managed:forged-region:start -->\n"
                "forged\n"
                "<!-- scaffold:managed:forged-region:end -->\n"
                + original
            )
            path.write_text(forged, encoding="utf-8")
            self.assertFalse(install_managed_bytes_verified(self.host, "AGENTS.md"))

            spans, issues = parse_managed_regions(original)
            self.assertEqual(issues, [])
            start, end = spans[AGENTS_ROUTER_REGION]
            deleted = original[:start] + original[end:]
            path.write_text(deleted, encoding="utf-8")
            self.assertNotIn(AGENTS_ROUTER_REGION, deleted)
            self.assertFalse(install_managed_bytes_verified(self.host, "AGENTS.md"))

            spans, _issues = parse_managed_regions(original)
            start, end = spans[CONSUMER_INSTALL_REGION]
            tampered = original[: start + 40] + "TAMPERED\n" + original[start + 40 :]
            path.write_text(tampered, encoding="utf-8")
            self.assertFalse(install_managed_bytes_verified(self.host, "AGENTS.md"))
        finally:
            path.write_text(original, encoding="utf-8")

    def test_frozen_r10_install_only_agents_stays_attested(self) -> None:
        if not (FROZEN_R10 / "AGENTS.md").is_file():
            self.skipTest("frozen R10 consumer is not present")
        before = (FROZEN_R10 / "AGENTS.md").read_bytes()
        try:
            self.assertTrue(
                install_managed_bytes_verified(FROZEN_R10, "AGENTS.md")
            )
        finally:
            self.assertEqual((FROZEN_R10 / "AGENTS.md").read_bytes(), before)


class AbortedAttributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name)
        (self.host / "src").mkdir()
        (self.host / ADS).write_text("ads = 1\n", encoding="utf-8")
        write_yaml_atomic(
            self.host / ".scaffold" / "project.yaml",
            {"project_contract_generation": "1"},
        )
        self.live = _state(self.host, ADS)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _task(self, *session_ids: str, scope: list[str] | None = None) -> dict:
        return {
            "record_id": TASK_MAIN,
            "develop_session_ids": list(session_ids),
            "scope": {"paths": scope or [ADS], "modules": [], "exclude": []},
        }

    def _sealed_empty(self, path: str, state: tuple[str, str]) -> None:
        _write_session(
            self.host,
            SEALED_ID,
            status="SEALED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:01:00Z",
            files=[],
            s0=_overlay(path, state),
            s1=_overlay(path, state),
        )

    def _classify(self, task: dict, paths: list[str]) -> dict:
        linked = {str(item) for item in task["develop_session_ids"]}
        return classify_delta(
            self.host,
            real_paths=paths,
            sessions=load_sealed_sessions(self.host, linked_ids=linked),
            task=task,
        )

    def test_aborted_bytes_survive_later_empty_sealed_session(self) -> None:
        _write_session(
            self.host,
            ABORTED_ID,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:00Z",
            files=[
                _touch(
                    ADS,
                    before=("missing", None),
                    after=self.live,
                )
            ],
            s0=_overlay(ADS, ("missing", None)),
            s1=_overlay(ADS, self.live),
        )
        self._sealed_empty(ADS, self.live)
        task = self._task(ABORTED_ID, SEALED_ID)
        sealed_only = classify_delta(
            self.host,
            real_paths=[ADS],
            sessions=load_sealed_sessions(
                self.host, linked_ids={ABORTED_ID, SEALED_ID}
            ),
            task={
                "record_id": TASK_MAIN,
                "develop_session_ids": [SEALED_ID],
                "scope": {"paths": [ADS], "modules": []},
            },
        )
        self.assertEqual(sealed_only["classes"][ADS], "PREEXISTING_CHANGE")
        self.assertEqual(
            sealed_only["task_delta_classes"][ADS], "inherited_baseline"
        )
        delta = self._classify(task, [ADS])
        self.assertEqual(delta["classes"][ADS], "ABORTED_ATTRIBUTED")
        self.assertNotEqual(delta["classes"][ADS], "DEVELOP_KNOWN")
        self.assertEqual(delta["task_delta_classes"][ADS], "task_product_delta")
        self.assertNotEqual(
            delta["task_delta_classes"][ADS], "inherited_baseline"
        )

    def test_later_sealed_edit_keeps_sealed_authority(self) -> None:
        (self.host / ADS).write_text("ads = 2\n", encoding="utf-8")
        changed = _state(self.host, ADS)
        _write_session(
            self.host,
            ABORTED_ID,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:00Z",
            files=[_touch(ADS, before=("missing", None), after=self.live)],
            s0=_overlay(ADS, ("missing", None)),
            s1=_overlay(ADS, self.live),
        )
        _write_session(
            self.host,
            SEALED_ID,
            status="SEALED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:01:00Z",
            files=[_touch(ADS, before=self.live, after=changed)],
            s0=_overlay(ADS, self.live),
            s1=_overlay(ADS, changed),
        )
        delta = self._classify(self._task(ABORTED_ID, SEALED_ID), [ADS])
        self.assertEqual(delta["classes"][ADS], "DEVELOP_KNOWN")
        self.assertNotEqual(delta["classes"][ADS], "ABORTED_ATTRIBUTED")

    def test_other_task_aborted_edit_is_not_this_task_product(self) -> None:
        (self.host / OTHER).write_text("other = 1\n", encoding="utf-8")
        other_state = _state(self.host, OTHER)
        _write_session(
            self.host,
            ABORTED_ID,
            status="ABORTED",
            task_id=TASK_OTHER,
            created_at="2026-10-08T12:00:00Z",
            files=[_touch(OTHER, before=("missing", None), after=other_state)],
            s0=_overlay(OTHER, ("missing", None)),
            s1=_overlay(OTHER, other_state),
        )
        self._sealed_empty(OTHER, other_state)
        task = self._task(ABORTED_ID, SEALED_ID, scope=[ADS, OTHER])
        delta = self._classify(task, [OTHER])
        self.assertEqual(delta["classes"][OTHER], "PREEXISTING_CHANGE")
        self.assertNotEqual(delta["classes"][OTHER], "ABORTED_ATTRIBUTED")
        self.assertNotEqual(delta["classes"][OTHER], "DEVELOP_KNOWN")
        self.assertEqual(
            delta["task_delta_classes"][OTHER], "inherited_baseline"
        )

    def test_failed_and_pending_writes_are_not_aborted_attribution(self) -> None:
        _write_session(
            self.host,
            ABORTED_ID,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:00Z",
            files=[
                _touch(
                    ADS,
                    before=("missing", None),
                    after=self.live,
                    mutation_state="failed",
                )
            ],
            s0=_overlay(ADS, self.live),
            s1=_overlay(ADS, self.live),
        )
        self._sealed_empty(ADS, self.live)
        failed = self._classify(self._task(ABORTED_ID, SEALED_ID), [ADS])
        self.assertEqual(failed["classes"][ADS], "PREEXISTING_CHANGE")
        self.assertNotEqual(failed["classes"][ADS], "ABORTED_ATTRIBUTED")
        self.assertNotEqual(failed["classes"][ADS], "DEVELOP_KNOWN")
        pending_id = "dev-20261008T120010Z-aaaa0004"
        success_id = "dev-20261008T120020Z-aaaa0005"
        _write_session(
            self.host,
            success_id,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:20Z",
            files=[_touch(ADS, before=("missing", None), after=self.live)],
            s0=_overlay(ADS, ("missing", None)),
            s1=_overlay(ADS, self.live),
        )
        _write_session(
            self.host,
            pending_id,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:10Z",
            files=[
                _touch(
                    ADS,
                    before=("missing", None),
                    after=self.live,
                    mutation_state="authorized_pending",
                )
            ],
            s0=_overlay(ADS, self.live),
            s1=_overlay(ADS, self.live),
        )
        mixed = self._classify(
            self._task(ABORTED_ID, pending_id, success_id, SEALED_ID), [ADS]
        )
        self.assertEqual(mixed["classes"][ADS], "UNATTRIBUTED")
        self.assertNotEqual(mixed["classes"][ADS], "ABORTED_ATTRIBUTED")
        self.assertNotEqual(mixed["classes"][ADS], "DEVELOP_KNOWN")

    def test_broken_chain_is_not_proven_by_matching_hash(self) -> None:
        stale = ("regular_file", "sha256:" + ("ab" * 32))
        _write_session(
            self.host,
            ABORTED_ID,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:00Z",
            files=[_touch(ADS, before=("missing", None), after=stale)],
            s0=_overlay(ADS, ("missing", None)),
            s1=_overlay(ADS, stale),
        )
        _write_session(
            self.host,
            ABORTED_LATER,
            status="ABORTED",
            task_id=TASK_MAIN,
            created_at="2026-10-08T12:00:30Z",
            files=[_touch(ADS, before=("missing", None), after=self.live)],
            s0=_overlay(ADS, ("missing", None)),
            s1=_overlay(ADS, self.live),
        )
        self._sealed_empty(ADS, self.live)
        delta = self._classify(
            self._task(ABORTED_ID, ABORTED_LATER, SEALED_ID), [ADS]
        )
        self.assertEqual(delta["classes"][ADS], "UNATTRIBUTED")
        self.assertNotEqual(delta["classes"][ADS], "ABORTED_ATTRIBUTED")
        self.assertNotEqual(delta["classes"][ADS], "DEVELOP_KNOWN")
        self.assertNotEqual(
            delta["task_delta_classes"][ADS], "inherited_baseline"
        )


class TestProfileDedupTests(unittest.TestCase):
    def _task(self, *, finals: list[dict], stages: list[dict]) -> dict:
        return {
            "record_id": TASK_A,
            "scope": {"paths": ["src/app.py"], "modules": []},
            "final_tests": finals,
            "stages": stages,
        }

    def test_automatic_selection_dedupes_in_first_seen_order(self) -> None:
        task = self._task(
            finals=[_binding("final-req", "profile-a")],
            stages=[
                {
                    "stage_id": "stage-1",
                    "required_tests": [
                        _binding("stage-req", "profile-b"),
                        _binding("stage-again", "profile-a"),
                    ],
                }
            ],
        )
        payload = build_develop_to_test(
            task=task, session_id="dev-1", candidate_digest="abc"
        )
        requirement = payload["test_requirement"]
        self.assertEqual(requirement["selected"], ["profile-a", "profile-b"])
        self.assertEqual(
            [row["requirement_id"] for row in requirement["requirement_bindings"]],
            ["final-req", "stage-req", "stage-again"],
        )
        self.assertEqual(
            [row["profile_id"] for row in requirement["requirement_bindings"]],
            ["profile-a", "profile-b", "profile-a"],
        )

    def test_explicit_duplicate_selection_is_left_for_existing_validation(self) -> None:
        task = self._task(
            finals=[_binding("final-req", "profile-a")],
            stages=[],
        )
        payload = build_develop_to_test(
            task=task,
            session_id="dev-1",
            candidate_digest="abc",
            selected=["profile-a", "profile-a"],
        )
        selected = payload["test_requirement"]["selected"]
        self.assertEqual(selected, ["profile-a", "profile-a"])
        _ids, issues = validate_selected(selected, {"profile-a"})
        self.assertEqual(issues, ["duplicate selected profile id: profile-a"])

    def test_shared_profile_keeps_every_requirement_binding(self) -> None:
        task = self._task(
            finals=[_binding("final-req", "profile-shared")],
            stages=[
                {
                    "stage_id": "stage-1",
                    "required_tests": [_binding("stage-req", "profile-shared")],
                }
            ],
        )
        payload = build_develop_to_test(
            task=task, session_id="dev-1", candidate_digest="abc"
        )
        requirement = payload["test_requirement"]
        self.assertEqual(requirement["selected"], ["profile-shared"])
        self.assertEqual(len(requirement["requirement_bindings"]), 2)

    def test_empty_list_uses_the_same_automatic_selection_as_none(self) -> None:
        task = self._task(
            finals=[_binding("final-req", "profile-a")],
            stages=[
                {
                    "stage_id": "stage-1",
                    "required_tests": [_binding("stage-req", "profile-a")],
                }
            ],
        )
        omitted = build_develop_to_test(
            task=task, session_id="dev-1", candidate_digest="abc"
        )
        empty = build_develop_to_test(
            task=task, session_id="dev-1", candidate_digest="abc", selected=[]
        )
        self.assertEqual(
            empty["test_requirement"]["selected"],
            omitted["test_requirement"]["selected"],
        )
        self.assertEqual(empty["test_requirement"]["selected"], ["profile-a"])
        self.assertEqual(len(empty["test_requirement"]["requirement_bindings"]), 2)


class RepairRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name)
        self.host.mkdir(exist_ok=True)
        (self.host / "README.md").write_text("# repair\n", encoding="utf-8")
        _git(self.host, "init")
        _git(self.host, "add", "README.md")
        _git(self.host, "commit", "-m", "readme")
        self.task = write_task(self.host, TASK_A)
        self.live = observe_candidate(self.host).digest
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "candidate_digest": self.live,
                "session_id": "dev-fail",
                "fail_ids": ["fail-1"],
                "report_id": "report-fail",
                "reason": "required Test FAIL/BLOCKED produced a Repair handoff",
            },
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _covering(self, **overrides: object) -> dict:
        payload = {
            "task_id": TASK_A,
            "test_pass": True,
            "test_complete": True,
            "candidate_digest": observe_candidate(self.host).digest,
            "report_id": "report-pass",
            "session_id": "dev-pass",
        }
        payload.update(overrides)
        return payload

    def _satisfy(self, stage_id: str = "stage-1", digest: str | None = None) -> dict:
        task = dict(self.task)
        stages = [dict(row) for row in task["stages"]]
        stages[0] = dict(stages[0])
        stages[0]["completion_decision"] = {
            "outcome": "SATISFIED",
            "stage_id": stage_id,
            "candidate_digest": digest or observe_candidate(self.host).digest,
        }
        if stage_id != "stage-1":
            stages[0]["stage_id"] = stage_id
        task["stages"] = stages
        return task

    def test_genuine_recovery_resolves_and_keeps_failure_history(self) -> None:
        resolved = reconcile_pending_repair(
            self.host, task=self._satisfy(), covering=self._covering()
        )
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["fail_ids"], ["fail-1"])
        self.assertEqual(resolved["report_id"], "report-fail")
        self.assertEqual(len(resolved["failure_history"]), 1)
        self.assertEqual(resolved["failure_history"][0]["fail_ids"], ["fail-1"])
        again = reconcile_pending_repair(
            self.host, task=self._satisfy(), covering=self._covering()
        )
        assert again is not None
        self.assertEqual(len(again["failure_history"]), 1)
        self.assertEqual(load_repair_state(self.host, TASK_A)["status"], "resolved")

    def test_candidate_change_does_not_resolve(self) -> None:
        (self.host / "README.md").write_text("# repair changed\n", encoding="utf-8")
        result = reconcile_pending_repair(
            self.host,
            task=self._satisfy(digest=self.live),
            covering=self._covering(),
        )
        self.assertIsNone(result)
        self.assertEqual(load_repair_state(self.host, TASK_A)["status"], "pending")

    def test_unresolved_failure_and_mismatched_task_or_stage_stay_pending(self) -> None:
        failed = reconcile_pending_repair(
            self.host,
            task=self._satisfy(),
            covering=self._covering(test_pass=False, test_complete=False),
        )
        self.assertIsNone(failed)
        incomplete = reconcile_pending_repair(
            self.host,
            task=self._satisfy(),
            covering=self._covering(test_complete=False, report_id="report-pass-only"),
        )
        self.assertIsNone(incomplete)
        other = reconcile_pending_repair(
            self.host,
            task=self._satisfy(),
            covering=self._covering(task_id=TASK_B),
        )
        self.assertIsNone(other)
        wrong_stage = reconcile_pending_repair(
            self.host,
            task=self._satisfy(stage_id="stage-2"),
            covering=self._covering(report_id="report-stage"),
        )
        self.assertIsNone(wrong_stage)
        self.assertEqual(load_repair_state(self.host, TASK_A)["status"], "pending")
        self.assertEqual(load_repair_state(self.host, TASK_A)["fail_ids"], ["fail-1"])

    def test_ready_view_matches_repair_support_state(self) -> None:
        pending_view = reconstruct_repair_view(self.host, TASK_A)
        self.assertEqual(pending_view["repair_state_status"], "pending")
        self.assertIn("pending Repair", _next_action(
            task=self.task,
            state=load_repair_state(self.host, TASK_A),
            ready_ok=True,
        ))
        reconcile_pending_repair(
            self.host, task=self._satisfy(), covering=self._covering()
        )
        view = reconstruct_repair_view(self.host, TASK_A)
        self.assertEqual(view["repair_state_status"], "resolved")
        self.assertEqual(view["fail_ids"], ["fail-1"])
        self.assertEqual(
            _next_action(
                task=self.task,
                state=load_repair_state(self.host, TASK_A),
                ready_ok=True,
            ),
            "Repair loop is complete; Task is READY_FOR_REVIEW",
        )


class DevelopTestHandoffTests(unittest.TestCase):
    """Real DevelopEngine → invoke_test path, not the helper alone."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name)
        self.host.mkdir(exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _shared_profile_host(self) -> None:
        from p6_support import CORE_OWNERSHIP, passing_profile, write_host
        from p7_support import (
            bind_develop_lock,
            ensure_noscms_accepted_anchor,
            write_task,
        )
        from scaffold_p5.io_util import read_yaml
        from support import write

        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        project["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write(self.host, "src/app.py", "value = 1\n")
        ensure_noscms_accepted_anchor(self.host)
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [_binding("stage-unit", "unit")],
                }
            ],
            final_tests=[_binding("final-unit", "unit")],
        )

    def test_stage_and_final_tests_execute_the_shared_profile_once(self) -> None:
        from p7_support import develop_engine
        from scaffold_p5.io_util import read_yaml

        self._shared_profile_host()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertNotIn("duplicate selected profile id", " ".join(result.blockers))
        handoff = result.extras["develop_to_test"]
        requirement = handoff["test_requirement"]
        self.assertEqual(requirement["selected"], ["unit"])
        self.assertEqual(
            [row["requirement_id"] for row in requirement["requirement_bindings"]],
            ["final-unit", "stage-unit"],
        )
        self.assertEqual(
            [row["profile_id"] for row in requirement["requirement_bindings"]],
            ["unit", "unit"],
        )
        self.assertIs(result.extras["test_pass"], True)
        reports = list(
            (self.host / ".scaffold/runtime/test-runs").glob("*/report.yaml")
        )
        self.assertEqual(len(reports), 1)
        report = read_yaml(reports[0])
        self.assertEqual(report["selected"], ["unit"])
        executed = [
            row.get("id")
            for row in (report.get("profiles") or [])
            if isinstance(row, dict) and row.get("result") != "NOT_RUN"
        ]
        self.assertEqual(executed, ["unit"])

    def test_explicit_duplicate_selection_is_still_rejected(self) -> None:
        from p7_support import develop_engine

        self._shared_profile_host()
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit", "unit"],
        )
        selected = result.extras["develop_to_test"]["test_requirement"]["selected"]
        self.assertEqual(selected, ["unit", "unit"])
        handoff = result.extras["test_to_develop"]
        self.assertEqual(handoff["outcome"], "BLOCKED")
        self.assertIs(handoff["test_pass"], False)
        self.assertIn("duplicate selected profile id: unit", handoff["blockers"])


class RepairResumeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from p8_support import write_submit_host

        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_submit_host(self.host)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _task(self) -> dict:
        from scaffold_p5.io_util import read_yaml

        return read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")

    def _resolve_legally(self) -> dict:
        live = observe_candidate(self.host).digest
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "candidate_digest": live,
                "session_id": "dev-fail",
                "fail_ids": ["fail-1"],
                "report_id": "report-fail",
                "reason": "required Test FAIL/BLOCKED produced a Repair handoff",
            },
        )
        resolved = reconcile_pending_repair(
            self.host,
            task=self._task(),
            covering={
                "task_id": TASK_A,
                "test_pass": True,
                "test_complete": True,
                "candidate_digest": live,
                "report_id": "report-pass",
                "session_id": "dev-pass",
            },
        )
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(resolved["status"], "resolved")
        return resolved

    def _resume(self):
        from p10_support import resume

        return resume(self.host)

    def test_resolved_ready_routes_submit_and_keeps_history_queryable(self) -> None:
        from p10_support import subprocess_resume

        resolved = self._resolve_legally()
        first = self._resume()
        second = self._resume()
        restarted = subprocess_resume(self.host)
        self.assertEqual(first.next_route, "submit", first.extras.get("next_route_reason"))
        self.assertEqual(second.next_route, first.next_route)
        self.assertEqual(second.extras.get("next_route_reason"), first.extras.get("next_route_reason"))
        self.assertEqual(restarted["next_route"], "submit")
        repair = first.extras["work"]["repair"][0]
        self.assertEqual(repair["repair_state_status"], "resolved")
        self.assertEqual(repair["fail_ids"], ["fail-1"])
        self.assertEqual(repair["failure_history"][0]["fail_ids"], ["fail-1"])
        self.assertEqual(first.extras["test"]["required_failures"], [])
        self.assertEqual(len(resolved["failure_history"]), 1)
        again = reconcile_pending_repair(
            self.host,
            task=self._task(),
            covering={
                "task_id": TASK_A,
                "test_pass": True,
                "test_complete": True,
                "candidate_digest": observe_candidate(self.host).digest,
                "report_id": "report-pass",
                "session_id": "dev-pass",
            },
        )
        assert again is not None
        self.assertEqual(len(again["failure_history"]), 1)

    def test_pending_and_active_still_route_repair(self) -> None:
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": ["stage-1"],
                "fail_ids": ["fail-open"],
                "report_id": "report-open",
                "reason": "required Test FAIL",
            },
        )
        pending = self._resume()
        self.assertEqual(pending.next_route, "develop.repair")
        self.assertNotEqual(pending.next_route, "submit")
        self.assertEqual(
            pending.extras["test"]["required_failures"],
            [{"task_id": TASK_A, "fail_id": "fail-open"}],
        )
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "active",
                "target_stage_ids": ["stage-1"],
                "fail_ids": ["fail-active"],
                "report_id": "report-active",
                "reason": "required Test FAIL",
            },
        )
        active = self._resume()
        self.assertEqual(active.next_route, "develop.repair")
        self.assertEqual(
            [row["fail_id"] for row in active.extras["test"]["required_failures"]],
            ["fail-active"],
        )

    def test_consumed_history_is_not_a_current_required_failure(self) -> None:
        persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "consumed",
                "target_stage_ids": ["stage-1"],
                "fail_ids": ["fail-consumed"],
                "failure_history": [
                    {"status": "pending", "fail_ids": ["fail-consumed"], "report_id": "report-old"}
                ],
                "report_id": "report-old",
                "reason": "repair reopen consumed the failure",
            },
        )
        result = self._resume()
        repair = result.extras["work"]["repair"][0]
        self.assertEqual(repair["repair_state_status"], "consumed")
        self.assertEqual(repair["fail_ids"], ["fail-consumed"])
        self.assertEqual(repair["failure_history"][0]["fail_ids"], ["fail-consumed"])
        self.assertEqual(result.extras["test"]["required_failures"], [])
        self.assertNotEqual(result.next_route, "test")
        self.assertNotEqual(result.next_route, "develop.repair")

    def test_stale_candidate_or_decision_does_not_submit(self) -> None:
        from p8_support import bind_ready_completion_authority
        from scaffold_p5.io_util import read_yaml
        from support import write

        self._resolve_legally()
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        stages = [dict(row) for row in task["stages"]]
        stages[0]["completion_decision"] = dict(stages[0]["completion_decision"])
        stages[0]["completion_decision"]["outcome"] = "UNKNOWN"
        task["stages"] = stages
        write_yaml_atomic(task_path, task)
        decision = self._resume()
        self.assertNotEqual(decision.next_route, "submit")
        self.assertEqual(
            decision.extras["work"]["repair"][0]["fail_ids"],
            ["fail-1"],
        )
        bind_ready_completion_authority(self.host)
        self._resolve_legally()
        write(self.host, "src/app.py", "value = 9\n")
        candidate = self._resume()
        self.assertNotEqual(candidate.next_route, "submit")
        self.assertEqual(
            candidate.extras["work"]["repair"][0]["failure_history"][0]["fail_ids"],
            ["fail-1"],
        )

    def test_new_failure_after_resolve_keeps_history_and_blocks(self) -> None:
        from p6_support import failing_profile
        from p7_support import develop_engine
        from scaffold_p5.io_util import read_yaml

        self._resolve_legally()
        profile, command = failing_profile("unit")
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        tests["profiles"] = [profile]
        commands["commands"] = [command]
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        write_yaml_atomic(self.host / ".scaffold/commands.yaml", commands)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        task["status"] = "IN_PROGRESS"
        write_yaml_atomic(task_path, task)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertIs(result.extras.get("test_pass"), False, result.blockers)
        state = load_repair_state(self.host, TASK_A)
        assert state is not None
        self.assertEqual(state["status"], "pending")
        self.assertIn("unit", state["fail_ids"])
        self.assertTrue(
            any(row.get("fail_ids") == ["fail-1"] for row in state["failure_history"])
        )
        self.assertTrue(
            any(row.get("status") == "resolved" for row in state["failure_history"])
        )
        repeated = persist_repair_state(
            self.host,
            {
                "task_id": TASK_A,
                "status": "pending",
                "target_stage_ids": list(state.get("target_stage_ids") or []),
                "candidate_digest": state.get("candidate_digest") or "",
                "session_id": state.get("session_id") or "",
                "fail_ids": list(state.get("fail_ids") or []),
                "report_id": state.get("report_id") or "",
                "reason": state.get("reason") or "",
            },
        )
        self.assertEqual(len(repeated["failure_history"]), len(state["failure_history"]))
        routed = self._resume()
        self.assertEqual(routed.next_route, "develop.repair")
        self.assertNotEqual(routed.next_route, "submit")
        self.assertTrue(routed.extras["test"]["required_failures"])


if __name__ == "__main__":
    unittest.main()

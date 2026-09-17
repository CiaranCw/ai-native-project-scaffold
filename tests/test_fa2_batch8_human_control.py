from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from p8_support import (
    TASK_A,
    bind_ready_completion_authority,
    init_submit_git,
    run_submit,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p8.engine import SubmitEngine
from scaffold_p8.models import CHANGES_DIR, NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import COMPLETE_NAME
from scaffold_p8.records import is_durable
from support import write


class FA2Batch8HumanControlTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B8A01_caller_dictionary_cannot_authorize(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        reviewed = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(reviewed.outcome, "COMPLETED")
        self.assertFalse((reviewed.extras.get("s10") or {}).get("durable"))
        self.assertFalse(any((self.host / CHANGES_DIR).glob("*.yaml")))

    def test_B8A02_s10_apply_does_not_need_a_human_grant(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(is_durable(self.host, result.extras["change_record"]["record_id"]))

    def test_B8A03_default_submit_does_not_finalize(self):
        write_submit_host(self.host)
        first = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            fail_s10=True,
        )
        self.assertEqual(first.outcome, "COMPLETED")
        self.assertFalse(first.extras["s10"]["durable"])
        bind_ready_completion_authority(self.host)
        second = SubmitEngine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(second.outcome, "COMPLETED", second.blockers)
        self.assertTrue(second.extras["s10"]["durable"])

    def test_B8A04_candidate_change_is_still_machine_bound(self):
        write_submit_host(self.host)
        write(self.host, "src/app.py", "value = 2\n")
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(result.extras["s10"].get("reviewed_candidate_digest"))

    def test_B8A05_s10_does_not_authorize_push(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertFalse((result.extras.get("push") or {}).get("performed"))

    def test_B8A06_provider_objects_are_ignored(self):
        write_submit_host(self.host)
        forged = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            authorization_provider=object(),
            submit_authorization_ref="forged-ref",
        )
        self.assertEqual(forged.outcome, "COMPLETED", forged.blockers)
        self.assertTrue(forged.extras["s10"]["durable"])

    def test_B8A07_review_stop_is_not_a_human_submit_gate(self):
        write_submit_host(self.host)
        reviewed = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(reviewed.outcome, "COMPLETED")
        self.assertNotEqual(reviewed.next_route, "human")
        self.assertFalse(reviewed.extras["s10"]["durable"])
        self.assertTrue(reviewed.extras.get("review_ready") or reviewed.next_route == "caller")
        blocked = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(blocked.outcome, "COMPLETED", blocked.blockers)
        self.assertTrue(blocked.extras["s10"]["durable"])

    def test_B8A08_request_push_is_separate_from_s10(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            request_push=True,
            fail_push=True,
        )
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(result.extras["push"]["performed"])
        self.assertFalse(result.extras["push"]["ok"])

    def test_B8A10_no_grant_persistence(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            push=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        forbidden = (
            "submit_authorized: true",
            "push_authorized: true",
            "can_commit: true",
            "can_push: true",
            "granted: true",
            "COMMIT_AUTHORIZED",
            "HUMAN_CONFIRMED",
        )
        roots = [
            self.host / ".scaffold/tasks",
            self.host / CHANGES_DIR,
            self.host / SESSIONS_DIR,
            self.host / ".scaffold",
        ]
        texts: list[str] = []
        for folder in roots:
            if not folder.exists():
                continue
            for path in folder.rglob("*"):
                if path.is_file() and path.suffix in {".yaml", ".md", ".lock"}:
                    texts.append(path.read_text(encoding="utf-8").lower())
        blob = "\n".join(texts)
        for token in forbidden:
            self.assertNotIn(token.lower(), blob)
        self.assertFalse((self.host / SESSIONS_DIR / session_id).exists())

    def test_B8C01_cleanup_failure_is_not_completed(self):
        result = self._finalize_with_cleanup_failure()
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["stage"], "S12")
        self.assertTrue(result.extras["s10_durable"])
        self.assertTrue(result.extras["durable_finalization_occurred"])
        self.assertFalse(result.extras["cleanup"]["ok"])
        self.assertTrue(result.extras["cleanup_retry_required"])
        self.assertEqual(
            result.extras["cleanup_retry"]["operation"],
            "cleanup_retry",
        )
        self.assertTrue(result.extras["cleanup_retry"]["change_id"])
        self.assertEqual(result.next_route, "submit")

    def test_B8C02_cleanup_failure_does_not_invalidate_s10(self):
        result = self._finalize_with_cleanup_failure()
        record_id = result.extras["change_record"]["record_id"]
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(is_durable(self.host, record_id))
        self.assertTrue((self.host / CHANGES_DIR / f"{record_id}.yaml").is_file())
        self.assertTrue(
            (self.host / NOSCMS_PUBLICATIONS_DIR / record_id / COMPLETE_NAME).is_file()
        )
        write_submit_host(self.host)
        init_submit_git(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        git_result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_cleanup=True,
        )
        self.assertNotEqual(git_result.outcome, "COMPLETED")
        git_id = git_result.extras["change_record"]["record_id"]
        self.assertTrue(is_durable(self.host, git_id))
        from p6_support import git

        self.assertEqual(
            git(self.host, "rev-parse", "HEAD"),
            git_result.extras["s10"]["commit"],
        )
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())

    def test_B8C03_cleanup_retry_does_not_create_second_s10(self):
        first = self._finalize_with_cleanup_failure()
        record_id = first.extras["change_record"]["record_id"]
        before_records = sorted(path.name for path in (self.host / CHANGES_DIR).glob("*.yaml"))
        publications = list((self.host / NOSCMS_PUBLICATIONS_DIR).iterdir())
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertEqual(retry.extras["stage"], "S12")
        self.assertFalse(retry.extras.get("submit_authorized"))
        after_records = sorted(path.name for path in (self.host / CHANGES_DIR).glob("*.yaml"))
        self.assertEqual(after_records, before_records)
        self.assertEqual(
            [path.name for path in (self.host / NOSCMS_PUBLICATIONS_DIR).iterdir() if path.is_dir()],
            [path.name for path in publications if path.is_dir()],
        )
        self.assertTrue(is_durable(self.host, record_id))

    def test_B8C04_cleanup_retry_survives_restart(self):
        first = self._finalize_with_cleanup_failure()
        session_id = first.extras["cleanup"]["retained"][0]
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())
        restarted = SubmitEngine(self.host)
        retry = restarted.run(cleanup_retry=first.extras["cleanup_retry"])
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertTrue(retry.extras["s10_durable"])
        self.assertFalse((self.host / SESSIONS_DIR / session_id).exists())

    def test_B8C05_partial_cleanup_is_idempotent(self):
        write_submit_host(self.host)
        session_a = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T010000Z-aaaaaaaa",
        )
        session_b = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T010000Z-bbbbbbbb",
            replace_links=False,
        )
        write_ready_task(self.host, develop_session_ids=[session_a, session_b])
        first = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_cleanup_sessions=[session_b],
        )
        self.assertNotEqual(first.outcome, "COMPLETED")
        self.assertIn(session_a, first.extras["cleanup"]["cleaned"])
        self.assertIn(session_b, first.extras["cleanup"]["retained"])
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertFalse((self.host / SESSIONS_DIR / session_b).exists())

    def test_B8C06_s10_failure_never_runs_cleanup(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_s10=True,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertFalse(result.extras["cleanup"]["performed"])
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())

    def test_B8C07_malformed_unresolvable_cleanup_state(self):
        write_submit_host(self.host)
        session_id = "dev-20260903T010000Z-cccccccc"
        directory = self.host / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write(directory, "session.yaml", "bad: [\n")
        write_ready_task(self.host, develop_session_ids=[session_id])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertNotEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.extras["stage"], "S12")
        self.assertTrue(result.extras["s10_durable"])
        self.assertTrue(is_durable(self.host, result.extras["change_record"]["record_id"]))
        self.assertTrue((self.host / SESSIONS_DIR / session_id).is_dir())

    def test_B8C08_successful_cleanup_regression(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras["stage"], "S12")
        self.assertIn(session_id, result.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_id).exists())

    def test_B8C09_post_s10_new_session_is_not_cleaned(self):
        first = self._finalize_with_cleanup_failure()
        session_a = "dev-20260903T180000Z-abcd1234"
        self.assertTrue((self.host / SESSIONS_DIR / session_a).is_dir())
        session_b = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T181000Z-bbbbbbbb",
        )
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertIn(session_a, retry.extras["cleanup"]["cleaned"])
        self.assertNotIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())

    def test_B8C10_restart_uses_change_record_target_snapshot(self):
        first = self._finalize_with_cleanup_failure()
        session_a = "dev-20260903T180000Z-abcd1234"
        session_b = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T181000Z-bbbbbbbb",
        )
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertIn(session_b, task.get("develop_session_ids") or [])
        restarted = SubmitEngine(self.host)
        retry = restarted.run(cleanup_retry=first.extras["cleanup_retry"])
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        frozen = (first.extras["change_record"].get("provenance") or {}).get(
            "relevant_develop_session_ids"
        )
        self.assertEqual(frozen, [session_a])
        self.assertIn(session_a, retry.extras["cleanup"]["cleaned"])
        self.assertNotIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertTrue((self.host / SESSIONS_DIR / session_b).is_dir())

    def test_B8C11_partial_cleanup_plus_later_session(self):
        write_submit_host(self.host)
        session_a = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T010000Z-aaaaaaaa",
        )
        session_b = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T010000Z-bbbbbbbb",
        )
        engine = submit_engine(self.host)
        first = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_cleanup_sessions=[session_b],
        )
        self.assertNotEqual(first.outcome, "COMPLETED")
        self.assertEqual(
            first.extras["change_record"]["provenance"]["relevant_develop_session_ids"],
            [session_a, session_b],
        )
        self.assertIn(session_a, first.extras["cleanup"]["cleaned"])
        self.assertIn(session_b, first.extras["cleanup"]["retained"])
        session_c = self._write_sealed_session(
            ["src/app.py"],
            session_id="dev-20260903T010000Z-cccccccc",
        )
        retry = submit_engine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertIn(session_b, retry.extras["cleanup"]["cleaned"])
        self.assertNotIn(session_c, retry.extras["cleanup"]["cleaned"])
        self.assertFalse((self.host / SESSIONS_DIR / session_a).exists())
        self.assertFalse((self.host / SESSIONS_DIR / session_b).exists())
        self.assertTrue((self.host / SESSIONS_DIR / session_c).is_dir())

    def test_B8C12_durable_change_record_contains_exact_cleanup_target_set(self):
        write_submit_host(self.host)
        session_id = self._write_sealed_session(["src/app.py"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record = result.extras["change_record"]
        self.assertEqual(
            record["provenance"]["relevant_develop_session_ids"],
            [session_id],
        )
        durable = read_yaml(
            self.host / CHANGES_DIR / f"{record['record_id']}.yaml"
        )
        self.assertEqual(
            durable["provenance"]["relevant_develop_session_ids"],
            [session_id],
        )
        self.assertNotIn("submit_authorized", durable)
        self.assertNotIn("grant_ref", durable)
        self.assertNotIn("attempt_id", durable)
        self.assertNotIn("authorization_attempt_id", durable)
        self.assertNotIn("submit_authorized", durable.get("provenance") or {})
        self.assertNotIn("grant_ref", durable.get("provenance") or {})

    def test_B8X01_cleanup_retry_does_not_repeat_s10(self):
        first = self._finalize_with_cleanup_failure()
        self.assertTrue(first.extras["s10"]["durable"])
        retry = SubmitEngine(self.host).run(
            cleanup_retry=first.extras["cleanup_retry"],
        )
        self.assertEqual(retry.outcome, "COMPLETED", retry.blockers)
        self.assertFalse(retry.extras.get("submit_authorized"))
        self.assertNotIn("submit_authorization_ref", retry.extras.get("cleanup_retry") or {})
        self.assertNotIn("grant", str(retry.extras.get("cleanup_retry") or {}).lower())

    def _finalize_with_cleanup_failure(self, *, keep_auth: bool = False):
        write_submit_host(self.host)
        self._write_sealed_session(["src/app.py"])
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            fail_cleanup=True,
        )
        del keep_auth
        return result

    def _write_sealed_session(
        self,
        files: list[str],
        *,
        session_id: str = "dev-20260903T180000Z-abcd1234",
        task_id: str = TASK_A,
        replace_links: bool = True,
    ) -> str:
        directory = self.host / SESSIONS_DIR / session_id
        directory.mkdir(parents=True, exist_ok=True)
        write_yaml_atomic(
            directory / "session.yaml",
            {
                "record_type": "develop_session",
                "schema_version": "1",
                "record_id": session_id,
                "created_at": "2026-09-03T18:00:00Z",
                "updated_at": "2026-09-03T18:00:00Z",
                "status": "SEALED",
                "task_id": task_id,
                "mode": "normal_task",
                "project_name": self.host.name,
                "baseline": {"kind": "none", "value": None},
                "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                "observed_candidate_digest": observe_candidate(self.host).digest,
            },
        )
        write_yaml_atomic(
            directory / "files.yaml",
            {"files": [{"path": path} for path in files]},
        )
        if task_id == TASK_A and replace_links:
            existing = []
            task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            if task_path.is_file():
                current = read_yaml(task_path)
                existing = list(current.get("develop_session_ids") or [])
            write_ready_task(
                self.host,
                develop_session_ids=list(dict.fromkeys(existing + [session_id])),
            )
        return session_id


if __name__ == "__main__":
    unittest.main()

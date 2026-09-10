from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from p8_support import (
    OPERATION_PUSH,
    OPERATION_S10,
    TASK_A,
    authorized_submit_engine,
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
from scaffold_p8.authorization import consume_trusted_grant
from scaffold_p8.engine import SubmitEngine
from scaffold_p8.models import CHANGES_DIR, NOSCMS_PUBLICATIONS_DIR
from scaffold_p8.noscms import COMPLETE_NAME
from scaffold_p8.records import is_durable
from support import write


class _AlwaysGrantProvider:
    def validate(self, **_kwargs):
        return {"ok": True, "reason": "", "consumed": False}

    def consume(self, **_kwargs):
        return {"ok": True, "reason": "", "consumed": True}


class _AlwaysDenyProvider:
    def validate(self, **_kwargs):
        return {"ok": False, "reason": "forged provider denied", "consumed": False}

    def consume(self, **_kwargs):
        return {"ok": False, "reason": "forged provider denied", "consumed": False}


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
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorized={"granted": True, "candidate_digest": digest},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S6")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertFalse(any((self.host / CHANGES_DIR).glob("*.yaml")))
        self.assertTrue(any("SUBMIT_AUTHORIZED" in item or "not trusted" in item for item in result.blockers))

    def test_B8A02_trusted_one_shot_s10_grant(self):
        write_submit_host(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        result = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=provider.issue(
                operation=OPERATION_S10,
                candidate_digest=digest,
                attempt_id="A1",
            ),
            submit_authorization_attempt_id="A1",
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertTrue(is_durable(self.host, result.extras["change_record"]["record_id"]))

    def test_B8A03_same_grant_replay_fails_with_same_candidate(self):
        write_submit_host(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        first = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
            fail_s10=True,
        )
        self.assertEqual(first.outcome, "BLOCKED")
        self.assertFalse(first.extras["s10"]["durable"])
        bind_ready_completion_authority(self.host)
        second = SubmitEngine(
            self.host,
            authorization_provider=provider,
        ).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
        )
        self.assertEqual(second.outcome, "BLOCKED")
        self.assertFalse(second.extras["s10"]["durable"])
        joined = " ".join(second.blockers)
        self.assertIn("consumed", joined)
        self.assertNotIn("C1 authorization is unusable for C2", joined)

    def test_B8A04_c1_grant_cannot_authorize_c2(self):
        write_submit_host(self.host)
        engine, provider = authorized_submit_engine(self.host)
        c1 = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=c1,
            attempt_id="A1",
        )
        write(self.host, "src/app.py", "value = 2\n")
        result = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertTrue(
            any("C1 authorization is unusable for C2" in item for item in result.blockers)
        )

    def test_B8A05_operation_separation(self):
        write_submit_host(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        s10_ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        s10_as_push = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A2",
        )
        push_ref = provider.issue(
            operation=OPERATION_PUSH,
            candidate_digest=digest,
            attempt_id="P1",
        )
        bind_ready_completion_authority(self.host)
        push_as_s10 = SubmitEngine(
            self.host,
            authorization_provider=provider,
        ).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=push_ref,
            submit_authorization_attempt_id="P1",
        )
        self.assertEqual(push_as_s10.outcome, "BLOCKED")
        self.assertFalse(push_as_s10.extras["s10"]["durable"])
        self.assertTrue(
            any("operation" in item for item in push_as_s10.blockers)
        )
        s10_then_push = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=s10_ref,
            submit_authorization_attempt_id="A1",
            push_authorization_ref=s10_as_push,
            push_authorization_attempt_id="A2",
        )
        self.assertTrue(s10_then_push.extras["s10"]["durable"])
        self.assertFalse(s10_then_push.extras["push"].get("ok"))
        self.assertTrue(
            "operation" in str(s10_then_push.extras["push"].get("reason") or "")
        )

    def test_B8A06_provider_cannot_be_forged_through_run_opts(self):
        write_submit_host(self.host)
        digest = observe_candidate(self.host).digest
        forged = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            authorization_provider=_AlwaysGrantProvider(),
            submit_authorization_ref="forged-ref",
        )
        self.assertEqual(forged.outcome, "BLOCKED")
        self.assertFalse(forged.extras["s10"]["durable"])
        engine, provider = authorized_submit_engine(self.host)
        trusted = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=provider.issue(
                operation=OPERATION_S10,
                candidate_digest=digest,
                attempt_id="A1",
            ),
            submit_authorization_attempt_id="A1",
            authorization_provider=_AlwaysDenyProvider(),
        )
        self.assertEqual(trusted.outcome, "COMPLETED", trusted.blockers)
        self.assertTrue(trusted.extras["s10"]["durable"])

    def test_B8A07_no_provider_no_grant(self):
        write_submit_host(self.host)
        reviewed = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(reviewed.outcome, "COMPLETED")
        self.assertEqual(reviewed.next_route, "human")
        self.assertFalse(reviewed.extras["s10"]["durable"])
        self.assertEqual(
            reviewed.extras["authorization_request"]["operation"],
            OPERATION_S10,
        )
        blocked = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertEqual(blocked.extras["stage"], "S6")
        self.assertFalse(blocked.extras["s10"]["durable"])

    def test_B8A08_concurrent_same_grant_consumption(self):
        write_submit_host(self.host)
        provider_engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        consume_ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        consume_results: list = []
        consume_barrier = threading.Barrier(2)

        def consume_once():
            consume_barrier.wait()
            consume_results.append(
                provider.consume(
                    operation=OPERATION_S10,
                    grant_ref=consume_ref,
                    attempt_id="A1",
                    candidate_digest=digest,
                )
            )

        consume_threads = [threading.Thread(target=consume_once) for _ in range(2)]
        for thread in consume_threads:
            thread.start()
        for thread in consume_threads:
            thread.join()
        ok_consume = [item for item in consume_results if item.get("ok")]
        replay = [
            item
            for item in consume_results
            if not item.get("ok")
            and (
                item.get("consumed") is True
                or "consumed" in str(item.get("reason") or "").lower()
                or "replay" in str(item.get("reason") or "").lower()
            )
        ]
        self.assertEqual(len(consume_results), 2)
        self.assertEqual(len(ok_consume), 1)
        self.assertEqual(len(replay), 1)

        engine_ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A2",
        )
        results: list = []
        barrier = threading.Barrier(2)
        bind_ready_completion_authority(self.host)

        def attempt():
            barrier.wait()
            engine = SubmitEngine(self.host, authorization_provider=provider)
            results.append(
                engine.run(
                    task_id=TASK_A,
                    invoke_test=True,
                    selected=["unit"],
                    finalize=True,
                    submit_authorization_ref=engine_ref,
                    submit_authorization_attempt_id="A2",
                )
            )

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        del provider_engine
        durable = [item for item in results if item.extras.get("s10", {}).get("durable")]
        losers = [
            item
            for item in results
            if not item.extras.get("s10", {}).get("durable")
        ]
        self.assertEqual(len(results), 2)
        self.assertEqual(len(durable), 1)
        self.assertEqual(len(losers), 1)
        self.assertNotEqual(losers[0].outcome, "COMPLETED")
        change_dir = self.host / CHANGES_DIR
        change_ids = (
            [path.stem for path in change_dir.glob("*.yaml")]
            if change_dir.is_dir()
            else []
        )
        durable_changes = [
            record_id for record_id in change_ids if is_durable(self.host, record_id)
        ]
        self.assertEqual(len(durable_changes), 1)

    def test_B8A09_push_is_one_shot(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        s10_ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        push_ref = provider.issue(
            operation=OPERATION_PUSH,
            candidate_digest=digest,
            attempt_id="P1",
        )
        first = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=s10_ref,
            submit_authorization_attempt_id="A1",
            push_authorization_ref=push_ref,
            push_authorization_attempt_id="P1",
            fail_push=True,
        )
        self.assertTrue(first.extras["s10"]["durable"])
        self.assertTrue(first.extras["push"]["performed"])
        self.assertFalse(first.extras["push"]["ok"])
        commit = first.extras["s10"]["commit"]
        replay = consume_trusted_grant(
            provider,
            operation=OPERATION_PUSH,
            grant_ref=push_ref,
            attempt_id="P1",
            candidate_digest=digest,
        )
        self.assertFalse(replay.get("ok"))
        self.assertIn("consumed", replay.get("reason") or "")
        self.assertEqual(is_durable(self.host, first.extras["change_record"]["record_id"]), True)
        from p6_support import git

        self.assertEqual(git(self.host, "rev-parse", "HEAD"), commit)

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
            self.assertNotIn(token, blob)
        self.assertFalse((self.host / SESSIONS_DIR / session_id).exists())

    def test_B8A11_attempt_a1_grant_cannot_authorize_a2(self):
        write_submit_host(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        as_a2 = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A2",
        )
        self.assertEqual(as_a2.outcome, "BLOCKED")
        self.assertEqual(as_a2.extras["stage"], "S6")
        self.assertFalse(as_a2.extras["s10"]["durable"])
        self.assertTrue(
            any("attempt" in item for item in as_a2.blockers)
        )
        self.assertTrue(
            any("does not match" in item for item in as_a2.blockers)
        )
        still = provider.validate(
            operation=OPERATION_S10,
            grant_ref=ref,
            attempt_id="A1",
            candidate_digest=digest,
        )
        self.assertTrue(still.get("ok"))
        self.assertFalse(still.get("consumed"))
        bind_ready_completion_authority(self.host)
        as_a1 = SubmitEngine(
            self.host,
            authorization_provider=provider,
        ).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
        )
        self.assertEqual(as_a1.outcome, "COMPLETED", as_a1.blockers)
        self.assertTrue(as_a1.extras["s10"]["durable"])

    def test_B8A12_authorization_request_carries_attempt_identity(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        request = result.extras["authorization_request"]
        attempt = request.get("authorization_attempt_id")
        self.assertIsInstance(attempt, str)
        self.assertTrue(attempt.strip())
        self.assertEqual(request["operation"], OPERATION_S10)
        self.assertEqual(
            request["candidate_digest"],
            observe_candidate(self.host).digest,
        )
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse(result.extras["s10"]["durable"])
        replay = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_attempt_id=attempt,
        )
        self.assertEqual(replay.outcome, "BLOCKED")
        self.assertEqual(replay.extras["stage"], "S6")
        self.assertFalse(replay.extras["s10"]["durable"])

    def test_B8A13_caller_minted_attempt_without_grant_has_no_authority(self):
        write_submit_host(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_attempt_id="caller-forged-A9",
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S6")
        self.assertFalse(result.extras["submit_authorized"])
        self.assertFalse(result.extras["s10"]["durable"])
        self.assertFalse(any((self.host / CHANGES_DIR).glob("*.yaml")))

    def test_B8A14_push_attempt_binding(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        s10_ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        push_ref = provider.issue(
            operation=OPERATION_PUSH,
            candidate_digest=digest,
            attempt_id="P1",
        )
        result = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=s10_ref,
            submit_authorization_attempt_id="A1",
            push_authorization_ref=push_ref,
            push_authorization_attempt_id="P2",
        )
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertFalse(result.extras["push"].get("ok"))
        reason = str(result.extras["push"].get("reason") or "")
        self.assertIn("attempt", reason)
        still = provider.validate(
            operation=OPERATION_PUSH,
            grant_ref=push_ref,
            attempt_id="P1",
            candidate_digest=digest,
        )
        self.assertTrue(still.get("ok"))
        self.assertFalse(still.get("consumed"))
        self.assertTrue(
            is_durable(self.host, result.extras["change_record"]["record_id"])
        )
        from p6_support import git

        self.assertEqual(
            git(self.host, "rev-parse", "HEAD"),
            result.extras["s10"]["commit"],
        )

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
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        first = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=provider.issue(
                operation=OPERATION_S10,
                candidate_digest=digest,
                attempt_id="A1",
            ),
            submit_authorization_attempt_id="A1",
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

    def test_B8X01_cleanup_retry_does_not_need_another_s10_grant(self):
        first, provider, ref = self._finalize_with_cleanup_failure(keep_auth=True)
        self.assertTrue(first.extras["s10"]["durable"])
        bind_ready_completion_authority(self.host)
        replay = SubmitEngine(
            self.host,
            authorization_provider=provider,
        ).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
        )
        self.assertNotEqual(replay.outcome, "COMPLETED")
        self.assertFalse(replay.extras.get("s10", {}).get("durable"))
        self.assertTrue(any("consumed" in item for item in replay.blockers))
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
        engine, provider = authorized_submit_engine(self.host)
        digest = observe_candidate(self.host).digest
        ref = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id="A1",
        )
        result = engine.run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            finalize=True,
            submit_authorization_ref=ref,
            submit_authorization_attempt_id="A1",
            fail_cleanup=True,
        )
        if keep_auth:
            return result, provider, ref
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

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, passing_profile, write_host
from p7_support import (
    TASK_A,
    ensure_noscms_accepted_anchor,
    satisfied_decision,
    write_task,
)
from support import write
from test_consumer_installation import _clean_env, _install
from test_compatibility_lock_update_public import _write_live_lock

from scaffold_p5.first_use import SHELL_ALLOW, SHELL_DENY, classify_first_use_shell
from scaffold_p5.io_util import read_yaml
from scaffold_p7.develop_authority import load_execution_pointer
from scaffold_p7.models import SESSIONS_DIR


REQUIREMENT_ID = "mvp-vault-ladder-loop"
PROFILE_ID = "discovered-package-json-test-unit"
OTHER_REQUIRED = "other-required-project-unit"


def _public(host: Path, *args: str, timeout: int = 180) -> tuple[int, dict, str]:
    runner = host / ".scaffold" / "install" / "run.py"
    proc = subprocess.run(
        [sys.executable, str(runner), *args],
        cwd=str(host),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    text = (proc.stdout or "").strip()
    payload = json.loads(text) if text else {}
    return proc.returncode, payload, proc.stderr or ""


def _touch_runner(host: Path) -> None:
    runner = host / ".scaffold" / "install" / "run.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text("#!/usr/bin/env python3\n", encoding="utf-8")


def _session_record_ids(host: Path) -> set[str]:
    folder = host / SESSIONS_DIR
    if not folder.is_dir():
        return set()
    return {path.name for path in folder.iterdir() if path.is_dir()}


class PublicLifecycleCompletionSurfaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_first_use_allows_resume_bind_complete_after_adoption(self):
        _touch_runner(self.host)
        allowed = [
            "python .scaffold/install/run.py understand refresh --action resume",
            "python .scaffold/install/run.py develop bind --task-id "
            + TASK_A
            + " --requirement-id "
            + REQUIREMENT_ID
            + " --profile-id "
            + PROFILE_ID,
            "python .scaffold/install/run.py develop complete --task-id "
            + TASK_A
            + " --complete-json-b64 eyJyZWFkeSI6dHJ1ZX0=",
        ]
        for command in allowed:
            kind, detail = classify_first_use_shell(
                command, self.host, adopted=True
            )
            self.assertEqual(kind, SHELL_ALLOW, (command, detail))
        denied = classify_first_use_shell(
            "python .scaffold/install/run.py understand refresh --action lock_update",
            self.host,
            adopted=True,
        )
        self.assertEqual(denied[0], SHELL_DENY, denied)
        self.assertIn("compatibility", denied[1])

    def test_bind_grounding_cas_and_lifecycle(self):
        self._prepare_installed_host()
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "PENDING",
                    "required_tests": [{"requirement_id": REQUIREMENT_ID}],
                }
            ],
        )
        missing_req = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            "not-a-requirement",
            "--profile-id",
            PROFILE_ID,
        )[1]
        self.assertEqual(missing_req.get("outcome"), "BLOCKED", missing_req)
        self.assertTrue(
            any("does not exist" in str(item) for item in missing_req.get("blockers") or [])
        )

        missing_profile = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            "not-a-profile",
        )[1]
        self.assertEqual(missing_profile.get("outcome"), "BLOCKED", missing_profile)
        self.assertTrue(
            any(
                "not grounded in tests.yaml" in str(item)
                for item in missing_profile.get("blockers") or []
            )
        )

        bad_kind = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
            "--kind",
            "command",
        )[1]
        self.assertEqual(bad_kind.get("outcome"), "BLOCKED", bad_kind)

        code, bound, _err = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
        )
        self.assertEqual(bound.get("outcome"), "COMPLETED", bound)
        self.assertEqual(bound.get("mutations"), "task_book", bound)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        item = task["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], REQUIREMENT_ID)
        self.assertEqual(item["execution_binding"]["kind"], "test_profile")
        self.assertEqual(item["execution_binding"]["profile_id"], PROFILE_ID)
        self.assertNotEqual(item["requirement_id"], item["execution_binding"]["profile_id"])
        self.assertEqual(task["record_revision"], 2)
        first_rev = task["record_revision"]

        again = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
        )[1]
        self.assertEqual(again.get("outcome"), "COMPLETED", again)
        self.assertEqual(again.get("mutations"), "none", again)
        self.assertEqual(
            read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")["record_revision"],
            first_rev,
        )

        write_task(self.host, status="DRAFT", record_revision=1)
        draft = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
        )[1]
        self.assertEqual(draft.get("outcome"), "BLOCKED", draft)

    def test_complete_cannot_manufacture_ready(self):
        self._prepare_installed_host()
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "PENDING",
                    "required_tests": [{"requirement_id": REQUIREMENT_ID}],
                }
            ],
        )
        session = _public(
            self.host, "develop", "session", "--task-id", TASK_A, timeout=240
        )[1]
        self.assertEqual(session.get("outcome"), "COMPLETED", session)
        envelope = json.dumps({"ready": True}, separators=(",", ":"))
        payload = _public(
            self.host,
            "develop",
            "complete",
            "--task-id",
            TASK_A,
            "--complete-json",
            envelope,
            timeout=240,
        )[1]
        self.assertEqual(payload.get("outcome"), "BLOCKED", payload)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertNotEqual(task.get("status"), "READY_FOR_REVIEW")

    def test_complete_without_open_session_does_not_absorb_edits(self):
        self._prepare_installed_host()
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "PENDING",
                    "required_tests": [{"requirement_id": REQUIREMENT_ID}],
                }
            ],
        )
        bound = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
        )[1]
        self.assertEqual(bound.get("outcome"), "COMPLETED", bound)
        write(self.host, "src/app.py", "value = 1\npre-session edit\n")
        mutated = (self.host / "src" / "app.py").read_bytes()
        before_sessions = _session_record_ids(self.host)
        envelope = {
            "test": {"invoke": True},
            "stage_decision": satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    }
                ],
            ),
            "task_decision": satisfied_decision(
                basis=[
                    {
                        "kind": "task_fact",
                        "summary": "Stage acceptance and Task-level acceptance are satisfied.",
                    }
                ]
            ),
            "complete_stage": True,
            "ready": True,
        }
        payload = _public(
            self.host,
            "develop",
            "complete",
            "--task-id",
            TASK_A,
            "--complete-json",
            json.dumps(envelope, separators=(",", ":")),
            timeout=240,
        )[1]
        self.assertEqual(payload.get("outcome"), "BLOCKED", payload)
        self.assertTrue(
            any("develop session" in str(item).lower() for item in payload.get("blockers") or [])
            or "develop.session" == payload.get("next_route"),
            payload,
        )
        self.assertEqual(_session_record_ids(self.host), before_sessions)
        pointer, pointer_error = load_execution_pointer(self.host)
        self.assertEqual(pointer_error, "")
        self.assertIsNone(pointer)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task.get("status"), "IN_PROGRESS", task)
        self.assertNotEqual(task.get("status"), "READY_FOR_REVIEW")
        self.assertNotEqual((task.get("stages") or [{}])[0].get("status"), "COMPLETE")
        self.assertEqual((self.host / "src" / "app.py").read_bytes(), mutated)

        opened = _public(
            self.host, "develop", "session", "--task-id", TASK_A, timeout=240
        )[1]
        self.assertEqual(opened.get("outcome"), "COMPLETED", opened)
        session_id = ((opened.get("extras") or {}).get("session") or {}).get("record_id")
        self.assertTrue(session_id, opened)
        complete = _public(
            self.host,
            "develop",
            "complete",
            "--task-id",
            TASK_A,
            "--complete-json",
            json.dumps(envelope, separators=(",", ":")),
            timeout=300,
        )[1]
        self.assertEqual(complete.get("outcome"), "COMPLETED", complete)
        extras = complete.get("extras") or {}
        test_to_develop = extras.get("test_to_develop") or {}
        self.assertTrue(test_to_develop.get("test_pass"), test_to_develop)
        self.assertIs(test_to_develop.get("test_complete"), False, test_to_develop)
        self.assertTrue(extras.get("ready_for_review"), extras)
        self.assertEqual((extras.get("session") or {}).get("status"), "SEALED", extras)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW", task)
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        locator = task["stages"][0]["required_tests"][0].get("evidence_ref", {}).get("locator")
        self.assertTrue(str(locator).startswith("test-runs/"), locator)
        persisted = read_yaml(
            self.host / SESSIONS_DIR / str(session_id) / "session.yaml"
        )
        self.assertEqual(persisted.get("status"), "SEALED")

    def test_public_e2e_resume_bind_test_complete_ready_seal(self):
        self._prepare_installed_host()
        write_task(
            self.host,
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Write the fixture source.",
                    "acceptance": "src/app.py has the expected content.",
                    "status": "PENDING",
                    "required_tests": [{"requirement_id": REQUIREMENT_ID}],
                }
            ],
        )

        code, resume, resume_err = _public(
            self.host,
            "understand",
            "refresh",
            "--action",
            "resume",
            timeout=240,
        )
        self.assertEqual(resume.get("outcome"), "COMPLETED", resume)
        self.assertEqual(resume.get("mutations"), "none", resume)
        extras = resume.get("extras") or {}
        self.assertTrue(extras.get("observational"), extras)
        self.assertFalse(extras.get("chat_memory", True), extras)
        work = extras.get("work") or {}
        task_rows = work.get("tasks") or []
        self.assertTrue(
            any(
                row.get("record_id") == TASK_A and row.get("status") == "IN_PROGRESS"
                for row in task_rows
                if isinstance(row, dict)
            ),
            work,
        )
        self.assertIn("scaffold: WORKING", resume_err)

        code, bound, _err = _public(
            self.host,
            "develop",
            "bind",
            "--task-id",
            TASK_A,
            "--requirement-id",
            REQUIREMENT_ID,
            "--profile-id",
            PROFILE_ID,
        )
        self.assertEqual(bound.get("outcome"), "COMPLETED", bound)
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        item = task["stages"][0]["required_tests"][0]
        self.assertEqual(item["requirement_id"], REQUIREMENT_ID)
        self.assertEqual(item["execution_binding"]["profile_id"], PROFILE_ID)
        self.assertNotEqual(item["requirement_id"], item["execution_binding"]["profile_id"])

        code, session, session_err = _public(
            self.host,
            "develop",
            "session",
            "--task-id",
            TASK_A,
            timeout=240,
        )
        self.assertEqual(session.get("outcome"), "COMPLETED", session)
        self.assertIn("scaffold: WORKING", session_err)
        session_id = ((session.get("extras") or {}).get("session") or {}).get("record_id")
        self.assertTrue(session_id, session)

        envelope = {
            "test": {"invoke": True},
            "stage_decision": satisfied_decision(
                stage_id="stage-1",
                basis=[
                    {
                        "kind": "repository_observation",
                        "summary": "src/app.py has the expected content.",
                    },
                    {
                        "kind": "test_evidence",
                        "summary": "Bound requirement verification passed for this candidate.",
                    },
                ],
            ),
            "task_decision": satisfied_decision(
                basis=[
                    {
                        "kind": "task_fact",
                        "summary": "Stage acceptance and Task-level acceptance are satisfied.",
                    },
                ]
            ),
            "complete_stage": True,
            "ready": True,
        }
        code, complete, complete_err = _public(
            self.host,
            "develop",
            "complete",
            "--task-id",
            TASK_A,
            "--complete-json",
            json.dumps(envelope, separators=(",", ":")),
            timeout=300,
        )
        self.assertEqual(complete.get("outcome"), "COMPLETED", complete)
        self.assertIn("scaffold: WORKING", complete_err)
        extras = complete.get("extras") or {}
        test_to_develop = extras.get("test_to_develop") or {}
        self.assertTrue(test_to_develop.get("test_pass"), test_to_develop)
        self.assertIs(test_to_develop.get("test_complete"), False, test_to_develop)
        self.assertTrue(extras.get("ready_for_review"), extras)
        session_row = extras.get("session") or {}
        self.assertEqual(session_row.get("status"), "SEALED", extras)

        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(task["status"], "READY_FOR_REVIEW", task)
        self.assertEqual(task["stages"][0]["status"], "COMPLETE")
        self.assertEqual(task["stages"][0]["completion_decision"]["outcome"], "SATISFIED")
        self.assertEqual(task["task_completion_decision"]["outcome"], "SATISFIED")
        locator = task["stages"][0]["required_tests"][0].get("evidence_ref", {}).get("locator")
        self.assertTrue(str(locator).startswith("test-runs/"), locator)
        persisted = read_yaml(
            self.host / SESSIONS_DIR / str(session_id) / "session.yaml"
        )
        self.assertEqual(persisted.get("status"), "SEALED")

        adapters = (
            self.host / ".cursor" / "skills" / "scaffold-understand" / "SKILL.md"
        ).read_text(encoding="utf-8")
        develop_adapter = (
            self.host / ".cursor" / "skills" / "scaffold-develop" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("understand refresh --action resume", adapters)
        self.assertIn("develop bind", develop_adapter)
        self.assertIn("develop complete", develop_adapter)

    def _prepare_installed_host(self) -> None:
        bound_profile, bound_command = passing_profile(PROFILE_ID)
        other_profile, other_command = passing_profile(OTHER_REQUIRED)
        _install(self.host)
        write_host(
            self.host,
            [(bound_profile, bound_command), (other_profile, other_command)],
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        _write_live_lock(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        ensure_noscms_accepted_anchor(self.host)


if __name__ == "__main__":
    unittest.main()

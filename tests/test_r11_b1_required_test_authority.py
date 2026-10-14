"""R11-B1 required-test authority after the focused audit correction."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from p6_support import (
    REPO_TEST,
    failing_profile,
    init_git,
    passing_profile,
    test_engine as make_test_engine,
    write_commands,
    write_host,
    write_project,
    write_tests,
)
from p7_support import (
    TASK_A,
    develop_engine,
    ensure_noscms_accepted_anchor,
    write_active_host,
    write_task,
)
from p8_support import rebind_noscms_baseline, run_submit, write_submit_host
from scaffold_p5.consumer_install import import_project, installed_main
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.first_use import SHELL_ALLOW, SHELL_DENY, classify_first_use_shell, hook_main
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.preflight import PreflightDecision
from scaffold_p5.refresh import refresh_host
from scaffold_p5.required_tests import (
    POLICY_REL,
    STAGING_REL,
    establish_required_tests,
    reconcile_required_authority,
)
from scaffold_p8.completeness import evaluate_completeness
from support import REPO, adopt, distribution, write


POLICY_REQUIRED = """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
  - package.json#scripts.test-extra
"""
POLICY_ZERO = """schema_version: "1"
kind: required_test_policy
policy: zero_required
required_sources: []
"""


def _proposal(**extra) -> dict:
    payload = {"publish": True}
    payload.update(extra)
    return payload


class RequiredTestAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name)
        self._path = os.environ.get("PATH", "")

    def tearDown(self) -> None:
        os.environ["PATH"] = self._path
        self._tmp.cleanup()

    def test_policy_publish_refresh_test_and_s5(self) -> None:
        self._package_host(POLICY_REQUIRED)
        first = refresh_host(self.host)
        self.assertTrue(first.get("ok"), first.get("conflicts"))
        before = read_yaml(self.host / ".scaffold/tests.yaml")
        discovery_confidence = before["confidence"]
        self.assertEqual(before["required_authority"], "UNKNOWN")

        narrowed = establish_required_tests(
            self.host,
            proposal=_proposal(required_profile_ids=["discovered-package-json-test"]),
        )
        self.assertFalse(narrowed["ok"])
        self.assertIn("cannot narrow or widen", narrowed["blockers"][0])

        preview = establish_required_tests(self.host, proposal=_proposal())
        self.assertTrue(preview["ok"], preview)
        self.assertFalse(preview["wrote"])
        self.assertEqual(preview["plan"]["required_profile_ids"], [
            "discovered-package-json-test",
            "discovered-package-json-test-extra",
        ])
        self.assertEqual(
            read_yaml(self.host / ".scaffold/tests.yaml")["confidence"],
            discovery_confidence,
        )
        stale = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest="0" * 64,
        )
        self.assertFalse(stale["ok"])

        staging = self.host / STAGING_REL
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text(json.dumps(_proposal()) + "\n", encoding="utf-8")
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
            staging_path=STAGING_REL,
        )
        self.assertTrue(applied["ok"], applied)
        self.assertFalse(staging.exists())
        published = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(published["confidence"], discovery_confidence)
        self.assertEqual(published["required_authority"], "VERIFIED")
        self.assertTrue(_profile(published, "discovered-package-json-test")["required"])
        self.assertTrue(_profile(published, "discovered-package-json-test-extra")["required"])
        self.assertEqual(
            _profile(published, "observed-tests")["required_authority"],
            "UNKNOWN",
        )
        self.assertFalse(_profile(published, "observed-tests")["required"])

        again = refresh_host(self.host)
        self.assertTrue(again.get("ok"), again.get("conflicts"))
        self.assertFalse(again.get("authority_diagnostics"))
        kept = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(kept["confidence"], discovery_confidence)
        self.assertEqual(kept["required_authority"], "VERIFIED")

        self._commit()
        self._npm(0)
        selected = [
            "discovered-package-json-test",
            "discovered-package-json-test-extra",
        ]
        completed = make_test_engine(self.host).run(selected=selected)
        completeness = completed.extras["completeness"]
        self.assertEqual(completeness["required_policy"], "VERIFIED")
        self.assertTrue(completeness["test_complete"], completeness)
        judged = evaluate_completeness(
            self.host,
            task=None,
            report=None,
            invoke=False,
            selected=selected,
            test_package=REPO_TEST,
            report_id=completed.extras["report_id"],
        )
        self.assertTrue(judged["test_complete"], judged)

    def test_inferred_discovery_confidence_stays_inferred(self) -> None:
        write_active_host(self.host)
        write(self.host, "src/app.ts", "export const value = 1;\n")
        write(
            self.host,
            "package.json",
            json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
        )
        project = read_yaml(self.host / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write(self.host, POLICY_REL, """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
""")
        self._accept_policy()
        refreshed = refresh_host(self.host)
        self.assertTrue(refreshed.get("ok"), refreshed.get("conflicts") or refreshed)
        discovered = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(discovered["confidence"], "INFERRED")
        preview = establish_required_tests(self.host, proposal=_proposal())
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        published = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(published["confidence"], "INFERRED")
        self.assertEqual(published["required_authority"], "VERIFIED")
        kept = refresh_host(self.host)
        self.assertTrue(kept.get("ok"), kept.get("conflicts"))
        self.assertEqual(read_yaml(self.host / ".scaffold/tests.yaml")["confidence"], "INFERRED")

    def test_script_body_change_invalidates_without_argv_change(self) -> None:
        self._package_host(POLICY_REQUIRED)
        self.assertTrue(refresh_host(self.host).get("ok"))
        preview = establish_required_tests(self.host, proposal=_proposal())
        establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        package = json.loads((self.host / "package.json").read_text(encoding="utf-8"))
        package["scripts"]["test-extra"] = "vitest run extra --changed"
        write(self.host, "package.json", json.dumps(package) + "\n")
        refreshed = refresh_host(self.host)
        self.assertTrue(refreshed.get("authority_diagnostics"))
        self.assertIn("no longer matches", " ".join(refreshed["authority_diagnostics"]))
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(tests["required_authority"], "UNKNOWN")
        command = next(
            row
            for row in read_yaml(self.host / ".scaffold/commands.yaml")["commands"]
            if row["id"] == "package-json-test-extra"
        )
        self.assertEqual(command["argv"], ["npm", "run", "test-extra"])

    def test_zero_required_needs_policy_and_unknown_confidence_can_complete(self) -> None:
        self._package_host(POLICY_ZERO)
        self.assertTrue(refresh_host(self.host).get("ok"))
        refused = establish_required_tests(
            self.host,
            proposal=_proposal(zero_required=True, required_profile_ids=["discovered-package-json-test"]),
        )
        self.assertFalse(refused["ok"])
        missing = self.host / POLICY_REL
        missing.unlink()
        absent = establish_required_tests(self.host, proposal=_proposal(zero_required=True))
        self.assertFalse(absent["ok"])
        self.assertIn("stays UNKNOWN", absent["blockers"][0])
        write(self.host, POLICY_REL, POLICY_ZERO)
        self._accept_policy()
        preview = establish_required_tests(
            self.host,
            proposal=_proposal(zero_required=True),
        )
        self.assertTrue(preview["ok"], preview)
        before = read_yaml(self.host / ".scaffold/tests.yaml")["confidence"]
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(zero_required=True),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(tests["confidence"], before)
        self.assertEqual(tests["required_authority"], "VERIFIED")
        self.assertFalse(any(row.get("required") for row in tests["profiles"]))
        self._commit()
        judged = evaluate_completeness(
            self.host,
            task=None,
            report=None,
            invoke=True,
            selected=[],
            test_package=REPO_TEST,
        )
        self.assertTrue(judged["test_complete"], judged)

    def test_failed_stale_and_corrupt_grounding_stay_rejected(self) -> None:
        self._package_host(POLICY_REQUIRED)
        self.assertTrue(refresh_host(self.host).get("ok"))
        self._commit()
        self._npm(0)
        selected = [
            "discovered-package-json-test",
            "discovered-package-json-test-extra",
        ]
        before = make_test_engine(self.host).run(selected=selected)
        self.assertFalse(before.extras["completeness"]["test_complete"])
        early = evaluate_completeness(
            self.host,
            task=None,
            report=None,
            invoke=False,
            selected=selected,
            test_package=REPO_TEST,
            report_id=before.extras["report_id"],
        )
        self.assertFalse(early["test_complete"])
        self.assertIn("required_tests", " ".join(early["authority_blockers"]))

        preview = establish_required_tests(self.host, proposal=_proposal())
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        profile = _profile(tests, "discovered-package-json-test")
        profile["timeout_seconds"] = 15
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        stale_plan = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertFalse(stale_plan["ok"])
        self.assertEqual(
            read_yaml(self.host / ".scaffold/tests.yaml")["required_authority"],
            "UNKNOWN",
        )
        profile["timeout_seconds"] = 60
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=establish_required_tests(self.host, proposal=_proposal())["plan_digest"],
        )
        self._npm(1)
        failed = make_test_engine(self.host).run(selected=selected)
        self.assertEqual(failed.extras["completeness"]["required_policy"], "VERIFIED")
        self.assertFalse(failed.extras["completeness"]["test_complete"])
        self._npm(0)
        passed = make_test_engine(self.host).run(selected=selected)
        self.assertTrue(passed.extras["completeness"]["test_complete"])
        write(self.host, "src/app.ts", "export const value = 2;\n")
        stale = evaluate_completeness(
            self.host,
            task=None,
            report=None,
            invoke=False,
            selected=selected,
            test_package=REPO_TEST,
            report_id=passed.extras["report_id"],
        )
        self.assertFalse(stale["test_complete"])
        self.assertTrue(stale["stale_report"] or not stale["usable"])

        current = read_yaml(self.host / ".scaffold/tests.yaml")
        current["required_grounding"]["plan_digest"] = "ab" * 32
        regenerated = json.loads(json.dumps(current))
        diagnostics = reconcile_required_authority(
            self.host,
            regenerated,
            current,
            read_yaml(self.host / ".scaffold/commands.yaml"),
        )
        self.assertTrue(diagnostics)
        self.assertIn("does not match its content", diagnostics[0])
        self.assertEqual(regenerated["required_authority"], "UNKNOWN")

        contradictory = read_yaml(self.host / ".scaffold/tests.yaml")
        contradictory["required_grounding"]["plan"]["zero_required"] = True
        contradictory["required_grounding"]["plan"]["required_profile_ids"] = []
        contradictory["required_grounding"]["plan"]["profiles"] = []
        from scaffold_p5.required_tests import plan_digest_of

        contradictory["required_grounding"]["plan_digest"] = plan_digest_of(
            contradictory["required_grounding"]["plan"]
        )
        regenerated = json.loads(json.dumps(contradictory))
        diagnostics = reconcile_required_authority(
            self.host,
            regenerated,
            contradictory,
            read_yaml(self.host / ".scaffold/commands.yaml"),
        )
        self.assertTrue(diagnostics)
        self.assertIn("zero_required", diagnostics[0])
        self.assertEqual(regenerated["required_authority"], "UNKNOWN")

    def test_submit_s5_accepts_policy_grounded_evidence(self) -> None:
        write_submit_host(self.host, noscms_baseline=False)
        required, required_command = passing_profile("unit", False)
        optional, optional_command = passing_profile("optional", False)
        write(self.host, "scripts/unit.txt", "unit required command\n")
        write(self.host, "scripts/optional.txt", "optional command\n")
        required_command["source"] = "scripts/unit.txt"
        optional_command["source"] = "scripts/optional.txt"
        write_commands(self.host, [required_command, optional_command])
        write_tests(
            self.host,
            [required, optional],
            confidence="UNKNOWN",
            required_authority="UNKNOWN",
        )
        write(
            self.host,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - scripts/unit.txt
""",
        )
        first_baseline = rebind_noscms_baseline(self.host)
        self.assertTrue(first_baseline.get("ok"), first_baseline)
        blocked = run_submit(
            self.host,
            task_id="task-20260829T120000Z-aaa11111",
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(blocked.extras["stage"], "S5")
        self.assertFalse(blocked.extras["completeness"]["test_complete"])
        preview = establish_required_tests(self.host, proposal=_proposal())
        self.assertTrue(preview["ok"], preview)
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        published = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(published["confidence"], "UNKNOWN")
        self.assertEqual(published["required_authority"], "VERIFIED")
        self.assertFalse(_profile(published, "optional")["required"])
        refreshed_baseline = rebind_noscms_baseline(self.host)
        self.assertTrue(refreshed_baseline.get("ok"), refreshed_baseline)
        accepted = run_submit(
            self.host,
            task_id="task-20260829T120000Z-aaa11111",
            invoke_test=True,
            selected=["unit"],
        )
        self.assertNotEqual(accepted.extras.get("stage"), "S5", accepted.blockers)

    def test_hook_allows_only_the_staging_file(self) -> None:
        write_project(self.host)
        runner = self.host / ".scaffold/install/run.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("# launcher\n", encoding="utf-8")
        allowed = _hook(
            self.host,
            "Write",
            {"path": STAGING_REL, "contents": "{\"publish\": true}\n"},
        )
        self.assertEqual(allowed["permission"], "allow", allowed)
        denied_contract = _hook(
            self.host,
            "Write",
            {"path": ".scaffold/tests.yaml", "contents": "schema_version: \"1\"\n"},
        )
        self.assertEqual(denied_contract["permission"], "deny", denied_contract)
        denied_pair = _hook(
            self.host,
            "MultiEdit",
            {
                "edits": [
                    {"path": STAGING_REL},
                    {"path": ".scaffold/project.yaml"},
                ]
            },
        )
        self.assertEqual(denied_pair["permission"], "deny", denied_pair)
        denied_delete = _hook(self.host, "Delete", {"path": STAGING_REL})
        self.assertEqual(denied_delete["permission"], "deny", denied_delete)
        command = (
            "python .scaffold/install/run.py understand refresh --action required_tests "
            "--required-tests-json-file .scaffold/transport/required-tests.json "
            "--plan-digest " + ("ab" * 32)
        )
        kind, detail = classify_first_use_shell(command, self.host, adopted=True)
        self.assertEqual(kind, SHELL_ALLOW, detail)
        bare = classify_first_use_shell(
            "python .scaffold/install/run.py understand refresh --action required_tests",
            self.host,
            adopted=True,
        )
        self.assertEqual(bare[0], SHELL_DENY)

    def test_engine_preview_does_not_require_a_test_report(self) -> None:
        profile, command = passing_profile("unit", False)
        write(self.host, "scripts/unit.txt", "unit\n")
        command["source"] = "scripts/unit.txt"
        write_host(self.host, [(profile, command)])
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        tests["confidence"] = "INFERRED"
        tests["required_authority"] = "UNKNOWN"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        write(
            self.host,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - scripts/unit.txt
""",
        )
        self._accept_policy()
        engine = UnderstandEngine(self.host, distribution())
        preflight = PreflightDecision(
            context="HOST_COMPATIBILITY",
            host_class="ESTABLISHED_HOST",
            allowed=True,
        )
        preview = engine._required_tests(
            snapshot_host(self.host),
            preflight,
            {"proposal": _proposal()},
        )
        self.assertEqual(preview.outcome, "COMPLETED", preview.blockers)
        self.assertEqual(
            read_yaml(self.host / ".scaffold/tests.yaml")["confidence"],
            "INFERRED",
        )
        applied = engine._required_tests(
            snapshot_host(self.host),
            preflight,
            {
                "proposal": _proposal(),
                "plan_digest": preview.extras["required_tests"]["plan_digest"],
            },
        )
        self.assertEqual(applied.outcome, "COMPLETED", applied.blockers)
        published = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(published["confidence"], "INFERRED")
        self.assertEqual(published["required_authority"], "VERIFIED")

    def test_installed_consumer_can_preview_the_public_command(self) -> None:
        project = self.host / "project"
        project.mkdir()
        write(project, "README.md", "# fresh consumer\n")
        write(
            project,
            "package.json",
            json.dumps({"name": "fresh", "scripts": {"test": "node -e process.exit(0)"}}) + "\n",
        )
        write(project, "src/__tests__/a.test.ts", "export {}\n")
        write(project, POLICY_REL, """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
""")
        imported = import_project(project, REPO)
        self.assertIn(imported.get("outcome"), {"PROJECT_SCAFFOLD_READY", "ALREADY_READY"}, imported)
        adopted = adopt(project)
        self.assertEqual(adopted.outcome, "COMPLETED", getattr(adopted, "blockers", None))
        refresh = _run_installed(project, ["understand", "refresh"])
        self.assertEqual(refresh["outcome"], "COMPLETED", refresh.get("blockers"))
        from p6_support import init_git

        init_git(project)
        staging = project / STAGING_REL
        staging.parent.mkdir(parents=True, exist_ok=True)
        staging.write_text(json.dumps(_proposal()) + "\n", encoding="utf-8")
        preview = _run_installed(
            project,
            [
                "understand",
                "refresh",
                "--action",
                "required_tests",
                "--required-tests-json-file",
                STAGING_REL,
            ],
        )
        self.assertEqual(preview["outcome"], "COMPLETED", preview.get("blockers"))
        digest = preview["extras"]["required_tests"]["plan_digest"]
        discovery_confidence = read_yaml(project / ".scaffold/tests.yaml")["confidence"]
        self.assertTrue(staging.is_file())
        applied = _run_installed(
            project,
            [
                "understand",
                "refresh",
                "--action",
                "required_tests",
                "--required-tests-json-file",
                STAGING_REL,
                "--plan-digest",
                digest,
            ],
        )
        self.assertEqual(applied["outcome"], "COMPLETED", applied.get("blockers"))
        self.assertFalse(staging.exists())
        tests = read_yaml(project / ".scaffold/tests.yaml")
        self.assertEqual(tests["required_authority"], "VERIFIED")
        self.assertEqual(tests["confidence"], discovery_confidence)
        bindir = project / "bin"
        bindir.mkdir(exist_ok=True)
        (bindir / "npm.cmd").write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
        os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
        ran = _run_installed(project, ["test"])
        self.assertTrue(
            ran["extras"]["completeness"]["test_complete"],
            ran["extras"].get("completeness"),
        )
        report_id = ran["extras"]["report_id"]
        stripped = read_yaml(project / ".scaffold/tests.yaml")
        stripped.pop("required_grounding", None)
        for row in stripped["profiles"]:
            row.pop("required_grounding", None)
        write_yaml_atomic(project / ".scaffold/tests.yaml", stripped)
        self.assertEqual(stripped["required_authority"], "VERIFIED")
        self.assertEqual(stripped["confidence"], discovery_confidence)
        again = _run_installed(project, ["test"])
        self.assertFalse(again["extras"]["completeness"]["required_set_authoritative"])
        self.assertFalse(again["extras"]["completeness"]["test_complete"])
        judged = evaluate_completeness(
            project,
            task=None,
            report=None,
            invoke=False,
            selected=None,
            test_package=REPO_TEST,
            report_id=report_id,
        )
        self.assertFalse(judged["test_complete"], judged)

    def _package_host(self, policy: str) -> None:
        write_active_host(self.host)
        write(self.host, "src/app.ts", "export const value = 1;\n")
        write(self.host, "src/__tests__/a.test.ts", "export {}\n")
        write(
            self.host,
            "package.json",
            json.dumps(
                {
                    "name": "demo",
                    "scripts": {
                        "test": "vitest run",
                        "test-extra": "vitest run extra",
                    },
                }
            )
            + "\n",
        )
        write(self.host, POLICY_REL, policy)
        self._accept_policy()
        project = read_yaml(self.host / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)

    def test_unaccepted_policy_and_live_grounding_fail_closed(self) -> None:
        from scaffold_p6.contract import inspect_host_project, resolve_contract
        from scaffold_p7.mutation import hard_mutation_boundary_reason

        write_active_host(self.host)
        write(self.host, "src/app.ts", "export const value = 1;\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        reason = hard_mutation_boundary_reason(self.host, POLICY_REL)
        self.assertIn("protected Scaffold governance", reason or "")
        parent = hard_mutation_boundary_reason(self.host, "docs/project", deleting=True)
        self.assertIn("protected Scaffold governance", parent or "")
        sibling = hard_mutation_boundary_reason(self.host, "docs/project/notes.md")
        self.assertIsNone(sibling)
        write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            stages=[
                {
                    "stage_id": "stage-1",
                    "goal": "Implement the fixture.",
                    "acceptance": "src/app.ts has the expected content.",
                    "status": "IN_PROGRESS",
                    "required_tests": [],
                }
            ],
        )
        ensure_noscms_accepted_anchor(self.host)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        denied = _hook(
            self.host,
            "Write",
            {"path": POLICY_REL, "contents": "schema_version: \"1\"\n"},
        )
        self.assertEqual(denied["permission"], "deny", denied)
        self.assertIn("protected Scaffold governance", denied.get("reason") or "")
        write(self.host, "package.json", json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n")
        write(self.host, POLICY_REL, """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
""")
        refreshed = refresh_host(self.host)
        self.assertTrue(refreshed.get("ok"), refreshed.get("conflicts") or refreshed)
        unaccepted = establish_required_tests(self.host, proposal=_proposal())
        self.assertFalse(unaccepted["ok"], unaccepted)
        self.assertIn("accepted", unaccepted["blockers"][0])
        self._accept_policy()
        preview = establish_required_tests(self.host, proposal=_proposal())
        self.assertTrue(preview["ok"], preview)
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        self._accept_policy()
        self._npm(0)
        selected = ["discovered-package-json-test"]
        passed = make_test_engine(self.host).run(selected=selected)
        self.assertTrue(passed.extras["completeness"]["test_complete"], passed.extras["completeness"])
        package = json.loads((self.host / "package.json").read_text(encoding="utf-8"))
        package["scripts"]["test"] = "vitest run --changed"
        write(self.host, "package.json", json.dumps(package) + "\n")
        still_verified = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(still_verified["required_authority"], "VERIFIED")
        status, _reasons, project = inspect_host_project(self.host)
        resolved = resolve_contract(
            self.host, project_status=status, project=project
        )
        self.assertFalse(resolved.required_set_authoritative)
        judged = evaluate_completeness(
            self.host,
            task=None,
            report=None,
            invoke=False,
            selected=selected,
            test_package=REPO_TEST,
            report_id=passed.extras["report_id"],
        )
        self.assertFalse(judged["test_complete"], judged)
        runner = self.host / ".scaffold/install/run.py"
        runner.parent.mkdir(parents=True, exist_ok=True)
        runner.write_text("# launcher\n", encoding="utf-8")
        bare = classify_first_use_shell(
            "python .scaffold/install/run.py understand refresh --plan-digest " + ("ab" * 32),
            self.host,
            adopted=True,
        )
        self.assertEqual(bare[0], SHELL_DENY, bare[1])
        self.assertIn("--action required_tests", bare[1])

    def test_noscms_owner_baseline_accepts_policy_and_working_copy_does_not(self) -> None:
        from p7_support import ensure_noscms_accepted_anchor

        write_active_host(self.host)
        write(self.host, "src/app.ts", "export const value = 1;\n")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write(self.host, "package.json", json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n")
        write(self.host, POLICY_REL, POLICY_ZERO)
        refreshed = refresh_host(self.host)
        self.assertTrue(refreshed.get("ok"), refreshed.get("conflicts") or refreshed)
        before = establish_required_tests(self.host, proposal=_proposal(zero_required=True))
        self.assertFalse(before["ok"], before)
        ensure_noscms_accepted_anchor(self.host)
        preview = establish_required_tests(self.host, proposal=_proposal(zero_required=True))
        self.assertTrue(preview["ok"], preview)
        write(self.host, POLICY_REL, POLICY_REQUIRED)
        changed = establish_required_tests(self.host, proposal=_proposal())
        self.assertFalse(changed["ok"], changed)

    def test_conflicting_discovery_confidence_cannot_establish_authority(self) -> None:
        from scaffold_p6.contract import inspect_host_project, resolve_contract

        self._package_host(POLICY_REQUIRED)
        self.assertTrue(refresh_host(self.host).get("ok"))
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        discovered = tests["confidence"]
        tests["confidence"] = "CONFLICTING"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        blocked = establish_required_tests(self.host, proposal=_proposal())
        self.assertFalse(blocked["ok"], blocked)
        self.assertIn("CONFLICTING", blocked["blockers"][0])
        tests["confidence"] = discovered
        for row in tests["profiles"]:
            if row.get("command_ref"):
                row["confidence"] = "CONFLICTING"
                break
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        profile_blocked = establish_required_tests(self.host, proposal=_proposal())
        self.assertFalse(profile_blocked["ok"], profile_blocked)
        self.assertIn("CONFLICTING", profile_blocked["blockers"][0])
        for row in tests["profiles"]:
            row["confidence"] = discovered
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        preview = establish_required_tests(self.host, proposal=_proposal())
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        published = read_yaml(self.host / ".scaffold/tests.yaml")
        for row in published["profiles"]:
            if row.get("required") is True:
                row["confidence"] = "CONFLICTING"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", published)
        self.assertEqual(published["required_authority"], "VERIFIED")
        status, _reasons, project = inspect_host_project(self.host)
        resolved = resolve_contract(
            self.host, project_status=status, project=project
        )
        self.assertFalse(resolved.required_set_authoritative)

    def test_legacy_authority_does_not_absorb_a_stripped_publication(self) -> None:
        from scaffold_p6.contract import inspect_host_project, resolve_contract

        def authoritative(host: Path) -> bool:
            status, _reasons, project = inspect_host_project(host)
            return resolve_contract(
                host, project_status=status, project=project
            ).required_set_authoritative

        def surfaces(host: Path, selected: list[str] | None = None) -> tuple[bool, bool, bool]:
            ran = make_test_engine(host).run(selected=selected)
            completeness = ran.extras["completeness"]
            judged = evaluate_completeness(
                host,
                task=None,
                report=None,
                invoke=False,
                selected=selected,
                test_package=REPO_TEST,
                report_id=ran.extras.get("report_id"),
            )
            return (
                authoritative(host),
                bool(completeness.get("test_complete")),
                bool(judged.get("test_complete")),
            )

        write_host(self.host, [passing_profile("unit")])
        legacy = read_yaml(self.host / ".scaffold/tests.yaml")
        legacy["required_authority"] = "VERIFIED"
        legacy["confidence"] = "VERIFIED"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", legacy)
        self.assertEqual(surfaces(self.host), (True, True, True))

        write(self.host, "README.md", "# zero\n")
        write_commands(self.host, [])
        write_tests(
            self.host,
            [],
            applicable=False,
            applicability="NOT_APPLICABLE",
            confidence="VERIFIED",
            required_authority="VERIFIED",
        )
        self.assertEqual(surfaces(self.host), (True, True, True))

        profile, command = passing_profile("unit")
        profile["required_authority"] = "VERIFIED"
        write_host(self.host, [(profile, command)])
        inferred = read_yaml(self.host / ".scaffold/tests.yaml")
        inferred["confidence"] = "INFERRED"
        inferred["required_authority"] = "VERIFIED"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", inferred)
        self.assertEqual(surfaces(self.host), (False, False, False))
        unknown = read_yaml(self.host / ".scaffold/tests.yaml")
        unknown["confidence"] = "UNKNOWN"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", unknown)
        self.assertFalse(authoritative(self.host))
        blocked = make_test_engine(self.host).run()
        self.assertFalse(blocked.extras["completeness"]["test_complete"])
        self.assertFalse(
            evaluate_completeness(
                self.host,
                task=None,
                report=None,
                invoke=False,
                selected=None,
                test_package=REPO_TEST,
                report_id=blocked.extras.get("report_id"),
            )["test_complete"]
        )

        inferred_host = self.host / "inferred-publication"
        write_active_host(inferred_host)
        write(inferred_host, "src/app.ts", "export const value = 1;\n")
        inferred_project = read_yaml(inferred_host / ".scaffold/project.yaml")
        inferred_ownership = dict(inferred_project.get("ownership") or {})
        inferred_ownership["AGENTS.md"] = "GENERATED"
        inferred_project["ownership"] = inferred_ownership
        write_yaml_atomic(inferred_host / ".scaffold/project.yaml", inferred_project)
        write(
            inferred_host,
            "package.json",
            json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
        )
        write(
            inferred_host,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
""",
        )
        self.host, inferred_host = inferred_host, self.host
        self._accept_policy()
        self.host, inferred_host = inferred_host, self.host
        self.assertTrue(refresh_host(inferred_host).get("ok"))
        inferred_preview = establish_required_tests(inferred_host, proposal=_proposal())
        self.assertTrue(inferred_preview.get("ok"), inferred_preview)
        inferred_applied = establish_required_tests(
            inferred_host,
            proposal=_proposal(),
            plan_digest=inferred_preview["plan_digest"],
        )
        self.assertTrue(inferred_applied["ok"], inferred_applied)
        inferred_published = read_yaml(inferred_host / ".scaffold/tests.yaml")
        self.assertEqual(inferred_published["confidence"], "INFERRED")
        inferred_published.pop("required_grounding", None)
        for row in inferred_published["profiles"]:
            row.pop("required_grounding", None)
        write_yaml_atomic(inferred_host / ".scaffold/tests.yaml", inferred_published)
        self.assertEqual(
            surfaces(inferred_host, ["discovered-package-json-test"]),
            (False, False, False),
        )

        self._package_host(POLICY_REQUIRED)
        self.assertTrue(refresh_host(self.host).get("ok"))
        preview = establish_required_tests(self.host, proposal=_proposal())
        applied = establish_required_tests(
            self.host,
            proposal=_proposal(),
            plan_digest=preview["plan_digest"],
        )
        self.assertTrue(applied["ok"], applied)
        self._npm(0)
        saved = read_yaml(self.host / ".scaffold/tests.yaml")
        self.assertEqual(saved["confidence"], "VERIFIED")
        self.assertEqual(surfaces(self.host), (True, True, True))

        def reject(mutate) -> None:
            current = json.loads(json.dumps(saved))
            mutate(current)
            write_yaml_atomic(self.host / ".scaffold/tests.yaml", current)
            self.assertEqual(surfaces(self.host), (False, False, False))

        reject(lambda current: current.pop("required_grounding", None))
        reject(
            lambda current: (
                current.pop("required_grounding", None),
                [row.pop("required_grounding", None) for row in current["profiles"]],
            )
        )
        reject(lambda current: current["required_grounding"].pop("plan_digest"))

        with tempfile.TemporaryDirectory() as plain_root:
            self._assert_noscms_reinit_keeps_the_accepted_policy(Path(plain_root))

    def _assert_noscms_reinit_keeps_the_accepted_policy(self, root: Path) -> None:
        from scaffold_p8.noscms import BASELINE_REL, initialize_noscms_baseline

        plain = root / "host"
        write_active_host(plain)
        write(plain, "src/app.ts", "export const value = 1;\n")
        project = read_yaml(plain / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(plain / ".scaffold/project.yaml", project)
        write(
            plain,
            "package.json",
            json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
        )
        write(plain, POLICY_REL, POLICY_ZERO)
        self.assertTrue(refresh_host(plain).get("ok"))
        ensure_noscms_accepted_anchor(plain)
        accepted_digest = read_yaml(plain / BASELINE_REL)["inventory"][POLICY_REL]["digest"]
        self.assertTrue(
            establish_required_tests(
                plain, proposal=_proposal(zero_required=True)
            )["ok"]
        )
        write(plain, "docs/project/notes.md", "unrelated\n")
        maintained = initialize_noscms_baseline(plain)
        self.assertTrue(maintained.get("ok"), maintained)
        self.assertEqual(
            read_yaml(plain / BASELINE_REL)["inventory"][POLICY_REL]["digest"],
            accepted_digest,
        )
        write(plain, POLICY_REL, POLICY_REQUIRED)
        refused = initialize_noscms_baseline(plain)
        self.assertFalse(refused.get("ok"), refused)
        self.assertIn("not approval", refused["blockers"][0])
        self.assertEqual(
            read_yaml(plain / BASELINE_REL)["inventory"][POLICY_REL]["digest"],
            accepted_digest,
        )
        self.assertFalse(establish_required_tests(plain, proposal=_proposal())["ok"])

    def test_format_identity_survives_policy_and_grounding_loss(self) -> None:
        from p6_support import git
        from scaffold_p5.schemas import (
            REQUIRED_AUTHORITY_FORMAT,
            REQUIRED_AUTHORITY_FORMAT_KEY,
        )
        from scaffold_p5.io_util import file_digest
        from scaffold_p6.contract import inspect_host_project, resolve_contract
        from scaffold_p8.noscms import BASELINE_REL, initialize_noscms_baseline

        def authoritative(host: Path) -> bool:
            status, _reasons, project = inspect_host_project(host)
            return resolve_contract(
                host, project_status=status, project=project
            ).required_set_authoritative

        def surfaces(host: Path) -> tuple[bool, bool, bool]:
            ran = make_test_engine(host).run()
            judged = evaluate_completeness(
                host,
                task=None,
                report=None,
                invoke=False,
                selected=None,
                test_package=REPO_TEST,
                report_id=ran.extras.get("report_id"),
            )
            return (
                authoritative(host),
                bool(ran.extras["completeness"].get("test_complete")),
                bool(judged.get("test_complete")),
            )

        def identity(host: Path) -> str:
            project = read_yaml(host / ".scaffold/project.yaml")
            return str(project.get(REQUIRED_AUTHORITY_FORMAT_KEY) or "")

        write_host(self.host, [passing_profile("unit")])
        legacy = read_yaml(self.host / ".scaffold/tests.yaml")
        legacy["required_authority"] = "VERIFIED"
        legacy["confidence"] = "VERIFIED"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", legacy)
        self.assertEqual(identity(self.host), "")
        self.assertEqual(surfaces(self.host), (True, True, True))
        write(self.host, "README.md", "# zero\n")
        write_commands(self.host, [])
        write_tests(
            self.host,
            [],
            applicable=False,
            applicability="NOT_APPLICABLE",
            confidence="VERIFIED",
            required_authority="VERIFIED",
        )
        self.assertEqual(surfaces(self.host), (True, True, True))
        profile, command = passing_profile("unit")
        profile["required_authority"] = "VERIFIED"
        write_host(self.host, [(profile, command)])
        inferred = read_yaml(self.host / ".scaffold/tests.yaml")
        inferred["required_authority"] = "VERIFIED"
        inferred["confidence"] = "INFERRED"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", inferred)
        self.assertEqual(surfaces(self.host), (False, False, False))
        inferred["confidence"] = "UNKNOWN"
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", inferred)
        self.assertFalse(authoritative(self.host))

        host = self.host / "published"
        write_active_host(host)
        write(host, "src/app.ts", "export const value = 1;\n")
        write(host, "src/__tests__/a.test.ts", "export {}\n")
        project = read_yaml(host / ".scaffold/project.yaml")
        ownership = dict(project.get("ownership") or {})
        ownership["AGENTS.md"] = "GENERATED"
        project["ownership"] = ownership
        write_yaml_atomic(host / ".scaffold/project.yaml", project)
        write(
            host,
            "package.json",
            json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
        )
        write(
            host,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - package.json#scripts.test
""",
        )
        original = self.host
        self.host = host
        self._accept_policy()
        self.host = original
        self.assertTrue(refresh_host(host).get("ok"))
        preview = establish_required_tests(host, proposal=_proposal())
        applied = establish_required_tests(
            host, proposal=_proposal(), plan_digest=preview["plan_digest"]
        )
        self.assertTrue(applied["ok"], applied)
        self.assertEqual(identity(host), REQUIRED_AUTHORITY_FORMAT)
        published = read_yaml(host / ".scaffold/tests.yaml")
        self.assertEqual(published["confidence"], "VERIFIED")
        self._npm_at(host, 0)
        self.assertEqual(surfaces(host), (True, True, True))
        again = establish_required_tests(
            host,
            proposal=_proposal(),
            plan_digest=establish_required_tests(host, proposal=_proposal())["plan_digest"],
        )
        self.assertTrue(again["ok"], again)
        self.assertEqual(identity(host), REQUIRED_AUTHORITY_FORMAT)
        self.assertTrue(refresh_host(host).get("ok"))
        self.assertEqual(identity(host), REQUIRED_AUTHORITY_FORMAT)
        self.assertTrue(authoritative(host))
        saved = read_yaml(host / ".scaffold/tests.yaml")

        def restore_tests() -> None:
            write_yaml_atomic(host / ".scaffold/tests.yaml", json.loads(json.dumps(saved)))

        top = json.loads(json.dumps(saved))
        top.pop("required_grounding", None)
        write_yaml_atomic(host / ".scaffold/tests.yaml", top)
        self.assertEqual(surfaces(host), (False, False, False))
        restore_tests()
        stripped = json.loads(json.dumps(saved))
        stripped.pop("required_grounding", None)
        for row in stripped["profiles"]:
            row.pop("required_grounding", None)
        write_yaml_atomic(host / ".scaffold/tests.yaml", stripped)
        self.assertEqual(stripped["confidence"], "VERIFIED")
        self.assertEqual(surfaces(host), (False, False, False))
        (host / POLICY_REL).unlink()
        self.assertEqual(identity(host), REQUIRED_AUTHORITY_FORMAT)
        git(host, "cat-file", "-e", f"HEAD:{POLICY_REL}")
        self.assertEqual(surfaces(host), (False, False, False))

        git(host, "add", "-A")
        git(
            host,
            "-c",
            "user.name=P6 Test",
            "-c",
            "user.email=p6@example.invalid",
            "commit",
            "-m",
            "delete policy",
        )
        self.assertEqual(identity(host), REQUIRED_AUTHORITY_FORMAT)
        self.assertFalse((host / POLICY_REL).exists())
        self.assertEqual(surfaces(host), (False, False, False))

        failed = self.host / "failed-required"
        bad, bad_command = failing_profile("bad")
        other, other_command = passing_profile("other")
        bad_command["source"] = "scripts/bad.txt"
        other_command["source"] = "scripts/other.txt"
        write_host(failed, [(bad, bad_command), (other, other_command)])
        write(failed, "scripts/bad.txt", "bad\n")
        write(failed, "scripts/other.txt", "other\n")
        write(
            failed,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - scripts/bad.txt
  - scripts/other.txt
""",
        )
        self.host = failed
        self._accept_policy()
        self.host = original
        failed_preview = establish_required_tests(failed, proposal=_proposal())
        failed_applied = establish_required_tests(
            failed,
            proposal=_proposal(),
            plan_digest=failed_preview["plan_digest"],
        )
        self.assertTrue(failed_applied["ok"], failed_applied)
        failed_surfaces = surfaces(failed)
        self.assertTrue(failed_surfaces[0])
        self.assertFalse(failed_surfaces[1])
        self.assertFalse(failed_surfaces[2])
        selected = make_test_engine(failed).run(selected=["other"])
        self.assertFalse(selected.extras["completeness"]["test_complete"])
        (failed / POLICY_REL).unlink()
        current = read_yaml(failed / ".scaffold/tests.yaml")
        current.pop("required_grounding", None)
        for row in current["profiles"]:
            row.pop("required_grounding", None)
        write_yaml_atomic(failed / ".scaffold/tests.yaml", current)
        self.assertEqual(identity(failed), REQUIRED_AUTHORITY_FORMAT)
        self.assertEqual(surfaces(failed), (False, False, False))

        with tempfile.TemporaryDirectory() as raw:
            plain = Path(raw) / "host"
            write_active_host(plain)
            write(plain, "src/app.ts", "export const value = 1;\n")
            owned = read_yaml(plain / ".scaffold/project.yaml")
            owned_map = dict(owned.get("ownership") or {})
            owned_map["AGENTS.md"] = "GENERATED"
            owned["ownership"] = owned_map
            write_yaml_atomic(plain / ".scaffold/project.yaml", owned)
            write(
                plain,
                "package.json",
                json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}) + "\n",
            )
            write(plain, POLICY_REL, POLICY_ZERO)
            self.assertTrue(refresh_host(plain).get("ok"))
            ensure_noscms_accepted_anchor(plain)
            zero_preview = establish_required_tests(
                plain, proposal=_proposal(zero_required=True)
            )
            zero_applied = establish_required_tests(
                plain,
                proposal=_proposal(zero_required=True),
                plan_digest=zero_preview["plan_digest"],
            )
            self.assertTrue(zero_applied["ok"], zero_applied)
            self.assertEqual(identity(plain), REQUIRED_AUTHORITY_FORMAT)
            write(plain, "docs/project/notes.md", "note\n")
            maintained = initialize_noscms_baseline(plain)
            self.assertTrue(maintained.get("ok"), maintained)
            self.assertEqual(identity(plain), REQUIRED_AUTHORITY_FORMAT)
            accepted = read_yaml(plain / BASELINE_REL)["inventory"][
                ".scaffold/project.yaml"
            ]["digest"]
            self.assertEqual(accepted, file_digest(plain / ".scaffold/project.yaml"))
            (plain / POLICY_REL).unlink()
            self.assertEqual(identity(plain), REQUIRED_AUTHORITY_FORMAT)
            self.assertFalse(authoritative(plain))

        legacy_host = self.host / "mid-publication"
        kept, kept_command = passing_profile("unit")
        kept_command["source"] = "scripts/unit.txt"
        write_host(legacy_host, [(kept, kept_command)])
        write(legacy_host, "scripts/unit.txt", "unit\n")
        legacy_doc = read_yaml(legacy_host / ".scaffold/tests.yaml")
        legacy_doc["required_authority"] = "VERIFIED"
        legacy_doc["confidence"] = "VERIFIED"
        write_yaml_atomic(legacy_host / ".scaffold/tests.yaml", legacy_doc)
        write(
            legacy_host,
            POLICY_REL,
            """schema_version: "1"
kind: required_test_policy
policy: required_set
required_sources:
  - scripts/unit.txt
""",
        )
        self.host = legacy_host
        self._accept_policy()
        self.host = original
        self.assertTrue(authoritative(legacy_host))
        from scaffold_p5 import required_tests as required_module

        original_write = required_module.write_yaml_atomic

        def fail_tests(path, data):
            if str(path).replace("\\", "/").endswith(".scaffold/tests.yaml"):
                raise OSError("injected publication failure")
            return original_write(path, data)

        required_module.write_yaml_atomic = fail_tests
        try:
            blocked = establish_required_tests(
                legacy_host,
                proposal=_proposal(),
                plan_digest=establish_required_tests(
                    legacy_host, proposal=_proposal()
                )["plan_digest"],
            )
        finally:
            required_module.write_yaml_atomic = original_write
        self.assertFalse(blocked["ok"], blocked)
        self.assertEqual(identity(legacy_host), REQUIRED_AUTHORITY_FORMAT)
        self.assertFalse(authoritative(legacy_host))

    def _npm_at(self, host: Path, code: int) -> None:
        bindir = host / "bin"
        bindir.mkdir(exist_ok=True)
        (bindir / "npm.cmd").write_text(f"@echo off\r\nexit /b {code}\r\n", encoding="utf-8")
        os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")

    def _accept_policy(self) -> None:
        """Owner acceptance. Git commit is outside Develop autonomy."""
        from p6_support import git, init_git

        if not (self.host / ".git").exists():
            init_git(self.host)
            return
        git(self.host, "add", "-A")
        git(
            self.host,
            "-c",
            "user.name=P6 Test",
            "-c",
            "user.email=p6@example.invalid",
            "commit",
            "-m",
            "accept policy",
            "--allow-empty",
        )

    def _commit(self) -> None:
        init_git(self.host)
        gitignore = self.host / ".gitignore"
        gitignore.write_text(
            gitignore.read_text(encoding="utf-8") + ".scaffold/ext/\n",
            encoding="utf-8",
        )
        from p6_support import git

        git(self.host, "add", "-A")
        git(
            self.host,
            "-c",
            "user.name=P6 Test",
            "-c",
            "user.email=p6@example.invalid",
            "commit",
            "-m",
            "authority",
        )

    def _npm(self, code: int) -> None:
        bindir = self.host / "bin"
        bindir.mkdir(exist_ok=True)
        (bindir / "npm.cmd").write_text(f"@echo off\r\nexit /b {code}\r\n", encoding="utf-8")
        os.environ["PATH"] = str(bindir) + os.pathsep + self._path


def _profile(tests: dict, profile_id: str) -> dict:
    return next(row for row in tests["profiles"] if row["id"] == profile_id)


def _hook(host: Path, tool_name: str, tool_input: dict) -> dict:
    stdout = io.StringIO()
    payload = {
        "hook_event_name": "preToolUse",
        "tool_name": tool_name,
        "cwd": str(host),
        "tool_input": tool_input,
    }
    code = hook_main(stdin=io.StringIO(json.dumps(payload)), stdout=stdout)
    result = json.loads(stdout.getvalue())
    result["exit_code"] = code
    return result


def _run_installed(host: Path, argv: list[str]) -> dict:
    completed = subprocess.run(
        [sys.executable, str(host / ".scaffold/install/run.py"), *argv],
        cwd=host,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "outcome": "UNPARSEABLE",
            "blockers": [completed.stdout, completed.stderr],
            "returncode": completed.returncode,
        }


def _launcher(host: Path, argv: list[str]) -> tuple[int, dict]:
    install = host / ".scaffold" / "install"
    install.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    from contextlib import redirect_stdout

    with redirect_stdout(buffer):
        code = installed_main(install, argv)
    return code, json.loads(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()

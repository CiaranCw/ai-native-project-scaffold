from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import adopt, write
from p6_support import (
    CORE_OWNERSHIP,
    REPO_TEST,
    passing_profile,
    test_engine,
    write_commands,
    write_tests,
)
from p7_support import TASK_A, bind_develop_lock, develop_engine, write_active_host, write_task
from p8_support import (
    bind_ready_completion_authority,
    bind_submit_lock,
    rebind_noscms_baseline,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_text, read_yaml, write_yaml_atomic
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.rules import resolve_project_rules, rule_test_ids
from scaffold_p7.mutation import authorize_writes
from scaffold_p8.completeness import evaluate_completeness


class FA2Batch1ProjectAuthorityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.host = self.root / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_A01_real_p5_output_registers_business_source_human_owned(self):
        result = self._adopt_source_host()
        source_action = next(
            row
            for row in result.extras["plan"]["actions"]
            if row.get("target") == "src/"
        )
        self.assertEqual(source_action["action_class"], "PRESERVE")
        self.assertEqual(source_action["ownership"], "HUMAN_OWNED")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["ownership"].get("src/"), "HUMAN_OWNED")
        self.assertNotEqual(project["ownership"].get("src/app.py"), "GENERATED")
        resolved = resolve_ownership(project["ownership"], "src/app.py")
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertEqual(resolved.mode, "HUMAN_OWNED")
        self.assertEqual(resolved.matched_key, "src/")

    def test_A02_task_scoped_human_owned_business_source_may_be_mutated(self):
        self._adopt_source_host()
        bind_develop_lock(self.host)
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 2\n"}],
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(read_text(self.host / "src/app.py"), "value = 2\n")
        self.assertEqual(
            result.extras["ownership_authority"][0]["ownership"],
            "HUMAN_OWNED",
        )

    def test_A03_human_owned_source_without_valid_task_intent_is_blocked(self):
        self._adopt_source_host()
        bind_develop_lock(self.host)
        before = read_text(self.host / "src/app.py")
        result = develop_engine(self.host).run(
            "normal_task",
            writes=[{"path": "src/app.py", "content": "value = 3\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(read_text(self.host / "src/app.py"), before)

    def test_A04_submit_accepts_legitimate_human_owned_business_change(self):
        self._adopt_source_host()
        profile, command = passing_profile("unit")
        write_commands(self.host, [command])
        write_tests(self.host, [profile])
        bind_submit_lock(self.host)
        write_ready_task(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["ownership"] = {
            **project["ownership"],
            ".scaffold/ext/submit/": "GENERATED",
        }
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        rebound = rebind_noscms_baseline(self.host)
        self.assertTrue(rebound.get("ok"), rebound)
        write(self.host, "src/app.py", "value = 2\n")
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertNotEqual(result.extras.get("stage"), "S3")
        structural = result.extras["structural"]
        self.assertTrue(structural["structural_review_pass"])
        self.assertEqual(
            structural["ownership_authority"][0]["ownership"],
            "HUMAN_OWNED",
        )

    def test_A05_missing_and_conflicting_ownership_fail_closed(self):
        missing = resolve_ownership(CORE_OWNERSHIP, "src/app.py")
        conflicting = resolve_ownership(
            {
                **CORE_OWNERSHIP,
                "src/": "HUMAN_OWNED",
                "./src/": "GENERATED",
            },
            "src/app.py",
        )
        self.assertEqual(missing.status, "UNKNOWN")
        self.assertEqual(conflicting.status, "CONFLICTING")

    def test_A06_exact_scaffold_and_generated_authority_keeps_precedence(self):
        ownership = {
            **CORE_OWNERSHIP,
            "src/": "HUMAN_OWNED",
            "src/generated.py": "GENERATED",
            "docs/project/testing.md": "HUMAN_OWNED",
        }
        generated = resolve_ownership(ownership, "src/generated.py")
        core = resolve_ownership(ownership, ".scaffold/project.yaml")
        self.assertEqual(generated.mode, "GENERATED")
        self.assertEqual(generated.matched_key, "src/generated.py")
        self.assertEqual(core.mode, "GENERATED")
        generated_plan = authorize_writes(
            self.host,
            writes=[{"path": "src/generated.py", "content": "generated = True\n"}],
            task={
                "status": "IN_PROGRESS",
                "scope": {
                    "paths": ["src/generated.py"],
                    "modules": [],
                    "exclude": [],
                },
            },
            project={"ownership": ownership, "source_areas": ["src"]},
        )
        self.assertTrue(generated_plan.ok, generated_plan.blockers)

        write_active_host(
            self.host,
            ownership=ownership,
            source_areas=["src"],
        )
        write_task(
            self.host,
            scope={
                "paths": ["docs/project/testing.md"],
                "modules": [],
                "exclude": [],
            },
        )
        before = "human text\n"
        write(self.host, "docs/project/testing.md", before)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[
                {
                    "path": "docs/project/testing.md",
                    "content": "overwritten\n",
                }
            ],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(read_text(self.host / "docs/project/testing.md"), before)

    def test_A07_managed_without_bounded_region_cannot_gain_whole_file_write(self):
        write_active_host(
            self.host,
            ownership={
                **CORE_OWNERSHIP,
                "src/": "HUMAN_OWNED",
                "src/app.py": "MANAGED",
            },
            source_areas=["src"],
        )
        write_task(self.host)
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "value = 7\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("bounded managed region" in item for item in result.blockers))
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R01_global_rule_is_visible_to_p6_p7_and_p8(self):
        self._submit_host()
        self._set_global_refs(["docs/project/global.rules.yaml"])
        self._write_rules(
            "docs/project/global.rules.yaml",
            [self._rule("global-advice", effect="ADVISE")],
        )
        for skill, operation in (
            ("test", "test_execute"),
            ("develop", "develop"),
            ("submit", "source_write"),
        ):
            resolved = resolve_project_rules(
                self.host,
                project=read_yaml(self.host / ".scaffold/project.yaml"),
                skill_id=skill,
                paths=["src/app.py"],
                modules=[],
                test_ids=["unit"],
                operation=operation,
            )
            self.assertTrue(resolved["ok"], resolved["blockers"])
            self.assertTrue(resolved["agents_loaded"])
            self.assertEqual(
                [row["rule_id"] for row in resolved["applicable"]],
                ["global-advice"],
            )

    def test_R02_module_rule_applies_inside_declared_scope(self):
        self._submit_host()
        self._set_modules(
            [
                {
                    "id": "app",
                    "path": "src",
                    "kind": "source",
                    "confidence": "VERIFIED",
                    "rule_refs": ["docs/project/app.rules.yaml"],
                }
            ]
        )
        self._write_rules(
            "docs/project/app.rules.yaml",
            [self._rule("app-advice", effect="ADVISE", scope=None)],
        )
        resolved = self._resolve("develop", ["src/app.py"], ["app"], "develop")
        self.assertTrue(resolved["ok"])
        self.assertEqual(
            [row["rule_id"] for row in resolved["applicable"]],
            ["app-advice"],
        )

    def test_R03_module_rule_does_not_leak_outside_scope(self):
        self._submit_host()
        self._set_modules(
            [
                {
                    "id": "app",
                    "path": "src",
                    "kind": "source",
                    "confidence": "VERIFIED",
                    "rule_refs": ["docs/project/app.rules.yaml"],
                }
            ]
        )
        self._write_rules(
            "docs/project/app.rules.yaml",
            [self._rule("app-advice", effect="ADVISE", scope=None)],
        )
        resolved = self._resolve("develop", ["tools/build.py"], [], "develop")
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["applicable"], [])

    def test_R04_hard_rule_blocks_p7_before_business_source_write(self):
        self._develop_host()
        self._set_global_refs(["docs/project/no-app.rules.yaml"])
        self._write_rules(
            "docs/project/no-app.rules.yaml",
            [
                self._rule(
                    "no-app-write",
                    effect="PROHIBIT",
                    operations=["source_write"],
                    scope={"kind": "path", "paths": ["src/app.py"]},
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "blocked\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("no-app-write" in item for item in result.blockers))
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R05_conflicting_applicable_rules_are_not_guessed_through(self):
        self._develop_host()
        self._set_global_refs(
            ["docs/project/first.rules.yaml", "docs/project/second.rules.yaml"]
        )
        first = self._rule(
            "same-id",
            effect="ADVISE",
            statement="first normative statement",
        )
        second = self._rule(
            "same-id",
            effect="ADVISE",
            statement="different normative statement",
        )
        self._write_rules("docs/project/first.rules.yaml", [first])
        self._write_rules("docs/project/second.rules.yaml", [second])
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "blocked\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("conflict" in item.lower() for item in result.blockers))
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R06_p6_observes_test_rule_and_runs_no_adapter_when_prohibited(self):
        self._submit_host()
        tests_path = self.host / ".scaffold/tests.yaml"
        tests_data = read_yaml(tests_path)
        tests_data["profiles"][0]["rule_refs"] = [
            "docs/project/no-test.rules.yaml"
        ]
        write_yaml_atomic(tests_path, tests_data)
        self._write_rules(
            "docs/project/no-test.rules.yaml",
            [
                self._rule(
                    "no-test-command",
                    applies_to=["test"],
                    effect="PROHIBIT",
                    operations=["test_execute"],
                )
            ],
        )
        engine = test_engine(self.host)
        result = engine.run("scoped_verification", selected=["unit"])
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(engine.adapter_invocations, 0)
        self.assertTrue(
            any("no-test-command" in item for item in result.blockers)
        )
        self.assertEqual(
            result.extras["project_rules"]["prohibitions"][0]["rule_id"],
            "no-test-command",
        )

    def test_R07_p8_receives_applicable_rule_for_real_changed_scope(self):
        self._submit_host()
        self._set_global_refs(["docs/project/no-submit.rules.yaml"])
        self._write_rules(
            "docs/project/no-submit.rules.yaml",
            [
                self._rule(
                    "no-app-submit",
                    applies_to=["submit"],
                    effect="PROHIBIT",
                    operations=["source_write"],
                    scope={"kind": "path", "paths": ["src/app.py"]},
                )
            ],
        )
        write(self.host, "src/app.py", "value = 2\n")
        result = submit_engine(self.host).run(task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S3")
        self.assertTrue(any("no-app-submit" in item for item in result.blockers))
        self.assertEqual(
            result.extras["project_rules"]["prohibitions"][0]["rule_id"],
            "no-app-submit",
        )

    def test_R08_rule_resolution_cannot_grant_missing_mutation_authority(self):
        write_active_host(self.host)
        write_task(self.host)
        self._set_global_refs(["docs/project/advice.rules.yaml"])
        self._write_rules(
            "docs/project/advice.rules.yaml",
            [self._rule("advice-only", effect="ADVISE")],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "not granted\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("UNKNOWN" in item for item in result.blockers))
        self.assertEqual(result.extras["project_rules"]["grants"], [])
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R09_understand_targeted_rule_is_valid_and_non_applicable(self):
        self._submit_host()
        self._set_global_refs(["docs/project/understand.rules.yaml"])
        self._write_rules(
            "docs/project/understand.rules.yaml",
            [self._rule("understand-only", applies_to=["understand"])],
        )
        for skill, operation in (
            ("test", "test_execute"),
            ("develop", "source_write"),
            ("submit", "source_write"),
        ):
            resolved = resolve_project_rules(
                self.host,
                project=read_yaml(self.host / ".scaffold/project.yaml"),
                skill_id=skill,
                paths=["src/app.py"],
                modules=[],
                test_ids=["unit"],
                operation=operation,
            )
            self.assertTrue(resolved["ok"], resolved["blockers"])
            self.assertEqual(resolved["blockers"], [])
            self.assertEqual(resolved["applicable"], [])
            self.assertEqual(
                [row["path"] for row in resolved["sources"]],
                ["docs/project/understand.rules.yaml"],
            )

    def test_R10_agents_link_does_not_author_unindexed_rule(self):
        self._submit_host()
        write(
            self.host,
            "AGENTS.md",
            read_text(self.host / "AGENTS.md")
            + "\nRule: `docs/project/direct.rules.yaml`\n",
        )
        self._write_rules(
            "docs/project/direct.rules.yaml",
            [self._rule("direct-advice", effect="ADVISE")],
        )
        resolved = self._resolve("develop", ["src/app.py"], [], "source_write")
        self.assertTrue(resolved["ok"], resolved["blockers"])
        self.assertNotIn(
            "docs/project/direct.rules.yaml",
            [row["path"] for row in resolved["sources"]],
        )
        self.assertNotIn(
            "docs/project/direct.rules.yaml",
            resolved["agents_rule_routes"],
        )
        self.assertEqual(resolved["applicable"], [])

    def test_R11_p2_index_rule_ref_loads_the_same_document(self):
        self._submit_host()
        self._set_global_refs(["docs/project/direct.rules.yaml"])
        self._write_rules(
            "docs/project/direct.rules.yaml",
            [self._rule("indexed-advice", effect="ADVISE")],
        )
        resolved = self._resolve("develop", ["src/app.py"], [], "source_write")
        self.assertTrue(resolved["ok"], resolved["blockers"])
        self.assertEqual(
            [row["path"] for row in resolved["sources"]],
            ["docs/project/direct.rules.yaml"],
        )
        self.assertEqual(
            [row["rule_id"] for row in resolved["applicable"]],
            ["indexed-advice"],
        )

    def test_R12_p7_loads_task_declared_test_rule_without_selected(self):
        self._develop_host()
        unit, _command = passing_profile("unit")
        unit["rule_refs"] = ["docs/project/unit.rules.yaml"]
        write_tests(self.host, [unit])
        write_task(
            self.host,
            final_tests=[
                {"requirement_id": "unit", "observed_outcome": "NOT_EXECUTED"}
            ],
        )
        self._write_rules(
            "docs/project/unit.rules.yaml",
            [
                self._rule(
                    "no-develop-unit",
                    applies_to=["develop"],
                    effect="PROHIBIT",
                    operations=["source_write"],
                    scope={"kind": "test", "tests": ["unit"]},
                )
            ],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            writes=[{"path": "src/app.py", "content": "blocked\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("no-develop-unit" in item for item in result.blockers))
        self.assertEqual(
            result.extras["project_rules"]["scope"]["tests"],
            ["unit"],
        )
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R13_p8_loads_task_declared_test_rule_without_selected(self):
        self._submit_host()
        tests_path = self.host / ".scaffold/tests.yaml"
        tests_data = read_yaml(tests_path)
        for profile in tests_data.get("profiles") or []:
            if profile.get("id") == "unit":
                profile["rule_refs"] = ["docs/project/unit.rules.yaml"]
        write_yaml_atomic(tests_path, tests_data)
        self._write_rules(
            "docs/project/unit.rules.yaml",
            [
                self._rule(
                    "no-submit-unit",
                    applies_to=["submit"],
                    effect="PROHIBIT",
                    operations=["source_write"],
                    scope={"kind": "test", "tests": ["unit"]},
                )
            ],
        )
        write_ready_task(
            self.host,
            bind_ready_authority=False,
            final_tests=[
                {
                    "requirement_id": "unit",
                    "execution_binding": {
                        "kind": "test_profile",
                        "profile_id": "unit",
                    },
                }
            ],
        )
        engine = test_engine(self.host)
        test_result = engine.run("scoped_verification", selected=["unit"])
        refs = engine.build_evidence_refs(test_result.extras["report_id"])
        self.assertTrue(refs)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        task = read_yaml(task_path)
        task["final_tests"][0]["evidence_ref"] = {"locator": refs[0]["locator"]}
        write_yaml_atomic(task_path, task)
        bind_ready_completion_authority(self.host, TASK_A)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            report=test_result.extras["report"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S3")
        self.assertTrue(any("no-submit-unit" in item for item in result.blockers))
        self.assertEqual(
            result.extras["project_rules"]["scope"]["tests"],
            ["unit"],
        )

    def test_R14_task_required_and_caller_selected_are_unioned(self):
        self._develop_host()
        unit, _unit_command = passing_profile("unit")
        extra, _extra_command = passing_profile("extra", required=False)
        unit["rule_refs"] = ["docs/project/unit.rules.yaml"]
        extra["rule_refs"] = ["docs/project/extra.rules.yaml"]
        write_tests(self.host, [unit, extra])
        write_task(
            self.host,
            final_tests=[
                {"requirement_id": "unit", "observed_outcome": "NOT_EXECUTED"}
            ],
        )
        self._write_rules(
            "docs/project/unit.rules.yaml",
            [
                self._rule(
                    "no-develop-unit",
                    applies_to=["develop"],
                    effect="PROHIBIT",
                    operations=["source_write"],
                    scope={"kind": "test", "tests": ["unit"]},
                )
            ],
        )
        self._write_rules(
            "docs/project/extra.rules.yaml",
            [
                self._rule(
                    "extra-advice",
                    applies_to=["develop"],
                    effect="ADVISE",
                    scope={"kind": "test", "tests": ["extra"]},
                )
            ],
        )
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        self.assertEqual(
            rule_test_ids(task=task, selected=["extra"]),
            ["extra", "unit"],
        )
        result = develop_engine(self.host).run(
            "normal_task",
            task_id=TASK_A,
            selected=["extra"],
            writes=[{"path": "src/app.py", "content": "blocked\n"}],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(
            result.extras["project_rules"]["scope"]["tests"],
            ["extra", "unit"],
        )
        self.assertTrue(any("no-develop-unit" in item for item in result.blockers))
        self.assertFalse((self.host / "src/app.py").exists())

    def test_R15_rule_test_scope_does_not_change_completeness_semantics(self):
        self._submit_host()
        task = read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        task["final_tests"] = [{"requirement_id": "unit"}]
        self.assertEqual(
            rule_test_ids(task=task, selected=["extra"]),
            ["extra", "unit"],
        )
        completeness = evaluate_completeness(
            self.host,
            task=task,
            report=None,
            invoke=False,
            selected=["extra"],
            test_package=REPO_TEST,
        )
        self.assertEqual(completeness["required_ids"], ["unit"])
        self.assertNotIn("extra", completeness["required_ids"])
        self.assertFalse(completeness["test_complete"])
        self.assertFalse(completeness["test_pass"])
        self.assertFalse(completeness["usable"])
        engine = test_engine(self.host)
        test_result = engine.run(
            "scoped_verification", selected=["unit"]
        )
        report = test_result.extras["report"]
        task["final_tests"][0]["evidence_ref"] = engine.build_evidence_refs(
            test_result.extras["report_id"]
        )[0]
        reported = evaluate_completeness(
            self.host,
            task=task,
            report=None,
            invoke=False,
            selected=["extra"],
            test_package=REPO_TEST,
            report_id=test_result.extras["report_id"],
        )
        self.assertEqual(reported["required_ids"], ["unit"])
        self.assertNotIn("extra", reported["required_ids"])
        self.assertEqual(reported["test_complete"], report["completeness"]["test_complete"])
        self.assertEqual(reported["test_pass"], report["completeness"]["test_pass"])

    def _adopt_source_host(self):
        write(self.host, "README.md", "# ordinary project\n")
        write(self.host, "src/app.py", "value = 1\n")
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        return result

    def _develop_host(self) -> None:
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write_task(self.host)

    def _submit_host(self) -> None:
        write_submit_host(self.host)

    def _set_global_refs(self, refs: list[str]) -> None:
        path = self.host / ".scaffold/project.yaml"
        project = read_yaml(path)
        project["rule_refs"] = refs
        write_yaml_atomic(path, project)

    def _set_modules(self, modules: list[dict]) -> None:
        write_yaml_atomic(
            self.host / ".scaffold/modules.yaml",
            {"schema_version": "1", "modules": modules},
        )

    def _write_rules(self, rel: str, rules: list[dict]) -> None:
        write_yaml_atomic(
            self.host / rel,
            {"schema_version": "1", "rules": rules},
        )

    def _resolve(
        self,
        skill: str,
        paths: list[str],
        modules: list[str],
        operation: str,
    ) -> dict:
        return resolve_project_rules(
            self.host,
            project=read_yaml(self.host / ".scaffold/project.yaml"),
            skill_id=skill,
            paths=paths,
            modules=modules,
            test_ids=[],
            operation=operation,
        )

    @staticmethod
    def _rule(
        rule_id: str,
        *,
        applies_to: list[str] | None = None,
        effect: str = "ADVISE",
        operations: list[str] | None = None,
        scope: dict | None = None,
        statement: str = "fixture project rule",
    ) -> dict:
        row = {
            "rule_id": rule_id,
            "applies_to": applies_to or ["test", "develop", "submit"],
            "effect": effect,
            "operations": operations or ["*"],
            "statement": statement,
        }
        if scope is not None:
            row["scope"] = scope
        return row


if __name__ == "__main__":
    unittest.main()

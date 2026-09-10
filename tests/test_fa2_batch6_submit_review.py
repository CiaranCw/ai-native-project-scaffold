from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from p6_support import (
    CORE_OWNERSHIP,
    passing_profile,
    write_modules,
)
from p7_support import TASK_A, TASK_B, write_task
from p8_support import (
    run_submit,
    COMPLETE_STAGES,
    init_submit_git,
    publish_knowledge_outcomes,
    rebind_noscms_baseline,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.structural import (
    IMPACT_COMMAND,
    IMPACT_DEPENDENCY,
    IMPACT_PUBLIC_INTERFACE,
    IMPACT_TEST_CONFIGURATION,
    STATUS_UNKNOWN,
    missing_scoped_source,
    scope_covers_path,
    scope_path_present,
)
from support import write


class FA2Batch6SubmitReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_B6N01_no_task_ordinary_diff_reaches_review(self):
        self._no_task_host()
        result = run_submit(self.host, 
            invoke_test=True,
            selected=["unit"],
            changed_paths=["docs/fake.md"],
        )
        self.assertNotIn(
            "missing Task Book identity",
            " ".join(result.blockers),
        )
        self.assertTrue(result.extras.get("no_task"))
        self.assertEqual(result.extras["task_identity"], "none")
        self.assertEqual(result.extras["task_book_ids"], [])
        self.assertEqual(result.extras["task_complete"], "NOT_APPLICABLE")
        self.assertEqual(result.extras["ready_for_review"], "NOT_APPLICABLE")
        self.assertNotIn("task", result.extras)
        self.assertIn(result.extras.get("stage"), {"S3", "S4", "S5", "S6"})
        self.assertIn("src/app.py", result.extras.get("delta", {}).get("paths") or [])
        self.assertIn("structural", result.extras)
        self.assertIn("knowledge", result.extras)
        self.assertIn("completeness", result.extras)

    def test_B6N02_no_task_does_not_bypass_project_test_policy(self):
        self._no_task_host()
        result = run_submit(self.host, )
        self.assertEqual(result.outcome, "BLOCKED", result.blockers)
        self.assertEqual(result.extras.get("stage"), "S5")
        completeness = result.extras["completeness"]
        self.assertIn("unit", completeness.get("project_required_ids") or [])
        self.assertFalse(completeness.get("test_complete"))
        self.assertFalse(completeness.get("zero_required"))

    def test_B6N03_no_task_change_record(self):
        self._no_task_host()
        digest = observe_candidate(self.host).digest
        result = run_submit(self.host, 
            invoke_test=True,
            selected=["unit"],
            finalize=True,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        record = result.extras["change_record"]
        self.assertEqual(record["task_book_ids"], [])
        self.assertFalse(any("synthetic" in item for item in record["task_book_ids"]))
        self.assertTrue(
            any("No Task Book" in item for item in record.get("limitations") or [])
        )
        self.assertTrue(result.extras["s10"]["durable"])
        self.assertFalse(result.extras["push"]["performed"])

    def test_B6N04_existing_non_ready_task_cannot_masquerade_as_no_task(self):
        write_submit_host(self.host)
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        result = run_submit(self.host, )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("READY_FOR_REVIEW" in item for item in result.blockers))
        self.assertFalse(result.extras.get("no_task"))
        self.assertNotEqual(result.extras.get("task_complete"), "NOT_APPLICABLE")

    def test_B6N05_task_based_submit_regression(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["task"]["status"], "READY_FOR_REVIEW")
        self.assertFalse(result.extras.get("no_task"))
        self.assertEqual(result.extras["task_identity"], "task")
        self.assertTrue(result.extras["task_complete"] in {True, False})
        self.assertTrue(result.extras["ready_for_review"])

    def test_B6N06_unknown_module_cannot_masquerade_as_no_task(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={
                "paths": [],
                "modules": ["missing-module"],
                "exclude": [],
            },
        )
        init_submit_git(self.host)
        write(self.host, "src/save/impl.py", "impl = 1\n")
        result = run_submit(self.host, )
        self.assertNotEqual(result.extras.get("no_task"), True)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S1")
        joined = " ".join(result.blockers)
        self.assertIn("UNKNOWN", joined)
        self.assertIn("missing-module", joined)
        self.assertIn(TASK_A, joined)
        self.assertEqual(result.next_route, "understand.refresh")

    def test_B6N07_known_applicable_plus_unknown_is_not_unique(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        self._write_ready_other(
            TASK_B,
            scope={
                "paths": [],
                "modules": ["missing-module"],
                "exclude": [],
            },
        )
        result = run_submit(self.host, )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(result.extras.get("no_task"), True)
        self.assertNotEqual(result.extras.get("task_identity"), "task")
        self.assertNotIn("task", result.extras)
        self.assertNotIn(TASK_A, result.extras.get("task_book_ids") or [])
        joined = " ".join(result.blockers)
        self.assertIn("UNKNOWN", joined)
        self.assertIn(TASK_B, joined)
        self.assertEqual(result.next_route, "understand.refresh")

    def test_B6N08_explicit_task_with_unknown_module_remains_task_path(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={
                "paths": [],
                "modules": ["missing-module"],
                "exclude": [],
            },
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras.get("no_task"))
        self.assertEqual(result.extras.get("task_identity"), "task")
        self.assertEqual(result.extras.get("task", {}).get("record_id"), TASK_A)
        self.assertEqual(result.extras.get("stage"), "S3")
        joined = " ".join(result.blockers)
        self.assertIn("UNKNOWN", joined)
        self.assertIn("missing-module", joined)

    def test_B6N09_deterministic_zero_applicable_remains_no_task(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={"paths": ["src/a/"], "modules": [], "exclude": []},
        )
        self._write_ready_other(
            TASK_B,
            scope={"paths": ["src/b/"], "modules": [], "exclude": []},
        )
        init_submit_git(self.host)
        write(self.host, "docs/readme.md", "unrelated note\n")
        result = run_submit(self.host, 
            invoke_test=True,
            selected=["unit"],
        )
        self.assertNotIn(
            "missing Task Book identity",
            " ".join(result.blockers),
        )
        self.assertNotIn(
            "Task applicability is UNKNOWN",
            " ".join(result.blockers),
        )
        self.assertTrue(result.extras.get("no_task"))
        self.assertEqual(result.extras["task_identity"], "none")
        self.assertEqual(result.extras["task_book_ids"], [])
        self.assertEqual(result.extras["task_complete"], "NOT_APPLICABLE")
        self.assertIn(result.extras.get("stage"), {"S3", "S4", "S5", "S6"})

    def test_B6N10_known_path_proves_applicable_with_unknown_extra_module(self):
        write_submit_host(self.host)
        self._set_ownership({"src/": "HUMAN_OWNED"})
        write_ready_task(
            self.host,
            scope={
                "paths": ["src/save/"],
                "modules": ["missing-module"],
                "exclude": [],
            },
        )
        init_submit_git(self.host)
        write(self.host, "src/save/a.py", "save_a = 1\n")
        result = run_submit(self.host, )
        self.assertNotEqual(result.extras.get("no_task"), True)
        self.assertEqual(result.extras.get("task_identity"), "task")
        self.assertEqual(result.extras.get("task", {}).get("record_id"), TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        joined = " ".join(result.blockers)
        self.assertIn("UNKNOWN", joined)
        self.assertIn("missing-module", joined)

    def test_B6S01_directory_scope_positive(self):
        self.assertTrue(scope_covers_path("src/", "src/app.py"))
        self.assertTrue(scope_covers_path("src/", "src/sub/a.py"))
        self.assertTrue(scope_covers_path("src/", "src/"))
        write_submit_host(self.host)
        write(self.host, "src/sub/a.py", "nested = 1\n")
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertNotIn("src/app.py", undeclared)
        self.assertNotIn("src/sub/a.py", undeclared)

    def test_B6S02_directory_boundary_negative(self):
        self.assertFalse(scope_covers_path("src/", "src2/app.py"))
        write_submit_host(self.host)
        write(self.host, "src2/app.py", "other = 1\n")
        self._set_ownership({"src/": "HUMAN_OWNED", "src2/": "HUMAN_OWNED"})
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(
            any("undeclared" in item for item in result.extras["structural"]["blockers"])
        )
        self.assertIn("src2/app.py", result.extras["structural"].get("undeclared") or [])

    def test_B6S03_nested_directory_boundary(self):
        self.assertTrue(scope_covers_path("foo/bar/", "foo/bar/a.py"))
        self.assertFalse(scope_covers_path("foo/bar/", "foo/barista/a.py"))
        write_submit_host(self.host)
        write(self.host, "foo/bar/a.py", "inside = 1\n")
        write(self.host, "foo/barista/a.py", "outside = 1\n")
        self._set_ownership(
            {"src/": "HUMAN_OWNED", "foo/": "HUMAN_OWNED"}
        )
        write_ready_task(
            self.host,
            scope={"paths": ["foo/bar/", "src/"], "modules": [], "exclude": []},
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertNotIn("foo/bar/a.py", undeclared)
        self.assertIn("foo/barista/a.py", undeclared)

    def test_B6S04_directory_itself_exists(self):
        write_submit_host(self.host)
        self.assertTrue(scope_path_present(self.host, "src/"))
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        missing = missing_scoped_source(self.host, read_yaml(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        ))
        self.assertEqual(missing, [])
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse(result.extras["structural"].get("repair_required"))

    def test_B6S05_module_only_scope_rejects_extra_path(self):
        self._module_scope_host(
            paths=[],
            modules=["save"],
            extra_ownership={"other/": "HUMAN_OWNED"},
        )
        init_submit_git(self.host)
        write(self.host, "src/save/impl.py", "impl = 1\n")
        write(self.host, "other/unrelated.py", "outside = 1\n")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertIn("other/unrelated.py", undeclared)
        self.assertNotIn("src/save/impl.py", undeclared)
        self.assertTrue(
            any("undeclared" in item for item in result.extras["structural"]["blockers"])
        )

    def test_B6S06_module_only_positive(self):
        self._module_scope_host(paths=[], modules=["save"])
        init_submit_git(self.host)
        write(self.host, "src/save/impl.py", "impl = 1\n")
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertNotIn("src/save/impl.py", undeclared)
        self.assertTrue(result.extras["structural"]["structural_review_pass"])

    def test_B6S07_path_and_module_union(self):
        self._module_scope_host(
            paths=["docs/custom/"],
            modules=["save"],
            extra_ownership={"other/": "HUMAN_OWNED"},
        )
        init_submit_git(self.host)
        write(self.host, "docs/custom/x.md", "custom note\n")
        write(self.host, "src/save/a.py", "save_a = 1\n")
        write(self.host, "other/unrelated.py", "outside = 1\n")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertNotIn("docs/custom/x.md", undeclared)
        self.assertNotIn("src/save/a.py", undeclared)
        self.assertIn("other/unrelated.py", undeclared)

    def test_B6S08_unknown_module_fails_closed(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={
                "paths": [],
                "modules": ["missing-module"],
                "exclude": [],
            },
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertFalse(result.extras["structural"]["structural_review_pass"])
        joined = " ".join(result.blockers)
        self.assertIn("UNKNOWN", joined)
        self.assertIn("missing-module", joined)
        self.assertNotEqual(result.outcome, "COMPLETED")

    def test_B6S09_module_exclude(self):
        self._module_scope_host(
            paths=[],
            modules=["save"],
            exclude=["src/save/generated/"],
        )
        init_submit_git(self.host)
        write(self.host, "src/save/core.py", "core = 1\n")
        write(self.host, "src/save/generated/a.py", "generated = 1\n")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        undeclared = result.extras["structural"].get("undeclared") or []
        self.assertNotIn("src/save/core.py", undeclared)
        self.assertIn("src/save/generated/a.py", undeclared)

    def test_B6R01_real_diff_input(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            changed_paths=["docs/fake.md"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        reviewed = result.extras["structural"]["reviewed_paths"]
        self.assertEqual(reviewed, result.extras["delta"]["paths"])
        self.assertIn("src/app.py", reviewed)
        self.assertNotIn("docs/fake.md", reviewed)

    def test_B6R02_module_public_interface_impact(self):
        self._interface_host()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            (result.extras.get("structural") or {}).get("impact_classes") or [],
            result.blockers,
        )
        self.assertNotEqual(
            (result.extras.get("structural") or {}).get("impacts"), []
        )

    def test_B6R03_dependency_config_impact(self):
        write_submit_host(self.host)
        write_ready_task(
            self.host,
            scope={"paths": ["src/", "requirements.txt"], "modules": [], "exclude": []},
        )
        init_submit_git(self.host)
        write(self.host, "requirements.txt", "demo==1.0\n")
        result = run_submit(self.host, task_id=TASK_A)
        self.assertIn(
            IMPACT_DEPENDENCY,
            result.extras["structural"].get("impact_classes") or [],
        )

    def test_B6R04_command_metadata_impact(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        commands["commands"].append(
            {
                "id": "cmd-extra",
                "argv": ["python", "-c", "print(1)"],
                "availability": "declared",
                "confidence": "VERIFIED",
            }
        )
        write_yaml_atomic(self.host / ".scaffold/commands.yaml", commands)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertIn(
            IMPACT_COMMAND,
            (result.extras.get("structural") or {}).get("impact_classes") or [],
            result.blockers,
        )

    def test_B6R05_test_configuration_impact(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        extra, command = passing_profile("extra", required=False)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        tests["profiles"].append(extra)
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        commands["commands"].append(command)
        write_yaml_atomic(self.host / ".scaffold/commands.yaml", commands)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertIn(
            IMPACT_TEST_CONFIGURATION,
            (result.extras.get("structural") or {}).get("impact_classes") or [],
            result.blockers,
        )

    def test_B6R06_ordinary_non_structural_source_edit(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["structural"]["structural_review_pass"])
        self.assertEqual(result.extras["structural"].get("impact_classes") or [], [])
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])

    def test_B6R07_unknown_structural_surface(self):
        write_submit_host(self.host)
        write(self.host, "src/save/api.py", "def save():\n    return 1\n")
        write_modules(
            self.host,
            [
                {
                    "id": "save",
                    "path": "src/save/",
                    "public_interface": "UNKNOWN",
                }
            ],
        )
        self._set_ownership({"src/": "HUMAN_OWNED"})
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(result.extras["structural"].get("structural_unknown"))
        self.assertFalse(result.extras["structural"]["structural_review_pass"])
        statuses = {
            row.get("status")
            for row in result.extras["structural"].get("impacts") or []
        }
        self.assertIn(STATUS_UNKNOWN, statuses)

    def test_B6K01_structural_impact_requires_knowledge_check(self):
        self._interface_host()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")

    def test_B6K02_relevant_knowledge_updated(self):
        self._interface_host()
        write(
            self.host,
            "docs/project/architecture.md",
            "save module public interface src/save/api.py\n",
        )
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])

    def test_B6K03_command_knowledge(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        commands["commands"].append(
            {
                "id": "cmd-extra",
                "argv": ["python", "-c", "print(1)"],
                "availability": "declared",
                "confidence": "VERIFIED",
            }
        )
        write_yaml_atomic(self.host / ".scaffold/commands.yaml", commands)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_B6K04_test_knowledge(self):
        write_submit_host(self.host)
        init_submit_git(self.host)
        extra, command = passing_profile("extra", required=False)
        tests = read_yaml(self.host / ".scaffold/tests.yaml")
        tests["profiles"].append(extra)
        write_yaml_atomic(self.host / ".scaffold/tests.yaml", tests)
        commands = read_yaml(self.host / ".scaffold/commands.yaml")
        commands["commands"].append(command)
        write_yaml_atomic(self.host / ".scaffold/commands.yaml", commands)
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_B6K05_maintenance_flag_cannot_override_diff(self):
        self._interface_host()
        result = run_submit(self.host, 
            task_id=TASK_A,
            maintenance_required=False,
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])

    def test_B6K06_non_structural_source_change(self):
        write_submit_host(self.host)
        result = run_submit(self.host, 
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.extras["structural"].get("impact_classes") or [], [])
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("missing_surfaces") or [], [])

    def test_B6K07_preexisting_mention_does_not_satisfy_new_impact(self):
        self._interface_host()
        write(
            self.host,
            "docs/project/architecture.md",
            "The save module lives at src/save/api.py.\n",
        )
        init_submit_git(self.host)
        write(
            self.host,
            "src/save/api.py",
            "def save(name):\n    return name\n",
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            result.extras["structural"].get("impact_classes") or [],
        )
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertNotIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )
        self.assertIn(
            "src/save/api.py",
            result.extras.get("delta", {}).get("paths") or [],
        )

    def test_B6K08_current_diff_knowledge_update_passes(self):
        self._interface_host()
        write(
            self.host,
            "docs/project/architecture.md",
            "The save module lives at src/save/api.py.\n",
        )
        init_submit_git(self.host)
        write(
            self.host,
            "src/save/api.py",
            "def save(name):\n    return name\n",
        )
        write(
            self.host,
            "docs/project/architecture.md",
            "save public interface now accepts a name at src/save/api.py.\n",
        )
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["knowledge"]["knowledge_consistent"])
        self.assertIn(
            "docs/project/architecture.md",
            result.extras.get("delta", {}).get("paths") or [],
        )

    def test_B6K09_wrong_module_doc_does_not_satisfy_impact(self):
        self._interface_host()
        write(
            self.host,
            "docs/project/architecture.md",
            "The save module lives at src/save/api.py.\n",
        )
        write(self.host, "docs/project/modules/save.md", "save module notes\n")
        write(self.host, "docs/project/modules/other.md", "other module notes\n")
        init_submit_git(self.host)
        write(
            self.host,
            "src/save/api.py",
            "def save(name):\n    return name\n",
        )
        write(
            self.host,
            "docs/project/modules/other.md",
            "other module notes were edited\n",
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            result.extras["structural"].get("impact_classes") or [],
        )
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")
        paths = result.extras.get("delta", {}).get("paths") or []
        self.assertIn("docs/project/modules/other.md", paths)
        self.assertNotIn("docs/project/modules/save.md", paths)
        self.assertNotIn("docs/project/architecture.md", paths)

    def test_B6X01_no_task_structural_human_diff(self):
        self._interface_host(remove_task=True)
        result = run_submit(self.host, )
        self.assertNotIn(
            "missing Task Book identity",
            " ".join(result.blockers),
        )
        self.assertTrue(result.extras.get("no_task"))
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertIn(result.extras.get("stage"), {"S3", "S4"})
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            (result.extras.get("structural") or {}).get("impact_classes") or [],
        )

    def test_B6X02_directory_scoped_task_structural_diff(self):
        self._interface_host()
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        write(
            self.host,
            "docs/project/architecture.md",
            "save module public interface src/save/api.py\n",
        )
        first = run_submit(self.host, task_id=TASK_A)
        self.assertNotIn(
            "undeclared",
            " ".join(first.extras.get("structural", {}).get("blockers") or []),
        )
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            first.extras["structural"].get("impact_classes") or [],
        )
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        result = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)

    def test_B6X03_rule_conflict_still_wins(self):
        write_submit_host(self.host)
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["rule_refs"] = ["docs/project/no-submit.rules.yaml"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        write_yaml_atomic(
            self.host / "docs/project/no-submit.rules.yaml",
            {
                "schema_version": "1",
                "rules": [
                    {
                        "rule_id": "no-app-submit",
                        "applies_to": ["submit"],
                        "effect": "PROHIBIT",
                        "operations": ["source_write"],
                        "statement": "fixture prohibition",
                        "scope": {"kind": "path", "paths": ["src/app.py"]},
                    }
                ],
            },
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S3")
        self.assertTrue(any("no-app-submit" in item for item in result.blockers))

    def test_B6X04_scm_observation_unknown(self):
        write_submit_host(self.host)
        failed = {
            "ok": False,
            "kind": "git",
            "paths": [],
            "entries": [],
            "blockers": ["Git real Diff observation is UNKNOWN"],
        }
        with mock.patch(
            "scaffold_p8.engine.observe_real_diff",
            return_value=failed,
        ):
            result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S2")
        self.assertNotEqual(result.extras.get("structural", {}).get("structural_review_pass"), True)
        self.assertNotEqual(result.extras.get("knowledge", {}).get("knowledge_consistent"), True)

    def _write_ready_other(self, task_id: str, **overrides) -> dict:
        data = {
            "status": "READY_FOR_REVIEW",
            "stages": COMPLETE_STAGES,
            "final_tests": [],
        }
        data.update(overrides)
        return write_task(self.host, task_id, **data)

    def _no_task_host(self) -> None:
        write_submit_host(self.host, noscms_working_diff=False)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        if task_path.is_file():
            task_path.unlink()
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")

    def _interface_host(self, *, remove_task: bool = False) -> None:
        write_submit_host(self.host, noscms_working_diff=False)
        write(self.host, "src/save/api.py", "def save():\n    return 1\n")
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
        self._set_ownership({"src/": "HUMAN_OWNED"})
        if remove_task:
            task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            if task_path.is_file():
                task_path.unlink()
        else:
            write_ready_task(
                self.host,
                scope={"paths": ["src/"], "modules": [], "exclude": []},
            )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")

    def _module_scope_host(
        self,
        *,
        paths: list[str] | None = None,
        modules: list[str] | None = None,
        exclude: list[str] | None = None,
        extra_ownership: dict[str, str] | None = None,
    ) -> None:
        write_submit_host(self.host, noscms_working_diff=False)
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
        ownership = {"src/": "HUMAN_OWNED"}
        if extra_ownership:
            ownership.update(extra_ownership)
        self._set_ownership(ownership)
        write_ready_task(
            self.host,
            scope={
                "paths": list(paths or []),
                "modules": list(modules if modules is not None else ["save"]),
                "exclude": list(exclude or []),
            },
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")

    def _set_ownership(self, ownership: dict[str, str]) -> None:
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, **ownership}
        payload["source_areas"] = sorted(
            {
                key.rstrip("/")
                for key in ownership
                if key.endswith("/")
            }
            | set(payload.get("source_areas") or [])
        )
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)


if __name__ == "__main__":
    unittest.main()

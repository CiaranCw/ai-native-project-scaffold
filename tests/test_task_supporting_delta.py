from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import TASK_A, write_active_host, write_task
from support import write

from scaffold_p5.host_state import snapshot_host
from scaffold_p7.intake import prepare_proposal
from scaffold_p7.mutation import authorize_writes
from scaffold_p8.delta import classify_delta
from scaffold_p8.preflight import inspect_host_project
from scaffold_p8.structural import review_structure
from scaffold_p8.task_authority import resolve_task_scope


VAULT_PRODUCT = "src/mvp/vault.js"
VAULT_TEST = "tests/unit/vault.test.js"
VAULT_TOOL = "tools/mvp/verify-vault.mjs"
VAULT_EVIDENCE = "artifacts/evidence/mvp-vault/run.log"
UNDECLARED = "lib/other/secret.js"

VAULT_SCOPE = {
    "paths": ["src/mvp"],
    "modules": [],
    "exclude": [],
    "supporting_paths": [
        "tests/unit",
        "tools/mvp/verify-vault.mjs",
        "artifacts/evidence/mvp-vault",
    ],
}


def _vault_proposal() -> dict:
    return {
        "title": "Vault candidate",
        "goal": "Ship product plus supporting tests, tool, and evidence.",
        "acceptance": "Product and supporting delta are Task-bound.",
        "scope": dict(VAULT_SCOPE),
        "stages": [
            {
                "stage_id": "stage-1",
                "goal": "Implement the vault candidate.",
                "acceptance": "Product and supporting files exist.",
                "required_tests": [],
            }
        ],
        "final_tests": [],
    }


class TaskSupportingDeltaTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, VAULT_PRODUCT, "export const vault = true\n")
        write(self.host, VAULT_TEST, "assert(true)\n")
        write(self.host, VAULT_TOOL, "console.log('verify')\n")
        write(self.host, VAULT_EVIDENCE, "ok\n")
        write(self.host, UNDECLARED, "nope\n")
        write(self.host, "legacy/dirty.txt", "inherited\n")
        self.task = write_task(
            self.host,
            TASK_A,
            status="IN_PROGRESS",
            scope=dict(VAULT_SCOPE),
        )
        self.project = inspect_host_project(self.host)[2]

    def tearDown(self):
        self._tmp.cleanup()

    def test_supporting_paths_are_not_project_ownership(self):
        ownership = (self.project or {}).get("ownership") or {}
        for rel in (VAULT_TEST, VAULT_TOOL, VAULT_EVIDENCE):
            self.assertNotIn(rel, ownership)
            self.assertFalse(
                any(
                    rel == key or rel.startswith(str(key).rstrip("/") + "/")
                    for key in ownership
                    if str(key).startswith(("tests", "tools", "artifacts"))
                )
            )
        resolution = resolve_task_scope(self.host, self.task)
        self.assertIn("tests/unit", resolution.supporting_paths)
        self.assertNotIn("tests/unit", resolution.declared_paths)
        self.assertNotIn("tests/unit", resolution.allowed)

    def test_prepare_proposal_keeps_supporting_paths(self):
        normalized, issues = prepare_proposal(_vault_proposal())
        self.assertEqual(issues, [])
        self.assertIsNotNone(normalized)
        self.assertEqual(
            normalized["scope"]["supporting_paths"],
            sorted(VAULT_SCOPE["supporting_paths"]),
        )

    def test_develop_may_mutate_declared_supporting_paths(self):
        plan = authorize_writes(
            self.host,
            writes=[
                {"path": VAULT_TEST, "content": "assert(vault)\n"},
                {"path": VAULT_TOOL, "content": "console.log('ok')\n"},
                {"path": VAULT_EVIDENCE, "content": "pass\n"},
            ],
            task=self.task,
            project=self.project,
        )
        self.assertTrue(plan.ok, plan.blockers)
        roles = {row["path"]: row["scope_role"] for row in plan.authority}
        self.assertEqual(roles[VAULT_TEST], "supporting")
        self.assertEqual(roles[VAULT_TOOL], "supporting")
        self.assertEqual(roles[VAULT_EVIDENCE], "supporting")

    def test_undeclared_and_governance_supporting_fail_closed(self):
        undeclared = authorize_writes(
            self.host,
            writes=[{"path": UNDECLARED, "content": "x\n"}],
            task=self.task,
            project=self.project,
        )
        self.assertFalse(undeclared.ok)
        governance, issues = prepare_proposal(
            {
                **_vault_proposal(),
                "scope": {
                    **VAULT_SCOPE,
                    "supporting_paths": [".scaffold/project.yaml"],
                },
            }
        )
        self.assertIsNone(governance)
        self.assertTrue(any("governance" in item for item in issues))
        wildcard, wild_issues = prepare_proposal(
            {
                **_vault_proposal(),
                "scope": {**VAULT_SCOPE, "supporting_paths": ["**"]},
            }
        )
        self.assertIsNone(wildcard)
        self.assertTrue(wild_issues)

    def test_s2_distinguishes_inherited_product_supporting_unrelated(self):
        sessions = [
            {
                "session": {
                    "record_id": "dev-20260913T000000Z-abcd1234",
                    "created_at": "2026-09-13T00:00:00Z",
                    "workspace_overlay_s0": {"coverage": "unavailable", "paths": []},
                    "workspace_overlay_s1": {"coverage": "unavailable", "paths": []},
                },
                "files": [
                    {
                        "path": "legacy/dirty.txt",
                        "was_preexisting_dirty": True,
                    }
                ],
            }
        ]
        delta = classify_delta(
            self.host,
            real_paths=[
                VAULT_PRODUCT,
                VAULT_TEST,
                VAULT_TOOL,
                VAULT_EVIDENCE,
                "legacy/dirty.txt",
                UNDECLARED,
            ],
            sessions=sessions,
            task=self.task,
        )
        roles = delta["task_delta_classes"]
        self.assertEqual(roles[VAULT_PRODUCT], "task_product_delta")
        self.assertEqual(roles[VAULT_TEST], "task_supporting_delta")
        self.assertEqual(roles[VAULT_TOOL], "task_supporting_delta")
        self.assertEqual(roles[VAULT_EVIDENCE], "task_supporting_delta")
        self.assertEqual(roles["legacy/dirty.txt"], "inherited_baseline")
        self.assertEqual(roles[UNDECLARED], "unrelated_delta")

    def test_vault_shaped_candidate_reaches_structural_review(self):
        paths = [VAULT_PRODUCT, VAULT_TEST, VAULT_TOOL, VAULT_EVIDENCE]
        structural = review_structure(
            root=self.host,
            task=self.task,
            real_diff={
                "paths": paths,
                "entries": [{"path": item} for item in paths],
            },
            project=self.project,
        )
        self.assertEqual(structural["unknown_ownership"], [])
        self.assertEqual(structural["undeclared"], [])
        self.assertTrue(structural["structural_review_pass"], structural["blockers"])

    def test_undeclared_path_still_blocks_structural_review(self):
        paths = [VAULT_PRODUCT, UNDECLARED]
        structural = review_structure(
            root=self.host,
            task=self.task,
            real_diff={
                "paths": paths,
                "entries": [{"path": item} for item in paths],
            },
            project=self.project,
        )
        self.assertFalse(structural["structural_review_pass"])
        self.assertTrue(structural["undeclared"] or structural["unknown_ownership"])

    def test_candidate_authority_remains_valid(self):
        self.assertEqual(snapshot_host(self.host).host_class, "ESTABLISHED_HOST")
        self.assertEqual(self.task["status"], "IN_PROGRESS")

    def test_arbitrary_invented_deep_supporting_prefix_is_rejected(self):
        from scaffold_p7.engine import _intake_scope_issues

        proposal = _vault_proposal()
        proposal["scope"] = {
            **VAULT_SCOPE,
            "supporting_paths": ["tests/totally/invented/deep/prefix"],
        }
        normalized, issues = prepare_proposal(proposal)
        self.assertEqual(issues, [])
        grounded = _intake_scope_issues(self.host, self.project or {}, normalized)
        self.assertTrue(
            any("tests/totally/invented/deep/prefix" in item for item in grounded),
            grounded,
        )

    def test_bounded_new_child_under_existing_support_area_is_grounded(self):
        from scaffold_p7.engine import _intake_scope_issues

        proposal = _vault_proposal()
        proposal["scope"] = {
            **VAULT_SCOPE,
            "supporting_paths": ["tests/unit/new_helper.test.js"],
        }
        normalized, issues = prepare_proposal(proposal)
        self.assertEqual(issues, [])
        grounded = _intake_scope_issues(self.host, self.project or {}, normalized)
        self.assertFalse(
            any("tests/unit/new_helper.test.js" in item for item in grounded),
            grounded,
        )

    def test_arbitrary_nonexistent_supporting_prefix_is_rejected(self):
        from scaffold_p7.engine import _intake_scope_issues

        proposal = _vault_proposal()
        proposal["scope"] = {
            **VAULT_SCOPE,
            "supporting_paths": ["nonexistent/anything"],
        }
        normalized, issues = prepare_proposal(proposal)
        self.assertEqual(issues, [])
        grounded = _intake_scope_issues(self.host, self.project or {}, normalized)
        self.assertTrue(
            any("nonexistent/anything" in item for item in grounded),
            grounded,
        )

    def test_managed_and_human_owned_cannot_be_smuggled_as_supporting(self):
        from scaffold_p5.io_util import read_yaml, write_yaml_atomic

        project_path = self.host / ".scaffold" / "project.yaml"
        project = read_yaml(project_path)
        project["ownership"] = {
            **(project.get("ownership") or {}),
            "tests/unit/": "MANAGED",
            "tools/mvp/": "HUMAN_OWNED",
        }
        write_yaml_atomic(project_path, project)
        project = inspect_host_project(self.host)[2]
        managed = authorize_writes(
            self.host,
            writes=[{"path": VAULT_TEST, "content": "assert(false)\n"}],
            task=self.task,
            project=project,
        )
        self.assertFalse(managed.ok, managed.blockers)
        human = authorize_writes(
            self.host,
            writes=[{"path": VAULT_TOOL, "content": "console.log('no')\n"}],
            task=self.task,
            project=project,
        )
        self.assertFalse(human.ok, human.blockers)
        structural = review_structure(
            root=self.host,
            task=self.task,
            real_diff={
                "paths": [VAULT_TEST, VAULT_TOOL],
                "entries": [{"path": VAULT_TEST}, {"path": VAULT_TOOL}],
            },
            project=project,
        )
        self.assertFalse(structural["structural_review_pass"], structural["blockers"])

    def test_hook_and_p7_share_path_authorization(self):
        from scaffold_p7.mutation import authorize_path_mutation

        allowed, reason, role = authorize_path_mutation(
            self.host,
            VAULT_TEST,
            task=self.task,
            project=self.project,
        )
        self.assertTrue(allowed, reason)
        self.assertEqual(role, "supporting")
        denied, _reason, _role = authorize_path_mutation(
            self.host,
            UNDECLARED,
            task=self.task,
            project=self.project,
        )
        self.assertFalse(denied)


if __name__ == "__main__":
    unittest.main()

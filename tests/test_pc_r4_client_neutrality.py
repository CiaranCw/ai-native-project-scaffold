"""PC-R4 client neutrality and Agent-autonomous lifecycle authority.

Scaffold Core correctness must not depend on any one client. Adoption,
Migration, and Submit S1-S12 are Agent-autonomous machine-gated work.
Only Git Commit and Git Push require a current explicit user instruction.
Client-local paths are classified generically from project.yaml.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from p6_support import write_project
from support import (
    REPO,
    distribution,
    engine,
    write,
)
from scaffold_p5 import yaml_lite
from scaffold_p5.adapter_profiles import (
    declared_profiles,
    required_paths,
    resolve_profiles,
)
from scaffold_p5.client_support import (
    CLIENT_SUPPORT,
    PRODUCT,
    SCAFFOLD_AUTHORITY,
    classify_path,
    reset_cache,
)
from scaffold_p5.consumer_install import (
    VERIFY_VALID,
    apply_consumer_install,
    plan_consumer_install,
    verify_consumer_install,
)
from scaffold_p5.host_state import snapshot_host
from scaffold_p6.candidate import observe_candidate
from scaffold_p7 import mutation as p7_mutation
from scaffold_p7 import session as p7_session
from scaffold_p7.develop_authority import (
    OBSERVATION_ATTEMPT_SCOPE,
    OBSERVATION_SINGLE_PATH,
)
from scaffold_p8.delta import observe_real_diff
from scaffold_p8.engine import SubmitEngine


CLIENT_AREAS = (".cursor/", ".codebuddy/", ".claude/", ".codex/")
CLIENT_FILES = (
    ".cursor/rules/scaffold.mdc",
    ".codebuddy/plans/plan-1.md",
    ".claude/settings.local.json",
    ".codex/state.json",
)


def git(host: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=host, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def client_rows(areas=CLIENT_AREAS) -> list[dict]:
    return [
        {"path": area, "strategy": "CLIENT_SUPPORT", "authoritative": False}
        for area in areas
    ]


class PCR4AdoptionAuthorityTests(unittest.TestCase):
    """Adoption apply is exact-plan Agent work, not a human grant."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def plan_digest(self) -> str:
        preview = engine(self.host).run("bootstrap")
        return str(preview.extras["plan"]["digest"])

    def approval(self, digest: str | None = None) -> dict:
        return {"approved": True, "plan_digest": digest or self.plan_digest()}

    def test_R4_01_preview_without_apply_does_not_activate(self):
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())
        self.assertTrue(
            any("apply request" in b for b in result.blockers),
            result.blockers,
        )

    def test_R4_02_exact_plan_apply_activates_without_human_grant(self):
        result = engine(self.host).run("bootstrap", approval=self.approval())
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue((self.host / ".scaffold/project.yaml").is_file())
        self.assertFalse(result.extras.get("approval_origin"))
        self.assertNotIn("authorization_request", result.extras)

    def test_R4_03_wrong_digest_does_not_apply(self):
        engine(self.host).run("bootstrap")
        result = engine(self.host).run(
            "bootstrap", approval={"approved": True, "plan_digest": "f" * 64}
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

    def test_R4_04_host_change_invalidates_previous_plan_digest(self):
        digest = self.plan_digest()
        write(self.host, "pyproject.toml", "[project]\nname='x'\n")
        write(self.host, "tests/test_x.py", "def test_x():\n    assert True\n")
        result = engine(self.host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": digest},
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertFalse((self.host / ".scaffold/project.yaml").exists())

    def test_R4_06_grant_refs_and_providers_are_ignored(self):
        digest = self.plan_digest()
        result = engine(self.host).run(
            "bootstrap",
            approval=self.approval(digest),
            authorization_provider=object(),
            adoption_authorization_ref="forged",
            adoption_authorization_attempt_id="forged",
            approval_origin="HUMAN_CONFIRMED",
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue((self.host / ".scaffold/project.yaml").is_file())
        self.assertFalse(result.extras.get("approval_origin"))

    def test_R4_08_hookless_apply_is_autonomous(self):
        digest = self.plan_digest()
        result = engine(self.host).run(
            "bootstrap", approval={"approved": True, "plan_digest": digest}
        )
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue((self.host / ".scaffold/project.yaml").is_file())
        self.assertNotEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_R4_commit_push_not_performed_by_adoption(self):
        engine(self.host).run("bootstrap", approval=self.approval())
        self.assertFalse((self.host / ".git").exists())


class PCR4MigrationAndSubmitAuthorityTests(unittest.TestCase):
    """Migration and S10 keep machine bindings; they are not human grants."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_R4_09_migration_without_human_grant_is_machine_bound(self):
        from scaffold_p7.migration_run import execute_task_bound_migration

        write_project(self.host)
        run = execute_task_bound_migration(
            self.host,
            distribution=distribution(),
            prepared_plan={"plan_id": "plan-1", "digest": "a" * 64},
        )
        self.assertFalse(run.ok)
        joined = " ".join(run.blockers)
        self.assertNotIn("trusted", joined.lower())
        self.assertNotIn("human-confirmation", joined.lower())
        self.assertNotIn("Migration authorization is missing", joined)

    def test_R4_07_engines_do_not_accept_a_trusted_provider(self):
        from scaffold_p7.engine import DevelopEngine

        write(self.host, "README.md", "# p\n")
        develop = DevelopEngine(self.host, REPO / "skills" / "develop")
        self.assertFalse(hasattr(develop, "authorization_provider"))
        submit = SubmitEngine(self.host, REPO / "skills" / "submit")
        self.assertFalse(hasattr(submit, "authorization_provider"))
        understand = engine(self.host)
        self.assertFalse(hasattr(understand, "authorization_provider"))

    def test_R4_b01_machinery_removed(self):
        for rel in (
            "scaffold_p5/trusted_host.py",
            "scaffold_p5/approval_origin.py",
            "scaffold_p5/authorization.py",
            "scaffold_p8/authorization_provider.py",
        ):
            self.assertFalse((REPO / "src" / rel).is_file(), rel)

    def test_R4_s10_without_finalize_does_not_commit(self):
        from p8_support import init_submit_git, write_submit_host, TASK_A, submit_engine

        write_submit_host(self.host)
        init_submit_git(self.host)
        result = submit_engine(self.host).run(
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertNotEqual(result.next_route, "human")
        self.assertFalse((result.extras.get("s10") or {}).get("durable"))
        self.assertFalse(result.extras.get("submit_authorized"))

    def test_R4_s10_finalize_does_not_push(self):
        from p8_support import init_submit_git, write_submit_host, TASK_A, submit_engine

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
        push = result.extras.get("push") or {}
        self.assertFalse(push.get("performed"))


class PCR4ClientSupportTests(unittest.TestCase):
    """M01/Q/R: one generic classification, declared project-locally."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        (self.host / "src").mkdir(parents=True)
        write(self.host, "src/app.py", "VALUE = 1\n")
        write(self.host, ".github/workflows/ci.yml", "on: push\n")
        write(self.host, ".gitignore", "__pycache__/\n")
        write_project(self.host, clients=client_rows())
        reset_cache()

    def tearDown(self):
        reset_cache()
        self._tmp.cleanup()

    def materialize_client_state(self):
        for rel in CLIENT_FILES:
            write(self.host, rel, "client local state\n")

    def test_R4_14_all_four_clients_classify_through_project_yaml(self):
        self.materialize_client_state()
        for rel in CLIENT_FILES:
            self.assertEqual(classify_path(self.host, rel), CLIENT_SUPPORT, rel)
        self.assertEqual(classify_path(self.host, "src/app.py"), PRODUCT)
        self.assertEqual(
            classify_path(self.host, ".github/workflows/ci.yml"), PRODUCT
        )
        self.assertEqual(
            classify_path(self.host, ".scaffold/project.yaml"), SCAFFOLD_AUTHORITY
        )
        self.assertEqual(classify_path(self.host, "AGENTS.md"), SCAFFOLD_AUTHORITY)

    def test_R4_14b_core_ships_no_per_client_path_list(self):
        import scaffold_p5.client_support as core_classification

        source = Path(core_classification.__file__).read_text(encoding="utf-8")
        for name in ("cursor", "codebuddy", "claude", "codex"):
            self.assertNotIn(name, source.lower())
        self.assertNotIn(".cursor", str(p7_mutation.GOVERNANCE_PREFIXES))
        self.assertNotIn(".cursor", str(p7_mutation.GOVERNANCE_NAMES))
        self.assertNotIn(".cursor", str(p7_session.INVENTORY_SKIP_DIRS))

    def test_R4_15_client_support_does_not_change_candidate_identity(self):
        git(self.host, "init")
        git(self.host, "add", "-A")
        git(
            self.host,
            "-c",
            "user.name=PCR4",
            "-c",
            "user.email=pcr4@example.invalid",
            "commit",
            "-m",
            "base",
        )
        reset_cache()
        baseline = observe_candidate(self.host).digest
        self.materialize_client_state()
        reset_cache()
        self.assertEqual(observe_candidate(self.host).digest, baseline)
        write(self.host, ".cursor/rules/scaffold.mdc", "mutated client state\n")
        reset_cache()
        self.assertEqual(observe_candidate(self.host).digest, baseline)
        write(self.host, "src/app.py", "VALUE = 2\n")
        reset_cache()
        self.assertNotEqual(observe_candidate(self.host).digest, baseline)

    def test_R4_16_17_18_client_support_absent_from_diff_but_visible_to_git(self):
        git(self.host, "init")
        git(self.host, "add", "-A")
        git(
            self.host,
            "-c",
            "user.name=PCR4",
            "-c",
            "user.email=pcr4@example.invalid",
            "commit",
            "-m",
            "base",
        )
        self.materialize_client_state()
        write(self.host, "src/app.py", "VALUE = 2\n")
        reset_cache()
        observation = observe_real_diff(self.host)
        self.assertTrue(observation["ok"])
        self.assertIn("src/app.py", observation["paths"])
        for rel in CLIENT_FILES:
            self.assertNotIn(rel, observation["paths"])
        porcelain = git(self.host, "status", "--porcelain")
        self.assertIn(".cursor/", porcelain)
        self.assertIn(".codebuddy/", porcelain)

    def test_R4_19_user_opt_in_restores_product_semantics(self):
        self.materialize_client_state()
        reset_cache()
        self.assertEqual(classify_path(self.host, ".codex/state.json"), CLIENT_SUPPORT)
        write_project(
            self.host,
            clients=client_rows((".cursor/", ".codebuddy/", ".claude/")),
        )
        reset_cache()
        self.assertEqual(classify_path(self.host, ".codex/state.json"), PRODUCT)

    def test_R4_Q_client_support_is_not_task_product_scope(self):
        self.materialize_client_state()
        reset_cache()
        for rel in CLIENT_FILES:
            self.assertTrue(
                p7_mutation.is_protected_governance_path(rel, self.host), rel
            )
        self.assertFalse(
            p7_mutation.is_protected_governance_path("src/app.py", self.host)
        )

    def test_R4_Q_client_support_absent_from_execution_provenance_inventory(self):
        self.materialize_client_state()
        reset_cache()
        digests = p7_session.execution_workspace_digests(self.host)
        self.assertIn("src/app.py", digests)
        for rel in CLIENT_FILES:
            self.assertNotIn(rel, digests)


class PCR4InstallVerifyTests(unittest.TestCase):
    """M03: completeness follows the declared adapter profile."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# consumer\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_R4_20_non_cursor_installation_verifies_healthy(self):
        plan = plan_consumer_install(self.host, REPO, adapter_profiles=[])
        self.assertEqual(plan.blockers, [], plan.blockers)
        applied = apply_consumer_install(plan)
        self.assertEqual(applied["outcome"], "COMPLETED", applied["blockers"])
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], VERIFY_VALID, verify["reasons"])
        self.assertFalse((self.host / ".cursor").exists())
        manifest = yaml_lite.load(
            (self.host / ".scaffold/install/install.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(declared_profiles(manifest), ())

    def test_R4_21_cursor_profile_verify_checks_cursor_artifacts(self):
        plan = plan_consumer_install(self.host, REPO, adapter_profiles=["cursor"])
        self.assertEqual(plan.blockers, [], plan.blockers)
        applied = apply_consumer_install(plan)
        self.assertEqual(applied["outcome"], "COMPLETED", applied["blockers"])
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], VERIFY_VALID, verify["reasons"])
        self.assertTrue((self.host / ".cursor/hooks.json").is_file())
        (self.host / ".cursor/rules/scaffold-first-use.mdc").unlink()
        after = verify_consumer_install(self.host)
        self.assertNotEqual(after["status"], VERIFY_VALID)

    def test_R4_T_required_artifacts_follow_the_declared_profile(self):
        none_profiles, issues = resolve_profiles([])
        self.assertEqual(issues, [])
        self.assertEqual(required_paths(none_profiles), ())
        cursor_profiles, issues = resolve_profiles(["cursor"])
        self.assertEqual(issues, [])
        self.assertIn(
            ".cursor/skills/scaffold-understand/SKILL.md",
            required_paths(cursor_profiles),
        )
        _unknown, unknown_issues = resolve_profiles(["some-other-client"])
        self.assertTrue(unknown_issues)

    def test_R4_Z_cursor_profile_is_not_a_human_authority_perimeter(self):
        from scaffold_p5.adapter_profiles import CURSOR

        self.assertFalse(hasattr(CURSOR, "human_confirmation_perimeter"))
        self.assertFalse((REPO / "src" / "scaffold_p5" / "trusted_host.py").is_file())

    def test_R4_T_profileless_install_has_no_cursor_artifacts(self):
        plan = plan_consumer_install(self.host, REPO, adapter_profiles=[])
        apply_consumer_install(plan)
        self.assertFalse((self.host / ".cursor").exists())
        manifest = yaml_lite.load(
            (self.host / ".scaffold/install/install.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(declared_profiles(manifest), ())


class PCR4ObservationScopeTests(unittest.TestCase):
    """N01: Core consumes a generic scope; the adapter translates client events."""

    def test_R4_22_core_exposes_generic_observation_scopes(self):
        self.assertEqual(OBSERVATION_SINGLE_PATH, "single_path")
        self.assertEqual(OBSERVATION_ATTEMPT_SCOPE, "attempt_scope")
        source = Path(
            REPO / "src" / "scaffold_p7" / "develop_authority.py"
        ).read_text(encoding="utf-8")
        for event in ("afterFileEdit", "afterTabFileEdit", "postToolUse"):
            self.assertNotIn(event, source)

    def test_R4_22b_adapter_translates_client_events_to_generic_scope(self):
        from scaffold_p5.first_use import _observation_scope

        self.assertEqual(_observation_scope("afterFileEdit"), OBSERVATION_SINGLE_PATH)
        self.assertEqual(
            _observation_scope("afterTabFileEdit"), OBSERVATION_SINGLE_PATH
        )
        self.assertEqual(
            _observation_scope("postToolUse"), OBSERVATION_ATTEMPT_SCOPE
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import FIXTURE_DIST, REPO, REPO_UNDERSTAND, adopt, apply_fresh_migration, distribution, engine, files_under, write
from scaffold_p5.compatibility import evaluate_package
from scaffold_p5.discovery import discover
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_yaml
from scaffold_p5.models import DiscoveryFact
from scaffold_p5.packages import load_package
from scaffold_p5.preflight import run_preflight


class P5UnderstandTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_A_fresh_ordinary_project_bootstrap_preflight(self):
        snap = snapshot_host(self.host)
        decision = run_preflight(snap, distribution())
        self.assertEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(decision.context, "PRE_ADOPTION_BOOTSTRAP")
        self.assertTrue(decision.allowed)

    def test_B_no_mutation_before_b4_approval(self):
        before = files_under(self.host)
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(files_under(self.host), before)
        self.assertFalse((self.host / ".scaffold").exists())

    def test_C_unknown_is_not_false(self):
        facts = discover(self.host)
        tests = next(f for f in facts if f.name == "test_tree")
        self.assertEqual(tests.confidence, "UNKNOWN")
        self.assertIsNone(tests.value)
        self.assertIsNot(tests.value, False)
        result = engine(self.host).run("bootstrap")
        recorded = next(f for f in result.extras["facts"] if f["name"] == "test_tree")
        self.assertEqual(recorded["confidence"], "UNKNOWN")
        self.assertNotEqual(recorded["value"], False)

    def test_D_critical_unknown_conflicting_blocks_activation(self):
        result = adopt(
            self.host,
            extra_facts=[DiscoveryFact("project_authority", ["AGENTS.md", "CLAUDE.md"], "CONFLICTING", True)],
        )
        self.assertEqual(result.outcome, "FAILED")
        self.assertTrue(any("B7 FAIL" in b for b in result.blockers))
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["lifecycle"], "ADOPTING")
        self.assertTrue(any(self.host.joinpath(".scaffold/runtime/adoption-sessions").glob("*/session.yaml")))

    def test_E_bootstrap_exact_u1_identity(self):
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.skill_version, "2.0.0")
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        released = load_package(FIXTURE_DIST / "packages/understand-2.0.0")
        self.assertEqual(lock["skills"]["understand"]["skill_version"], "2.0.0")
        self.assertEqual(
            lock["skills"]["understand"]["package_digest"],
            released.ref.package_digest,
        )
        self.assertEqual(set(lock["skills"]), {"understand", "develop", "test", "submit"})

    def test_F_release_u1_actual_u2_blocks_before_bootstrap(self):
        before = files_under(self.host)
        result = engine(self.host, "2.0.1").run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("identity mismatch" in b for b in result.blockers))
        self.assertTrue(any("BLOCK before bootstrap" in b for b in result.blockers))
        self.assertEqual(files_under(self.host), before)

    def test_G_missing_lock_alone_is_not_bootstrap(self):
        write(
            self.host,
            ".scaffold/project.yaml",
            "schema_version: \"1\"\nlifecycle: ACTIVE\nproject_contract_generation: \"2\"\n",
        )
        snap = snapshot_host(self.host)
        decision = run_preflight(snap, distribution())
        self.assertNotEqual(decision.context, "PRE_ADOPTION_BOOTSTRAP")
        self.assertEqual(snap.host_class, "ESTABLISHED_HOST_CONSISTENCY")
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(any("PRE_ADOPTION_BOOTSTRAP" == result.extras.get("preflight_context") and result.outcome == "COMPLETED" for _ in [0]))

    def test_H_interrupted_after_project_yaml_plan_session_recovery(self):
        first = adopt(self.host, interrupt_after="project_yaml")
        self.assertEqual(first.outcome, "BLOCKED")
        self.assertTrue((self.host / ".scaffold/project.yaml").exists())
        self.assertFalse((self.host / ".scaffold/skills.lock").exists())
        session = next((self.host / ".scaffold/runtime/adoption-sessions").glob("*/session.yaml"))
        plan = read_yaml(session.parent / "plan.yaml")
        digest = plan["digest"]
        resumed = engine(self.host).run("bootstrap", approval={"approved": True, "plan_digest": digest})
        self.assertEqual(resumed.outcome, "COMPLETED")
        self.assertTrue(resumed.extras.get("zero_context_recovery"))
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "ACTIVE")
        self.assertTrue((self.host / ".scaffold/skills.lock").exists())

    def test_I_partial_initial_lock_is_not_authority(self):
        adopt(self.host, interrupt_after="partial_lock")
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        self.assertNotEqual(set(lock.get("skills") or {}), {"understand", "develop", "test", "submit"})
        result = engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("not ordinary compatibility authority" in b or "not authority" in b.lower() or "evidence" in b.lower() for b in result.blockers))
        snap = snapshot_host(self.host)
        self.assertFalse(snap.lock.complete_authoritative)

    def test_J_recovery_with_only_u2_when_plan_requires_u1_blocks(self):
        adopt(self.host, interrupt_after="project_yaml")
        plan = read_yaml(next((self.host / ".scaffold/runtime/adoption-sessions").glob("*/plan.yaml")))
        result = engine(self.host, "2.0.1").run(
            "bootstrap",
            approval={"approved": True, "plan_digest": plan["digest"]},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("exact release-pinned" in b or "identity" in b for b in result.blockers))
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "ADOPTING")
        self.assertFalse((self.host / ".scaffold/skills.lock").exists())

    def test_K_complete_lock_authority_handoff(self):
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.extras.get("authority"), "skills.lock")
        self.assertIn("durable expected-version SSOT", result.extras.get("authority_handoff", ""))
        compat = engine(self.host).run("compatibility")
        self.assertEqual(compat.extras.get("authority"), "skills.lock")
        self.assertEqual(compat.compatibility, "EXACT")
        self.assertFalse((self.host / ".scaffold/runtime/adoption-sessions").exists())

    def test_L_active_host_lost_lock_does_not_reuse_historical_plan(self):
        adopt(self.host)
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/adopt-historical/plan.yaml",
            "schema_version: \"1\"\nplan_id: historical\ndigest: deadbeef\nrelease_id: rel-r1\n",
        )
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/adopt-historical/session.yaml",
            "record_type: adoption_session\nschema_version: \"1\"\nrecord_id: adopt-historical\nstatus: INTERRUPTED\nplan:\n  identity: historical\n  digest: deadbeef\n  observed_approved: true\n",
        )
        (self.host / ".scaffold/skills.lock").unlink()
        project = read_yaml(self.host / ".scaffold/project.yaml")
        project["lifecycle"] = "ACTIVE"
        from scaffold_p5.io_util import write_yaml_atomic

        write_yaml_atomic(self.host / ".scaffold/project.yaml", project)
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "ESTABLISHED_HOST_CONSISTENCY")
        result = engine(self.host).run("bootstrap")
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertTrue(any("historical" in b.lower() or "not available" in b for b in result.blockers + [result.extras.get("host_class", "")]))
        self.assertEqual(result.extras.get("host_class"), "ESTABLISHED_HOST_CONSISTENCY")
        self.assertNotEqual(result.extras.get("authority"), "approved_plan_selected_release")

    def test_M_established_host_compatible_substitution(self):
        adopt(self.host)
        result = engine(self.host, "2.0.1").run("compatibility")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.compatibility, "COMPATIBLE")
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        self.assertEqual(lock["skills"]["understand"]["skill_version"], "2.0.0")

    def test_N_five_result_taxonomy_is_exact(self):
        released = load_package(REPO / "tests/fixtures/distribution/packages/understand-2.0.0")
        pinned = released.ref
        dist = distribution()
        exact = evaluate_package(pinned, released, project={"project_contract_generation": "2"}, distribution=dist)
        self.assertEqual(exact["validity"], "VALID")
        self.assertEqual(exact["result"], "EXACT")
        live = load_package(REPO_UNDERSTAND)
        live_exact = evaluate_package(
            live.ref,
            live,
            project={"project_contract_generation": "2"},
            distribution=dist,
        )
        self.assertEqual(live.validity, "VALID")
        self.assertEqual(live.ref.skill_version, "2.1.0")
        self.assertEqual(live_exact["result"], "EXACT")
        compatible = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.0.1"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.0.1"),
        )
        self.assertEqual(compatible["result"], "COMPATIBLE")
        migration = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.1.0"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.1.0"),
        )
        self.assertEqual(migration["result"], "MIGRATION_REQUIRED")
        unknown = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-2.2.0"),
            project={"project_contract_generation": "2"},
            distribution=distribution("2.2.0"),
        )
        self.assertEqual(unknown["result"], "UNKNOWN")
        incompat = evaluate_package(
            pinned,
            load_package(REPO / "tests/fixtures/distribution/packages/understand-incompat"),
            project={"project_contract_generation": "2"},
            distribution=distribution(),
        )
        self.assertEqual(incompat["result"], "INCOMPATIBLE")
        invalid = load_package(REPO / "tests/fixtures/distribution/packages/understand-invalid")
        self.assertEqual(invalid.validity, "INVALID")
        invalid_eval = evaluate_package(pinned, invalid, project={"project_contract_generation": "2"}, distribution=dist)
        self.assertEqual(invalid_eval["validity"], "INVALID")
        self.assertIsNone(invalid_eval["result"])
        self.assertEqual(
            {exact["result"], compatible["result"], migration["result"], unknown["result"], incompat["result"]},
            {"EXACT", "COMPATIBLE", "MIGRATION_REQUIRED", "INCOMPATIBLE", "UNKNOWN"},
        )

    def test_O_lock_update_is_not_migration(self):
        adopt(self.host)
        alt = load_package(REPO / "tests/fixtures/distribution/packages/understand-2.0.1")
        planned = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected={"understand": {"skill_version": "2.0.1", "package_digest": alt.ref.package_digest}},
        )
        self.assertEqual(planned.outcome, "NEEDS_HUMAN")
        self.assertTrue(planned.extras["lock_update_is_not_migration"])
        self.assertFalse(planned.extras["lock_update_plan"]["migration_required"])
        applied = engine(self.host, "2.0.1").run(
            "compatibility",
            action="lock_update",
            new_expected={"understand": {"skill_version": "2.0.1", "package_digest": alt.ref.package_digest}},
            approval={"approved": True, "plan_digest": planned.extras["lock_update_plan"]["digest"]},
        )
        self.assertEqual(applied.outcome, "COMPLETED")
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertNotIn("NEEDS_MIGRATION", project.get("maintenance") or [])
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        self.assertEqual(lock["skills"]["understand"]["skill_version"], "2.0.1")

    def test_P_migration_prepared_applying_validating_completed(self):
        adopt(self.host)
        planned = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN")
        self.assertEqual(planned.mutations, "none")
        self.assertIn("develop", planned.next_route)
        self.assertIn("migration_plan", planned.extras)
        done = apply_fresh_migration(
            self.host,
            planned.extras["migration_plan"],
        )
        self.assertEqual(done.outcome, "COMPLETED")
        self.assertEqual(done.extras["migration"]["status"], "COMPLETED")
        self.assertTrue(any("PREPARED" in e for e in done.evidence))
        project = read_yaml(self.host / ".scaffold/project.yaml")
        self.assertEqual(project["project_contract_generation"], "3")
        self.assertNotIn("NEEDS_MIGRATION", project.get("maintenance") or [])

    def test_Q_interrupted_migration_recovery_required(self):
        adopt(self.host)
        planned = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        interrupted = apply_fresh_migration(
            self.host,
            planned.extras["migration_plan"],
            interrupt_after="first_mutation",
        )
        self.assertEqual(interrupted.outcome, "BLOCKED")
        self.assertEqual(interrupted.extras["migration"]["status"], "RECOVERY_REQUIRED")
        self.assertEqual(read_yaml(self.host / ".scaffold/project.yaml")["lifecycle"], "RECOVERY_REQUIRED")

    def test_R_aborted_restrictions(self):
        adopt(self.host)
        planned = engine(self.host, "2.1.0").run("compatibility", action="migrate")
        aborted = apply_fresh_migration(
            self.host,
            planned.extras["migration_plan"],
            abort_before_mutation=True,
        )
        self.assertEqual(aborted.extras["migration"]["status"], "ABORTED")
        adopt_host = self.host
        planned2 = engine(adopt_host, "2.1.0").run("compatibility", action="migrate")
        apply_fresh_migration(
            adopt_host,
            planned2.extras["migration_plan"],
            interrupt_after="first_mutation",
        )
        refuse = engine(adopt_host, "2.1.0").run("compatibility", action="migrate", abort=True)
        self.assertEqual(refuse.outcome, "BLOCKED")
        self.assertTrue(any("ABORTED is invalid" in b for b in refuse.blockers))

    def test_S_full_creates_only_approved_scaffold_artifacts(self):
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        created = files_under(self.host)
        self.assertIn(".scaffold/project.yaml", created)
        self.assertIn("docs/project/overview.md", created)
        self.assertNotIn("docs/project/architecture.md", created)
        self.assertNotIn("skills/develop/SKILL.md", created)

    def test_T_human_owned_files_remain_preserved(self):
        write(self.host, "docs/human.md", "human text\r\nunchanged\r\n", newline="\r\n")
        original = (self.host / "docs/human.md").read_bytes()
        adopt(self.host)
        self.assertEqual((self.host / "docs/human.md").read_bytes(), original)
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        self.assertEqual(ownership.get("docs/human.md"), "HUMAN_OWNED")

    def test_U_refresh_does_not_edit_business_source(self):
        adopt(self.host)
        write(self.host, "src/app.py", "print('business')\n")
        original = (self.host / "src/app.py").read_bytes()
        result = engine(self.host).run("refresh")
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual((self.host / "src/app.py").read_bytes(), original)
        self.assertIn("src/app.py", result.extras.get("untouched_business") or [])

    def test_V_ownership_registry_remains_coherent(self):
        adopt(self.host, derived_copy=True)
        ownership = read_yaml(self.host / ".scaffold/project.yaml")["ownership"]
        for path in (
            ".scaffold/project.yaml",
            ".scaffold/modules.yaml",
            ".scaffold/commands.yaml",
            ".scaffold/tests.yaml",
            ".scaffold/skills.lock",
            "docs/project/overview.md",
            "AGENTS.md",
        ):
            self.assertIn(ownership.get(path), {"GENERATED", "MANAGED", "HUMAN_OWNED"}, path)
        self.assertEqual(ownership[".scaffold/skills.lock"], "GENERATED")
        self.assertEqual(ownership[".scaffold/derived/understand.md"], "GENERATED")
        self.assertTrue(set(ownership.values()) <= {"GENERATED", "MANAGED", "HUMAN_OWNED"})

    def test_W_zero_context_recovery_uses_durable_session_plan_only(self):
        adopt(self.host, interrupt_after="before_lock")
        plan_path = next((self.host / ".scaffold/runtime/adoption-sessions").glob("*/plan.yaml"))
        digest = read_yaml(plan_path)["digest"]
        fresh = engine(self.host)
        result = fresh.run("bootstrap", approval={"approved": True, "plan_digest": digest})
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertTrue(result.extras.get("zero_context_recovery"))

    def test_X_no_scm_fixture_works_without_git(self):
        self.assertFalse((self.host / ".git").exists())
        result = adopt(self.host)
        self.assertEqual(result.outcome, "COMPLETED")
        self.assertEqual(result.baseline["kind"], "none")
        compat = engine(self.host).run("compatibility")
        self.assertEqual(compat.outcome, "COMPLETED")
        (self.host / ".scaffold/skills.lock").unlink()
        write(
            self.host,
            ".scaffold/runtime/adoption-sessions/adopt-x/session.yaml",
            "record_type: adoption_session\nschema_version: \"1\"\nrecord_id: adopt-x\nstatus: INTERRUPTED\nplan:\n  identity: none\n  digest: x\n  observed_approved: true\n",
        )
        # recovery without git still classifies; missing complete binding blocks rather than inventing SHA
        blocked = engine(self.host).run("bootstrap")
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertFalse((self.host / ".git").exists())

    def test_Y_client_derived_material_is_non_authoritative(self):
        write(self.host, "CLAUDE.md", "existing client notes\n")
        result = adopt(self.host, derived_copy=True)
        self.assertEqual(result.outcome, "COMPLETED")
        derived = (self.host / ".scaffold/derived/understand.md").read_text(encoding="utf-8")
        self.assertIn("authoritative: false", derived)
        self.assertIn("source_skill_id: understand", derived)
        clients = read_yaml(self.host / ".scaffold/project.yaml")["clients"]
        self.assertTrue(any(c.get("path") == "CLAUDE.md" and c.get("authoritative") is False for c in clients))
        self.assertEqual((self.host / "CLAUDE.md").read_text(encoding="utf-8"), "existing client notes\n")


class P5SupportTests(unittest.TestCase):
    def test_canonical_understand_package_is_valid(self):
        pkg = load_package(REPO_UNDERSTAND)
        self.assertEqual(pkg.validity, "VALID")
        self.assertEqual(pkg.ref.skill_id, "understand")
        self.assertEqual(pkg.ref.skill_version, "2.1.0")

    def test_yaml_roundtrip_facts(self):
        from scaffold_p5 import yaml_lite

        data = {"facts": [{"name": "scm", "value": "none", "confidence": "VERIFIED"}]}
        loaded = yaml_lite.load(yaml_lite.dump(data))
        self.assertEqual(loaded["facts"][0]["name"], "scm")


if __name__ == "__main__":
    unittest.main()

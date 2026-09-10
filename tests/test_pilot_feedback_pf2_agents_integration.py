from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import REPO, adopt, engine, files_under, write

from scaffold_entry import present_result
from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    GENERATED_AGENTS,
    REGION_END,
    REGION_START,
    classify_agents_text,
)
from scaffold_p5.discovery import discover
from scaffold_p5.io_util import read_yaml
from scaffold_p5.schemas import ADOPTION_PLAN_BODY_FIELDS, adoption_plan_digest


FORBIDDEN_PRODUCTION = (
    "Roguelike",
    "Beacon",
    "Vortex",
    "concept-roguelike",
    "src/game",
    "src/content",
    "src/ui",
    "src/__tests__",
)
DIVE_TOKEN = re.compile(r"(?<![A-Za-z])DIVE(?![A-Za-z])")
PRODUCTION_ROOTS = (
    REPO / "src" / "scaffold_p5",
    REPO / "skills" / "understand",
)

HUMAN_AGENTS = (
    "# Project instructions\n"
    "\n"
    "Follow the project rules in `.cursor/rules`.\n"
    "\n"
    "Human-owned workflow notes remain here.\n"
)
GENUINE_BRIDGE = (
    "# Existing bridge\n"
    "Read `.scaffold/project.yaml`, `docs/project/overview.md`, and "
    "`.scaffold/skills.lock`.\n"
)
CONFLICTING_MARKERS = (
    "# Ambiguous router markers\n"
    f"{REGION_START}\n"
    "first region\n"
    f"{REGION_START}\n"
    "second start\n"
    f"{REGION_END}\n"
)


def _fact(facts, name: str):
    if facts and hasattr(facts[0], "name"):
        return next(row for row in facts if row.name == name)
    return next(row for row in facts if row["name"] == name)


def _action(plan: dict, target: str) -> dict:
    return next(row for row in plan["actions"] if row["target"] == target)


class PilotFeedbackPF2AgentsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _host(self, name: str = "host") -> Path:
        host = self.root / name
        host.mkdir()
        write(host, "README.md", "Synthetic PF-2 fixture.\n")
        return host

    def test_PF2_01_absent_agents_still_creates_generated_router(self):
        host = self._host()
        self.assertFalse((host / "AGENTS.md").exists())
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        action = _action(result.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "CREATE")
        self.assertEqual(action["ownership"], "GENERATED")
        self.assertEqual(
            (host / "AGENTS.md").read_text(encoding="utf-8"),
            GENERATED_AGENTS,
        )
        self.assertEqual(read_yaml(host / ".scaffold/project.yaml")["lifecycle"], "ACTIVE")

    def test_PF2_02_existing_router_is_preserved_without_rewrite(self):
        host = self._host()
        write(host, "AGENTS.md", GENUINE_BRIDGE)
        before = (host / "AGENTS.md").read_bytes()
        preview = engine(host).run("bootstrap")
        action = _action(preview.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["ownership"], "HUMAN_OWNED")
        self.assertEqual(action["client_strategy"], "THIN_BRIDGE")
        self.assertNotIn("AGENTS.md", preview.extras["plan"]["mutation_envelope"])
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual((host / "AGENTS.md").read_bytes(), before)
        self.assertNotEqual(
            (host / "AGENTS.md").read_text(encoding="utf-8"),
            GENERATED_AGENTS,
        )
        managed = self._host("already-managed")
        region = (
            HUMAN_AGENTS
            + f"{REGION_START}\n"
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
            f"{REGION_END}\n"
        )
        write(managed, "AGENTS.md", region)
        managed_bytes = (managed / "AGENTS.md").read_bytes()
        managed_preview = engine(managed).run("bootstrap")
        managed_action = _action(managed_preview.extras["plan"], "AGENTS.md")
        self.assertEqual(managed_action["action_class"], "PRESERVE")
        self.assertEqual(managed_action["ownership"], "MANAGED")
        self.assertNotIn("AGENTS.md", managed_preview.extras["plan"]["mutation_envelope"])
        managed_result = adopt(managed)
        self.assertEqual(managed_result.outcome, "COMPLETED", managed_result.blockers)
        self.assertEqual((managed / "AGENTS.md").read_bytes(), managed_bytes)

    def test_PF2_03_ordinary_human_agents_proposes_bounded_integration(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        action = _action(result.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "MANAGED_UPDATE")
        self.assertEqual(action["ownership"], "MANAGED")
        self.assertEqual(action["client_strategy"], "THIN_BRIDGE")
        self.assertNotEqual(action["action_class"], "CREATE")
        self.assertNotIn("whole-file replace", action["expected"])
        self.assertIn("region", action["expected"])
        self.assertNotEqual(action.get("client_strategy"), "DEFER")
        presented = present_result(result)
        self.assertIn(
            "Review and approve this Adoption Plan before any project files are changed.",
            presented["human_action_required"],
        )
        self.assertNotIn("B4", presented["human_action_required"])
        self.assertTrue(any("B4" in blocker for blocker in result.blockers))

    def test_PF2_04_integration_is_inside_envelope_and_plan_digest(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        preview = engine(host).run("bootstrap")
        plan = preview.extras["plan"]
        action = _action(plan, "AGENTS.md")
        self.assertIn("AGENTS.md", plan["mutation_envelope"])
        self.assertEqual(action["action_class"], "MANAGED_UPDATE")
        dumped = json.dumps(plan)
        self.assertIn("AGENTS.md", dumped)
        self.assertIn("MANAGED_UPDATE", dumped)
        self.assertTrue(plan["digest"])
        self.assertEqual(plan["plan_id"], f"plan-{plan['digest'][:16]}")
        rejected = engine(host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": "0" * 64},
        )
        self.assertEqual(rejected.outcome, "NEEDS_HUMAN")
        self.assertEqual(rejected.mutations, "none")
        self.assertEqual((host / "AGENTS.md").read_text(encoding="utf-8"), HUMAN_AGENTS)

    def test_PF2_05_no_mutation_before_b4(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        write(host, "CLAUDE.md", "Human Claude notes.\n")
        before = files_under(host)
        agents = (host / "AGENTS.md").read_bytes()
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        self.assertEqual(result.mutations, "none")
        self.assertEqual(files_under(host), before)
        self.assertEqual((host / "AGENTS.md").read_bytes(), agents)
        self.assertFalse((host / ".scaffold").exists())

    def test_PF2_06_approved_region_preserves_human_text_outside_region(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        text = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Human-owned workflow notes remain here.", text)
        self.assertIn("Follow the project rules in `.cursor/rules`.", text)
        self.assertIn(REGION_START, text)
        self.assertIn(REGION_END, text)
        self.assertNotEqual(text, GENERATED_AGENTS)
        self.assertTrue(text.startswith("# Project instructions"))
        prefix = text.split(REGION_START, 1)[0]
        suffix = text.split(REGION_END, 1)[1]
        self.assertNotIn("This host is managed by AI-Native Project Scaffold.", prefix)
        self.assertNotIn("This host is managed by AI-Native Project Scaffold.", suffix)
        self.assertIn("This host is managed by AI-Native Project Scaffold.", text)

    def test_PF2_07_successful_integration_reobserves_and_activates(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        preview = engine(host).run("bootstrap")
        self.assertNotIn(
            "agents_scaffold_bridge:CONFLICTING",
            preview.extras["plan"]["activation_blockers"],
        )
        self.assertEqual(
            _fact(preview.extras["facts"], "agents_scaffold_bridge")["confidence"],
            "CONFLICTING",
        )
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertFalse(
            any("agents_scaffold_bridge:CONFLICTING" in value for value in result.blockers)
        )
        project = read_yaml(host / ".scaffold/project.yaml")
        self.assertEqual(project["lifecycle"], "ACTIVE")
        observed = _fact(discover(host), "agents_scaffold_bridge")
        self.assertEqual(observed.confidence, "VERIFIED")
        self.assertIs(observed.value, True)
        recorded = _fact(project["facts"], "agents_scaffold_bridge")
        self.assertEqual(recorded["confidence"], "VERIFIED")
        self.assertIs(recorded["value"], True)
        clients = next(row for row in project["clients"] if row["path"] == "AGENTS.md")
        self.assertEqual(clients["strategy"], "THIN_BRIDGE")
        self.assertEqual(clients["ownership"], "MANAGED")

    def test_PF2_08_malformed_integration_fails_closed(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)

        def _malformed(original: str, *args, **kwargs) -> str:
            return original + f"\n{REGION_START}\nbroken region without end\n"

        with patch("scaffold_p5.full.integrated_agents_text", side_effect=_malformed):
            result = adopt(host)
        self.assertEqual(result.outcome, "FAILED")
        self.assertTrue(any("B7 FAIL" in value for value in result.blockers))
        self.assertTrue(
            any("agents_scaffold_bridge" in value for value in result.blockers)
        )
        self.assertTrue(
            any("did not materialize" in value for value in result.blockers)
        )
        self.assertEqual(
            read_yaml(host / ".scaffold/project.yaml")["lifecycle"],
            "ADOPTING",
        )
        text = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Human-owned workflow notes remain here.", text)
        self.assertNotEqual(
            _fact(discover(host), "agents_scaffold_bridge").confidence,
            "VERIFIED",
        )

    def test_PF2_09_conflicting_markers_need_human_without_guessing(self):
        host = self._host()
        write(host, "AGENTS.md", CONFLICTING_MARKERS)
        before = (host / "AGENTS.md").read_bytes()
        result = engine(host).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN")
        action = _action(result.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["client_strategy"], "DEFER")
        self.assertNotEqual(action["action_class"], "MANAGED_UPDATE")
        self.assertNotIn("AGENTS.md", result.extras["plan"]["mutation_envelope"])
        self.assertIn(
            "agents_scaffold_bridge:CONFLICTING",
            result.extras["plan"]["activation_blockers"],
        )
        self.assertEqual(result.mutations, "none")
        self.assertEqual((host / "AGENTS.md").read_bytes(), before)
        presented = present_result(result)
        self.assertIn("cannot be integrated automatically", presented["human_action_required"])

    def test_PF2_10_rejected_integration_leaves_host_and_agents_untouched(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        before = files_under(host)
        agents = (host / "AGENTS.md").read_bytes()
        preview = engine(host).run("bootstrap")
        rejected = engine(host).run(
            "bootstrap",
            approval={
                "approved": False,
                "plan_digest": preview.extras["plan"]["digest"],
            },
        )
        self.assertEqual(rejected.outcome, "NEEDS_HUMAN")
        self.assertEqual(rejected.mutations, "none")
        self.assertEqual(files_under(host), before)
        self.assertEqual((host / "AGENTS.md").read_bytes(), agents)
        self.assertFalse((host / ".scaffold").exists())
        self.assertFalse((host / ".scaffold/project.yaml").exists())

    def test_PF2_11_claude_and_cursor_rules_remain_preserved(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        write(host, "CLAUDE.md", "Human Claude notes for this host.\n")
        write(host, ".cursor/rules/keep.mdc", "Human Cursor rule text.\n")
        claude = (host / "CLAUDE.md").read_bytes()
        rules = (host / ".cursor/rules/keep.mdc").read_bytes()
        preview = engine(host).run("bootstrap")
        actions = {
            row["target"]: row for row in preview.extras["plan"]["actions"]
        }
        self.assertEqual(actions["CLAUDE.md"]["action_class"], "PRESERVE")
        self.assertEqual(actions[".cursor/rules"]["action_class"], "PRESERVE")
        self.assertNotIn("CLAUDE.md", preview.extras["plan"]["mutation_envelope"])
        self.assertNotIn(".cursor/rules", preview.extras["plan"]["mutation_envelope"])
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual((host / "CLAUDE.md").read_bytes(), claude)
        self.assertEqual((host / ".cursor/rules/keep.mdc").read_bytes(), rules)

    def test_PF2_12_no_project_specific_or_dive_hardcoding(self):
        for root in PRODUCTION_ROOTS:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {".py", ".md", ".yaml", ".yml"}:
                    continue
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(
                    DIVE_TOKEN.search(text),
                    f"DIVE token in production file {path}",
                )
                for token in FORBIDDEN_PRODUCTION:
                    self.assertNotIn(token, text, f"{token} in {path}")

    def test_PF2_R13_managed_region_id_is_durable_after_session_cleanup(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        runtime = host / ".scaffold/runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        self.assertFalse(runtime.exists())
        project = read_yaml(host / ".scaffold/project.yaml")
        self.assertEqual(project["ownership"]["AGENTS.md"], "MANAGED")
        self.assertEqual(
            project["managed_regions"]["AGENTS.md"],
            [AGENTS_ROUTER_REGION],
        )
        text = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(REGION_START, text)
        self.assertIn(REGION_END, text)
        observed = _fact(discover(host), "agents_scaffold_bridge")
        self.assertEqual(observed.confidence, "VERIFIED")
        self.assertIs(observed.value, True)

    def test_PF2_R14_registered_region_without_markers_fails_closed(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        self.assertEqual(adopt(host).outcome, "COMPLETED")
        write(host, "AGENTS.md", HUMAN_AGENTS)
        before = (host / "AGENTS.md").read_bytes()
        observed = _fact(discover(host), "agents_scaffold_bridge")
        self.assertEqual(observed.confidence, "CONFLICTING")
        refreshed = engine(host).run("refresh")
        self.assertEqual(refreshed.outcome, "NEEDS_HUMAN")
        self.assertEqual((host / "AGENTS.md").read_bytes(), before)
        self.assertNotEqual(
            (host / "AGENTS.md").read_text(encoding="utf-8"),
            GENERATED_AGENTS,
        )

    def test_PF2_R15_unapproved_region_id_is_not_writable(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        self.assertEqual(adopt(host).outcome, "COMPLETED")
        foreign = (
            HUMAN_AGENTS
            + "<!-- scaffold:managed:other-client:start -->\n"
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
            "<!-- scaffold:managed:other-client:end -->\n"
        )
        write(host, "AGENTS.md", foreign)
        before = (host / "AGENTS.md").read_bytes()
        refreshed = engine(host).run("refresh")
        self.assertEqual(refreshed.outcome, "NEEDS_HUMAN")
        self.assertEqual((host / "AGENTS.md").read_bytes(), before)
        self.assertEqual(
            _fact(discover(host), "agents_scaffold_bridge").confidence,
            "CONFLICTING",
        )

    def test_PF2_R16_region_identity_is_bound_into_plan_digest(self):
        host = self._host()
        write(host, "AGENTS.md", HUMAN_AGENTS)
        preview = engine(host).run("bootstrap")
        plan = preview.extras["plan"]
        action = _action(plan, "AGENTS.md")
        self.assertEqual(action["managed_region"], AGENTS_ROUTER_REGION)
        body = {field: plan[field] for field in ADOPTION_PLAN_BODY_FIELDS}
        changed = json.loads(json.dumps(body))
        for row in changed["actions"]:
            if row["target"] == "AGENTS.md":
                row["managed_region"] = "other-router"
        new_digest = adoption_plan_digest(changed)
        self.assertNotEqual(new_digest, plan["digest"])
        rejected = engine(host).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": new_digest},
        )
        self.assertEqual(rejected.outcome, "NEEDS_HUMAN")
        self.assertEqual((host / "AGENTS.md").read_text(encoding="utf-8"), HUMAN_AGENTS)

    def test_PF2_R17_human_anti_integration_outranks_valid_region(self):
        host = self._host()
        text = (
            "# Project instructions\n"
            "Do not use Scaffold.\n"
            f"{REGION_START}\n"
            "Read `.scaffold/project.yaml`, `docs/project/overview.md`, "
            "and `.scaffold/skills.lock`.\n"
            f"{REGION_END}\n"
        )
        write(host, "AGENTS.md", text)
        self.assertNotEqual(classify_agents_text(text), "genuine")
        preview = engine(host).run("bootstrap")
        self.assertEqual(preview.outcome, "NEEDS_HUMAN")
        action = _action(preview.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["client_strategy"], "DEFER")
        self.assertNotEqual(action["action_class"], "MANAGED_UPDATE")
        result = adopt(host)
        self.assertEqual(result.outcome, "FAILED")
        self.assertNotEqual(
            read_yaml(host / ".scaffold/project.yaml")["lifecycle"],
            "ACTIVE",
        )
        self.assertEqual((host / "AGENTS.md").read_text(encoding="utf-8"), text)

    def test_PF2_R18_do_not_modify_agents_is_not_auto_integrated(self):
        host = self._host()
        write(
            host,
            "AGENTS.md",
            "Do not modify AGENTS.md.\nHuman workflow notes remain here.\n",
        )
        preview = engine(host).run("bootstrap")
        action = _action(preview.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "PRESERVE")
        self.assertEqual(action["client_strategy"], "DEFER")
        self.assertNotEqual(action["action_class"], "MANAGED_UPDATE")
        self.assertNotIn("AGENTS.md", preview.extras["plan"]["mutation_envelope"])

    def test_PF2_R19_unrelated_human_instruction_is_not_a_false_blocker(self):
        host = self._host()
        write(
            host,
            "AGENTS.md",
            "# Notes\nDo not skip the visual regression tests.\nKeep local setup notes here.\n",
        )
        preview = engine(host).run("bootstrap")
        action = _action(preview.extras["plan"], "AGENTS.md")
        self.assertEqual(action["action_class"], "MANAGED_UPDATE")
        self.assertEqual(action["managed_region"], AGENTS_ROUTER_REGION)
        result = adopt(host)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        text = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not skip the visual regression tests.", text)
        self.assertIn(REGION_START, text)


if __name__ == "__main__":
    unittest.main()

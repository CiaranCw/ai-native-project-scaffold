from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP, write_modules
from p7_support import TASK_A
from p8_support import (
    publish_knowledge_outcomes,
    rebind_noscms_baseline,
    run_submit,
    submit_engine,
    write_ready_task,
    write_submit_host,
)
from scaffold_p5.compatibility import evaluate_host
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.knowledge_assessment import (
    current_head_path,
    knowledge_relevant_impacts,
    publish_knowledge_assessment,
    resolve_current_knowledge_assessment,
)
from scaffold_p5.packages import load_package
from scaffold_p5.preflight import run_preflight
from scaffold_p6.candidate import observe_candidate
from scaffold_p8.structural import IMPACT_COMMAND, IMPACT_PUBLIC_INTERFACE
from support import (
    FIXTURE_DIST,
    REPO_UNDERSTAND,
    adopt,
    distribution,
    engine,
    files_under,
    live_understand_distribution,
    live_understand_engine,
    write,
)


ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "docs/contracts/CONSTITUTION.md"
RECORDS = ROOT / "docs/contracts/RECORDS_CONTRACT.md"
NOTE = ROOT / "docs/implementation/FA2_FND_004_KNOWLEDGE_ASSESSMENT.md"
P8_NOTE = ROOT / "docs/implementation/P8_SUBMIT.md"


def text(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class FA2FoundationAmendment004Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _interface_host(self) -> None:
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
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")

    def test_FND4_normative_knowledge_assessment_is_supporting_not_canonical(self):
        constitution = text(CONSTITUTION)
        records = text(RECORDS)
        note = text(NOTE)
        p8 = text(P8_NOTE)
        self.assertIn("Knowledge Assessment", constitution)
        self.assertIn("not a fourth canonical development record", constitution)
        self.assertIn("FA2-FND-004", records)
        self.assertIn("not a canonical development record", records)
        self.assertIn("MUST NOT independently establish SATISFIED", note)
        self.assertIn("superseded by FA2-FND-004", p8)
        self.assertIn("FND4-E01", records)
        self.assertIn("FND4-C01", records)
        self.assertIn("FND4-V01", records)
        self.assertIn("current-head", note)
        self.assertIn("supersedes", note)
        self.assertIn("does not add a fifth Skill, S13", note)
        self.assertNotIn("token in update_text", (ROOT / "src/scaffold_p8/knowledge.py").read_text(encoding="utf-8"))

    def test_FND4_E01_structural_impact_without_assessment_routes_understand(self):
        self._interface_host()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")
        self.assertIn(
            IMPACT_PUBLIC_INTERFACE,
            result.extras["structural"].get("impact_classes") or [],
        )

    def test_FND4_E02_satisfied_current_assessment_may_pass(self):
        self._interface_host()
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

    def test_FND4_E03_c1_assessment_cannot_support_c2(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        write(self.host, "src/save/api.py", "def save():\n    return 9\n")
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertIn("stale", " ".join(result.blockers).lower())

    def test_FND4_E04_current_candidate_wrong_impact_digest_is_blocked(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host,
            first.extras["structural"],
            impacts=[
                {
                    "class": IMPACT_COMMAND,
                    "path": ".scaffold/commands.yaml",
                    "status": "DETERMINED",
                    "detail": "readable",
                }
            ],
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        self.assertEqual(
            observe_candidate(self.host).digest,
            first.extras["candidate"]["candidate_digest"],
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("assessment_state"), "impact_mismatch"
        )

    def test_FND4_E05_partial_impact_coverage_is_blocked(self):
        self._interface_host()
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
        first = run_submit(self.host, task_id=TASK_A)
        impacts = knowledge_relevant_impacts(
            first.extras["structural"].get("impacts") or []
        )
        self.assertGreaterEqual(len(impacts), 2)
        published = publish_knowledge_outcomes(
            self.host,
            first.extras["structural"],
            impacts=[impacts[0]],
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        joined = " ".join(result.blockers).lower()
        self.assertTrue("subset" in joined or "stale" in joined)

    def test_FND4_E06_unknown_outcome_routes_understand(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")

    def test_FND4_E07_needs_human_is_explicit_human_blocker(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="NEEDS_HUMAN"
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertEqual(result.next_route, "human")
        self.assertTrue(result.extras["knowledge"].get("needs_human"))
        self.assertTrue(any("human" in item.lower() for item in result.blockers))

    def test_FND4_E08_assessment_artifact_does_not_change_candidate(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        before = observe_candidate(self.host).digest
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"]
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        after = observe_candidate(self.host).digest
        self.assertEqual(after, before)
        self.assertTrue(
            (
                self.host
                / ".scaffold/runtime"
                / published["locator"]
            ).is_file()
        )

    def test_FND4_p5_refresh_publishes_candidate_bound_assessment(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        outcomes = [
            {
                "class": row["class"],
                "path": row["path"],
                "outcome": "SATISFIED",
                "rationale": "Understand assessed current knowledge as covering this impact.",
            }
            for row in knowledge_relevant_impacts(
                first.extras["structural"].get("impacts") or []
            )
        ]
        extras: dict = {}
        engine(self.host)._maybe_publish_knowledge_assessment(
            "refresh",
            {
                "structural": first.extras["structural"],
                "knowledge_outcomes": outcomes,
            },
            extras,
        )
        published = extras.get("knowledge_assessment") or {}
        self.assertTrue(published.get("ok"), published)
        locator = extras.get("knowledge_assessment_ref")
        self.assertTrue(locator)
        self.assertEqual(
            published.get("candidate_digest"),
            observe_candidate(self.host).digest,
        )
        self.assertTrue((self.host / ".scaffold/runtime" / locator).is_file())
        self.assertTrue(published.get("current_head_locator"))
        self.assertTrue(
            (
                self.host
                / ".scaffold/runtime"
                / published["current_head_locator"]
            ).is_file()
        )

    def test_FND4_raw_caller_dict_is_not_s4_authority(self):
        self._interface_host()
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment={"outcome": "SATISFIED"},
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        direct = submit_engine(self.host).run(
            task_id=TASK_A,
            knowledge_assessment={"outcome": "SATISFIED"},
            knowledge_assessment_ref={"outcome": "SATISFIED"},
        )
        self.assertEqual(direct.outcome, "BLOCKED")
        self.assertFalse(direct.extras["knowledge"]["knowledge_consistent"])

    def test_FND4_boolean_false_is_not_unknown(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_assessment(
            self.host,
            mode="refresh",
            impacts=list(first.extras["structural"].get("impacts") or []),
            outcomes=[
                {
                    "class": IMPACT_PUBLIC_INTERFACE,
                    "path": "src/save/api.py",
                    "outcome": False,
                }
            ],
        )
        self.assertFalse(published.get("ok") or False)
        self.assertTrue(
            any("boolean false" in item.lower() for item in published.get("blockers") or [])
        )


class FA2FoundationAmendment004VersionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        write(self.host, "README.md", "# Ordinary project\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_FND4_V01_live_understand_identity_is_not_released_2_0_0(self):
        pkg = load_package(REPO_UNDERSTAND)
        self.assertNotEqual(pkg.ref.skill_version, "2.0.0")
        self.assertEqual(pkg.ref.skill_version, "2.3.0")
        self.assertEqual(pkg.ref.skill_id, "understand")

    def test_FND4_V02_skill_md_and_yaml_identity_agree(self):
        pkg = load_package(REPO_UNDERSTAND)
        self.assertEqual(pkg.validity, "VALID", pkg.validity_reasons)
        manifest = read_yaml(REPO_UNDERSTAND / "skill.yaml")
        skill_md = (REPO_UNDERSTAND / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(manifest.get("skill_id"), "understand")
        self.assertEqual(manifest.get("skill_version"), "2.3.0")
        self.assertIn("- `skill_id`: `understand`", skill_md)
        self.assertIn("- `skill_version`: `2.3.0`", skill_md)

    def test_FND4_V03_live_understand_package_is_valid(self):
        pkg = load_package(REPO_UNDERSTAND)
        self.assertEqual(pkg.validity, "VALID", pkg.validity_reasons)
        self.assertEqual(pkg.ref.skill_version, "2.3.0")
        substitutions = pkg.manifest.get("may_substitute_for") or []
        self.assertTrue(
            any(
                item.get("skill_id") == "understand"
                and str(item.get("skill_version")) == "2.0.0"
                for item in substitutions
                if isinstance(item, dict)
            ),
            substitutions,
        )
        self.assertTrue(
            any(
                item.get("skill_id") == "understand"
                and str(item.get("skill_version")) == "2.1.0"
                for item in substitutions
                if isinstance(item, dict)
            ),
            substitutions,
        )

    def test_FND4_V04_established_host_2_0_0_evaluates_live_2_3_0_compatible(self):
        adopted = adopt(self.host)
        self.assertEqual(adopted.outcome, "COMPLETED")
        lock_path = self.host / ".scaffold/skills.lock"
        before = lock_path.read_bytes()
        expected = read_yaml(lock_path)["skills"]["understand"]
        self.assertEqual(expected["skill_version"], "2.0.0")
        dist = live_understand_distribution()
        evaluation = evaluate_host(snapshot_host(self.host), dist)
        row = evaluation["results"]["understand"]
        self.assertEqual(row["result"], "COMPATIBLE", evaluation)
        self.assertNotEqual(row["result"], "EXACT")
        self.assertEqual(row["actual_version"], "2.3.0")
        self.assertEqual(row["expected_version"], "2.0.0")
        result = live_understand_engine(self.host).run("compatibility")
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertEqual(result.compatibility, "COMPATIBLE")
        self.assertEqual(result.skill_version, "2.3.0")
        self.assertEqual(lock_path.read_bytes(), before)
        self.assertEqual(
            read_yaml(lock_path)["skills"]["understand"]["skill_version"],
            "2.0.0",
        )
        self.assertEqual(
            read_yaml(lock_path)["skills"]["understand"]["package_digest"],
            expected["package_digest"],
        )

    def test_FND4_V05_pre_adoption_bootstrap_exact_understand_unchanged(self):
        before = files_under(self.host)
        snap = snapshot_host(self.host)
        decision = run_preflight(snap, distribution())
        self.assertEqual(decision.context, "PRE_ADOPTION_BOOTSTRAP")
        self.assertTrue(decision.allowed)
        blocked = live_understand_engine(self.host).run("bootstrap")
        self.assertEqual(blocked.outcome, "BLOCKED")
        self.assertTrue(
            any("identity mismatch" in blocker for blocker in blocked.blockers)
        )
        self.assertTrue(
            any("BLOCK before bootstrap" in blocker for blocker in blocked.blockers)
        )
        self.assertNotEqual(blocked.compatibility, "COMPATIBLE")
        self.assertEqual(files_under(self.host), before)
        adopted = adopt(self.host)
        self.assertEqual(adopted.outcome, "COMPLETED")
        self.assertEqual(adopted.skill_version, "2.0.0")
        lock = read_yaml(self.host / ".scaffold/skills.lock")
        released = load_package(FIXTURE_DIST / "packages/understand-2.0.0")
        self.assertEqual(lock["skills"]["understand"]["skill_version"], "2.0.0")
        self.assertEqual(
            lock["skills"]["understand"]["package_digest"],
            released.ref.package_digest,
        )

    def test_FND4_V06_released_2_0_0_does_not_represent_fnd004(self):
        live = load_package(REPO_UNDERSTAND)
        self.assertNotEqual(live.ref.skill_version, "2.0.0")
        self.assertEqual(live.ref.skill_version, "2.3.0")
        live_md = (REPO_UNDERSTAND / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("2.3.0", live_md)
        self.assertIn("Knowledge Assessment", live_md)
        released_dir = FIXTURE_DIST / "packages/understand-2.0.0"
        released = load_package(released_dir)
        self.assertEqual(released.validity, "VALID", released.validity_reasons)
        self.assertEqual(released.ref.skill_version, "2.0.0")
        released_md = (released_dir / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("Knowledge Assessment", released_md)
        self.assertNotIn("current-head", released_md)
        self.assertNotIn("current head", released_md)


class FA2FoundationAmendment004CurrentnessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _interface_host(self) -> None:
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
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write_ready_task(
            self.host,
            scope={"paths": ["src/"], "modules": [], "exclude": []},
        )
        rebind_noscms_baseline(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/save/api.py", "def save():\n    return 2\n")

    def test_FND4_C01_old_satisfied_locator_is_superseded(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published_a = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        self.assertNotEqual(published_a["locator"], published_b["locator"])
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published_a["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("assessment_state"), "superseded")
        self.assertNotEqual(result.outcome, "COMPLETED")

    def test_FND4_C02_current_unknown_locator_is_not_pass(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published_b["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras.get("stage"), "S4")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.next_route, "understand.refresh")

    def test_FND4_C03_later_satisfied_is_current_and_old_cannot_pass(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published_a = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        stale = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published_a["locator"],
        )
        self.assertEqual(stale.outcome, "BLOCKED")
        self.assertFalse(stale.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(stale.extras["knowledge"].get("assessment_state"), "superseded")
        current = run_submit(
            self.host,
            task_id=TASK_A,
            invoke_test=True,
            selected=["unit"],
            knowledge_assessment_ref=published_b["locator"],
        )
        self.assertEqual(current.outcome, "COMPLETED", current.blockers)
        self.assertTrue(current.extras["knowledge"]["knowledge_consistent"])

    def test_FND4_C04_no_locator_resolves_current_head_only(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published_a = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="UNKNOWN"
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("knowledge_assessment_ref"),
            published_b["locator"],
        )
        self.assertNotEqual(
            result.extras["knowledge"].get("knowledge_assessment_ref"),
            published_a["locator"],
        )

    def test_FND4_C05_missing_head_is_unknown_and_does_not_guess(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        published_b = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        artifacts = list(
            (self.host / ".scaffold/runtime/understand-assessments").glob(
                "ka-*/assessment.yaml"
            )
        )
        self.assertGreaterEqual(len(artifacts), 2)
        head_path = current_head_path(self.host, published_b["current_head_locator"])
        self.assertIsNotNone(head_path)
        assert head_path is not None
        head_path.unlink()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(result.extras["knowledge"].get("assessment_state"), "missing")
        self.assertFalse(result.extras["knowledge"].get("knowledge_assessment_ref"))

    def test_FND4_C06_mutated_assessment_bytes_fail_integrity(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        path = self.host / ".scaffold/runtime" / published["locator"]
        before = file_digest(path)
        data = read_yaml(path)
        data["assessments"][0]["rationale"] = "mutated after P5 publication"
        write_yaml_atomic(path, data)
        mutated = read_yaml(path)
        from scaffold_p5.knowledge_assessment import validate_knowledge_assessment

        self.assertEqual(validate_knowledge_assessment(mutated), [])
        self.assertNotEqual(file_digest(path), before)
        result = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertFalse(result.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            result.extras["knowledge"].get("assessment_state"),
            "integrity_mismatch",
        )

    def test_FND4_C07_c1_head_cannot_support_c2(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        write(self.host, "src/save/api.py", "def save():\n    return 9\n")
        explicit = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(explicit.outcome, "BLOCKED")
        self.assertFalse(explicit.extras["knowledge"]["knowledge_consistent"])
        self.assertIn("stale", " ".join(explicit.blockers).lower())
        auto = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(auto.outcome, "BLOCKED")
        self.assertFalse(auto.extras["knowledge"]["knowledge_consistent"])

    def test_FND4_C08_i1_head_cannot_support_i2(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host,
            first.extras["structural"],
            impacts=[
                {
                    "class": IMPACT_COMMAND,
                    "path": ".scaffold/commands.yaml",
                    "status": "DETERMINED",
                    "detail": "readable",
                }
            ],
        )
        self.assertTrue(published["ok"], published.get("blockers"))
        self.assertEqual(
            observe_candidate(self.host).digest,
            first.extras["candidate"]["candidate_digest"],
        )
        auto = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(auto.outcome, "BLOCKED")
        self.assertFalse(auto.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(auto.extras["knowledge"].get("assessment_state"), "missing")
        explicit = run_submit(
            self.host,
            task_id=TASK_A,
            knowledge_assessment_ref=published["locator"],
        )
        self.assertEqual(explicit.outcome, "BLOCKED")
        self.assertFalse(explicit.extras["knowledge"]["knowledge_consistent"])
        self.assertEqual(
            explicit.extras["knowledge"].get("assessment_state"),
            "impact_mismatch",
        )

    def test_FND4_C09_current_head_does_not_change_candidate_digest(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        before = observe_candidate(self.host).digest
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        self.assertTrue(published.get("ok"), published.get("blockers"))
        self.assertTrue(published.get("current_head_locator"))
        self.assertEqual(observe_candidate(self.host).digest, before)
        self.assertEqual(published.get("candidate_digest"), before)

    def test_FND4_C10_fresh_resolve_recovers_current_head_from_disk(self):
        self._interface_host()
        first = run_submit(self.host, task_id=TASK_A)
        published = publish_knowledge_outcomes(
            self.host, first.extras["structural"], outcome="SATISFIED"
        )
        candidate = observe_candidate(self.host).digest
        impact_digest = published["impact_digest"]
        first_resolve = resolve_current_knowledge_assessment(
            self.host,
            candidate_digest=candidate,
            impact_digest=impact_digest,
        )
        second_resolve = resolve_current_knowledge_assessment(
            self.host,
            candidate_digest=candidate,
            impact_digest=impact_digest,
        )
        self.assertTrue(first_resolve.get("ok"), first_resolve)
        self.assertTrue(second_resolve.get("ok"), second_resolve)
        self.assertEqual(first_resolve.get("locator"), published["locator"])
        self.assertEqual(second_resolve.get("locator"), published["locator"])
        self.assertEqual(
            first_resolve.get("assessment_digest"),
            second_resolve.get("assessment_digest"),
        )
        self.assertEqual(
            first_resolve.get("assessment_digest"),
            published.get("assessment_digest"),
        )


if __name__ == "__main__":
    unittest.main()

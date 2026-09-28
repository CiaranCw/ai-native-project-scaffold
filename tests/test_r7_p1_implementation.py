"""R7 P1 implementation regression tests (F1 autonomous adoption, F2 docs, F9)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _clean_env() -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _run_installed(host: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(host / ".scaffold" / "install" / "run.py"), *args],
        cwd=str(host),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _import_project(host: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "src" / "scaffold_consumer.py"),
            "import-project",
            "--host",
            str(host),
        ],
        cwd=str(REPO),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )


def _apply_command(digest: str) -> str:
    return (
        "python .scaffold/install/run.py understand bootstrap "
        f"--approved --plan-digest {digest}"
    )


def _hook_payload(host: Path, **fields) -> dict:
    payload = {
        "cwd": str(host),
        "workspace_roots": [str(host)],
    }
    payload.update(fields)
    return payload


def _shell_before(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="beforeShellExecution",
        command=command,
        sandbox=False,
    )


PUBLIC_REFERENCE = REPO / "docs" / "PUBLIC_LIFECYCLE_REFERENCE.md"


class R7P1DocumentationTests(unittest.TestCase):
    """TU01/TU12: public docs exist, are discoverable, and stay consistent."""

    def test_TU01_public_reference_exists_with_key_sections(self):
        self.assertTrue(PUBLIC_REFERENCE.is_file(), PUBLIC_REFERENCE)
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        for needle in (
            "Develop Intake Envelope",
            "Develop Complete Envelope",
            "Session 状态机",
            "Session 状态查询",
            "TEST_PASS / coverage_complete / required_policy / TEST_COMPLETE / READY",
            "required_tests",
            "evidence_ref",
            "required_authority",
            "交付报告",
        ):
            self.assertIn(needle, text, needle)
        self.assertIn(
            "评估器不直接读 TEST_COMPLETE",
            text,
            "document must not claim TEST_COMPLETE is a universal READY precondition",
        )
        self.assertIn(
            "只有当 READY 请求同时消费",
            text,
            "document must state the actual published-report hard-block paths",
        )

    def test_TU12_quick_start_and_install_surface_discover_docs(self):
        quick = (REPO / "docs" / "QUICK_START.md").read_text(encoding="utf-8")
        self.assertIn("PUBLIC_LIFECYCLE_REFERENCE.md", quick)
        from scaffold_p5.agents import CONSUMER_AGENTS_INNER

        self.assertIn("PUBLIC_LIFECYCLE_REFERENCE.md", CONSUMER_AGENTS_INNER)
        self.assertIn(
            ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md",
            CONSUMER_AGENTS_INNER,
        )
        self.assertIn(
            "installed MANAGED",
            CONSUMER_AGENTS_INNER,
        )
        adoption_flow = (
            REPO / "docs" / "architecture" / "ADOPTION_FLOW.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Agent-autonomous", adoption_flow)
        self.assertNotIn("default = not authorized", adoption_flow)
        self.assertNotIn("B4 Human Plan Approval", adoption_flow)

    def test_TU12b_adoption_flow_still_keeps_not_adopted_boundary(self):
        text = (
            REPO / "docs" / "architecture" / "ADOPTION_FLOW.md"
        ).read_text(encoding="utf-8")
        self.assertIn("NOT_ADOPTED` forbids ordinary project mutation", text)
        self.assertIn("Git Commit and Git Push remain separate", text)


class R7P1EnvelopeSampleTests(unittest.TestCase):
    """TU02-TU04: documented envelope samples are accepted by real parsers."""

    def test_TU02_intake_sample_accepted(self):
        from scaffold_p7.intake import parse_intake_envelope

        sample = json.loads(
            (PUBLIC_REFERENCE.read_text(encoding="utf-8").split("```json")[1])
            .split("```")[0]
        )
        envelope, error = parse_intake_envelope(sample)
        self.assertIsNone(error, error)
        self.assertIsNotNone(envelope)
        self.assertEqual(envelope["structured_intent"]["kind"], "develop")

    def test_TU03_intake_sample_fully_grounded_direct(self):
        from scaffold_p7.intake import assess_grounding, prepare_proposal

        sample = json.loads(
            (PUBLIC_REFERENCE.read_text(encoding="utf-8").split("```json")[1])
            .split("```")[0]
        )
        proposal, issues = prepare_proposal(sample["proposal"])
        self.assertEqual(issues, [], issues)
        grounding = assess_grounding(
            sample["structured_intent"], sample["grounding"], proposal
        )
        self.assertTrue(grounding["fully_grounded"], grounding)
        self.assertTrue(grounding["direct_activation"], grounding)

    def test_TU04_complete_sample_accepted_by_run_opts(self):
        from scaffold_p7.engine import complete_run_opts

        blocks = PUBLIC_REFERENCE.read_text(encoding="utf-8").split("```json")
        complete_sample = None
        for block in blocks[1:]:
            payload = json.loads(block.split("```")[0])
            if "complete_stage" in payload:
                complete_sample = payload
                break
        self.assertIsNotNone(complete_sample)
        opts, error = complete_run_opts(complete_sample)
        self.assertIsNone(error, error)
        self.assertTrue(opts["invoke_test"])
        self.assertTrue(opts["request_stage_complete"])
        self.assertTrue(opts["request_ready_for_review"])
        self.assertEqual(opts["stage_completion_decision"]["stage_id"], "stage-1")

    def test_TU04b_complete_rejects_unknown_fields_and_conflicts(self):
        from scaffold_p7.engine import complete_run_opts

        _, error = complete_run_opts({"bogus": True})
        self.assertIsNotNone(error)
        _, error = complete_run_opts(
            {"test": {"invoke": True, "published_report_id": "r1"}}
        )
        self.assertIsNotNone(error)


class R7P1AdoptionTests(unittest.TestCase):
    """TU05-TU11: autonomous adoption, authorization basis, and regressions."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        _git(self.host, "init")
        (self.host / "README.md").write_text("# host\n", encoding="utf-8")
        _git(self.host, "add", "-A")
        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def _engine(self):
        from scaffold_p5.consumer_install import load_installed_distribution
        from scaffold_p5.engine import UnderstandEngine
        return UnderstandEngine(self.host, load_installed_distribution(self.host))

    def _bootstrap_digest(self) -> str:
        planned = self._engine().run("bootstrap")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        return planned.extras["plan"]["digest"]

    def test_TU09_hook_allows_digest_bound_apply_without_ask(self):
        from scaffold_p5.first_use import evaluate_cursor_hook

        digest = self._bootstrap_digest()
        result = evaluate_cursor_hook(
            _shell_before(self.host, _apply_command(digest)), self.host
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_TU05_apply_persists_authorization_basis(self):
        from scaffold_p5.host_state import snapshot_host

        digest = self._bootstrap_digest()
        applied = self._engine().run(
            "bootstrap", approval={"approved": True, "plan_digest": digest}
        )
        self.assertEqual(applied.outcome, "COMPLETED", applied.blockers)
        basis = applied.extras["apply_request"]["authorization_basis"]
        self.assertEqual(basis["kind"], "standing_policy")
        self.assertTrue(basis.get("location"))
        sessions = self.host / ".scaffold" / "runtime" / "adoption-sessions"
        self.assertFalse(sessions.exists(), "B9 cleans the adoption session")
        self.assertEqual(snapshot_host(self.host).host_class, "ESTABLISHED_HOST")

    def test_TU05b_agent_asserted_basis_is_recorded_not_human(self):
        from scaffold_p5.adoption import normalize_authorization_basis

        basis = normalize_authorization_basis(
            {"kind": "agent_asserted", "note": "agent asserted without human input"}
        )
        self.assertEqual(basis["kind"], "agent_asserted")
        self.assertNotIn("human", basis["kind"])
        self.assertIsNone(normalize_authorization_basis({"kind": "human_grant"}))
        self.assertIsNone(normalize_authorization_basis("approved"))

    def test_TU06_legacy_session_without_basis_reads_back(self):
        from scaffold_p5 import yaml_lite
        from scaffold_p5.adoption import (
            make_id,
            normalize_authorization_basis,
            persist_session,
            plan_from_dict,
        )
        from scaffold_p5.host_state import snapshot_host
        from scaffold_p5.io_util import read_yaml

        digest = self._bootstrap_digest()
        plan_data = self._engine().run("bootstrap").extras["plan"]
        plan = plan_from_dict(plan_data)
        self.assertEqual(plan.digest, digest)
        session_dir = persist_session(
            self.host,
            plan,
            status="OPEN",
            steps=["B1"],
            checkpoints=[],
            mutations=[],
            observed_approved=True,
            authorization_basis=None,
        )
        data = read_yaml(session_dir / "session.yaml")
        self.assertNotIn("authorization_basis", data["plan"])
        self.assertIsNone(normalize_authorization_basis(None))
        legacy_class = snapshot_host(self.host).host_class
        self.assertIn(
            legacy_class,
            {"NOT_ADOPTED", "INTERRUPTED_INITIAL_ADOPTION"},
            legacy_class,
        )
        from scaffold_p5.adoption import replace_session_plan

        prior = replace_session_plan(
            session_dir, plan, authorization_basis=None
        )
        self.assertIsNone(prior)
        replaced = read_yaml(session_dir / "session.yaml")
        self.assertNotIn(
            "authorization_basis", replaced.get("plan") or {}
        )

    def test_TU07_not_adopted_product_mutation_still_denied(self):
        from scaffold_p5.first_use import evaluate_cursor_hook
        from scaffold_p5.host_state import snapshot_host

        self._bootstrap_digest()
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={"path": "src/app.py", "contents": "x\n"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / "src" / "app.py").exists())

    def test_TU08_digest_mismatch_apply_still_rejected(self):
        from scaffold_p5.host_state import snapshot_host

        self._bootstrap_digest()
        applied = self._engine().run(
            "bootstrap",
            approval={"approved": True, "plan_digest": "f" * 64},
        )
        self.assertEqual(applied.outcome, "NEEDS_HUMAN", applied.blockers)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_TU10_commit_and_push_remain_blocked(self):
        from scaffold_p5.first_use import classify_first_use_shell
        from scaffold_p5.shell_boundary import ordinary_shell_hard_boundary

        digest = self._bootstrap_digest()
        self._engine().run(
            "bootstrap", approval={"approved": True, "plan_digest": digest}
        )
        for command in (
            "git commit -m x",
            "git push origin main",
            "git push --force origin main",
            "git rebase main",
        ):
            argv = command.split()
            reason = ordinary_shell_hard_boundary(argv, self.host)
            self.assertIsNotNone(reason, command)
        for command in ("git status", "git log -n 1", "git diff"):
            argv = command.split()
            self.assertIsNone(
                ordinary_shell_hard_boundary(argv, self.host), command
            )

    def test_TU11_legacy_lifecycle_behavior_regression(self):
        from scaffold_p5.first_use import evaluate_cursor_hook
        from scaffold_p5.host_state import snapshot_host

        digest = self._bootstrap_digest()
        # Preview does not mutate the host.
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        # Agent-originated digest-bound apply command is an official allow.
        apply_hook = evaluate_cursor_hook(
            _shell_before(self.host, _apply_command(digest)), self.host
        )
        self.assertEqual(apply_hook["permission"], "allow", apply_hook)
        # Non-bootstrap approval flags are still rejected by the shell gate.
        bad = evaluate_cursor_hook(
            _shell_before(
                self.host,
                "python .scaffold/install/run.py status --approved --plan-digest "
                + digest,
            ),
            self.host,
        )
        self.assertEqual(bad["permission"], "deny", bad)


class R7P1ConsumerDocDeliveryTests(unittest.TestCase):
    """Real-install integration: the public lifecycle reference is delivered
    as a MANAGED install file and discoverable from installed AGENTS.md."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.host = cls.tmp / "host"
        cls.host.mkdir()
        _git(cls.host, "init")
        (cls.host / "README.md").write_text("# host\n", encoding="utf-8")
        (cls.host / "NOTES.md").write_text(
            "# Human notes\n\nDo not lose this paragraph.\n",
            encoding="utf-8",
        )
        _git(cls.host, "add", "-A")
        proc = _import_project(cls.host)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_F01_installed_reference_exists_and_is_readable(self):
        installed = self.host / ".scaffold" / "install" / "docs" / (
            "PUBLIC_LIFECYCLE_REFERENCE.md"
        )
        self.assertTrue(installed.is_file(), installed)
        text = installed.read_text(encoding="utf-8")
        self.assertIn("Develop Intake Envelope", text)
        self.assertIn("Develop Complete Envelope", text)

    def test_F02_installed_reference_matches_public_interface(self):
        installed = (
            self.host / ".scaffold" / "install" / "docs" / (
                "PUBLIC_LIFECYCLE_REFERENCE.md"
            )
        ).read_text(encoding="utf-8")
        source = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertEqual(installed, source)
        self.assertIn(
            "评估器不直接读 TEST_COMPLETE", installed
        )

    def test_F03_installed_agents_points_to_real_installed_doc(self):
        agents = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md", agents)
        self.assertTrue(
            (self.host / ".scaffold" / "install" / "docs" / (
                "PUBLIC_LIFECYCLE_REFERENCE.md"
            )).is_file()
        )
        self.assertNotIn(
            "QUICK_START links it",
            agents,
            "installed AGENTS must point at the installed copy, not the Distribution checkout",
        )

    def test_F04_verify_is_valid_after_install(self):
        proc = _run_installed(self.host, "verify")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "VALID", payload)

    def test_F05_human_owned_agents_content_preserved(self):
        # Install into a host whose AGENTS.md already carries human text:
        # the managed region must be appended without dropping it.
        host2 = self.tmp / "host2"
        host2.mkdir()
        _git(host2, "init")
        (host2 / "README.md").write_text("# host\n", encoding="utf-8")
        (host2 / "AGENTS.md").write_text(
            "# Human agents notes\n\nDo not lose this paragraph.\n",
            encoding="utf-8",
        )
        _git(host2, "add", "-A")
        proc = _import_project(host2)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        agents = (host2 / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not lose this paragraph.", agents)
        self.assertIn("scaffold:managed:scaffold-consumer:start", agents)
        self.assertLess(
            agents.index("Do not lose this paragraph."),
            agents.index("scaffold:managed:scaffold-consumer:start"),
            "human text must stay outside the managed region",
        )
        # The primary host had no pre-existing AGENTS.md; install creates
        # the managed region without claiming human content.
        self.assertIn(
            "scaffold:managed:scaffold-consumer:start",
            (self.host / "AGENTS.md").read_text(encoding="utf-8"),
        )

    def test_F06_skill_package_identities_unchanged(self):
        from scaffold_p5.consumer_install import load_installed_distribution

        dist = load_installed_distribution(self.host)
        selected = dist.selected_packages()
        from scaffold_p5.distribution import load_package

        expected = {
            "understand": REPO / "skills" / "understand",
            "develop": REPO / "skills" / "develop",
            "test": REPO / "skills" / "test",
            "submit": REPO / "skills" / "submit",
        }
        for skill_id, path in expected.items():
            pkg = load_package(path)
            self.assertEqual(
                selected[skill_id].ref.package_digest,
                pkg.ref.package_digest,
                skill_id,
            )
            self.assertEqual(
                selected[skill_id].ref.skill_version,
                pkg.ref.skill_version,
                skill_id,
            )

    def test_F07_rc2_predecessor_region_digest_recognizes_historical_text(self):
        from scaffold_p5.consumer_install import (
            CONSUMER_REGION_END,
            CONSUMER_REGION_START,
            RC2_CONSUMER_AGENTS_INNER,
            expected_region_digest,
            predecessor_region_digests,
        )
        from scaffold_p5.io_util import sha256_bytes

        rc2_text = (
            f"{CONSUMER_REGION_START}\n"
            f"{RC2_CONSUMER_AGENTS_INNER.strip()}\n"
            f"{CONSUMER_REGION_END}"
        )
        digests = predecessor_region_digests("AGENTS.md")
        self.assertIn(sha256_bytes(rc2_text.encode("utf-8")), digests)
        # The current canonical region digest differs from the RC2 one.
        current = expected_region_digest("AGENTS.md", host=self.host)
        self.assertIsNotNone(current)
        self.assertNotIn(current, digests)

    def test_F08_rc2_historical_text_is_restored_verbatim(self):
        from scaffold_p5.consumer_install import RC2_CONSUMER_AGENTS_INNER

        self.assertIn(
            "Stop for explicit human approval of that exact plan",
            RC2_CONSUMER_AGENTS_INNER,
            "RC2 historical constant must keep its original identification text",
        )
        self.assertNotIn(
            "authorization basis", RC2_CONSUMER_AGENTS_INNER
        )
        self.assertNotIn(
            "PUBLIC_LIFECYCLE_REFERENCE", RC2_CONSUMER_AGENTS_INNER
        )

    def test_F09_manifest_records_installed_reference(self):
        from scaffold_p5.io_util import read_yaml

        manifest = read_yaml(self.host / ".scaffold" / "install" / "install.yaml")
        rel = ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md"
        rows = [
            row
            for row in (manifest.get("files") or [])
            if isinstance(row, dict) and row.get("path") == rel
        ]
        self.assertEqual(len(rows), 1, manifest.get("files"))
        self.assertEqual(rows[0].get("ownership"), "MANAGED")

    def test_F10_installed_reference_is_verified_as_managed(self):
        installed = (
            self.host / ".scaffold" / "install" / "docs" / (
                "PUBLIC_LIFECYCLE_REFERENCE.md"
            )
        )
        original = installed.read_bytes()
        try:
            installed.write_bytes(original + b"\n<!-- drift -->\n")
            proc = _run_installed(self.host, "verify")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "DRIFTED", payload)
        finally:
            installed.write_bytes(original)
        proc = _run_installed(self.host, "verify")
        self.assertEqual(json.loads(proc.stdout)["status"], "VALID")

    def test_F11_missing_reference_fails_verify(self):
        installed = (
            self.host / ".scaffold" / "install" / "docs" / (
                "PUBLIC_LIFECYCLE_REFERENCE.md"
            )
        )
        original = installed.read_bytes()
        try:
            installed.unlink()
            proc = _run_installed(self.host, "verify")
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "INCOMPLETE", payload)
            self.assertIn(
                ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md",
                payload.get("missing") or [],
            )
        finally:
            installed.write_bytes(original)


class R7P1ConsumerUpdateTests(unittest.TestCase):
    """Old-version consumer UPDATE gains the reference doc; human text and
    Gen1→Gen2 migration semantics stay intact."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        _git(self.host, "init")
        (self.host / "README.md").write_text("# host\n", encoding="utf-8")
        _git(self.host, "add", "-A")

    def tearDown(self):
        self._tmp.cleanup()

    def _strip_reference_from_host(self) -> None:
        """Simulate an old-version installation: remove the docs file and
        rewrite the manifest without it (digest bookkeeping included)."""
        import hashlib

        from scaffold_p5 import yaml_lite
        from scaffold_p5.io_util import sha256_bytes

        installed = (
            self.host / ".scaffold" / "install" / "docs" / (
                "PUBLIC_LIFECYCLE_REFERENCE.md"
            )
        )
        installed.unlink()
        installed.parent.rmdir()
        manifest_path = self.host / ".scaffold" / "install" / "install.yaml"
        manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
        rel = ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md"
        manifest["files"] = [
            row
            for row in (manifest.get("files") or [])
            if not (isinstance(row, dict) and row.get("path") == rel)
        ]
        manifest_path.write_text(yaml_lite.dump(manifest), encoding="utf-8")
        # install.yaml digest itself is not recorded in the manifest; drop
        # cached pyc so the stripped state is verified cleanly.
        caches = self.host / ".scaffold" / "install" / "runtime"
        for cache in caches.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

    def test_U01_old_install_without_reference_verifies_incomplete_or_valid(self):
        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._strip_reference_from_host()
        proc = _run_installed(self.host, "verify")
        payload = json.loads(proc.stdout)
        # The stripped host has an extra-free, manifest-consistent tree;
        # old manifests simply did not require the docs file.
        self.assertIn(payload["status"], {"VALID", "INCOMPLETE"}, payload)
        if payload["status"] == "INCOMPLETE":
            self.assertIn(
                ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md",
                payload.get("missing") or [],
            )

    def test_U02_update_from_old_manifest_gains_reference_doc(self):
        from scaffold_p5.consumer_install import (
            INSTALL_PUBLIC_LIFECYCLE_REFERENCE_REL,
            plan_consumer_install,
            apply_consumer_install,
        )

        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._strip_reference_from_host()
        plan = plan_consumer_install(
            self.host, REPO, mode="update"
        )
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertIn(
            INSTALL_PUBLIC_LIFECYCLE_REFERENCE_REL, plan.added, plan.added
        )
        result = apply_consumer_install(plan)
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        installed = self.host / ".scaffold" / "install" / "docs" / (
            "PUBLIC_LIFECYCLE_REFERENCE.md"
        )
        self.assertTrue(installed.is_file())
        self.assertEqual(
            installed.read_text(encoding="utf-8"),
            PUBLIC_REFERENCE.read_text(encoding="utf-8"),
        )
        proc = _run_installed(self.host, "verify")
        self.assertEqual(json.loads(proc.stdout)["status"], "VALID")

    def test_U03_update_preserves_human_agents_text(self):
        from scaffold_p5.consumer_install import (
            plan_consumer_install,
            apply_consumer_install,
        )

        (self.host / "NOTES.md").write_text(
            "# Human notes\n\nDo not lose this paragraph.\n",
            encoding="utf-8",
        )
        (self.host / "AGENTS.md").write_text(
            "# Human agents notes\n\nDo not lose this paragraph.\n",
            encoding="utf-8",
        )
        _git(self.host, "add", "-A")
        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        agents_before = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not lose this paragraph.", agents_before)
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        result = apply_consumer_install(plan)
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        agents_after = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not lose this paragraph.", agents_after)

    def test_U04_update_keeps_skill_package_identities(self):
        from scaffold_p5.consumer_install import (
            plan_consumer_install,
            apply_consumer_install,
            load_installed_distribution,
        )

        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        before = load_installed_distribution(self.host).selected_packages()
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        result = apply_consumer_install(plan)
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        after = load_installed_distribution(self.host).selected_packages()
        for skill_id in ("understand", "develop", "test", "submit"):
            self.assertEqual(
                before[skill_id].ref.package_digest,
                after[skill_id].ref.package_digest,
                skill_id,
            )
            self.assertEqual(
                before[skill_id].ref.skill_version,
                after[skill_id].ref.skill_version,
                skill_id,
            )

    def test_U05_update_keeps_projection_generation_semantics(self):
        from scaffold_p5.consumer_install import (
            plan_consumer_install,
            apply_consumer_install,
        )

        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        records_dir = self.host / ".scaffold" / "runtime" / "candidate-projection"
        before = {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(records_dir.glob("*.yaml"))
        }
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(plan.modified, [], "update must not rewrite migration records")
        result = apply_consumer_install(plan)
        self.assertEqual(result.get("outcome"), "COMPLETED", result)
        after = {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(records_dir.glob("*.yaml"))
        }
        self.assertEqual(before, after,
            "Consumer UPDATE must not change Gen1→Gen2 migration or Gen2 candidate state")

    def test_U06_update_from_old_runtime_via_installed_command(self):
        """End-to-end: an old-manifest host updates through the installed
        launcher (`consumer update --distribution`) and gains the doc."""
        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self._strip_reference_from_host()
        proc = subprocess.run(
            [
                sys.executable,
                str(self.host / ".scaffold" / "install" / "run.py"),
                "consumer",
                "update",
                "--distribution",
                str(REPO),
            ],
            cwd=str(self.host),
            env=_clean_env(),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        installed = self.host / ".scaffold" / "install" / "docs" / (
            "PUBLIC_LIFECYCLE_REFERENCE.md"
        )
        self.assertTrue(installed.is_file(), proc.stdout + proc.stderr)
        proc = _run_installed(self.host, "verify")
        self.assertEqual(json.loads(proc.stdout)["status"], "VALID")


class R7P1AdoptionParityTests(unittest.TestCase):
    """Baseline-vs-P1 adoption behavior comparison, encoded as assertions.

    Documented conclusion (see R7_P1_IMPLEMENTATION.md §3): the release
    baseline b34b3db already classified the digest-bound apply command as
    SHELL_ALLOW (commit 5e731f6, 2026-09-17). P1 does not newly enable
    autonomous Adoption; its additions are the persisted authorization
    basis and contract/documentation consistency.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        _git(self.host, "init")
        (self.host / "README.md").write_text("# host\n", encoding="utf-8")
        _git(self.host, "add", "-A")
        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def tearDown(self):
        self._tmp.cleanup()

    def _engine(self):
        from scaffold_p5.consumer_install import load_installed_distribution
        from scaffold_p5.engine import UnderstandEngine
        return UnderstandEngine(self.host, load_installed_distribution(self.host))

    def _bootstrap_digest(self) -> str:
        planned = self._engine().run("bootstrap")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        return planned.extras["plan"]["digest"]

    def test_P01_same_inputs_same_outcome_as_baseline_contract(self):
        from scaffold_p5.first_use import classify_first_use_shell

        digest = self._bootstrap_digest()
        command = _apply_command(digest)
        # Hook layer: baseline and P1 both return allow with the same reason
        # constant (ASK_APPLY_REASON text is unchanged from the baseline).
        before = classify_first_use_shell(command, self.host)
        self.assertEqual(before[0], "allow", before)
        self.assertEqual(
            before[1],
            "digest-bound Adoption apply is an official lifecycle command",
            "reason text must match the b34b3db baseline verbatim",
        )
        # Engine layer: same plan digest, same NEEDS_HUMAN preview.
        planned = self._engine().run("bootstrap")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN", planned.blockers)
        self.assertEqual(planned.extras["plan"]["digest"], digest)

    def test_P02_p1_adds_authorization_basis_without_changing_permission(self):
        from scaffold_p5.first_use import classify_first_use_shell

        digest = self._bootstrap_digest()
        kind, _detail = classify_first_use_shell(_apply_command(digest), self.host)
        self.assertEqual(kind, "allow")
        applied = self._engine().run(
            "bootstrap", approval={"approved": True, "plan_digest": digest}
        )
        self.assertEqual(applied.outcome, "COMPLETED", applied.blockers)
        basis = applied.extras["apply_request"]["authorization_basis"]
        self.assertEqual(basis["kind"], "standing_policy")
        # The permission outcome is identical to baseline (allow); only the
        # persisted basis is new.
        self.assertNotIn("permission", applied.extras["apply_request"])


if __name__ == "__main__":
    unittest.main()

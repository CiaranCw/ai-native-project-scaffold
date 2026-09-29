"""R7 P2 implementation regression tests.

F3: install-managed drift classification.
F4: structured test evidence documentation.
F7: stale candidate evidence diagnostics.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(REPO / "tests"))

from p6_support import (  # noqa: E402
    CORE_OWNERSHIP,
    init_git,
    passing_profile,
    write_host,
)
from p6_support import test_engine as make_test_engine  # noqa: E402
from p7_support import TASK_A, develop_engine, write_active_host, write_task  # noqa: E402
from support import REPO as REPO_ROOT, write  # noqa: E402

from scaffold_p5.consumer_install import (  # noqa: E402
    current_manifest,
    manifest_file_map,
    verify_consumer_install,
)
from scaffold_p5.io_util import read_yaml, write_yaml_atomic  # noqa: E402
from scaffold_p6.candidate import observe_candidate  # noqa: E402
from scaffold_p6.published import consume_published_report  # noqa: E402
from scaffold_p7.unexplained import (  # noqa: E402
    CLASS_INSTALL_MANAGED,
    CLASS_UNEXPLAINED,
    UNEXPLAINED_REL,
    inspect_drift_authority,
    reconcile_unexplained_drift,
    unexplained_matches_current,
    unexplained_path_map,
)

PUBLIC_REFERENCE = REPO_ROOT / "docs" / "PUBLIC_LIFECYCLE_REFERENCE.md"
INSTALL_DOC = (
    ".scaffold/install/docs/PUBLIC_LIFECYCLE_REFERENCE.md"
)


def _clean_env() -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


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


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )


def _row(host: Path, rel: str) -> dict:
    rows = unexplained_path_map(host)
    if rel not in rows:
        raise AssertionError(f"{rel} missing from unexplained map: {sorted(rows)}")
    return rows[rel]


class _InstalledHostCase(unittest.TestCase):
    """Real install into a fresh git host: install happens before Adoption."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.host = cls.tmp / "host"
        cls.host.mkdir()
        _git(cls.host, "init")
        (cls.host / "README.md").write_text("# host\n", encoding="utf-8")
        (cls.host / "src").mkdir()
        (cls.host / "src" / "app.py").write_text("value = 0\n", encoding="utf-8")
        _git(cls.host, "add", "-A")
        _git(
            cls.host,
            "-c",
            "user.name=P2 Test",
            "-c",
            "user.email=p2@example.invalid",
            "commit",
            "-m",
            "baseline",
        )
        proc = _import_project(cls.host)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        cls._adopt(cls.host)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _adopt(cls, host: Path) -> None:
        """First Adoption after install: consumes the compatibility boundary
        the same way a real host does (Understand bootstrap --approved)."""
        from scaffold_p5.consumer_install import load_installed_distribution
        from scaffold_p5.engine import UnderstandEngine

        engine = UnderstandEngine(host, load_installed_distribution(host))
        planned = engine.run("bootstrap")
        assert planned.outcome == "NEEDS_HUMAN", planned.blockers
        digest = planned.extras["plan"]["digest"]
        applied = engine.run(
            "bootstrap", approval={"approved": True, "plan_digest": digest}
        )
        assert applied.outcome == "COMPLETED", applied.blockers


class F3InstallManagedDriftTests(_InstalledHostCase):
    """F3: Scaffold-installed MANAGED files must separate from unexplained."""

    def test_F3_01_install_files_are_classified_install_managed(self):
        reconcile = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(reconcile.get("ok"), reconcile.get("blockers"))
        rows = unexplained_path_map(self.host)
        managed = manifest_file_map(current_manifest(self.host))
        self.assertTrue(managed, "fixture must have whole-file MANAGED entries")
        install_rows = [
            rel for rel in managed
            if rel.startswith(".scaffold/install/")
        ]
        self.assertTrue(install_rows, install_rows)
        for rel in install_rows:
            self.assertEqual(
                _row(self.host, rel)["classification"],
                CLASS_INSTALL_MANAGED,
                rel,
            )

    def test_F3_02_cursor_adapters_classified_install_managed(self):
        reconcile_unexplained_drift(self.host, boundary="open")
        rows = unexplained_path_map(self.host)
        adapters = [
            rel for rel in rows
            if rel.startswith(".cursor/skills/scaffold-")
            and rows[rel]["classification"] == CLASS_INSTALL_MANAGED
        ]
        self.assertTrue(adapters, sorted(rows))
        for rel in adapters:
            self.assertEqual(rows[rel]["classification"], CLASS_INSTALL_MANAGED)

    def test_F3_03_mixed_ownership_agents_md_not_install_managed(self):
        """AGENTS.md is mixed-ownership: the human part may differ freely, so
        the file itself must never be wholesale attested as install-managed."""
        reconcile_unexplained_drift(self.host, boundary="open")
        rows = unexplained_path_map(self.host)
        if "AGENTS.md" in rows:
            self.assertNotEqual(
                rows["AGENTS.md"]["classification"],
                CLASS_INSTALL_MANAGED,
            )

    def test_F3_04_tampered_install_file_falls_back_to_unexplained(self):
        target = None
        reconcile_unexplained_drift(self.host, boundary="open")
        managed = manifest_file_map(current_manifest(self.host))
        for rel in sorted(managed):
            if rel.startswith(".scaffold/install/runtime/scaffold_p5/"):
                target = rel
                break
        self.assertIsNotNone(target, "fixture must expose a runtime module")
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertEqual(_row(self.host, target)["classification"], CLASS_INSTALL_MANAGED)
        path = self.host / target
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(original + "\n# human patch\n", encoding="utf-8")
            reconcile_unexplained_drift(self.host, boundary="open")
            self.assertEqual(_row(self.host, target)["classification"], CLASS_UNEXPLAINED)
        finally:
            path.write_text(original, encoding="utf-8")
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertEqual(_row(self.host, target)["classification"], CLASS_INSTALL_MANAGED)

    def test_F3_05_new_human_file_stays_unexplained(self):
        (self.host / "src" / "human_note.md").write_text(
            "# human\n", encoding="utf-8"
        )
        reconcile_unexplained_drift(self.host, boundary="open")
        self.assertEqual(
            _row(self.host, "src/human_note.md")["classification"],
            CLASS_UNEXPLAINED,
        )

    def test_F3_06_legacy_unexplained_row_converges_with_evidence(self):
        """Old unexplained.yaml rows converge only with sufficient install
        evidence; unrelated rows stay untouched (no blanket amnesty)."""
        target = None
        managed = manifest_file_map(current_manifest(self.host))
        for rel in sorted(managed):
            if rel.startswith(".scaffold/install/runtime/scaffold_p5/"):
                target = rel
                break
        self.assertIsNotNone(target)
        raw = (
            "record_type: develop_unexplained_drift\n"
            'schema_version: "1"\n'
            "initialization:\n"
            "  completed: true\n"
            "  completed_at: '2026-01-01T00:00:00Z'\n"
            "paths:\n"
            "  - path: " + target + "\n"
            "    kind: regular_file\n"
            "    digest: sha256:deadbeef\n"
            "    accepted_kind: git\n"
            "    accepted_revision: old\n"
            "    classification: unexplained\n"
            "    first_observed_boundary: open\n"
            "    first_observed_at: '2026-01-01T00:00:00Z'\n"
            "  - path: src/human_note.md\n"
            "    kind: regular_file\n"
            "    digest: sha256:cafebabe\n"
            "    accepted_kind: git\n"
            "    accepted_revision: old\n"
            "    classification: unexplained\n"
            "    first_observed_boundary: open\n"
            "    first_observed_at: '2026-01-01T00:00:00Z'\n"
        )
        dest = self.host / UNEXPLAINED_REL
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(raw, encoding="utf-8")
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("ok"), result.get("blockers"))
        self.assertEqual(
            _row(self.host, target)["classification"],
            CLASS_INSTALL_MANAGED,
            "convergence requires verified install evidence",
        )
        self.assertEqual(
            _row(self.host, "src/human_note.md")["classification"],
            CLASS_UNEXPLAINED,
            "no blanket amnesty: non-install rows keep the conservative class",
        )

    def test_F3_07_matches_current_covers_install_managed(self):
        reconcile_unexplained_drift(self.host, boundary="open")
        managed = manifest_file_map(current_manifest(self.host))
        target = next(
            rel for rel in sorted(managed)
            if rel.startswith(".scaffold/install/runtime/scaffold_p5/")
        )
        self.assertTrue(unexplained_matches_current(self.host, target))

    def test_F3_08_verify_stays_valid_after_reconcile(self):
        reconcile_unexplained_drift(self.host, boundary="open")
        payload = verify_consumer_install(self.host)
        self.assertEqual(payload["status"], "VALID", payload["reasons"])


class F3NoScmConsumerTests(unittest.TestCase):
    """F3 on a no-SCM consumer: reconciliation relies on the noscms baseline."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_F3_09_noscms_install_files_classified(self):
        from scaffold_p5.io_util import read_yaml, write_yaml_atomic
    def test_F3_09_noscms_install_files_classified(self):
        """no-SCM consumer: a file that differs from the noscms baseline but
        matches the trusted Install Manifest is install-managed; a tampered
        file that matches neither stays unexplained."""
        from scaffold_p5.io_util import read_yaml, write_yaml_atomic
        from scaffold_p8.noscms import initialize_noscms_baseline

        proc = _import_project(self.host)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        F3InstallManagedDriftTests._adopt(self.host)
        project_path = self.host / ".scaffold/project.yaml"
        payload = read_yaml(project_path)
        ownership = dict(payload.get("ownership") or {})
        ownership[".scaffold/ext/submit/"] = "GENERATED"
        payload["ownership"] = ownership
        write_yaml_atomic(project_path, payload)
        target = self.host / ".scaffold/install/runtime/scaffold_p5/models.py"
        original = target.read_text(encoding="utf-8")
        tampered = original + "\n# human patch\n"
        baseline = initialize_noscms_baseline(self.host)
        self.assertTrue(baseline.get("ok"), baseline)
        target.write_text(tampered, encoding="utf-8")
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("ok"), result.get("blockers"))
        self.assertEqual(
            _row(
                self.host,
                ".scaffold/install/runtime/scaffold_p5/models.py",
            )["classification"],
            CLASS_UNEXPLAINED,
            "bytes matching neither the baseline nor the manifest stay unexplained",
        )
        target.write_text(original, encoding="utf-8")
        result = reconcile_unexplained_drift(self.host, boundary="open")
        self.assertTrue(result.get("ok"), result.get("blockers"))
        self.assertNotIn(
            ".scaffold/install/runtime/scaffold_p5/models.py",
            unexplained_path_map(self.host),
            "restored bytes equal the accepted baseline again: no drift, row retires",
        )
        from scaffold_p7.unexplained import _install_managed_verified

        self.assertTrue(
            _install_managed_verified(self.host, ".scaffold/install/runtime/scaffold_p5/models.py")
        )
        target.write_text(tampered, encoding="utf-8")
        self.assertFalse(
            _install_managed_verified(self.host, ".scaffold/install/runtime/scaffold_p5/models.py")
        )


class F4DocumentationTests(unittest.TestCase):
    """F4: public docs must teach structured test binding without changing
    contract strength."""

    def test_F4_01_public_reference_covers_binding_guidance(self):
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        for needle in (
            "如何在 Intake 中声明测试要求",
            "如何绑定已有 Test Profile",
            "如何关联正式 Test Report",
            "如何判断 Evidence 对应当前 Candidate",
            "如何区分正式 Scaffold Test 与额外执行的本地测试",
        ):
            self.assertIn(needle, text, needle)

    def test_F4_02_stale_diagnostic_contract_documented(self):
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("2.2.1", text)
        self.assertIn("current_candidate_digest", text)
        self.assertIn("evidence_candidate_digest", text)
        self.assertIn("remediation", text)

    def test_F4_03_examples_match_actual_interface(self):
        text = PUBLIC_REFERENCE.read_text(encoding="utf-8")
        self.assertIn("execution_binding: {kind: \"test_profile\", profile_id}", text)
        self.assertIn("develop bind --task-id", text)
        self.assertIn("bind_published_evidence", text)

    def test_F4_04_installed_consumer_document_synced(self):
        installed = REPO_ROOT / INSTALL_DOC
        if not installed.is_file():
            self.skipTest("no project-local installation in the repo itself")
        self.assertEqual(
            installed.read_text(encoding="utf-8"),
            PUBLIC_REFERENCE.read_text(encoding="utf-8"),
        )


class F7StaleEvidenceDiagnosticsTests(unittest.TestCase):
    """F7: stale evidence rejection must carry structured diagnostics and
    must keep the existing refusal semantics."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()
        profile, command = passing_profile("unit")
        write_host(self.host, [(profile, command)])
        self.task = write_task(
            self.host,
            TASK_A,
            final_tests=[
                {
                    "requirement_id": "REQ-A",
                    "execution_binding": {
                        "kind": "test_profile",
                        "profile_id": "unit",
                    },
                }
            ],
        )
        write(self.host, "src/app.py", "print('ok')\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run_test(self):
        result = make_test_engine(self.host).run(
            task_id=TASK_A,
            selected=["unit"],
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        return str(result.extras["report_id"])

    def test_F7_01_current_evidence_consumes_without_stale_field(self):
        report_id = self._run_test()
        loaded = consume_published_report(
            self.host, report_id, task=read_yaml(
                self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            )
        )
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        self.assertNotIn("stale_evidence", loaded)

    def test_F7_02_stale_evidence_carries_diagnostic(self):
        report_id = self._run_test()
        (self.host / "src" / "app.py").write_text(
            "print('changed')\n", encoding="utf-8"
        )
        loaded = consume_published_report(
            self.host, report_id, task=read_yaml(
                self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            )
        )
        self.assertFalse(loaded.get("ok"), "stale report must stay rejected")
        stale = loaded.get("stale_evidence")
        self.assertIsInstance(stale, dict, loaded.get("blockers"))
        current = observe_candidate(self.host).digest
        self.assertEqual(stale["current_candidate_digest"], current)
        self.assertNotEqual(
            stale["evidence_candidate_digest"], current
        )
        self.assertEqual(stale["evidence_report_id"], report_id)
        self.assertIn("re-run Test", stale["remediation"])
        self.assertTrue(
            any(
                "stale for the current candidate" in item
                for item in loaded.get("blockers") or []
            ),
            loaded.get("blockers"),
        )

    def test_F7_03_normal_development_not_flagged_by_install_files(self):
        """Ordinary development: install-managed paths must not pollute the
        candidate or fabricate drift during normal Task work."""
        report_id = self._run_test()
        loaded = consume_published_report(
            self.host, report_id, task=read_yaml(
                self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            )
        )
        self.assertTrue(loaded.get("ok"), loaded.get("blockers"))
        # Write inside the declared task scope: candidate changes, evidence
        # becomes stale, but the refusal must name both digests cleanly.
        write(self.host, "src/app.py", "print('iterate')\n")
        reloaded = consume_published_report(
            self.host, report_id, task=read_yaml(
                self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
            )
        )
        self.assertFalse(reloaded.get("ok"))
        stale = reloaded.get("stale_evidence") or {}
        self.assertIn("evidence_candidate_digest", stale)


if __name__ == "__main__":
    unittest.main()

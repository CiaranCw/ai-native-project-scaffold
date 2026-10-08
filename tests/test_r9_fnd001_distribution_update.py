"""Real Consumer UPDATE must keep Scaffold maintenance off the product candidate."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from support import REPO

from scaffold_p5 import yaml_lite
from scaffold_p5.client_support import is_client_support_path
from scaffold_p5.consumer_install import (
    apply_consumer_install,
    distribution_cli,
    plan_consumer_install,
    verify_consumer_install,
)
from scaffold_p5.io_util import file_digest
from scaffold_p5.host_state import snapshot_host
from scaffold_p6.candidate import observe_candidate, report_usable_for, semantic_body
from scaffold_p6.models import PROJECTION_GENERATION_CURRENT, PROJECTION_GENERATION_LEGACY
from scaffold_p6.projection import migration_dir
from scaffold_p7.lifecycle import decision_is_satisfied_current, evaluate_ready_for_review

PUBLISHED = "2e3b86438c68170255ae55020296051f6708d8f4"
HISTORICAL = "79755b15466155b7fefacfaded3444669eb93450"
RULE = ".cursor/rules/scaffold-first-use.mdc"
DEVELOP = ".cursor/skills/scaffold-develop/SKILL.md"
RUNTIME_INSTALL = ".scaffold/install/runtime/scaffold_p5/consumer_install.py"
RUNTIME_FIRST_USE = ".scaffold/install/runtime/scaffold_p5/first_use.py"
MARKER = b"\n# r9-fnd001-cotamper\n"


def _git(root: Path, *args: str) -> None:
    subprocess.check_call(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=T", *args],
        cwd=root,
        stdout=subprocess.DEVNULL,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _archive(commit: str, dest: Path) -> None:
    dest.mkdir()
    archive = dest.parent / f"{commit[:12]}.tar"
    subprocess.check_call(
        ["git", "archive", "--format=tar", "-o", str(archive), commit],
        cwd=REPO,
        stdout=subprocess.DEVNULL,
    )
    subprocess.check_call(["tar", "-xf", str(archive), "-C", str(dest)])


def _install(host: Path, distribution: Path) -> None:
    host.mkdir()
    _git(host, "init")
    _write(host / "README.md", "product\n")
    _git(host, "add", "README.md")
    _git(host, "commit", "-m", "product")
    plan = plan_consumer_install(host, distribution, mode="install")
    if not plan.allowed:
        raise AssertionError(plan.blockers)
    installed = apply_consumer_install(plan)
    if installed["outcome"] != "COMPLETED":
        raise AssertionError(installed.get("blockers"))


def _adopt(host: Path) -> None:
    from test_consumer_installation import _run_installed

    boot = _run_installed(host, "understand", "bootstrap")
    if boot.returncode != 0:
        raise AssertionError(boot.stdout + boot.stderr)
    payload = json.loads(boot.stdout)
    digest = ((payload.get("extras") or {}).get("plan") or {}).get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AssertionError(boot.stdout)
    applied = _run_installed(
        host,
        "understand",
        "bootstrap",
        "--approved",
        "--plan-digest",
        digest,
    )
    if applied.returncode != 0:
        raise AssertionError(applied.stdout + applied.stderr)
    adopted = json.loads(applied.stdout)
    if adopted.get("outcome") != "COMPLETED":
        raise AssertionError(applied.stdout)


def _bind_ready(
    host: Path,
    *,
    generation: str = PROJECTION_GENERATION_LEGACY,
) -> str:
    task_path = host / ".scaffold" / "tasks" / "bound.yaml"
    placeholder = {
        "outcome": "SATISFIED",
        "candidate_digest": "0" * 64,
        "basis": [{"kind": "task_fact", "summary": "held"}],
        "rationale": "held",
    }
    _write(
        task_path,
        yaml_lite.dump(
            {
                "record_type": "task_book",
                "record_id": "bound",
                "goal": "hold",
                "status": "READY_FOR_REVIEW",
                "acceptance": "held",
                "stages": [
                    {
                        "stage_id": "s1",
                        "status": "COMPLETE",
                        "required_tests": [],
                        "completion_decision": {**placeholder, "stage_id": "s1"},
                    }
                ],
                "final_tests": [],
                "task_completion_decision": placeholder,
            }
        ),
    )
    observed = observe_candidate(host, generation=generation)
    book = yaml_lite.load(task_path.read_text(encoding="utf-8"))
    book["stages"][0]["completion_decision"]["candidate_digest"] = observed.digest
    book["task_completion_decision"]["candidate_digest"] = observed.digest
    if generation == PROJECTION_GENERATION_CURRENT:
        book["stages"][0]["completion_decision"]["projection_generation"] = generation
        book["task_completion_decision"]["projection_generation"] = generation
    _write(task_path, yaml_lite.dump(book))
    return observed.digest


def _ready(host: Path, live_digest: str) -> tuple[bool, str]:
    book = yaml_lite.load(
        (host / ".scaffold" / "tasks" / "bound.yaml").read_text(encoding="utf-8")
    )
    return evaluate_ready_for_review(book, candidate_digest=live_digest, root=host)


def _current(
    host: Path,
    cited: str,
    live_digest: str,
    *,
    generation: str | None = None,
) -> bool:
    decision = {
        "outcome": "SATISFIED",
        "candidate_digest": cited,
        "basis": [{"kind": "task_fact", "summary": "held"}],
        "rationale": "held",
    }
    if generation is not None:
        decision["projection_generation"] = generation
    return decision_is_satisfied_current(decision, live_digest, root=host)


def _rewrite_manifest_digest(host: Path, rel: str) -> None:
    manifest_path = host / ".scaffold/install/install.yaml"
    manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
    rewritten = False
    for row in manifest.get("files") or []:
        if str(row.get("path") or "").replace("\\", "/") == rel:
            row["digest"] = file_digest(host / rel)
            rewritten = True
    if not rewritten:
        raise AssertionError(rel)
    _write(manifest_path, yaml_lite.dump(manifest))


def _agree_client_with_runtime(host: Path, client_rel: str, runtime_rel: str) -> None:
    """Write one marker into a client file and the runtime literal that emits it.

    The runtime copy may use CRLF while the installed client file uses LF.
    The marker is inserted into whichever literal form is actually stored.
    """
    client = host / client_rel
    original = client.read_bytes()
    runtime = host / runtime_rel
    source = runtime.read_bytes()
    needles = [original]
    if b"\n" in original:
        needles.append(original.replace(b"\n", b"\r\n"))
    if original.endswith(b"\n"):
        trimmed = original[:-1]
        needles.extend([trimmed, trimmed.replace(b"\n", b"\r\n")])
    needle = next((item for item in needles if item and item in source), None)
    if needle is None:
        raise AssertionError(f"{client_rel} is not a literal in {runtime_rel}")
    runtime.write_bytes(source.replace(needle, needle + MARKER, 1))
    client.write_bytes(original + MARKER)


def _untracked(host: Path) -> set[str]:
    rows = semantic_body(observe_candidate(host).data).get("untracked_paths") or []
    return {str(row.get("path") or "") for row in rows}


def _tracked(host: Path) -> set[str]:
    rows = semantic_body(observe_candidate(host).data).get("tracked_paths") or []
    return {str(row.get("path") or "") for row in rows}


class PublishedUpdateTests(unittest.TestCase):
    def test_adopted_published_update_keeps_ready_current(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "base"
        host = Path(tmp.name) / "host"
        _archive(PUBLISHED, base)
        _install(host, base)
        _adopt(host)
        self.assertEqual(snapshot_host(host).host_class, "ESTABLISHED_HOST")
        self.assertTrue(is_client_support_path(host, RULE))
        self.assertTrue(is_client_support_path(host, DEVELOP))
        before_rule = (host / RULE).read_bytes()
        before_adapter = (host / DEVELOP).read_bytes()
        cited = _bind_ready(host, generation=PROJECTION_GENERATION_CURRENT)
        self.assertEqual(observe_candidate(host).digest, cited)
        code = distribution_cli(
            ["update", "--host", str(host), "--distribution", str(REPO)]
        )
        self.assertEqual(code, 0)
        self.assertEqual(verify_consumer_install(host)["status"], "VALID")
        live = observe_candidate(host)
        self.assertEqual(live.digest, cited)
        self.assertEqual(live.data.get("projection_generation"), PROJECTION_GENERATION_CURRENT)
        report = {
            "candidate": {
                "candidate_digest": cited,
                "projection_generation": PROJECTION_GENERATION_CURRENT,
            }
        }
        self.assertTrue(report_usable_for(report, live))
        self.assertTrue(
            _current(host, cited, live.digest, generation=PROJECTION_GENERATION_CURRENT)
        )
        ready, reason = _ready(host, live.digest)
        self.assertTrue(ready, reason)
        self.assertNotIn(RULE, _untracked(host))
        self.assertNotIn(DEVELOP, _untracked(host))
        self.assertNotEqual((host / RULE).read_bytes(), before_rule)
        self.assertNotEqual((host / DEVELOP).read_bytes(), before_adapter)

        stable = live.digest
        _write(host / ".cursor/rules/team.mdc", "human rule\n")
        _write(host / ".cursor/skills/team-notes/SKILL.md", "sibling skill\n")
        _write(host / ".cursor/settings.json", "{}\n")
        self.assertEqual(observe_candidate(host).digest, stable)
        agents = (host / "AGENTS.md").read_text(encoding="utf-8")
        _write(host / "AGENTS.md", agents + "\nHuman note.\n")
        self.assertNotEqual(observe_candidate(host).digest, stable)
        _write(host / "AGENTS.md", agents)
        attrs = (host / ".gitattributes").read_text(encoding="utf-8")
        _write(host / ".gitattributes", attrs + "\n# human attribute\n")
        self.assertNotEqual(observe_candidate(host).digest, stable)
        _write(host / ".gitattributes", attrs)

        _write(host / "README.md", "product changed\n")
        shifted = observe_candidate(host)
        self.assertNotEqual(shifted.digest, live.digest)
        self.assertFalse(report_usable_for(report, shifted))
        self.assertFalse(
            _current(host, cited, shifted.digest, generation=PROJECTION_GENERATION_CURRENT)
        )
        ready, reason = _ready(host, shifted.digest)
        self.assertFalse(ready, reason)

    def test_adopted_tracked_update_keeps_ready_current(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "base"
        host = Path(tmp.name) / "host"
        _archive(PUBLISHED, base)
        _install(host, base)
        _adopt(host)
        _git(host, "add", "-A")
        _git(host, "commit", "-m", "track adopted client support")
        cited = _bind_ready(host, generation=PROJECTION_GENERATION_CURRENT)
        self.assertEqual(observe_candidate(host).digest, cited)
        code = distribution_cli(
            ["update", "--host", str(host), "--distribution", str(REPO)]
        )
        self.assertEqual(code, 0)
        live = observe_candidate(host)
        self.assertEqual(live.digest, cited)
        self.assertEqual(verify_consumer_install(host)["status"], "VALID")
        self.assertTrue(
            _current(host, cited, live.digest, generation=PROJECTION_GENERATION_CURRENT)
        )
        ready, reason = _ready(host, live.digest)
        self.assertTrue(ready, reason)
        self.assertNotIn(RULE, _tracked(host))
        self.assertNotIn(DEVELOP, _tracked(host))

    def test_nonadopted_update_blocks_before_currentness_loss(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name) / "base"
        host = Path(tmp.name) / "host"
        _archive(PUBLISHED, base)
        _install(host, base)
        self.assertFalse(is_client_support_path(host, RULE))
        before_rule = (host / RULE).read_bytes()
        before_adapter = (host / DEVELOP).read_bytes()
        cited = _bind_ready(host)
        pre = observe_candidate(host)
        plan = plan_consumer_install(host, REPO, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        result = apply_consumer_install(plan)
        self.assertEqual(result["outcome"], "BLOCKED", result.get("blockers"))
        self.assertEqual((host / RULE).read_bytes(), before_rule)
        self.assertEqual((host / DEVELOP).read_bytes(), before_adapter)
        self.assertEqual(list(migration_dir(host).glob("*.yaml")), [])
        live = observe_candidate(host)
        self.assertEqual(live.digest, pre.digest)
        self.assertTrue(_current(host, cited, live.digest))
        ready, reason = _ready(host, live.digest)
        self.assertTrue(ready, reason)


class AuthorityBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        _install(self.host, REPO)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unrelated_cursor_human_product_and_agents_stay_visible(self) -> None:
        before = observe_candidate(self.host).digest
        _write(self.host / ".cursor/rules/team.mdc", "human rule\n")
        self.assertIn(".cursor/rules/team.mdc", _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)
        _write(self.host / ".cursor/skills/scaffold-develop/notes.md", "human note\n")
        self.assertIn(".cursor/skills/scaffold-develop/notes.md", _untracked(self.host))
        product = observe_candidate(self.host).digest
        _write(self.host / "README.md", "product changed\n")
        self.assertNotEqual(observe_candidate(self.host).digest, product)
        agents = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        _write(self.host / "AGENTS.md", agents + "\nHuman note.\n")
        self.assertNotEqual(observe_candidate(self.host).digest, product)
        attrs = (self.host / ".gitattributes").read_text(encoding="utf-8")
        _write(self.host / ".gitattributes", attrs + "\n# human attribute\n")
        self.assertNotEqual(observe_candidate(self.host).digest, product)

    def test_adapter_only_stays_visible_and_verify_drifts(self) -> None:
        before = observe_candidate(self.host).digest
        (self.host / DEVELOP).write_bytes((self.host / DEVELOP).read_bytes() + MARKER)
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID")
        self.assertIn(DEVELOP, verify.get("drifted") or [])
        self.assertIn(DEVELOP, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)

    def test_adapter_plus_manifest_digest_stays_visible(self) -> None:
        before = observe_candidate(self.host).digest
        (self.host / DEVELOP).write_bytes((self.host / DEVELOP).read_bytes() + MARKER)
        _rewrite_manifest_digest(self.host, DEVELOP)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify.get("reasons"))
        self.assertIn(DEVELOP, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)

    def test_runtime_generator_only_fails_verify(self) -> None:
        before = observe_candidate(self.host).digest
        runtime = self.host / RUNTIME_INSTALL
        runtime.write_bytes(runtime.read_bytes() + b"\n# runtime-only\n")
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID")
        self.assertIn(RUNTIME_INSTALL, verify.get("drifted") or [])
        self.assertIn(DEVELOP, _untracked(self.host))
        self.assertEqual(observe_candidate(self.host).digest, before)

    def test_runtime_and_adapter_cotamper_stays_visible(self) -> None:
        before = observe_candidate(self.host).digest
        _agree_client_with_runtime(self.host, DEVELOP, RUNTIME_INSTALL)
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID")
        self.assertIn(DEVELOP, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)

    def test_runtime_adapter_and_manifest_cotamper_stays_visible(self) -> None:
        before = observe_candidate(self.host).digest
        _agree_client_with_runtime(self.host, DEVELOP, RUNTIME_INSTALL)
        _rewrite_manifest_digest(self.host, DEVELOP)
        _rewrite_manifest_digest(self.host, RUNTIME_INSTALL)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify.get("reasons"))
        self.assertIn(DEVELOP, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)

    def test_first_use_runtime_and_rule_cotamper_stays_visible(self) -> None:
        before = observe_candidate(self.host).digest
        _agree_client_with_runtime(self.host, RULE, RUNTIME_FIRST_USE)
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID")
        self.assertIn(RULE, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)

    def test_first_use_runtime_rule_and_manifest_cotamper_stays_visible(self) -> None:
        before = observe_candidate(self.host).digest
        _agree_client_with_runtime(self.host, RULE, RUNTIME_FIRST_USE)
        _rewrite_manifest_digest(self.host, RULE)
        _rewrite_manifest_digest(self.host, RUNTIME_FIRST_USE)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify.get("reasons"))
        self.assertIn(RULE, _untracked(self.host))
        self.assertNotEqual(observe_candidate(self.host).digest, before)


class NoScmDeliveryTests(unittest.TestCase):
    def test_agreeing_runtime_bytes_do_not_hide_client_files(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        host = Path(tmp.name) / "host"
        rule = "canonical rule\n"
        adapter = "develop body\n"
        runtime = host / ".scaffold/install/runtime/scaffold_p5"
        runtime.mkdir(parents=True)
        _write(
            runtime / "first_use.py",
            "FIRST_USE_RULE_TEXT = " + repr(rule) + "\n",
        )
        _write(
            runtime / "consumer_install.py",
            "CURSOR_BODIES = {'scaffold-develop': " + repr(adapter) + "}\n",
        )
        _write(host / RULE, rule)
        _write(host / DEVELOP, adapter)
        _write(host / "README.md", "product\n")
        _write(host / ".cursor/rules/team.mdc", "human\n")
        _write(host / "AGENTS.md", "human agents\n")
        current = observe_candidate(host)
        inventory = current.inventory or {}
        self.assertEqual(current.data.get("kind"), "none")
        self.assertIn(RULE, inventory)
        self.assertIn(DEVELOP, inventory)
        self.assertIn("README.md", inventory)
        self.assertIn(".cursor/rules/team.mdc", inventory)
        self.assertIn("AGENTS.md", inventory)
        staged = observe_candidate(host).digest
        _write(host / ".scaffold/transport/develop-intake.json", "{}\n")
        after_staging = observe_candidate(host)
        self.assertIn(
            ".scaffold/transport/develop-intake.json",
            after_staging.inventory or {},
        )
        self.assertNotEqual(after_staging.digest, staged)


if __name__ == "__main__":
    unittest.main()

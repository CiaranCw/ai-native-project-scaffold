from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO

from scaffold_p5.consumer_install import (
    ABS_SCAFFOLD_CHECKOUT_RE,
    CURSOR_ADAPTERS,
    GENERIC_CURSOR_ADAPTER,
    GITATTR_REGION,
    GITATTR_REQUIRED_LINES,
    GITATTRIBUTES,
    OWNERSHIP_MANAGED_REGION,
    OWNERSHIP_WHOLE_FILE,
    apply_consumer_install,
    expected_region_digest,
    load_installed_distribution,
    load_live_distribution,
    manifest_file_map,
    manifest_region_records,
    never_adopted_after_install,
    plan_consumer_install,
    plan_to_public_dict,
    verify_consumer_install,
)
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import file_digest, sha256_bytes
from scaffold_p5.models import CORE_SKILLS as MODEL_CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p5.result import result_dict
from scaffold_p5 import yaml_lite


EXPECTED_PACKAGES = {
    "understand": (
        "2.3.0",
        "869f492a67e10be592f9f1f8f1dd6553a34f0e36e61e8e7c99ad05439fa79cbf",
    ),
    "develop": (
        "2.1.0",
        "25ac19783621d64afff3d250ba1bde73cd4e2264485c0f987824aced3b784e70",
    ),
    "test": (
        "2.0.1",
        "c90af65699a323a1ff3597051f310a12edd8c72583015d7934e17d717a5366f8",
    ),
    "submit": (
        "2.1.0",
        "997cb2dd0273a2ef1625c735bd395b5f6b21e27047298ab2a1f167df73f94f06",
    ),
}

CONSUMER_PILOT = Path(r"F:\NewResearch\Project-City-consumer-pilot")
CANONICAL_PROJECT_CITY = Path(r"F:\NewResearch\Project-City")


def _empty_host(root: Path) -> Path:
    host = root / "host"
    host.mkdir()
    (host / "README.md").write_text("# Sample host\n", encoding="utf-8")
    return host


def _install(host: Path, dist: Path = REPO, mode: str = "install"):
    plan = plan_consumer_install(host, dist, mode=mode)
    if not plan.allowed:
        return plan, {
            "outcome": "BLOCKED",
            "blockers": list(plan.blockers),
        }
    return plan, apply_consumer_install(plan)


def _dry_plan_existing_consumer(host: Path):
    """Plan against an already-installed sibling without mutating it.

    Fresh source identity requires UPDATE, not a second INSTALL.
    """
    plan = plan_consumer_install(host, REPO, mode="install")
    if not plan.allowed and any(
        "use update" in str(item) for item in plan.blockers
    ):
        plan = plan_consumer_install(host, REPO, mode="update")
    return plan


def _clone_host(host: Path, dest: Path) -> Path:
    shutil.copytree(host, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_installed(host: Path, *args: str) -> subprocess.CompletedProcess[str]:
    runner = host / ".scaffold" / "install" / "run.py"
    return subprocess.run(
        [sys.executable, str(runner), *args],
        cwd=str(host),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _copy_live_dist(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "src", dest / "src")
    shutil.copytree(REPO / "skills", dest / "skills")
    shutil.copytree(REPO / "docs", dest / "docs")
    return dest


EXPECTED_CURSOR_ADAPTERS = (
    "scaffold-understand",
    "scaffold-develop",
    "scaffold-test",
    "scaffold-submit",
)


def _cursor_scaffold_adapters(host: Path) -> list[str]:
    root = host / ".cursor" / "skills"
    if not root.is_dir():
        return []
    names = []
    for path in sorted(root.iterdir()):
        if not (path / "SKILL.md").is_file():
            continue
        if path.name == "scaffold" or path.name.startswith("scaffold-"):
            names.append(path.name)
    return names


def _inject_pre_c01_generic_adapter(host: Path) -> None:
    body = (
        "---\n"
        "name: scaffold\n"
        "description: pre-C01 generic Cursor adapter\n"
        "---\n\n"
        "# scaffold\n"
    ).encode("utf-8")
    generic = host / GENERIC_CURSOR_ADAPTER
    generic.parent.mkdir(parents=True, exist_ok=True)
    generic.write_bytes(body)
    manifest_path = host / ".scaffold" / "install" / "install.yaml"
    manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
    files = list(manifest.get("files") or [])
    files.append(
        {
            "path": GENERIC_CURSOR_ADAPTER,
            "digest": sha256_bytes(body),
            "ownership": "MANAGED",
        }
    )
    manifest["files"] = files
    bridges = dict(manifest.get("bridges") or {})
    cursor = [
        str(item).replace("\\", "/")
        for item in (bridges.get("cursor") or [])
        if item
    ]
    if GENERIC_CURSOR_ADAPTER not in cursor:
        cursor.insert(0, GENERIC_CURSOR_ADAPTER)
    bridges["cursor"] = cursor
    manifest["bridges"] = bridges
    manifest_path.write_text(yaml_lite.dump(manifest), encoding="utf-8")


def _smoke_payload(proc: subprocess.CompletedProcess[str]) -> dict:
    combined = (proc.stdout or "") + (proc.stderr or "")
    if "ModuleNotFoundError" in combined or "ImportError" in combined:
        raise AssertionError(combined)
    if str(REPO.resolve()) in combined:
        raise AssertionError(f"operational Distribution path leaked:\n{combined}")
    payload = json.loads(proc.stdout)
    if payload.get("outcome") not in {"COMPLETED", "BLOCKED", "NEEDS_HUMAN"}:
        raise AssertionError(payload)
    return payload


PC_STYLE_GITATTRIBUTES = """* text=auto
*.md text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
"""


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_AUTHOR_NAME"] = "scaffold-c02"
    env["GIT_AUTHOR_EMAIL"] = "scaffold-c02@example.invalid"
    env["GIT_COMMITTER_NAME"] = "scaffold-c02"
    env["GIT_COMMITTER_EMAIL"] = "scaffold-c02@example.invalid"
    env["GIT_AUTHOR_DATE"] = "2026-09-11T00:00:00Z"
    env["GIT_COMMITTER_DATE"] = "2026-09-11T00:00:00Z"
    return env


def _git(host: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(host),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )


def _commit_host(host: Path, autocrlf: str) -> None:
    _git(host, "init")
    _git(host, "config", "core.autocrlf", autocrlf)
    _git(host, "add", "-A")
    _git(host, "commit", "-m", "consumer-install")


def _clone_repo(src: Path, dest: Path, autocrlf: str) -> Path:
    subprocess.run(
        [
            "git",
            "clone",
            "--config",
            f"core.autocrlf={autocrlf}",
            str(src),
            str(dest),
        ],
        env=_git_env(),
        capture_output=True,
        text=True,
        check=True,
    )
    return dest


def _manifest_bytes(host: Path) -> dict[str, str]:
    from scaffold_p5.io_util import read_yaml

    manifest = read_yaml(host / ".scaffold" / "install" / "install.yaml")
    return manifest_file_map(manifest)


def _assert_raw_byte_round_trip(test: unittest.TestCase, before: dict[str, str], clone: Path) -> None:
    after = {}
    drifted = []
    for rel, digest in before.items():
        path = clone / rel
        test.assertTrue(path.is_file(), rel)
        actual = file_digest(path)
        after[rel] = actual
        if actual != digest:
            drifted.append(rel)
    test.assertEqual(drifted, [], drifted)
    test.assertEqual(after, before)


def _simulate_pre_c02(host: Path) -> None:
    gitattr = host / GITATTRIBUTES
    if gitattr.exists():
        gitattr.unlink()
    manifest_path = host / ".scaffold" / "install" / "install.yaml"
    manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [
        row
        for row in (manifest.get("files") or [])
        if not (isinstance(row, dict) and row.get("path") == GITATTRIBUTES)
    ]
    bridges = dict(manifest.get("bridges") or {})
    bridges.pop("gitattributes_region", None)
    manifest["bridges"] = bridges
    manifest["regions"] = [
        row
        for row in (manifest.get("regions") or [])
        if not (isinstance(row, dict) and row.get("path") == GITATTRIBUTES)
    ]
    if not manifest["regions"]:
        manifest.pop("regions", None)
    manifest_path.write_text(yaml_lite.dump(manifest), encoding="utf-8")


def _load_clone_package(clone: Path, skill_id: str):
    runtime = clone / ".scaffold" / "install" / "runtime"
    package = clone / ".scaffold" / "install" / "packages" / skill_id
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(runtime)!r})\n"
        "from scaffold_p5.packages import load_package\n"
        f"pkg = load_package({str(package)!r})\n"
        "print(pkg.ref.skill_version)\n"
        "print(pkg.ref.package_digest)\n"
        "print(pkg.validity)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(clone),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    version, digest, validity = proc.stdout.strip().splitlines()
    return version, digest, validity


class ConsumerInstallationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def test_CI01_install_into_synthetic_project(self):
        plan, result = _install(self.host)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertTrue((self.host / ".scaffold" / "install" / "install.yaml").is_file())
        self.assertTrue((self.host / ".scaffold" / "install" / "run.py").is_file())

    def test_CI02_exact_four_skill_identities(self):
        _install(self.host)
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = load_package(self.host / ".scaffold" / "install" / "packages" / skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)
            src = load_package(REPO / "skills" / skill_id)
            self.assertEqual(pkg.ref.package_digest, src.ref.package_digest, skill_id)

    def test_CI03_and_CI25_runtime_without_distribution_checkout(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "clone")
        proc = _run_installed(clone, "verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "VALID")

    def test_CI04_no_pythonpath_to_source(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "clone")
        proc = _run_installed(clone, "verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_CI05_never_adopted_after_install(self):
        _install(self.host)
        state = never_adopted_after_install(self.host)
        self.assertTrue(state["never_adopted"], state)
        snap = snapshot_host(self.host)
        self.assertEqual(snap.host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        self.assertFalse((self.host / ".scaffold" / "skills.lock").exists())

    def test_CI06_first_use_adoption_starts(self):
        _install(self.host)
        dist = load_installed_distribution(self.host)
        result = UnderstandEngine(self.host, dist).run("bootstrap")
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result_dict(result))
        extras = result.extras or {}
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertEqual(extras.get("host_class"), "NOT_ADOPTED")
        self.assertTrue(extras.get("preview_is_not_approval"))
        self.assertIn("plan", extras)
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())

    def test_CI07_existing_agents_preserved(self):
        original = "# Human project rules\n\nDo not invent product claims.\n"
        (self.host / "AGENTS.md").write_text(original, encoding="utf-8")
        _install(self.host)
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Do not invent product claims.", text)
        self.assertIn("scaffold:managed:scaffold-consumer:start", text)
        self.assertNotIn("This host is managed by AI-Native Project Scaffold.", text)

    def test_CI08_unrelated_agent_skill_preserved(self):
        impeccable = self.host / ".agents" / "skills" / "impeccable" / "SKILL.md"
        impeccable.parent.mkdir(parents=True)
        impeccable.write_text("# impeccable\nkeep me\n", encoding="utf-8")
        _install(self.host)
        self.assertEqual(impeccable.read_text(encoding="utf-8"), "# impeccable\nkeep me\n")
        self.assertFalse((self.host / ".agents" / "skills" / "understand").exists())

    def test_CI09_and_CI10_provenance_and_verify_valid(self):
        _install(self.host)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            self.assertEqual(verify["skills"][skill_id]["skill_version"], version)
            self.assertEqual(verify["skills"][skill_id]["package_digest"], digest)

    def test_CI11_byte_drift_detected(self):
        _install(self.host)
        target = self.host / ".scaffold" / "install" / "runtime" / "scaffold_entry.py"
        target.write_bytes(target.read_bytes() + b"\n# drift\n")
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "DRIFTED", verify)

    def test_CI12_missing_skill_detected(self):
        _install(self.host)
        (self.host / ".scaffold" / "install" / "packages" / "test" / "SKILL.md").unlink()
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPLETE", verify)

    def test_CI13_update_clean_succeeds(self):
        _install(self.host)
        alt = _copy_live_dist(self.tmp / "alt-dist")
        marker = alt / "src" / "scaffold_p5" / "consumer_install.py"
        marker.write_bytes(marker.read_bytes() + b"\n# alt-runtime\n")
        plan, result = _install(self.host, alt, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertIn(b"# alt-runtime", (self.host / ".scaffold" / "install" / "runtime" / "scaffold_p5" / "consumer_install.py").read_bytes())

    def test_CI14_update_preserves_human_files(self):
        notes = self.host / "docs" / "notes.md"
        notes.parent.mkdir()
        notes.write_text("human notes\n", encoding="utf-8")
        impeccable = self.host / ".agents" / "skills" / "impeccable" / "SKILL.md"
        impeccable.parent.mkdir(parents=True)
        impeccable.write_text("keep\n", encoding="utf-8")
        _install(self.host)
        plan, result = _install(self.host, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertEqual(notes.read_text(encoding="utf-8"), "human notes\n")
        self.assertEqual(impeccable.read_text(encoding="utf-8"), "keep\n")

    def test_CI15_update_fails_closed_on_drift(self):
        _install(self.host)
        target = self.host / ".scaffold" / "install" / "run.py"
        target.write_bytes(target.read_bytes() + b"\n# tamper\n")
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertFalse(plan.allowed)
        self.assertTrue(any("drift" in item for item in plan.blockers))

    def test_CI16_reinstall_idempotent(self):
        _install(self.host)
        before = {
            path.relative_to(self.host).as_posix(): path.read_bytes()
            for path in self.host.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        _install(self.host)
        after = {
            path.relative_to(self.host).as_posix(): path.read_bytes()
            for path in self.host.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(before, after)

    def test_CI17_unsafe_targets_rejected(self):
        file_host = self.tmp / "not-a-dir"
        file_host.write_text("x", encoding="utf-8")
        plan = plan_consumer_install(file_host, REPO)
        self.assertFalse(plan.allowed)
        plan = plan_consumer_install(REPO, REPO)
        self.assertFalse(plan.allowed)
        missing = self.tmp / "missing-host"
        plan = plan_consumer_install(missing, REPO)
        self.assertFalse(plan.allowed)

    def test_CI18_source_digest_mismatch_blocks_install(self):
        dist = _copy_live_dist(self.tmp / "bad-dist")
        releases = dist / "releases"
        releases.mkdir()
        understand = load_package(dist / "skills" / "understand")
        body = {
            "release_id": "installed",
            "schema_version": "1",
            "core": {},
        }
        from scaffold_p5.packages import load_package as lp
        from scaffold_p5 import yaml_lite
        from scaffold_p5.io_util import write_text_atomic

        core = {}
        for skill_id in MODEL_CORE_SKILLS:
            pkg = lp(dist / "skills" / skill_id)
            digest = pkg.ref.package_digest
            if skill_id == "understand":
                digest = "0" * 64
            core[skill_id] = {
                "skill_id": skill_id,
                "skill_version": pkg.ref.skill_version,
                "package_digest": digest,
                "package_format_version": pkg.ref.package_format_version,
            }
        body["core"] = core
        write_text_atomic(releases / "installed.yaml", yaml_lite.dump(body))
        plan = plan_consumer_install(self.host, dist)
        self.assertFalse(plan.allowed)
        self.assertTrue(any("digest mismatch" in item for item in plan.blockers))

    def test_CI19_no_cache_or_tests_installed(self):
        _install(self.host)
        files = [
            path.relative_to(self.host).as_posix()
            for path in (self.host / ".scaffold" / "install").rglob("*")
            if path.is_file()
        ]
        self.assertFalse(any("__pycache__" in item or item.endswith(".pyc") for item in files))
        self.assertFalse(any("/tests/" in item or item.endswith("test_consumer_installation.py") for item in files))
        self.assertFalse(any("FREEZE.json" in item or item.endswith(".zip") for item in files))

    def test_CI20_no_operational_absolute_source_path(self):
        _install(self.host)
        hits = []
        for path in (self.host / ".scaffold" / "install").rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            if ABS_SCAFFOLD_CHECKOUT_RE.search(text):
                hits.append(path.as_posix())
        self.assertEqual(hits, [])
        self.assertNotIn(str(REPO.resolve()), (self.host / ".scaffold" / "install" / "run.py").read_text(encoding="utf-8"))

    def test_CI21_cursor_discovery_representation(self):
        _install(self.host)
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        for name in EXPECTED_CURSOR_ADAPTERS:
            path = self.host / ".cursor" / "skills" / name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            self.assertIn(f"name: {name}", text)
            self.assertIn(".scaffold/install/packages/", text)
            self.assertIn("python .scaffold/install/run.py", text)
            self.assertNotIn("disable-model-invocation: true", text)

    def test_CI24_commit_clone_suitable(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "git-clone")
        self.assertTrue((clone / ".scaffold" / "install" / "install.yaml").is_file())
        self.assertEqual(verify_consumer_install(clone)["status"], "VALID")

    def test_CI26_install_does_not_conflict_with_adoption_authority(self):
        _install(self.host)
        self.assertFalse((self.host / ".scaffold" / "skills.lock").exists())
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        from scaffold_p5.io_util import read_yaml

        manifest = read_yaml(self.host / ".scaffold" / "install" / "install.yaml")
        self.assertIn("skills.lock", str(manifest.get("skills_lock_relationship") or ""))
        self.assertEqual(manifest.get("kind"), "scaffold_consumer_install")

    def test_CI27_skills_lock_semantics_not_duplicated(self):
        _install(self.host)
        from scaffold_p5.io_util import read_yaml

        manifest = read_yaml(self.host / ".scaffold" / "install" / "install.yaml")
        self.assertNotIn("authoritative", manifest)
        self.assertNotEqual(manifest.get("kind"), "skills.lock")
        lock_path = self.host / ".scaffold" / "skills.lock"
        self.assertFalse(lock_path.exists())

    def test_CI28_exactly_four_skills_no_fifth(self):
        self.assertEqual(tuple(MODEL_CORE_SKILLS), ("understand", "develop", "test", "submit"))
        self.assertFalse((REPO / "skills" / "install").exists())
        self.assertFalse((REPO / "skills" / "consumer").exists())
        _install(self.host)
        installed = sorted(
            path.name
            for path in (self.host / ".scaffold" / "install" / "packages").iterdir()
            if path.is_dir()
        )
        self.assertEqual(installed, ["develop", "submit", "test", "understand"])

    def test_CI06_subprocess_first_use_without_source(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "first-use")
        proc = _run_installed(clone, "understand", "bootstrap")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN")
        self.assertFalse((clone / ".scaffold" / "project.yaml").exists())


class ProjectCityDryInstallTests(unittest.TestCase):
    def test_CI22_CI23_project_city_dry_install_plan(self):
        if not CONSUMER_PILOT.is_dir():
            self.skipTest("consumer-pilot workspace is not present")
        impeccable = CONSUMER_PILOT / ".agents" / "skills" / "impeccable" / "SKILL.md"
        self.assertTrue(impeccable.is_file())
        agents = (CONSUMER_PILOT / "AGENTS.md").read_text(encoding="utf-8")
        original_attrs = (CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8")
        plan = _dry_plan_existing_consumer(CONSUMER_PILOT)
        public = plan_to_public_dict(plan)
        self.assertTrue(plan.allowed, public)
        self.assertNotIn(".agents/skills/impeccable/SKILL.md", public["added"])
        self.assertNotIn(".agents/skills/impeccable/SKILL.md", public["modified"])
        self.assertEqual(public["agents_md"]["whole_file_replace"], False)
        self.assertTrue(public["agents_md"]["human_body_preserved"])
        self.assertIn("AGENTS.md", public["modified"] + public["unchanged"] + public["added"])
        self.assertIn("PZ", agents)
        self.assertEqual((CONSUMER_PILOT / "AGENTS.md").read_text(encoding="utf-8"), agents)
        self.assertTrue(impeccable.is_file())
        self.assertFalse(CANONICAL_PROJECT_CITY.joinpath(".scaffold", "install").exists())
        self.assertEqual(
            public["bridges"]["cursor"],
            [f".cursor/skills/{name}/SKILL.md" for name in EXPECTED_CURSOR_ADAPTERS],
        )
        planned = public["added"] + public["modified"] + public["unchanged"] + public["removed"]
        self.assertNotIn(GENERIC_CURSOR_ADAPTER, planned)
        self.assertFalse(
            any(
                item == ".cursor/skills/scaffold"
                or item.startswith(".cursor/skills/scaffold/")
                for item in planned
            )
        )
        self.assertEqual(len(public["bridges"]["cursor"]), 4)
        self.assertEqual(public["bridges"]["gitattributes_region"], GITATTR_REGION)
        self.assertEqual(public["gitattributes"]["whole_file_replace"], False)
        self.assertTrue(public["gitattributes"]["human_body_preserved"])
        gitattr_row = next(row for row in plan.files if row.rel == GITATTRIBUTES)
        gitattr_text = gitattr_row.data.decode("utf-8")
        self.assertIn("* text=auto", gitattr_text)
        self.assertIn("*.md text eol=lf", gitattr_text)
        self.assertIn("*.ps1 text eol=crlf", gitattr_text)
        self.assertIn(f"scaffold:managed:{GITATTR_REGION}:start", gitattr_text)
        self.assertTrue(
            gitattr_text.rstrip().endswith(f"scaffold:managed:{GITATTR_REGION}:end")
        )
        self.assertIn(".gitattributes", public["modified"] + public["added"] + public["unchanged"])
        self.assertEqual((CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8"), original_attrs)


class ConsumerInstallationC01Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def test_CIC01_01_cursor_adapter_count_is_exactly_four(self):
        _install(self.host)
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertEqual(list(CURSOR_ADAPTERS), list(EXPECTED_CURSOR_ADAPTERS))

    def test_CIC01_02_generic_cursor_skill_absent(self):
        _install(self.host)
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        self.assertFalse((self.host / ".cursor" / "skills" / "scaffold").exists())

    def test_CIC01_03_canonical_skill_package_count_is_exactly_four(self):
        _install(self.host)
        installed = sorted(
            path.name
            for path in (self.host / ".scaffold" / "install" / "packages").iterdir()
            if path.is_dir()
        )
        self.assertEqual(installed, ["develop", "submit", "test", "understand"])
        self.assertEqual(tuple(MODEL_CORE_SKILLS), ("understand", "develop", "test", "submit"))

    def test_CIC01_04_agents_region_first_use_understand_routing(self):
        _install(self.host)
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("scaffold:managed:scaffold-consumer:start", text)
        self.assertIn("Scaffold is installed", text)
        self.assertIn("Installation is not Adoption", text)
        self.assertIn("Understand bootstrap", text)
        self.assertIn("python .scaffold/install/run.py", text)
        self.assertIn("Exactly four Skills exist", text)
        self.assertIn("first-contact routing", text)
        self.assertNotIn(".cursor/skills/scaffold/SKILL.md", text)

    def test_CIC01_05_existing_agents_human_content_preserved(self):
        original = "# Human project rules\n\nKeep this human sentence.\n"
        (self.host / "AGENTS.md").write_text(original, encoding="utf-8")
        _install(self.host)
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Keep this human sentence.", text)
        self.assertTrue(text.startswith("# Human project rules"))
        self.assertIn("scaffold:managed:scaffold-consumer:start", text)
        self.assertNotIn("This host is managed by AI-Native Project Scaffold.", text)

    def test_CIC01_06_unrelated_impeccable_untouched(self):
        impeccable = self.host / ".agents" / "skills" / "impeccable" / "SKILL.md"
        impeccable.parent.mkdir(parents=True)
        impeccable.write_text("# impeccable\nkeep me\n", encoding="utf-8")
        _install(self.host)
        self.assertEqual(impeccable.read_text(encoding="utf-8"), "# impeccable\nkeep me\n")
        self.assertNotIn("impeccable", _cursor_scaffold_adapters(self.host))

    def test_CIC01_07_verify_accepts_four_adapter_installation(self):
        _install(self.host)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)
        from scaffold_p5.io_util import read_yaml

        manifest = read_yaml(self.host / ".scaffold" / "install" / "install.yaml")
        self.assertEqual(
            manifest["bridges"]["cursor"],
            [f".cursor/skills/{name}/SKILL.md" for name in EXPECTED_CURSOR_ADAPTERS],
        )

    def test_CIC01_08_update_removes_only_obsolete_managed_generic_adapter(self):
        impeccable = self.host / ".agents" / "skills" / "impeccable" / "SKILL.md"
        impeccable.parent.mkdir(parents=True)
        impeccable.write_text("keep\n", encoding="utf-8")
        unrelated = self.host / ".cursor" / "skills" / "other-skill" / "SKILL.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("# other\n", encoding="utf-8")
        _install(self.host)
        _inject_pre_c01_generic_adapter(self.host)
        self.assertTrue((self.host / GENERIC_CURSOR_ADAPTER).is_file())
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPATIBLE", verify)
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertIn(GENERIC_CURSOR_ADAPTER, plan.removed)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        self.assertFalse((self.host / ".cursor" / "skills" / "scaffold").exists())
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertEqual(impeccable.read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "# other\n")
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC01_09_recloned_host_works_without_distribution(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "clone")
        proc = _run_installed(clone, "verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "VALID")
        self.assertNotIn(str(REPO.resolve()), proc.stdout + proc.stderr)

    def test_CIC01_10_installed_understand_runtime_smoke(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "understand-smoke")
        proc = _run_installed(clone, "understand", "bootstrap")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = _smoke_payload(proc)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN")
        self.assertEqual(payload.get("skill_id"), "understand")
        self.assertFalse((clone / ".scaffold" / "project.yaml").exists())

    def test_CIC01_11_installed_develop_runtime_smoke(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "develop-smoke")
        proc = _run_installed(clone, "develop")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = _smoke_payload(proc)
        self.assertEqual(payload.get("skill_id"), "develop")
        self.assertEqual(payload.get("skill_version"), EXPECTED_PACKAGES["develop"][0])

    def test_CIC01_12_installed_test_runtime_smoke(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "test-smoke")
        proc = _run_installed(clone, "test")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = _smoke_payload(proc)
        self.assertEqual(payload.get("skill_id"), "test")
        self.assertEqual(payload.get("skill_version"), EXPECTED_PACKAGES["test"][0])

    def test_CIC01_13_installed_submit_runtime_smoke(self):
        _install(self.host)
        clone = _clone_host(self.host, self.tmp / "submit-smoke")
        proc = _run_installed(clone, "submit")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = _smoke_payload(proc)
        self.assertEqual(payload.get("skill_id"), "submit")
        self.assertEqual(payload.get("skill_version"), EXPECTED_PACKAGES["submit"][0])

    def test_CIC01_14_no_fifth_canonical_or_core_skill(self):
        self.assertEqual(tuple(MODEL_CORE_SKILLS), ("understand", "develop", "test", "submit"))
        for name in ("install", "consumer", "repair", "bootstrap", "scaffold"):
            self.assertFalse((REPO / "skills" / name).exists(), name)
        _install(self.host)
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertFalse((self.host / ".scaffold" / "install" / "packages" / "scaffold").exists())


class ConsumerInstallationC02GitRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def _round_trip(self, autocrlf: str, host_attrs: str | None = None) -> Path:
        if host_attrs is not None:
            (self.host / GITATTRIBUTES).write_text(host_attrs, encoding="utf-8")
        plan, result = _install(self.host)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        before = _manifest_bytes(self.host)
        _commit_host(self.host, autocrlf)
        clone = _clone_repo(self.host, self.tmp / f"clone-{autocrlf}-{id(host_attrs)}", autocrlf)
        verify = verify_consumer_install(clone)
        self.assertEqual(verify["status"], "VALID", verify)
        self.assertEqual(verify.get("missing"), [])
        self.assertEqual(verify.get("drifted"), [])
        _assert_raw_byte_round_trip(self, before, clone)
        return clone

    def test_CIC02_01_install_carries_clone_stability_authority(self):
        _install(self.host)
        text = (self.host / GITATTRIBUTES).read_text(encoding="utf-8")
        self.assertIn(f"scaffold:managed:{GITATTR_REGION}:start", text)
        for line in GITATTR_REQUIRED_LINES:
            self.assertIn(line, text)
        from scaffold_p5.io_util import read_yaml

        manifest = read_yaml(self.host / ".scaffold" / "install" / "install.yaml")
        self.assertEqual(manifest["bridges"]["gitattributes_region"], GITATTR_REGION)
        records = manifest_region_records(manifest)
        self.assertTrue(
            any(
                row["path"] == GITATTRIBUTES
                and row["ownership"] == OWNERSHIP_MANAGED_REGION
                and row["region_id"] == GITATTR_REGION
                for row in records
            ),
            records,
        )
        self.assertNotIn(GITATTRIBUTES, manifest_file_map(manifest))
        self.assertNotIn("AGENTS.md", manifest_file_map(manifest))

    def test_CIC02_02_existing_human_gitattributes_preserved(self):
        original = "* text=auto\n*.md text eol=lf\n# keep this human rule\n"
        (self.host / GITATTRIBUTES).write_text(original, encoding="utf-8")
        _install(self.host)
        text = (self.host / GITATTRIBUTES).read_text(encoding="utf-8")
        self.assertIn("* text=auto", text)
        self.assertIn("*.md text eol=lf", text)
        self.assertIn("# keep this human rule", text)
        self.assertIn(f"scaffold:managed:{GITATTR_REGION}:start", text)
        self.assertTrue(text.rstrip().endswith(f"scaffold:managed:{GITATTR_REGION}:end"))

    def test_CIC02_03_project_city_style_text_auto_does_not_rewrite(self):
        self._round_trip("true", host_attrs=PC_STYLE_GITATTRIBUTES)

    def test_CIC02_04_autocrlf_true_clone_verify_valid(self):
        self._round_trip("true")

    def test_CIC02_05_autocrlf_input_clone_verify_valid(self):
        self._round_trip("input")

    def test_CIC02_06_autocrlf_false_clone_verify_valid(self):
        self._round_trip("false")

    def test_CIC02_07_all_manifest_sha256_equal_post_clone(self):
        clone = self._round_trip("true", host_attrs=PC_STYLE_GITATTRIBUTES)
        before = _manifest_bytes(self.host)
        _assert_raw_byte_round_trip(self, before, clone)

    def test_CIC02_08_skill_identities_survive_clone(self):
        clone = self._round_trip("true")
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            actual_version, actual_digest, validity = _load_clone_package(clone, skill_id)
            self.assertEqual(actual_version, version, skill_id)
            self.assertEqual(actual_digest, digest, skill_id)
            self.assertEqual(validity, "VALID", skill_id)

    def test_CIC02_09_missing_git_attribute_policy_detected(self):
        _install(self.host)
        (self.host / GITATTRIBUTES).unlink()
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPLETE", verify)
        self.assertIn(GITATTRIBUTES, verify["missing"])

    def test_CIC02_10_drifted_malformed_policy_fails_closed(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(path.read_text(encoding="utf-8").replace("-text", "text"), encoding="utf-8")
        verify = verify_consumer_install(self.host)
        self.assertIn(verify["status"], {"DRIFTED", "INCOMPATIBLE"}, verify)
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertFalse(plan.allowed)
        broken_root = self.tmp / "broken"
        broken_root.mkdir()
        broken = _empty_host(broken_root)
        (broken / GITATTRIBUTES).write_text(
            "# scaffold:managed:scaffold-consumer-git:start\n* text=auto\n",
            encoding="utf-8",
        )
        plan = plan_consumer_install(broken, REPO, mode="install")
        self.assertFalse(plan.allowed)
        self.assertTrue(any("gitattributes" in item.lower() for item in plan.blockers))

    def test_CIC02_11_update_upgrades_pre_c02_installation(self):
        _install(self.host)
        _simulate_pre_c02(self.host)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPLETE", verify)
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")
        self.assertTrue((self.host / GITATTRIBUTES).is_file())
        clone = self.tmp / "pre-c02-updated-clone"
        _commit_host(self.host, "true")
        _clone_repo(self.host, clone, "true")
        self.assertEqual(verify_consumer_install(clone)["status"], "VALID")

    def test_CIC02_12_update_preserves_human_gitattributes_rules(self):
        original = "* text=auto\n*.md text eol=lf\n# human keep\n"
        (self.host / GITATTRIBUTES).write_text(original, encoding="utf-8")
        _install(self.host)
        _simulate_pre_c02(self.host)
        (self.host / GITATTRIBUTES).write_text(original, encoding="utf-8")
        plan, result = _install(self.host, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        text = (self.host / GITATTRIBUTES).read_text(encoding="utf-8")
        self.assertIn("# human keep", text)
        self.assertIn("* text=auto", text)
        self.assertIn(f"scaffold:managed:{GITATTR_REGION}:start", text)

    def test_CIC02_13_agents_integration_unchanged(self):
        original = "# Human project rules\n\nKeep this human sentence.\n"
        (self.host / "AGENTS.md").write_text(original, encoding="utf-8")
        _install(self.host)
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Keep this human sentence.", text)
        self.assertIn("scaffold:managed:scaffold-consumer:start", text)
        self.assertIn("Understand bootstrap", text)

    def test_CIC02_14_four_cursor_adapters_remain(self):
        _install(self.host)
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())

    def test_CIC02_15_self_contained_runtime_after_clone(self):
        clone = self._round_trip("true")
        proc = _run_installed(clone, "verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "VALID")
        understand = _smoke_payload(_run_installed(clone, "understand", "bootstrap"))
        self.assertEqual(understand["outcome"], "NEEDS_HUMAN")
        develop = _smoke_payload(_run_installed(clone, "develop"))
        self.assertEqual(develop["outcome"], "BLOCKED")
        test = _smoke_payload(_run_installed(clone, "test"))
        self.assertEqual(test["outcome"], "BLOCKED")
        submit = _smoke_payload(_run_installed(clone, "submit"))
        self.assertEqual(submit["outcome"], "BLOCKED")
        self.assertFalse((clone / ".scaffold" / "project.yaml").exists())

    def test_CIC02_16_no_absolute_distribution_path(self):
        _install(self.host)
        hits = []
        for path in list((self.host / ".scaffold" / "install").rglob("*")) + [
            self.host / GITATTRIBUTES,
            self.host / "AGENTS.md",
        ]:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            if ABS_SCAFFOLD_CHECKOUT_RE.search(text):
                hits.append(path.as_posix())
        self.assertEqual(hits, [])

    def test_CIC02_17_project_city_dry_run_conflict_free(self):
        if not CONSUMER_PILOT.is_dir():
            self.skipTest("consumer-pilot workspace is not present")
        attrs = (CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8")
        plan = _dry_plan_existing_consumer(CONSUMER_PILOT)
        public = plan_to_public_dict(plan)
        self.assertTrue(plan.allowed, public)
        self.assertTrue(public["gitattributes"]["human_body_preserved"])
        self.assertFalse(public["gitattributes"]["whole_file_replace"])
        self.assertEqual((CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8"), attrs)
        self.assertFalse(CANONICAL_PROJECT_CITY.joinpath(".scaffold", "install").exists())

    def test_CIC02_18_reinstall_idempotent(self):
        _install(self.host)
        before = {
            path.relative_to(self.host).as_posix(): path.read_bytes()
            for path in self.host.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        _install(self.host)
        after = {
            path.relative_to(self.host).as_posix(): path.read_bytes()
            for path in self.host.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }
        self.assertEqual(before, after)


def _simulate_c02_whole_file_provenance(host: Path) -> None:
    """Rewrite a C03 install.yaml into C02 whole-file MANAGED provenance."""
    manifest_path = host / ".scaffold" / "install" / "install.yaml"
    manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
    files = [
        row
        for row in (manifest.get("files") or [])
        if not (
            isinstance(row, dict)
            and str(row.get("path") or "").replace("\\", "/")
            in {"AGENTS.md", GITATTRIBUTES}
        )
    ]
    for rel in ("AGENTS.md", GITATTRIBUTES):
        path = host / rel
        if not path.is_file():
            continue
        files.append(
            {
                "path": rel,
                "digest": sha256_bytes(path.read_bytes()),
                "ownership": "MANAGED",
            }
        )
    files.sort(key=lambda row: str(row.get("path") or ""))
    manifest["files"] = files
    manifest.pop("regions", None)
    manifest_path.write_text(yaml_lite.dump(manifest), encoding="utf-8")


def _insert_before_marker(text: str, marker: str, insertion: str) -> str:
    index = text.index(marker)
    return text[:index] + insertion + text[index:]


def _insert_after_marker(text: str, marker: str, insertion: str) -> str:
    index = text.index(marker) + len(marker)
    return text[:index] + insertion + text[index:]


def _replace_inside_markers(text: str, start: str, end: str, old: str, new: str) -> str:
    begin = text.index(start)
    stop = text.index(end, begin)
    inner = text[begin:stop]
    if old not in inner:
        raise AssertionError(f"{old!r} not in managed region")
    return text[:begin] + inner.replace(old, new, 1) + text[stop:]


AGENTS_START = "<!-- scaffold:managed:scaffold-consumer:start -->"
AGENTS_END = "<!-- scaffold:managed:scaffold-consumer:end -->"
GITATTR_START = "# scaffold:managed:scaffold-consumer-git:start"
GITATTR_END = "# scaffold:managed:scaffold-consumer-git:end"
HUMAN_AGENTS_RULE = "Team rule: use deterministic save-game fixtures."
HUMAN_GITATTR_RULE = "*.fbx -text"


class ConsumerInstallationC03RegionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def _manifest(self) -> dict:
        from scaffold_p5.io_util import read_yaml

        return read_yaml(self.host / ".scaffold" / "install" / "install.yaml")

    def test_CIC03_01_agents_human_edit_outside_region_verify_valid(self):
        _install(self.host)
        path = self.host / "AGENTS.md"
        path.write_text(
            _insert_before_marker(path.read_text(encoding="utf-8"), AGENTS_START, HUMAN_AGENTS_RULE + "\n\n"),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)
        self.assertNotIn("AGENTS.md", verify.get("drifted") or [])

    def test_CIC03_02_agents_human_edit_update_preserves(self):
        _install(self.host)
        path = self.host / "AGENTS.md"
        path.write_text(
            _insert_before_marker(path.read_text(encoding="utf-8"), AGENTS_START, HUMAN_AGENTS_RULE + "\n\n"),
            encoding="utf-8",
        )
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        text = path.read_text(encoding="utf-8")
        self.assertIn(HUMAN_AGENTS_RULE, text)
        self.assertIn(AGENTS_START, text)
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_03_agents_managed_region_edit_fails_closed(self):
        _install(self.host)
        path = self.host / "AGENTS.md"
        path.write_text(
            _replace_inside_markers(
                path.read_text(encoding="utf-8"),
                AGENTS_START,
                AGENTS_END,
                "Exactly four Skills exist",
                "Exactly five Skills exist",
            ),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID", verify)
        self.assertIn("AGENTS.md", verify.get("drifted") or [])
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertFalse(plan.allowed)
        self.assertTrue(any("drift" in item for item in plan.blockers))

    def test_CIC03_04_gitattributes_human_rule_outside_region_verify_valid(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _insert_before_marker(
                path.read_text(encoding="utf-8"),
                GITATTR_START,
                HUMAN_GITATTR_RULE + "\n",
            ),
            encoding="utf-8",
        )
        _git(self.host, "init")
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)
        self.assertNotIn(GITATTRIBUTES, verify.get("drifted") or [])
        check = _git(
            self.host,
            "check-attr",
            "text",
            "--",
            ".scaffold/install/run.py",
            "AGENTS.md",
            GITATTRIBUTES,
        )
        for line in check.stdout.splitlines():
            if ": text: " in line:
                self.assertTrue(line.endswith(": unset"), line)

    def test_CIC03_05_gitattributes_human_rule_survives_update(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _insert_before_marker(
                path.read_text(encoding="utf-8"),
                GITATTR_START,
                HUMAN_GITATTR_RULE + "\n",
            ),
            encoding="utf-8",
        )
        plan, result = _install(self.host, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        text = path.read_text(encoding="utf-8")
        self.assertIn(HUMAN_GITATTR_RULE, text)
        self.assertTrue(text.rstrip().endswith("scaffold:managed:scaffold-consumer-git:end"))
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_06_gitattributes_managed_region_edit_fails_closed(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _replace_inside_markers(
                path.read_text(encoding="utf-8"),
                GITATTR_START,
                GITATTR_END,
                ".scaffold/install/** -text",
                ".scaffold/install/** text",
            ),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID", verify)
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertFalse(plan.allowed)

    def test_CIC03_07_later_human_git_rule_cannot_silently_override(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _insert_after_marker(
                path.read_text(encoding="utf-8"),
                GITATTR_END,
                "\n*.md text eol=lf\n",
            ),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPATIBLE", verify)
        self.assertTrue(
            any("later rules can override" in item for item in verify.get("reasons") or []),
            verify,
        )

    def test_CIC03_08_update_restores_region_last_without_deleting_human_rule(self):
        _install(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _insert_after_marker(
                path.read_text(encoding="utf-8"),
                GITATTR_END,
                "\n*.md text eol=lf\n",
            ),
            encoding="utf-8",
        )
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        text = path.read_text(encoding="utf-8")
        self.assertIn("*.md text eol=lf", text)
        self.assertTrue(text.rstrip().endswith("scaffold:managed:scaffold-consumer-git:end"))
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_09_manifest_distinguishes_whole_file_and_region(self):
        _install(self.host)
        manifest = self._manifest()
        files = manifest_file_map(manifest)
        self.assertNotIn("AGENTS.md", files)
        self.assertNotIn(GITATTRIBUTES, files)
        self.assertTrue(files)
        self.assertTrue(all(
            isinstance(row, dict) and row.get("ownership") == OWNERSHIP_WHOLE_FILE
            for row in (manifest.get("files") or [])
        ))
        records = {row["path"]: row for row in manifest_region_records(manifest)}
        self.assertEqual(records["AGENTS.md"]["ownership"], OWNERSHIP_MANAGED_REGION)
        self.assertEqual(records["AGENTS.md"]["region_id"], "scaffold-consumer")
        self.assertEqual(records[GITATTRIBUTES]["ownership"], OWNERSHIP_MANAGED_REGION)
        self.assertEqual(records[GITATTRIBUTES]["region_id"], GITATTR_REGION)

    def test_CIC03_10_whole_file_runtime_adapters_use_raw_sha256(self):
        _install(self.host)
        files = manifest_file_map(self._manifest())
        for rel, digest in files.items():
            self.assertEqual(file_digest(self.host / rel), digest, rel)
        for adapter in EXPECTED_CURSOR_ADAPTERS:
            rel = f".cursor/skills/{adapter}/SKILL.md"
            self.assertIn(rel, files)
            self.assertEqual(file_digest(self.host / rel), files[rel])
        self.assertIn(".scaffold/install/run.py", files)

    def test_CIC03_11_clean_c02_install_migrates_to_c03_provenance(self):
        _install(self.host)
        _simulate_c02_whole_file_provenance(self.host)
        c02 = self._manifest()
        self.assertIn("AGENTS.md", [row.get("path") for row in (c02.get("files") or [])])
        self.assertFalse(manifest_region_records(c02))
        plan, result = _install(self.host, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        manifest = self._manifest()
        self.assertNotIn("AGENTS.md", manifest_file_map(manifest))
        self.assertNotIn(GITATTRIBUTES, manifest_file_map(manifest))
        records = {row["path"]: row for row in manifest_region_records(manifest)}
        self.assertEqual(records["AGENTS.md"]["digest"], expected_region_digest("AGENTS.md"))
        self.assertEqual(records[GITATTRIBUTES]["digest"], expected_region_digest(GITATTRIBUTES))
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_12_c02_human_agents_edit_can_migrate(self):
        _install(self.host)
        _simulate_c02_whole_file_provenance(self.host)
        path = self.host / "AGENTS.md"
        path.write_text(
            _insert_before_marker(path.read_text(encoding="utf-8"), AGENTS_START, HUMAN_AGENTS_RULE + "\n\n"),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertIn(HUMAN_AGENTS_RULE, path.read_text(encoding="utf-8"))
        self.assertTrue(manifest_region_records(self._manifest()))
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_13_c02_human_gitattributes_edit_can_migrate(self):
        _install(self.host)
        _simulate_c02_whole_file_provenance(self.host)
        path = self.host / GITATTRIBUTES
        path.write_text(
            _insert_after_marker(
                path.read_text(encoding="utf-8"),
                GITATTR_END,
                "\n" + HUMAN_GITATTR_RULE + "\n",
            ),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPATIBLE", verify)
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        text = path.read_text(encoding="utf-8")
        self.assertIn(HUMAN_GITATTR_RULE, text)
        self.assertTrue(text.rstrip().endswith("scaffold:managed:scaffold-consumer-git:end"))
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")

    def test_CIC03_14_c02_region_tamper_cannot_migrate(self):
        _install(self.host)
        _simulate_c02_whole_file_provenance(self.host)
        path = self.host / "AGENTS.md"
        path.write_text(
            _replace_inside_markers(
                path.read_text(encoding="utf-8"),
                AGENTS_START,
                AGENTS_END,
                "Installation is not Adoption",
                "Installation is secretly Adoption",
            ),
            encoding="utf-8",
        )
        verify = verify_consumer_install(self.host)
        self.assertNotEqual(verify["status"], "VALID", verify)
        plan = plan_consumer_install(self.host, REPO, mode="update")
        self.assertFalse(plan.allowed)

    def test_CIC03_15_reduced_git_round_trip_matrix_valid(self):
        cases = (
            ("true", None),
            ("input", None),
            ("true", PC_STYLE_GITATTRIBUTES),
        )
        for autocrlf, attrs in cases:
            with self.subTest(autocrlf=autocrlf, attrs=bool(attrs)):
                root_dir = self.tmp / f"rt-{autocrlf}-{id(attrs)}"
                root_dir.mkdir()
                root = _empty_host(root_dir)
                if attrs is not None:
                    (root / GITATTRIBUTES).write_text(attrs, encoding="utf-8")
                _install(root)
                if attrs is not None:
                    self.assertIn("* text=auto", (root / GITATTRIBUTES).read_text(encoding="utf-8"))
                before_files = manifest_file_map(
                    yaml_lite.load(
                        (root / ".scaffold" / "install" / "install.yaml").read_text(encoding="utf-8")
                    )
                )
                agents_before = (root / "AGENTS.md").read_bytes()
                gitattr_before = (root / GITATTRIBUTES).read_bytes()
                _commit_host(root, autocrlf)
                clone = _clone_repo(root, self.tmp / f"clone-{autocrlf}-{id(attrs)}", autocrlf)
                verify = verify_consumer_install(clone)
                self.assertEqual(verify["status"], "VALID", verify)
                for rel, digest in before_files.items():
                    self.assertEqual(file_digest(clone / rel), digest, rel)
                self.assertEqual((clone / "AGENTS.md").read_bytes(), agents_before)
                self.assertEqual((clone / GITATTRIBUTES).read_bytes(), gitattr_before)
                self.assertEqual(
                    expected_region_digest("AGENTS.md"),
                    _live_region_digest(clone, "AGENTS.md"),
                )
                self.assertEqual(
                    expected_region_digest(GITATTRIBUTES),
                    _live_region_digest(clone, GITATTRIBUTES),
                )

    def test_CIC03_16_skill_identities_unchanged(self):
        _install(self.host)
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "id-clone", "true")
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            actual_version, actual_digest, validity = _load_clone_package(clone, skill_id)
            self.assertEqual(actual_version, version, skill_id)
            self.assertEqual(actual_digest, digest, skill_id)
            self.assertEqual(validity, "VALID", skill_id)

    def test_CIC03_17_exact_four_skill_adapters_unchanged(self):
        _install(self.host)
        self.assertEqual(_cursor_scaffold_adapters(self.host), sorted(EXPECTED_CURSOR_ADAPTERS))
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        public = plan_to_public_dict(plan_consumer_install(self.host, REPO, mode="install"))
        self.assertEqual(len(public["bridges"]["cursor"]), 4)

    def test_CIC03_18_project_city_dry_run_conflict_free(self):
        if not CONSUMER_PILOT.is_dir():
            self.skipTest("consumer-pilot workspace is not present")
        agents = (CONSUMER_PILOT / "AGENTS.md").read_text(encoding="utf-8")
        attrs = (CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8")
        impeccable = CONSUMER_PILOT / ".agents" / "skills" / "impeccable" / "SKILL.md"
        impeccable_bytes = impeccable.read_bytes()
        plan = _dry_plan_existing_consumer(CONSUMER_PILOT)
        public = plan_to_public_dict(plan)
        self.assertTrue(plan.allowed, public)
        ownership = {row.rel: row.ownership for row in plan.files}
        self.assertEqual(ownership.get("AGENTS.md"), OWNERSHIP_MANAGED_REGION)
        self.assertEqual(ownership.get(GITATTRIBUTES), OWNERSHIP_MANAGED_REGION)
        self.assertEqual(len(public["bridges"]["cursor"]), 4)
        self.assertTrue(public["agents_md"]["human_body_preserved"])
        self.assertFalse(public["agents_md"]["whole_file_replace"])
        self.assertTrue(public["gitattributes"]["human_body_preserved"])
        self.assertFalse(public["gitattributes"]["whole_file_replace"])
        self.assertEqual((CONSUMER_PILOT / "AGENTS.md").read_text(encoding="utf-8"), agents)
        self.assertEqual((CONSUMER_PILOT / ".gitattributes").read_text(encoding="utf-8"), attrs)
        self.assertEqual(impeccable.read_bytes(), impeccable_bytes)
        self.assertFalse(CANONICAL_PROJECT_CITY.joinpath(".scaffold", "install").exists())


def _live_region_digest(host: Path, rel: str) -> str:
    from scaffold_p5.consumer_install import _live_region_slice

    text = (host / rel).read_text(encoding="utf-8")
    slice_text, issues = _live_region_slice(rel, text)
    if issues or not slice_text:
        raise AssertionError((rel, issues, slice_text))
    return sha256_bytes(slice_text.encode("utf-8"))


class LiveDistributionIdentityTests(unittest.TestCase):
    def test_live_distribution_matches_source_packages(self):
        dist = load_live_distribution(REPO)
        self.assertEqual(dist.selected_release_id, "installed")
        selected = dist.selected_packages()
        self.assertEqual(set(selected), set(EXPECTED_PACKAGES))
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = selected[skill_id]
            self.assertEqual(pkg.validity, "VALID", skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)


if __name__ == "__main__":
    unittest.main()

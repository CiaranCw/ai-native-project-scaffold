from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from support import REPO, write
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p6.engine import TestEngine


REPO_TEST = REPO / "skills" / "test"

CORE_OWNERSHIP = {
    ".scaffold/project.yaml": "GENERATED",
    ".scaffold/modules.yaml": "GENERATED",
    ".scaffold/commands.yaml": "GENERATED",
    ".scaffold/tests.yaml": "GENERATED",
    ".scaffold/skills.lock": "GENERATED",
}


def test_engine(host: Path, package_root: Path | None = None) -> TestEngine:
    return TestEngine(host, package_root or REPO_TEST)


def actual_test_lock_entry() -> dict:
    pkg = load_package(REPO_TEST)
    return {
        "skill_version": pkg.ref.skill_version,
        "package_digest": pkg.ref.package_digest,
        "package_format_version": pkg.ref.package_format_version,
    }


def dummy_lock_entry(version: str = "2.0.0", digest: str | None = None) -> dict:
    return {
        "skill_version": version,
        "package_digest": digest or ("0" * 64),
        "package_format_version": "1",
    }


def four_core_lock_skills(*, test_entry: dict | None = None) -> dict:
    return {
        "understand": dummy_lock_entry("2.0.0", "0" * 64),
        "develop": dummy_lock_entry("2.0.0", "1" * 64),
        "test": test_entry if test_entry is not None else actual_test_lock_entry(),
        "submit": dummy_lock_entry("2.0.0", "3" * 64),
    }


def write_lock(host: Path, skills: dict | None = None, **overrides) -> None:
    data = {
        "lock_format_version": "1",
        "schema_version": "1",
        "authoritative": True,
        "skills": skills if skills is not None else four_core_lock_skills(),
    }
    data.update(overrides)
    write_yaml_atomic(host / ".scaffold/skills.lock", data)


def valid_baseline(kind: str = "none") -> dict:
    return {
        "kind": kind,
        "revision": None,
        "branch": None,
        "head_state": "not_applicable" if kind == "none" else "unborn",
        "working_tree": "unknown" if kind == "none" else "clean",
        "tracked_changes": "unknown" if kind == "none" else "absent",
        "untracked_changes": "unknown" if kind == "none" else "absent",
        "nested_workspace": "absent",
        "filesystem": {
            "project_state": "existing",
            "fingerprint": "p6-fixture",
            "file_count": 1,
        },
    }


def write_project(host: Path, **overrides) -> None:
    data = {
        "schema_version": "1",
        "project_contract_generation": "1",
        "name": host.name,
        "lifecycle": "ACTIVE",
        "maintenance": [],
        "baseline": valid_baseline(),
        "knowledge": {},
        "capabilities": {"scm": "none"},
        "ownership": dict(CORE_OWNERSHIP),
        "facts": [],
        "clients": [],
    }
    data.update(overrides)
    write_yaml_atomic(host / ".scaffold/project.yaml", data)
    write_yaml_atomic(host / ".scaffold/modules.yaml", {"schema_version": "1", "modules": []})
    write_lock(host)


def write_modules(host: Path, modules: list[dict]) -> None:
    write_yaml_atomic(
        host / ".scaffold/modules.yaml",
        {"schema_version": "1", "modules": modules},
    )


def write_commands(host: Path, commands: list[dict]) -> None:
    write_yaml_atomic(
        host / ".scaffold/commands.yaml",
        {"schema_version": "1", "commands": commands},
    )


def write_tests(
    host: Path,
    profiles: list[dict],
    *,
    applicable=True,
    applicability: str = "APPLICABLE",
    confidence: str = "VERIFIED",
    generated_outputs: list[str] | None = None,
) -> None:
    data = {
        "schema_version": "1",
        "applicability": applicability,
        "confidence": confidence,
        "profiles": profiles,
    }
    if applicable is not None:
        data["applicable"] = applicable
    if generated_outputs is not None:
        data["generated_outputs"] = generated_outputs
    write_yaml_atomic(host / ".scaffold/tests.yaml", data)


def py_command(script: str) -> list[str]:
    return [sys.executable, "-c", script]


def passing_profile(profile_id: str = "unit", required: bool = True) -> tuple[dict, dict]:
    command_id = f"cmd-{profile_id}"
    profile = {
        "id": profile_id,
        "purpose": f"{profile_id} verification",
        "required": required,
        "adapter": "local",
        "command_ref": command_id,
        "working_directory": ".",
        "timeout_seconds": 15,
        "success": {"exit_code": 0},
        "evidence_required": ["command_result"],
        "provenance": "LOCAL_EXECUTION",
    }
    command = {
        "id": command_id,
        "argv": py_command("print('P6_PASS')"),
        "availability": "declared",
        "confidence": "VERIFIED",
    }
    return profile, command


def failing_profile(profile_id: str = "failing") -> tuple[dict, dict]:
    profile, command = passing_profile(profile_id, True)
    command["argv"] = py_command("import sys; print('P6_FAIL'); sys.exit(1)")
    return profile, command


def write_host(
    host: Path,
    profiles: list[tuple[dict, dict]],
    **project,
) -> None:
    generated_outputs = project.pop("generated_outputs", None)
    write(host, "README.md", "# P6 host\n")
    write_project(host, **project)
    write_commands(host, [command for _profile, command in profiles])
    write_tests(
        host,
        [profile for profile, _command in profiles],
        generated_outputs=generated_outputs,
    )


def write_skill_package(
    dest: Path,
    *,
    skill_version: str,
    extra_manifest: dict | None = None,
    skill_md: str | None = None,
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {
        "skill_id": "test",
        "skill_version": skill_version,
        "package_format_version": "1",
        "entry": "SKILL.md",
        "modes": ["scoped_verification"],
        "contracts": {"project_contract_generations": ["1"]},
        "provides": ["test.scoped_verification"],
        "requires": [],
        "runtime": {"language": "python", "min_language_version": "3.10"},
    }
    if extra_manifest:
        contracts = dict(manifest.get("contracts") or {})
        contracts.update(extra_manifest.pop("contracts", {}) or {})
        manifest.update(extra_manifest)
        if contracts:
            manifest["contracts"] = contracts
    write_yaml_atomic(dest / "skill.yaml", manifest)
    text = skill_md or (
        "# Test\n\n"
        f"- skill_id: `test`\n"
        f"- skill_version: `{skill_version}`\n"
        "- modes: `scoped_verification`\n"
    )
    (dest / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")
    return dest


def git(host: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(host), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def init_git(host: Path) -> str:
    write(host, ".gitignore", ".scaffold/runtime/\n__pycache__/\n*.pyc\n.pytest_cache/\n")
    git(host, "init")
    git(host, "add", "-A")
    git(
        host,
        "-c",
        "user.name=P6 Test",
        "-c",
        "user.email=p6@example.invalid",
        "commit",
        "-m",
        "baseline",
    )
    return git(host, "rev-parse", "HEAD")

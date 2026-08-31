from __future__ import annotations

from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    actual_test_lock_entry,
    dummy_lock_entry,
    git,
    init_git,
    passing_profile,
    write_host,
    write_lock,
)
from p7_support import TASK_A, actual_develop_lock_entry, write_task
from scaffold_p5.packages import load_package
from scaffold_p8.engine import SubmitEngine
from support import REPO, write


REPO_SUBMIT = REPO / "skills" / "submit"

COMPLETE_STAGES = [
    {
        "stage_id": "stage-1",
        "goal": "Write the fixture source.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [
            {"requirement_id": "unit", "observed_outcome": "PASS"}
        ],
    }
]
FINAL_PASS = [{"requirement_id": "unit", "observed_outcome": "PASS"}]


def submit_engine(host: Path, package_root: Path | None = None) -> SubmitEngine:
    return SubmitEngine(host, package_root or REPO_SUBMIT)


def init_submit_git(host: Path) -> str:
    parent = init_git(host)
    git(host, "config", "--local", "user.name", "P8 Fixture User")
    git(host, "config", "--local", "user.email", "p8-fixture@example.invalid")
    git(host, "branch", "-M", "main")
    return parent


def actual_submit_lock_entry() -> dict:
    pkg = load_package(REPO_SUBMIT)
    return {
        "skill_version": pkg.ref.skill_version,
        "package_digest": pkg.ref.package_digest,
        "package_format_version": pkg.ref.package_format_version,
    }


def four_core_lock_skills_submit() -> dict:
    return {
        "understand": dummy_lock_entry("2.0.0", "0" * 64),
        "develop": actual_develop_lock_entry(),
        "test": actual_test_lock_entry(),
        "submit": actual_submit_lock_entry(),
    }


def bind_submit_lock(host: Path) -> None:
    write_lock(host, four_core_lock_skills_submit())


def write_ready_task(host: Path, **overrides) -> dict:
    data = {
        "status": "READY_FOR_REVIEW",
        "stages": COMPLETE_STAGES,
        "final_tests": FINAL_PASS,
    }
    data.update(overrides)
    return write_task(host, TASK_A, **data)


def write_submit_host(host: Path, **project) -> None:
    profile, command = passing_profile("unit")
    write_host(host, [(profile, command)], **project)
    bind_submit_lock(host)
    write(host, "src/app.py", "value = 1\n")
    ownership = {**CORE_OWNERSHIP, "src/app.py": "GENERATED"}
    from scaffold_p5.io_util import read_yaml, write_yaml_atomic

    payload = read_yaml(host / ".scaffold/project.yaml")
    payload["ownership"] = ownership
    if project.get("ownership"):
        payload["ownership"] = project["ownership"]
    if "maintenance" in project:
        payload["maintenance"] = project["maintenance"]
    if "lifecycle" in project:
        payload["lifecycle"] = project["lifecycle"]
    write_yaml_atomic(host / ".scaffold/project.yaml", payload)
    write_ready_task(host)

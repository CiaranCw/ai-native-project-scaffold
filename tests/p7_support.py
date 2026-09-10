from __future__ import annotations

from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    actual_test_lock_entry,
    dummy_lock_entry,
    write_lock,
    write_project,
)
from support import REPO, write
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p5.packages import load_package
from scaffold_p7.engine import DevelopEngine


REPO_DEVELOP = REPO / "skills" / "develop"
REPO_TEST = REPO / "skills" / "test"

TASK_A = "task-20260829T120000Z-aaa11111"
TASK_B = "task-20260829T120100Z-bbb22222"


def develop_engine(host: Path, package_root: Path | None = None) -> DevelopEngine:
    return DevelopEngine(host, package_root or REPO_DEVELOP)


def actual_develop_lock_entry() -> dict:
    pkg = load_package(REPO_DEVELOP)
    return {
        "skill_version": pkg.ref.skill_version,
        "package_digest": pkg.ref.package_digest,
        "package_format_version": pkg.ref.package_format_version,
    }


def four_core_lock_skills(
    *,
    develop_entry: dict | None = None,
    test_entry: dict | None = None,
) -> dict:
    return {
        "understand": dummy_lock_entry("2.0.0", "0" * 64),
        "develop": develop_entry if develop_entry is not None else actual_develop_lock_entry(),
        "test": test_entry if test_entry is not None else actual_test_lock_entry(),
        "submit": dummy_lock_entry("2.0.0", "3" * 64),
    }


def bind_develop_lock(host: Path, **overrides) -> None:
    write_lock(host, four_core_lock_skills(), **overrides)


def write_active_host(host: Path, **project) -> None:
    write(host, "README.md", "# P7 host\n")
    write_project(host, **project)
    bind_develop_lock(host)


def write_task(host: Path, task_id: str = TASK_A, **overrides) -> dict:
    data = {
        "record_type": "task_book",
        "schema_version": "1",
        "record_id": task_id,
        "record_revision": 1,
        "created_at": "2026-08-29T12:00:00Z",
        "updated_at": "2026-08-29T12:00:00Z",
        "title": "Fixture task",
        "goal": "Implement the fixture source change.",
        "acceptance": "Fixture source contains the expected line.",
        "baseline": {"kind": "none", "value": None},
        "scope": {"paths": ["src/app.py"], "modules": [], "exclude": []},
        "status": "IN_PROGRESS",
        "stages": [
            {
                "stage_id": "stage-1",
                "goal": "Write the fixture source.",
                "acceptance": "src/app.py has the expected content.",
                "status": "PENDING",
                "required_tests": [],
            }
        ],
        "final_tests": [],
        "develop_session_ids": [],
    }
    data.update(overrides)
    write_yaml_atomic(host / ".scaffold/tasks" / f"{task_id}.yaml", data)
    return data


def repair_handoff(
    *,
    task_id: str = TASK_A,
    candidate_digest: str,
    report: dict | None = None,
    kind: str = "test_to_develop",
    target_stage_ids: list[str] | None = None,
    **overrides,
) -> dict:
    payload = {
        "kind": kind,
        "task_id": task_id,
        "test_pass": False,
        "test_complete": False,
        "report_id": "tr-fixture",
        "candidate_digest": candidate_digest,
        "blockers": ["required verification failed"],
        "evidence_refs": [],
        "submit_authorized": False,
        "capabilities": {
            "commit": False,
            "push": False,
            "submit_authorized": False,
        },
    }
    if report is not None:
        payload["report"] = report
    if target_stage_ids is not None:
        payload["target_stage_ids"] = list(target_stage_ids)
    payload.update(overrides)
    return payload


def submit_repair_handoff(
    *,
    task_id: str = TASK_A,
    candidate_digest: str,
    target_stage_ids: list[str],
    **overrides,
) -> dict:
    return repair_handoff(
        task_id=task_id,
        candidate_digest=candidate_digest,
        kind="submit_to_develop",
        target_stage_ids=target_stage_ids,
        **overrides,
    )


def satisfied_decision(**overrides) -> dict:
    payload = {
        "outcome": "SATISFIED",
        "rationale": (
            "Current reconstructable Task Book and repository facts "
            "satisfy the declared acceptance criterion."
        ),
        "basis": [
            {
                "kind": "repository_observation",
                "summary": (
                    "Declared acceptance is observable from current "
                    "repository and Task Book facts."
                ),
            }
        ],
    }
    payload.update(overrides)
    return payload


def ready_lifecycle_opts() -> dict:
    return {
        "stage_completion_decision": satisfied_decision(stage_id="stage-1"),
        "task_completion_decision": satisfied_decision(
            rationale=(
                "Current Stage Completion Decisions and Task-level acceptance "
                "are reconstructable and SATISFIED for this candidate."
            ),
            basis=[
                {
                    "kind": "task_fact",
                    "summary": (
                        "Required Stages are COMPLETE with current SATISFIED "
                        "decisions and Task-level acceptance is satisfied."
                    ),
                }
            ],
        ),
    }


def write_invalid_develop_package(dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(
        dest / "skill.yaml",
        {
            "skill_id": "develop",
            "skill_version": "2.0.0",
            "package_format_version": "1",
            "entry": "SKILL.md",
            "modes": ["normal_task", "repair"],
            "provides": ["not-a-capability"],
            "requires": [],
        },
    )
    (dest / "SKILL.md").write_text(
        "# Develop\n\n- skill_id: `develop`\n- skill_version: `2.0.0`\n",
        encoding="utf-8",
        newline="\n",
    )
    return dest

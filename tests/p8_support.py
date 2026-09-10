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
from p7_support import TASK_A, actual_develop_lock_entry, satisfied_decision, write_task
from scaffold_p5.packages import load_package
from scaffold_p8.authorization_provider import (
    OPERATION_PUSH,
    OPERATION_S10,
    EphemeralAuthorizationProvider,
)
from scaffold_p8.engine import SubmitEngine
from support import REPO, write


REPO_SUBMIT = REPO / "skills" / "submit"

COMPLETE_STAGES = [
    {
        "stage_id": "stage-1",
        "goal": "Write the fixture source.",
        "acceptance": "src/app.py has the expected content.",
        "status": "COMPLETE",
        "required_tests": [],
    }
]
FINAL_PASS: list[dict] = []


class TestAuthorizationProvider(EphemeralAuthorizationProvider):
    """TEST-ONLY issuer. Production Submit never calls issue()."""

    def __init__(self) -> None:
        super().__init__()
        self._seq = 0

    def issue(
        self,
        *,
        operation: str,
        candidate_digest: str,
        attempt_id: str | None = None,
    ) -> str:
        self._seq += 1
        attempt = attempt_id or f"attempt-{self._seq}"
        grant_ref = f"grant-{operation}-{self._seq}-{attempt}"
        self._insert(
            grant_ref=grant_ref,
            operation=operation,
            attempt_id=attempt,
            candidate_digest=candidate_digest,
        )
        return grant_ref


def submit_engine(
    host: Path,
    package_root: Path | None = None,
    *,
    authorization_provider=None,
) -> SubmitEngine:
    engine = SubmitEngine(
        host,
        package_root or REPO_SUBMIT,
        authorization_provider=authorization_provider,
    )
    original = engine.run

    def run(mode: str = "", **opts):
        if opts.pop("bind_ready_authority", True):
            task_id = opts.get("task_id")
            if isinstance(task_id, str) and task_id.strip():
                bind_ready_completion_authority(host, task_id)
            else:
                bind_ready_completion_authority(host)
        return original(mode, **opts)

    engine.run = run
    return engine


def authorized_submit_engine(
    host: Path,
    package_root: Path | None = None,
) -> tuple[SubmitEngine, TestAuthorizationProvider]:
    provider = TestAuthorizationProvider()
    return submit_engine(host, package_root, authorization_provider=provider), provider


def finalize_auth(
    provider: TestAuthorizationProvider,
    digest: str,
    *,
    push: bool = False,
    attempt_id: str = "A1",
    push_attempt_id: str = "P1",
) -> dict:
    kwargs = {
        "finalize": True,
        "submit_authorization_ref": provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id=attempt_id,
        ),
        "submit_authorization_attempt_id": attempt_id,
    }
    if push:
        kwargs["push_authorization_ref"] = provider.issue(
            operation=OPERATION_PUSH,
            candidate_digest=digest,
            attempt_id=push_attempt_id,
        )
        kwargs["push_authorization_attempt_id"] = push_attempt_id
    return kwargs


def run_submit(host: Path, package_root: Path | None = None, *, push: bool = False, **opts):
    """Issue a trusted TEST grant when S10 is requested and no opaque ref is given.

    Caller dictionaries are ignored. Tests that prove those dictionaries are not
    authority must call submit_engine(...).run(...) directly.
    """
    from scaffold_p6.candidate import observe_candidate

    opts.pop("submit_authorized", None)
    opts.pop("push_authorized", None)
    opts.pop("authorization_provider", None)
    bind_ready = opts.pop("bind_ready_authority", True)
    if bind_ready:
        task_id = opts.get("task_id")
        if isinstance(task_id, str) and task_id.strip():
            bind_ready_completion_authority(host, task_id)
        else:
            bind_ready_completion_authority(host)
    opts["bind_ready_authority"] = bind_ready
    want = bool(opts.get("finalize") or opts.get("request_s10"))
    provider = None
    if want and not isinstance(opts.get("submit_authorization_ref"), str):
        provider = TestAuthorizationProvider()
        digest = observe_candidate(host).digest
        s10_attempt = opts.get("submit_authorization_attempt_id")
        if not isinstance(s10_attempt, str) or not s10_attempt.strip():
            s10_attempt = "A1"
        opts["submit_authorization_attempt_id"] = s10_attempt
        opts["submit_authorization_ref"] = provider.issue(
            operation=OPERATION_S10,
            candidate_digest=digest,
            attempt_id=s10_attempt,
        )
        if push or isinstance(opts.get("push_authorization_ref"), str):
            if not isinstance(opts.get("push_authorization_ref"), str):
                push_attempt = opts.get("push_authorization_attempt_id")
                if not isinstance(push_attempt, str) or not push_attempt.strip():
                    push_attempt = "P1"
                opts["push_authorization_attempt_id"] = push_attempt
                opts["push_authorization_ref"] = provider.issue(
                    operation=OPERATION_PUSH,
                    candidate_digest=digest,
                    attempt_id=push_attempt,
                )
        engine = submit_engine(host, package_root, authorization_provider=provider)
    else:
        engine = submit_engine(host, package_root)
    return engine.run(**opts)


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


def write_ready_task(
    host: Path,
    *,
    bind_ready_authority: bool = True,
    **overrides,
) -> dict:
    data = {
        "status": "READY_FOR_REVIEW",
        "stages": COMPLETE_STAGES,
        "final_tests": FINAL_PASS,
    }
    data.update(overrides)
    task_id = str(data.get("record_id") or TASK_A)
    written = write_task(host, task_id, **data)
    if bind_ready_authority:
        stamped = bind_ready_completion_authority(host, task_id)
        if isinstance(stamped, dict):
            return stamped
    return written


def bind_ready_completion_authority(
    host: Path, task_id: str = TASK_A
) -> dict | None:
    """TEST fixture: attach current SATISFIED Stage/Task decisions to a READY Task.

    Product Submit does not write the Task. Historical fixtures encoded
    status-only READY; Records §11 requires current completion authority.
    """
    from scaffold_p5.io_util import read_yaml, write_yaml_atomic
    from scaffold_p6.candidate import observe_candidate

    path = host / ".scaffold/tasks" / f"{task_id}.yaml"
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict) or data.get("status") != "READY_FOR_REVIEW":
        return data if isinstance(data, dict) else None
    candidate = observe_candidate(host)
    if not candidate.usable:
        return data
    digest = candidate.digest
    from scaffold_p7.lifecycle import evaluate_ready_for_review

    already_ok, _reason = evaluate_ready_for_review(
        data, candidate_digest=digest, root=host
    )
    if already_ok:
        return data
    stages = []
    for stage in data.get("stages") or []:
        if not isinstance(stage, dict):
            stages.append(stage)
            continue
        row = dict(stage)
        if row.get("status") == "COMPLETE":
            row["completion_decision"] = satisfied_decision(
                stage_id=str(row.get("stage_id") or ""),
                candidate_digest=digest,
            )
        stages.append(row)
    data["stages"] = stages
    data["task_completion_decision"] = satisfied_decision(candidate_digest=digest)
    write_yaml_atomic(path, data)
    return data


def write_submit_host(
    host: Path,
    *,
    noscms_baseline: bool = True,
    noscms_working_diff: bool = True,
    **project,
) -> None:
    profile, command = passing_profile("unit")
    write_host(host, [(profile, command)], **project)
    bind_submit_lock(host)
    write(host, "src/app.py", "value = 0\n" if noscms_baseline else "value = 1\n")
    ownership = {
        **CORE_OWNERSHIP,
        ".scaffold/ext/test/": "GENERATED",
        ".scaffold/ext/submit/": "GENERATED",
        "src/": "HUMAN_OWNED",
    }
    from scaffold_p5.io_util import read_yaml, write_yaml_atomic
    from scaffold_p5.scm import observe_scm
    from scaffold_p8.noscms import initialize_noscms_baseline

    payload = read_yaml(host / ".scaffold/project.yaml")
    payload["ownership"] = ownership
    payload["source_areas"] = ["src"]
    if project.get("ownership"):
        payload["ownership"] = project["ownership"]
    if "maintenance" in project:
        payload["maintenance"] = project["maintenance"]
    if "lifecycle" in project:
        payload["lifecycle"] = project["lifecycle"]
    write_yaml_atomic(host / ".scaffold/project.yaml", payload)
    write_ready_task(host, bind_ready_authority=False)
    if noscms_baseline and observe_scm(host).kind != "git":
        if noscms_working_diff:
            write(host, "src/app.py", "value = 1\n")
            bind_ready_completion_authority(host)
            write(host, "src/app.py", "value = 0\n")
            initialize_noscms_baseline(host)
            write(host, "src/app.py", "value = 1\n")
        else:
            bind_ready_completion_authority(host)
            initialize_noscms_baseline(host)
    else:
        bind_ready_completion_authority(host)


def rebind_noscms_baseline(host: Path) -> dict:
    """Explicit no-SCM baseline snapshot. Refuses Git hosts."""
    from scaffold_p5.scm import observe_scm
    from scaffold_p8.noscms import initialize_noscms_baseline

    if observe_scm(host).kind == "git":
        return {"ok": False, "skipped": "git"}
    return initialize_noscms_baseline(host)


def publish_knowledge_outcomes(
    host: Path,
    structural: dict,
    *,
    outcome: str = "SATISFIED",
    rationale: str = (
        "Understand assessed current mapped project knowledge as covering "
        "this exact impact."
    ),
    impacts: list | None = None,
) -> dict:
    """TEST helper: P5-publish a Knowledge Assessment for current S3 impacts."""
    from scaffold_p5.knowledge_assessment import (
        knowledge_relevant_impacts,
        mapped_surface_paths,
        publish_knowledge_assessment,
    )

    rows = impacts if impacts is not None else list(structural.get("impacts") or [])
    outcomes = []
    for row in knowledge_relevant_impacts(rows):
        outcomes.append(
            {
                "class": row["class"],
                "path": row["path"],
                "outcome": outcome,
                "surfaces": mapped_surface_paths(row),
                "rationale": rationale,
            }
        )
    return publish_knowledge_assessment(
        host,
        mode="refresh",
        impacts=rows,
        outcomes=outcomes,
    )

"""Zero-context project resume. Reconstructs from project-local truth only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5.compatibility import evaluate_host
from scaffold_p5.currentness import evaluate_understanding_currentness, load_current_snapshot
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_yaml
from scaffold_p5.understanding import load_derived_handoff
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import REPAIR_STATE_DIR, SESSIONS_DIR
from scaffold_p7.migration_run import reconstruct_migration_view
from scaffold_p7.repair_state import reconstruct_repair_view
from scaffold_p7.schemas import SESSION_ID_RE, validate_develop_session
from scaffold_p7.tasks import valid_tasks


SUBMIT_INDEX_RECOVERY_DIR = ".scaffold/runtime/submit-index-recovery"


CLIENT_SEMANTIC_KEYS = frozenset(
    {
        "cursor",
        "codebuddy",
        "claude",
        "claude_code",
        "codex",
        "chatgpt",
        "ide",
        "client_id",
        "client_name",
        "agent_id",
        "chat_id",
        "transcript_id",
    }
)

CONTINUABLE_TASK_STATUSES = frozenset({"IN_PROGRESS", "READY_FOR_REVIEW"})


def resume_project(
    root: str | Path,
    *,
    distribution: Any = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Observational zero-context entry. Chat, process memory, and summaries are not authority."""
    from scaffold_p8.records import durable_task_finalization

    host = Path(root)
    snapshot = snapshot_host(host)
    understanding = evaluate_understanding_currentness(host)
    candidate = observe_candidate(host)
    tasks, task_blockers = valid_tasks(host)
    sessions, session_blockers = inspect_sessions(host)
    migration = reconstruct_migration_view(host)
    repair_rows = _repair_rows(host, tasks)
    test_view = _test_view(repair_rows)
    finalization = durable_task_finalization(host)
    submit_view = _submit_view(host, tasks, finalization)
    project_view = _project_view(snapshot, distribution)
    selected = str(task_id or "").strip() or None
    route = select_next_route(
        snapshot=snapshot,
        understanding=understanding,
        tasks=tasks,
        sessions=sessions,
        migration=migration,
        repair_rows=repair_rows,
        test_view=test_view,
        submit_view=submit_view,
        task_id=selected,
        task_blockers=task_blockers,
        session_blockers=session_blockers,
        finalization=finalization,
    )
    handoff = load_derived_handoff(host)
    loaded = load_current_snapshot(host)
    handoff_trusted = _handoff_trusted(handoff, loaded)
    authority = {
        "project": project_view,
        "understanding": _understanding_authority(understanding, loaded),
        "work": {
            "tasks": [
                _task_resume_row(item, finalization)
                for item in tasks
            ],
            "task_blockers": task_blockers,
            "session_blockers": session_blockers,
            "sessions": sessions,
            "ready_task_ids": list(submit_view.get("ready_task_ids") or []),
            "durably_finalized_task_ids": list(
                submit_view.get("durably_finalized_task_ids") or []
            ),
            "continuable_ready_task_ids": list(
                submit_view.get("continuable_ready_task_ids") or []
            ),
            "finalization_blockers": list(finalization.get("blockers") or []),
            "repair": repair_rows,
            "migration": {
                "pending": bool(migration.get("pending")),
                "host_lifecycle": migration.get("host_lifecycle"),
                "executions": [
                    {
                        "migration_id": row.get("migration_id") or row.get("record_id"),
                        "status": row.get("status"),
                        "develop_binding": row.get("develop_binding") or {},
                    }
                    for row in (migration.get("executions") or [])
                    if isinstance(row, dict)
                ],
                "migration_recovery": migration.get("migration_recovery") or {},
            },
        },
        "test": test_view,
        "submit": submit_view,
        "candidate_digest": candidate.digest if candidate.usable else "",
        "knowledge_assessment": {
            "establishes_understanding": False,
            "role": "FA2-FND-004 S4 supporting authority only",
        },
        "handoff_summary": {
            "authoritative": False,
            "trusted": handoff_trusted,
            "locator": ".scaffold/runtime/understand-currentness/handoff.yaml",
            "present": handoff is not None,
        },
    }
    _assert_client_neutral(authority)
    summary = _summary_from_authority(authority, route)
    return {
        "ok": True,
        "mutations": False,
        "next_route": route["next_route"],
        "next_route_reason": route["reason"],
        "ambiguous_task_ids": list(route.get("ambiguous_task_ids") or []),
        "authority": authority,
        "summary": summary,
        "understanding": authority["understanding"],
        "project": project_view,
        "work": authority["work"],
        "test": test_view,
        "submit": submit_view,
    }


def select_next_route(
    *,
    snapshot,
    understanding: dict[str, Any],
    tasks: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    migration: dict[str, Any],
    repair_rows: list[dict[str, Any]],
    test_view: dict[str, Any],
    submit_view: dict[str, Any],
    task_id: str | None,
    task_blockers: list[str] | None = None,
    session_blockers: list[str] | None = None,
    finalization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if snapshot.host_class == "NOT_ADOPTED" or snapshot.lifecycle == "NOT_ADOPTED":
        return {
            "next_route": "understand.bootstrap",
            "reason": "host is not adopted; first attachment is Understand bootstrap",
        }
    recovery = dict(migration.get("migration_recovery") or {})
    executions = [
        row
        for row in (migration.get("executions") or [])
        if isinstance(row, dict)
    ]
    recovery_required = (
        snapshot.lifecycle == "RECOVERY_REQUIRED"
        or bool(recovery.get("requires_isolation"))
        or any(row.get("status") == "RECOVERY_REQUIRED" for row in executions)
        or str(recovery.get("classification") or "") == "RECOVERY_REQUIRED"
    )
    if recovery_required:
        return {
            "next_route": "migration.recovery",
            "reason": "Migration RECOVERY_REQUIRED outranks ordinary work continuation",
        }
    maintenance = list((snapshot.project or {}).get("maintenance") or []) if snapshot.project else []
    if "NEEDS_MIGRATION" in maintenance:
        return {
            "next_route": "human",
            "reason": "host is MIGRATION_REQUIRED; current Migration Plan/approval is a human gate",
        }
    work_blockers = [item for item in (task_blockers or []) if item] + [
        item for item in (session_blockers or []) if item
    ]
    if work_blockers:
        return {
            "next_route": "human",
            "reason": (
                "malformed or unreadable canonical Task/Session authority "
                "prevents optimistic continuation"
            ),
        }
    if submit_view.get("recovery"):
        return {
            "next_route": "submit",
            "reason": "active Submit recovery must continue from project-local Submit authority",
        }
    finalization = finalization or {}
    if finalization.get("blockers"):
        return {
            "next_route": "human",
            "reason": (
                "durable Change Record / S10 finalization lineage cannot be reconstructed"
            ),
        }
    focused = [item for item in tasks if not task_id or item.get("record_id") == task_id]
    if task_id and not focused:
        return {
            "next_route": "human",
            "reason": f"requested Task {task_id} is not reconstructable from Task Book authority",
        }
    finalized = {
        str(item)
        for item in (finalization.get("durably_finalized_task_ids") or [])
        if item
    }
    continuable = [
        item
        for item in focused
        if item.get("status") in CONTINUABLE_TASK_STATUSES
        and str(item.get("record_id") or "") not in finalized
    ]
    if not task_id and len(continuable) > 1:
        return {
            "next_route": "human",
            "reason": "multiple active Tasks exist; caller must select a Task rather than guessing",
            "ambiguous_task_ids": [str(item.get("record_id")) for item in continuable],
        }
    active_repair = [
        row
        for row in repair_rows
        if row.get("repair_state_status") in {"pending", "active"}
        and (not task_id or row.get("task_id") == task_id)
        and str(row.get("task_id") or "") not in finalized
    ]
    if len(continuable) <= 1 and active_repair:
        return {
            "next_route": "develop.repair",
            "reason": "Repair supporting state records an exact current blocker/target",
        }
    live_failures = [
        row
        for row in (test_view.get("required_failures") or [])
        if str(row.get("task_id") or "") not in finalized
        and (not task_id or row.get("task_id") == task_id)
    ]
    if live_failures and len(continuable) <= 1:
        return {
            "next_route": "test",
            "reason": "required Test failure is recorded against current work",
        }
    ready = [
        item
        for item in focused
        if item.get("status") == "READY_FOR_REVIEW"
        and str(item.get("record_id") or "") not in finalized
    ]
    if len(ready) == 1 and len(continuable) <= 1:
        return {
            "next_route": "submit",
            "reason": "exactly one continuable READY_FOR_REVIEW Task is reconstructable",
        }
    if len(ready) > 1 and not task_id:
        return {
            "next_route": "human",
            "reason": "multiple continuable READY_FOR_REVIEW Tasks exist; caller must select a Task",
            "ambiguous_task_ids": [str(item.get("record_id")) for item in ready],
        }
    currentness = str(understanding.get("currentness") or "UNKNOWN")
    if currentness in {"FULL_REFRESH_REQUIRED", "UNKNOWN"}:
        return {
            "next_route": "understand.refresh",
            "reason": "project understanding is not current; full Understand is required",
        }
    if currentness == "PARTIAL_REFRESH_REQUIRED":
        return {
            "next_route": "understand.refresh",
            "reason": "physical change is bounded; incremental Understand refresh is valid",
        }
    open_sessions = [
        row
        for row in sessions
        if row.get("status") == "OPEN" and row.get("reconstruction") == "VALID"
        and str(row.get("task_id") or "") not in finalized
        and (not task_id or row.get("task_id") == task_id)
    ]
    in_progress = [
        item
        for item in focused
        if item.get("status") == "IN_PROGRESS"
        and str(item.get("record_id") or "") not in finalized
    ]
    if len(in_progress) == 1 or (len(open_sessions) == 1 and len(in_progress) <= 1):
        return {
            "next_route": "develop.continue",
            "reason": "exactly one reconstructable Develop continuation target exists",
        }
    if open_sessions and not task_id and len(in_progress) != 1:
        return {
            "next_route": "human",
            "reason": "open Develop Sessions exist without a unique Task selection",
            "ambiguous_task_ids": sorted(
                {str(row.get("task_id")) for row in open_sessions if row.get("task_id")}
            ),
        }
    historical_ready = [
        item for item in focused if item.get("status") == "READY_FOR_REVIEW"
    ]
    if historical_ready and not ready and not continuable:
        return {
            "next_route": "none",
            "reason": (
                "READY_FOR_REVIEW Task is already consumed by durable S10 finalization"
            ),
        }
    return {
        "next_route": "none",
        "reason": "no current work, recovery, or understanding refresh is required",
    }


def _project_view(snapshot, distribution: Any) -> dict[str, Any]:
    project = snapshot.project or {}
    lock = snapshot.lock
    actual_versions: dict[str, str] = {}
    compatibility = None
    if distribution is not None and snapshot.project:
        evaluation = evaluate_host(snapshot, distribution)
        compatibility = evaluation.get("overall")
        actual = getattr(distribution, "actual_understand", None)
        if actual is not None:
            actual_versions["understand"] = actual.ref.skill_version
    expected = {}
    if lock is not None and getattr(lock, "data", None):
        skills = (lock.data or {}).get("skills") or {}
        if isinstance(skills, dict):
            for skill_id, row in skills.items():
                if isinstance(row, dict):
                    expected[str(skill_id)] = str(row.get("skill_version") or "")
    return {
        "identity": project.get("name") or project.get("project_id") or "",
        "host_class": snapshot.host_class,
        "lifecycle": snapshot.lifecycle,
        "normalization": snapshot.host_class,
        "project_contract_generation": project.get("project_contract_generation"),
        "maintenance": list(project.get("maintenance") or []),
        "compatibility": compatibility,
        "expected_skill_versions": expected,
        "actual_skill_versions": actual_versions,
        "lock_status": getattr(lock, "status", None),
    }


def _understanding_authority(evaluation: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    snapshot = evaluation.get("snapshot") or loaded.get("snapshot") or {}
    modules = []
    observed_modules = (evaluation.get("observed") or {}).get("modules") or snapshot.get("modules") or []
    for item in observed_modules:
        if not isinstance(item, dict):
            continue
        modules.append(
            {
                "id": item.get("id"),
                "path": item.get("path"),
                "digest": item.get("digest"),
                "knowledge_entry": item.get("knowledge_entry"),
            }
        )
    return {
        "currentness": evaluation.get("currentness"),
        "reasons": list(evaluation.get("reasons") or []),
        "affected_module_ids": list(evaluation.get("affected_module_ids") or []),
        "reusable_module_ids": list(evaluation.get("reusable_module_ids") or []),
        "locator": evaluation.get("locator") or loaded.get("locator") or "",
        "physical_digest": evaluation.get("physical_digest") or "",
        "structural_changed": bool(evaluation.get("structural_changed")),
        "module_set_changed": bool(evaluation.get("module_set_changed")),
        "unmapped_changed": bool(evaluation.get("unmapped_changed")),
        "modules": modules,
        "snapshot_digest": loaded.get("snapshot_digest") or "",
        "head_digest": loaded.get("head_digest") or "",
        "refreshed_module_ids": list(snapshot.get("refreshed_module_ids") or []),
        "reused_module_ids": list(snapshot.get("reused_module_ids") or evaluation.get("reusable_module_ids") or []),
        "supersedes": snapshot.get("supersedes") or "",
        "completion_locators": list(snapshot.get("completion_locators") or []),
    }


def inspect_sessions(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load canonical Sessions; malformed/orphaned/unreadable authority remains explicit."""
    folder = root / SESSIONS_DIR
    if not folder.exists():
        return [], []
    if not folder.is_dir():
        return [], ["Develop Session namespace is not a directory"]
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    children = sorted(folder.iterdir(), key=lambda path: path.name)
    for child in children:
        if not child.is_dir():
            blockers.append(f"Develop Session namespace contains a non-directory: {child.name}")
            continue
        session_id = child.name
        if not SESSION_ID_RE.fullmatch(session_id):
            rows.append(
                {
                    "record_id": session_id,
                    "status": "UNKNOWN",
                    "reconstruction": "UNKNOWN",
                }
            )
            blockers.append(f"Develop Session identity is malformed: {session_id}")
            continue
        path = child / "session.yaml"
        if not path.is_file():
            rows.append(
                {
                    "record_id": session_id,
                    "status": "UNKNOWN",
                    "reconstruction": "ORPHANED",
                }
            )
            blockers.append(
                f"Develop Session is orphaned or missing session.yaml: {session_id}"
            )
            continue
        try:
            data = read_yaml(path)
        except (OSError, ValueError, TypeError, UnicodeError):
            rows.append(
                {
                    "record_id": session_id,
                    "status": "UNKNOWN",
                    "reconstruction": "UNREADABLE",
                }
            )
            blockers.append(f"Develop Session is malformed or unreadable: {session_id}")
            continue
        issues = validate_develop_session(data, expected_id=session_id)
        if issues:
            rows.append(
                {
                    "record_id": session_id,
                    "status": data.get("status") if isinstance(data, dict) else "UNKNOWN",
                    "task_id": data.get("task_id") if isinstance(data, dict) else None,
                    "reconstruction": "MALFORMED",
                }
            )
            blockers.append(f"Develop Session is malformed: {session_id}")
            blockers.extend(issues)
            continue
        assert isinstance(data, dict)
        rows.append(
            {
                "record_id": data.get("record_id") or session_id,
                "status": data.get("status"),
                "task_id": data.get("task_id"),
                "mode": data.get("mode"),
                "reconstruction": "VALID",
            }
        )
    return rows, blockers


def _repair_rows(root: Path, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folder = root / REPAIR_STATE_DIR
    ids = {str(item.get("record_id")) for item in tasks if item.get("record_id")}
    if folder.is_dir():
        for path in folder.glob("*.yaml"):
            ids.add(path.stem)
    rows: list[dict[str, Any]] = []
    for task_id in sorted(ids):
        view = reconstruct_repair_view(root, task_id)
        if not view.get("repair_state_status") and not view.get("fail_ids") and not view.get("blockers"):
            continue
        rows.append(
            {
                "task_id": task_id,
                "task_status": view.get("task_status"),
                "repair_state_status": view.get("repair_state_status"),
                "target_stage_ids": list(view.get("target_stage_ids") or []),
                "blockers": list(view.get("blockers") or []),
                "fail_ids": list(view.get("fail_ids") or []),
                "reason": view.get("reason") or "",
                "next": view.get("next"),
                "candidate_digest": view.get("candidate_digest") or "",
            }
        )
    return rows


def _test_view(repair_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = []
    for row in repair_rows:
        for fail_id in row.get("fail_ids") or []:
            failures.append({"task_id": row.get("task_id"), "fail_id": fail_id})
        if row.get("blockers") and row.get("repair_state_status") in {"pending", "active"}:
            failures.append(
                {
                    "task_id": row.get("task_id"),
                    "blockers": list(row.get("blockers") or []),
                }
            )
    return {
        "required_failures": failures,
        "authority": "existing Repair/Test supporting state; P10 does not re-run Test",
    }


def _submit_view(
    root: Path,
    tasks: list[dict[str, Any]],
    finalization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recovery_dir = root / SUBMIT_INDEX_RECOVERY_DIR
    recovery = recovery_dir.is_dir() and any(recovery_dir.iterdir())
    ready_task_ids = [
        str(item.get("record_id"))
        for item in tasks
        if item.get("status") == "READY_FOR_REVIEW" and item.get("record_id")
    ]
    finalized = [
        str(item)
        for item in ((finalization or {}).get("durably_finalized_task_ids") or [])
        if item
    ]
    finalized_set = set(finalized)
    return {
        "recovery": recovery,
        "ready_task_ids": ready_task_ids,
        "durably_finalized_task_ids": finalized,
        "continuable_ready_task_ids": [
            task_id for task_id in ready_task_ids if task_id not in finalized_set
        ],
    }


def _task_resume_row(
    item: dict[str, Any], finalization: dict[str, Any] | None
) -> dict[str, Any]:
    record_id = str(item.get("record_id") or "")
    status = item.get("status")
    finalized = record_id in {
        str(value)
        for value in ((finalization or {}).get("durably_finalized_task_ids") or [])
        if value
    }
    return {
        "record_id": item.get("record_id"),
        "status": status,
        "title": item.get("title"),
        "durably_finalized": finalized,
        "continuable": (
            status in CONTINUABLE_TASK_STATUSES and not finalized
        ),
        "stages": [
            {
                "stage_id": stage.get("stage_id"),
                "status": stage.get("status"),
            }
            for stage in (item.get("stages") or [])
            if isinstance(stage, dict)
        ],
    }


def _handoff_trusted(handoff: dict[str, Any] | None, loaded: dict[str, Any]) -> bool:
    if not isinstance(handoff, dict):
        return False
    if handoff.get("authoritative") is True:
        return False
    if not loaded.get("ok"):
        return False
    if str(handoff.get("snapshot_locator") or "") != str(loaded.get("locator") or ""):
        return False
    if str(handoff.get("snapshot_digest") or "") != str(loaded.get("snapshot_digest") or ""):
        return False
    return True


def _summary_from_authority(authority: dict[str, Any], route: dict[str, Any]) -> str:
    understanding = authority.get("understanding") or {}
    project = authority.get("project") or {}
    return (
        f"lifecycle={project.get('lifecycle')} "
        f"understanding={understanding.get('currentness')} "
        f"next_route={route.get('next_route')}"
    )


def _assert_client_neutral(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in CLIENT_SEMANTIC_KEYS:
                raise ValueError(f"client-specific semantic key is not allowed: {key}")
            _assert_client_neutral(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_client_neutral(item)

"""Persist supporting project-understanding currentness. Not a canonical record."""

from __future__ import annotations

import contextlib
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5.currentness import (
    CURRENTNESS_ROOT,
    HEAD_LOCATOR,
    HEAD_RECORD_TYPE,
    RECORD_TYPE,
    SCHEMA_VERSION,
    SCOPE_PROJECT,
    evaluate_understanding_currentness,
    head_path,
    load_current_snapshot,
    observe_physical_understanding,
    physical_digest_for,
    snapshot_locator,
    snapshot_path,
    validate_currentness_head,
    validate_currentness_snapshot,
)
from scaffold_p5.io_util import file_digest, write_yaml_atomic
from scaffold_p5.refresh_completion import completions_covering
from scaffold_p6.candidate import observe_candidate


PRODUCER_SKILL = "understand"
HANDOFF_REL = ".scaffold/runtime/understand-currentness/handoff.yaml"
HEAD_LOCK = ".scaffold/runtime/understand-currentness/heads/project/head.lock"
_HEAD_LOCK_INITIALIZATION = threading.Lock()


def persist_project_understanding(
    root: str | Path,
    *,
    mode: str = "full",
    incremental: bool = False,
    expected_head_digest: str | None = None,
    producer_mode: str = "refresh",
) -> dict[str, Any]:
    """Publish a current-head only when refresh-completion authority covers required scope."""
    host = Path(root)
    with _current_head_lock(host):
        return _persist_locked(
            host,
            incremental=incremental,
            expected_head_digest=expected_head_digest,
            producer_mode=producer_mode,
        )


def _persist_locked(
    host: Path,
    *,
    incremental: bool,
    expected_head_digest: str | None,
    producer_mode: str,
) -> dict[str, Any]:
    evaluation = evaluate_understanding_currentness(host)
    observed = evaluation.get("observed") or observe_physical_understanding(host)
    if not observed.get("ok"):
        return {
            "ok": False,
            "currentness": evaluation.get("currentness") or "UNKNOWN",
            "blockers": list(observed.get("reasons") or ["physical understanding observation failed"]),
            "evaluation": evaluation,
            "mutations": False,
        }
    currentness = str(evaluation.get("currentness") or "UNKNOWN")
    existing = load_current_snapshot(host)
    if incremental and currentness in {"FULL_REFRESH_REQUIRED", "UNKNOWN"}:
        return {
            "ok": False,
            "rejected_incremental": True,
            "currentness": currentness,
            "blockers": [
                "incremental understanding reuse is not valid; FULL_REFRESH_REQUIRED"
            ]
            + list(evaluation.get("reasons") or []),
            "evaluation": evaluation,
            "mutations": False,
        }
    if currentness == "CURRENT" and existing.get("ok"):
        if expected_head_digest not in (None, "") and expected_head_digest != existing.get("head_digest"):
            return {
                "ok": False,
                "currentness": "CURRENT",
                "blockers": ["understanding current-head CAS expected digest does not match"],
                "evaluation": evaluation,
                "locator": existing.get("locator"),
                "mutations": False,
            }
        return {
            "ok": True,
            "currentness": "CURRENT",
            "noop": True,
            "mutations": False,
            "locator": existing.get("locator"),
            "snapshot_digest": existing.get("snapshot_digest"),
            "physical_digest": observed.get("physical_digest"),
            "head_digest": existing.get("head_digest"),
            "record_id": (existing.get("snapshot") or {}).get("record_id"),
            "refreshed_module_ids": [],
            "reused_module_ids": list(evaluation.get("reusable_module_ids") or []),
            "supersedes": "",
            "evaluation": evaluation,
            "snapshot": existing.get("snapshot"),
            "head": existing.get("head"),
            "blockers": [],
        }
    cas = _cas_blockers(host, expected_head_digest, existing)
    if cas:
        return {
            "ok": False,
            "currentness": currentness,
            "blockers": cas,
            "evaluation": evaluation,
            "mutations": False,
        }
    coverage = completions_covering(host, observed=observed)
    covered = coverage.get("covered") or {}
    mismatched = list(coverage.get("mismatched") or [])
    required = _required_module_ids(evaluation, observed)
    uncovered = [item for item in required if item not in covered]
    full_scope = (
        currentness in {"FULL_REFRESH_REQUIRED", "UNKNOWN"}
        or bool(evaluation.get("structural_changed"))
        or bool(evaluation.get("module_set_changed"))
        or bool(evaluation.get("unmapped_changed"))
    )
    if full_scope and uncovered:
        return {
            "ok": False,
            "currentness": currentness,
            "blockers": [
                "refresh completion authority does not cover the required full scope: "
                + ", ".join(uncovered)
            ]
            + mismatched,
            "uncovered_module_ids": uncovered,
            "evaluation": evaluation,
            "mutations": False,
        }
    if (not full_scope) and required and not any(item in covered for item in required):
        blockers = [
            "refresh completion authority is missing or stale for: " + ", ".join(required)
        ] + mismatched
        return {
            "ok": False,
            "currentness": currentness,
            "blockers": blockers,
            "uncovered_module_ids": uncovered or required,
            "evaluation": evaluation,
            "mutations": False,
        }
    previous = existing.get("snapshot") if existing.get("ok") else None
    previous_modules = {
        str(item.get("id")): item
        for item in ((previous or {}).get("modules") or [])
        if isinstance(item, dict) and item.get("id")
    }
    refreshed: list[str] = []
    reused: list[str] = []
    rows: list[dict[str, Any]] = []
    required_set = set(required)
    for item in observed.get("modules") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        module_id = str(item.get("id"))
        prior = previous_modules.get(module_id)
        if module_id in required_set and module_id in covered:
            rows.append(_module_row(item))
            refreshed.append(module_id)
            continue
        if prior is not None and str(prior.get("digest") or "") == str(item.get("digest") or ""):
            rows.append(_module_row(item))
            reused.append(module_id)
            continue
        if module_id in covered:
            rows.append(_module_row(item))
            refreshed.append(module_id)
            continue
        if prior is not None:
            rows.append(_module_row(prior))
            continue
        return {
            "ok": False,
            "currentness": currentness,
            "blockers": [
                f"refresh completion authority is missing for module {module_id}"
            ],
            "evaluation": evaluation,
            "mutations": False,
        }
    snapshot_physical = physical_digest_for(
        str(observed.get("structural_digest") or ""),
        rows,
        list(observed.get("unmapped") or []),
    )
    published_currentness = (
        "CURRENT" if snapshot_physical == observed.get("physical_digest") else currentness
    )
    record_id = _allocate_snapshot_id(host)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    candidate = observe_candidate(host)
    locator = snapshot_locator(record_id)
    payload = {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "record_id": record_id,
        "created_at": created_at,
        "scope": SCOPE_PROJECT,
        "producer": {"skill_id": PRODUCER_SKILL, "mode": producer_mode},
        "structural_digest": observed.get("structural_digest"),
        "physical_digest": snapshot_physical,
        "candidate_digest": candidate.digest if candidate.usable else "",
        "modules": rows,
        "unmapped": list(observed.get("unmapped") or []),
        "refreshed_module_ids": refreshed,
        "reused_module_ids": reused,
        "supersedes": str((previous or {}).get("record_id") or ""),
        "refresh_reasons": list(evaluation.get("reasons") or []),
        "refresh_kind": "incremental" if incremental and currentness == "PARTIAL_REFRESH_REQUIRED" else "full",
        "completion_locators": sorted(
            {
                str(covered[item]["locator"])
                for item in list(refreshed) + list(reused)
                if item in covered
            }
        ),
    }
    issues = validate_currentness_snapshot(payload)
    if issues:
        return {
            "ok": False,
            "currentness": currentness,
            "blockers": issues,
            "evaluation": evaluation,
            "snapshot": payload,
            "mutations": False,
        }
    path = snapshot_path(host, locator)
    if path is None:
        return {
            "ok": False,
            "blockers": ["understanding snapshot locator is illegal"],
            "evaluation": evaluation,
            "mutations": False,
        }
    write_yaml_atomic(path, payload)
    snapshot_digest = file_digest(path)
    head = {
        "record_type": HEAD_RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "scope": SCOPE_PROJECT,
        "locator": locator,
        "record_id": record_id,
        "snapshot_digest": snapshot_digest,
        "physical_digest": payload["physical_digest"],
    }
    head_issues = validate_currentness_head(head)
    if head_issues:
        return {
            "ok": False,
            "blockers": head_issues,
            "evaluation": evaluation,
            "locator": locator,
            "mutations": True,
        }
    write_yaml_atomic(head_path(host), head)
    written_head = file_digest(head_path(host))
    write_derived_handoff(
        host,
        snapshot=payload,
        locator=locator,
        snapshot_digest=snapshot_digest,
    )
    return {
        "ok": True,
        "currentness": published_currentness,
        "prior_currentness": currentness,
        "noop": False,
        "mutations": True,
        "locator": locator,
        "snapshot_digest": snapshot_digest,
        "physical_digest": payload["physical_digest"],
        "head_digest": written_head,
        "record_id": record_id,
        "refreshed_module_ids": refreshed,
        "reused_module_ids": reused,
        "uncovered_module_ids": uncovered,
        "supersedes": payload["supersedes"],
        "evaluation": evaluation,
        "snapshot": payload,
        "head": head,
        "blockers": [],
        "current_head_locator": HEAD_LOCATOR,
        "completion_locators": payload["completion_locators"],
    }


def _required_module_ids(evaluation: dict[str, Any], observed: dict[str, Any]) -> list[str]:
    currentness = str(evaluation.get("currentness") or "UNKNOWN")
    if currentness == "PARTIAL_REFRESH_REQUIRED":
        return [str(item) for item in (evaluation.get("affected_module_ids") or []) if item]
    return [
        str(item.get("id"))
        for item in observed.get("modules") or []
        if isinstance(item, dict) and item.get("id")
    ]


@contextlib.contextmanager
def _current_head_lock(root: Path) -> Iterator[None]:
    lock_path = root / HEAD_LOCK
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _HEAD_LOCK_INITIALIZATION:
        try:
            with open(lock_path, "xb") as created:
                created.write(b"*")
                created.flush()
                os.fsync(created.fileno())
        except FileExistsError:
            pass
        if lock_path.stat().st_size == 0:
            with open(lock_path, "r+b") as existing:
                existing.write(b"*")
                existing.flush()
                os.fsync(existing.fileno())
    handle = open(lock_path, "r+b")
    locked = False
    try:
        handle.seek(0)
        _lock_exclusive(handle)
        locked = True
        yield
    finally:
        try:
            if locked:
                handle.seek(0)
                _unlock_exclusive(handle)
        finally:
            handle.close()


def _lock_exclusive(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_exclusive(handle) -> None:
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_derived_handoff(
    root: str | Path,
    *,
    snapshot: dict[str, Any],
    locator: str,
    snapshot_digest: str,
) -> None:
    """Derived convenience only. Never currentness or routing authority."""
    host = Path(root)
    payload = {
        "record_type": "understand_handoff_summary",
        "schema_version": SCHEMA_VERSION,
        "supporting": True,
        "canonical": False,
        "authoritative": False,
        "snapshot_locator": locator,
        "snapshot_digest": snapshot_digest,
        "physical_digest": snapshot.get("physical_digest") or "",
        "record_id": snapshot.get("record_id") or "",
        "refreshed_module_ids": list(snapshot.get("refreshed_module_ids") or []),
        "reused_module_ids": list(snapshot.get("reused_module_ids") or []),
    }
    path = host / HANDOFF_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, payload)


def load_derived_handoff(root: str | Path) -> dict[str, Any] | None:
    from scaffold_p5.io_util import read_yaml

    path = Path(root) / HANDOFF_REL
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _cas_blockers(
    host: Path,
    expected_head_digest: str | None,
    existing: dict[str, Any],
) -> list[str]:
    path = head_path(host)
    if expected_head_digest in (None, ""):
        return []
    if not path.is_file():
        return ["understanding current-head CAS expected a head that is missing"]
    actual = existing.get("head_digest") or file_digest(path)
    if actual != expected_head_digest:
        return ["understanding current-head CAS expected digest does not match"]
    return []


def _module_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "path": str(item.get("path") or "").replace("\\", "/"),
        "digest": str(item.get("digest") or ""),
        "knowledge_entry": str(item.get("knowledge_entry") or ""),
        "kind": str(item.get("kind") or "source"),
        "missing": bool(item.get("missing")),
    }


def _allocate_snapshot_id(root: Path) -> str:
    used = set()
    folder = root / CURRENTNESS_ROOT
    if folder.is_dir():
        used = {path.name for path in folder.iterdir() if path.is_dir()}
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(32):
        candidate = f"uc-{utc}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
        utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raise RuntimeError("unable to allocate unique understanding snapshot identity")

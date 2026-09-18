"""Develop Session runtime. Advisory provenance. Never stronger than Task Book + workspace."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import scm_baseline
from scaffold_p5.io_util import file_digest, read_yaml, write_yaml_atomic
from scaffold_p5.scm import observe_scm

from scaffold_p5.client_support import is_client_support_path
from scaffold_p7.models import DIGEST_PREFIX, SESSIONS_DIR
from scaffold_p7.schemas import SESSION_ID_RE, validate_develop_session, validate_files_yaml

OPEN_INVENTORY_NAME = "open-inventory.yaml"
MUTATION_ATTEMPTS_NAME = "mutation-attempts.yaml"
MUTATION_PENDING = "authorized_pending"
MUTATION_OBSERVED = "observed_success"
MUTATION_RECONCILED = "reconciled"
MUTATION_FAILED = "failed"
MUTATION_CANCELLED = "cancelled"
PHYSICAL_ATTRIBUTION_STATES = frozenset({MUTATION_OBSERVED, MUTATION_RECONCILED})
INVENTORY_SKIP_DIRS = frozenset(
    {".git", ".scaffold", "__pycache__", "test-runs"}
)


def operational_project_name(
    project: dict[str, Any] | None,
    root: str | Path,
) -> str:
    """Stable Session identity. Does not resolve CONFLICTING product-name facts."""
    declared = str((project or {}).get("name") or "").strip()
    if declared:
        return declared
    return Path(root).name


class SessionResolution:
    def __init__(
        self,
        *,
        ok: bool,
        session: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        directory: Path | None = None,
        blockers: list[str] | None = None,
    ):
        self.ok = ok
        self.session = session
        self.files = files or []
        self.directory = directory
        self.blockers = blockers or []


def existing_session_ids(root: Path) -> set[str]:
    folder = root / SESSIONS_DIR
    if not folder.is_dir():
        return set()
    return {path.name for path in folder.iterdir() if path.is_dir()}


def new_session_id(root: Path) -> str:
    used = existing_session_ids(root)
    utc = _compact_utc()
    for _ in range(32):
        candidate = f"dev-{utc}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
        utc = _compact_utc()
    raise RuntimeError("unable to allocate a unique Develop Session id")


def create_session(
    root: Path,
    *,
    task_id: str,
    mode: str,
    project_name: str,
    candidate_digest: str,
) -> SessionResolution:
    record_id = new_session_id(root)
    now = _iso_utc()
    baseline = scm_baseline(root)
    session = {
        "record_type": "develop_session",
        "schema_version": "1",
        "record_id": record_id,
        "created_at": now,
        "updated_at": now,
        "status": "OPEN",
        "task_id": task_id,
        "mode": mode,
        "project_name": project_name,
        "baseline": {
            "kind": baseline.get("kind") or "unavailable",
            "value": baseline.get("revision") or baseline.get("value"),
        },
        "workspace_overlay_s0": _workspace_overlay(root, baseline),
        "observed_candidate_digest": candidate_digest,
    }
    directory = root / SESSIONS_DIR / record_id
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(directory / "session.yaml", session)
    write_yaml_atomic(directory / "files.yaml", {"files": []})
    return SessionResolution(ok=True, session=session, files=[], directory=directory)


def load_session(
    root: Path,
    session_id: str,
    *,
    task_id: str,
    mode: str,
    project_name: str,
    current_candidate_digest: str,
    require_candidate_match: bool = True,
) -> SessionResolution:
    if not SESSION_ID_RE.fullmatch(session_id):
        return SessionResolution(
            ok=False,
            blockers=["Develop Session identity is malformed"],
        )
    directory = root / SESSIONS_DIR / session_id
    path = directory / "session.yaml"
    if directory.exists() and not directory.is_dir():
        return SessionResolution(
            ok=False,
            blockers=["Develop Session path is not a directory"],
        )
    if not path.is_file():
        return SessionResolution(
            ok=False,
            blockers=["Develop Session is missing or orphaned"],
        )
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return SessionResolution(
            ok=False,
            blockers=["Develop Session is malformed or unreadable"],
        )
    issues = validate_develop_session(data, expected_id=session_id)
    if issues:
        return SessionResolution(
            ok=False,
            blockers=["Develop Session is malformed"] + issues,
        )
    assert isinstance(data, dict)
    if data.get("task_id") != task_id:
        return SessionResolution(
            ok=False,
            blockers=["Develop Session cannot be reused for a different Task Book"],
        )
    if data.get("mode") != mode:
        return SessionResolution(
            ok=False,
            blockers=["Develop Session mode does not match the requested Develop mode"],
        )
    bound_name = data.get("project_name")
    if bound_name != project_name:
        if not (isinstance(bound_name, str) and bound_name == "" and project_name):
            return SessionResolution(
                ok=False,
                blockers=["Develop Session is bound to a different project"],
            )
    if data.get("status") != "OPEN":
        return SessionResolution(
            ok=False,
            blockers=[
                f"Develop Session status {data.get('status')!r} cannot continue"
            ],
        )
    bound_digest = str(data.get("observed_candidate_digest") or "")
    if require_candidate_match:
        if not current_candidate_digest:
            return SessionResolution(
                ok=False,
                blockers=["current candidate identity is UNKNOWN; Session cannot resume"],
            )
        if bound_digest != current_candidate_digest:
            return SessionResolution(
                ok=False,
                blockers=[
                    "OPEN Develop Session is bound to a different candidate; "
                    "workspace truth overrides Session memory"
                ],
            )
    files, file_issues = load_files_yaml(directory)
    if file_issues or files is None:
        return SessionResolution(
            ok=False,
            blockers=file_issues or ["Develop Session files.yaml is unusable"],
        )
    return SessionResolution(
        ok=True,
        session=data,
        files=files,
        directory=directory,
    )


def load_files_yaml(directory: Path) -> tuple[list[dict[str, Any]] | None, list[str]]:
    path = directory / "files.yaml"
    if not path.is_file():
        return None, ["Develop Session files.yaml is missing"]
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, ["Develop Session files.yaml is malformed or unreadable"]
    issues = validate_files_yaml(data)
    if issues:
        return None, ["Develop Session files.yaml is malformed"] + issues
    assert isinstance(data, dict)
    return [row for row in data.get("files") or [] if isinstance(row, dict)], []


def load_mutation_attempts(
    directory: Path,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    path = directory / MUTATION_ATTEMPTS_NAME
    if not path.is_file():
        return [], []
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None, ["Develop Session mutation-attempts.yaml is malformed or unreadable"]
    if not isinstance(data, dict):
        return None, ["Develop Session mutation-attempts.yaml is malformed"]
    if data.get("record_type") not in {None, "develop_mutation_attempts"}:
        return None, ["Develop Session mutation-attempts.yaml record_type is unsupported"]
    rows = data.get("attempts")
    if rows is None:
        rows = data.get("files")
    if not isinstance(rows, list):
        return None, ["Develop Session mutation-attempts.yaml attempts must be a list"]
    return [row for row in rows if isinstance(row, dict)], []


def persist_mutation_attempts(
    directory: Path, attempts: list[dict[str, Any]]
) -> None:
    write_yaml_atomic(
        directory / MUTATION_ATTEMPTS_NAME,
        {
            "schema_version": "1",
            "record_type": "develop_mutation_attempts",
            "attempts": list(attempts),
        },
    )


def persist_files_yaml(directory: Path, files: list[dict[str, Any]]) -> None:
    write_yaml_atomic(directory / "files.yaml", {"files": list(files)})


def is_physical_attribution(row: dict[str, Any] | None) -> bool:
    """True when files.yaml bytes are legitimate Session attribution.

    Hook-enriched ``observed_success`` and physically reconciled rows both
    count when they describe live bytes. Pending/failed/cancelled never do.
    """
    if not isinstance(row, dict):
        return False
    state = str(row.get("mutation_state") or "").strip()
    if state in {MUTATION_PENDING, MUTATION_FAILED, MUTATION_CANCELLED}:
        return False
    if state in PHYSICAL_ATTRIBUTION_STATES:
        return True
    if row.get("change_kind") == "deleted":
        return True
    if row.get("after_kind") == "missing" and not row.get("after_digest"):
        return False
    return isinstance(row.get("after_digest"), str) and bool(row.get("after_digest"))


def record_touch(
    directory: Path,
    files: list[dict[str, Any]],
    *,
    rel: str,
    before_kind: str,
    after_kind: str,
    before_digest: str | None,
    after_digest: str | None,
    change_kind: str,
    was_preexisting_dirty: bool,
    stage_ids: list[str],
    mutation_state: str = MUTATION_OBSERVED,
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    entry = {
        "path": rel,
        "change_kind": change_kind,
        "was_preexisting_dirty": was_preexisting_dirty,
        "before_kind": before_kind,
        "after_kind": after_kind,
        "before_digest": before_digest,
        "after_digest": after_digest,
        "content_class": "text",
        "patch_ref": None,
        "stage_ids": list(stage_ids),
        "mutation_state": mutation_state,
    }
    if extra:
        entry.update(extra)
    updated = [row for row in files if row.get("path") != rel]
    updated.append(entry)
    persist_files_yaml(directory, updated)
    return updated


def persist_session(directory: Path, session: dict[str, Any]) -> None:
    write_yaml_atomic(directory / "session.yaml", session)


def seal_session(root: Path, directory: Path, session: dict[str, Any]) -> dict[str, Any]:
    updated = dict(session)
    updated["status"] = "SEALED"
    updated["updated_at"] = _iso_utc()
    updated["session_s1_sealed_at"] = updated["updated_at"]
    updated["workspace_overlay_s1"] = _workspace_overlay(root, scm_baseline(root))
    persist_session(directory, updated)
    return updated


def abort_session(directory: Path, session: dict[str, Any]) -> dict[str, Any]:
    updated = dict(session)
    updated["status"] = "ABORTED"
    updated["updated_at"] = _iso_utc()
    persist_session(directory, updated)
    return updated


def file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return DIGEST_PREFIX + file_digest(path)


def execution_workspace_digests(root: str | Path) -> dict[str, str]:
    """Digest project files that can participate in Develop execution provenance.

    Session bookkeeping, Git metadata, declared CLIENT_SUPPORT paths, and P6
    run artifacts are excluded so they cannot masquerade as Task product drift.
    """
    host = Path(root)
    out: dict[str, str] = {}
    if not host.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(host, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in INVENTORY_SKIP_DIRS and not name.endswith(".egg-info")
        ]
        rel_dir = Path(dirpath).relative_to(host).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                continue
            rel = name if not rel_dir else f"{rel_dir}/{name}"
            rel = rel.replace("\\", "/")
            if _inventory_skipped(rel, host):
                continue
            full = host / rel
            if full.is_symlink() or not full.is_file():
                continue
            digest = file_sha256(full)
            if digest:
                out[rel] = digest
    return out


def snapshot_open_inventory(
    root: str | Path,
    directory: Path,
    *,
    overwrite: bool = False,
) -> dict[str, str]:
    path = directory / OPEN_INVENTORY_NAME
    if path.is_file() and not overwrite:
        loaded = load_open_inventory(directory)
        if loaded is not None:
            return loaded
    files = execution_workspace_digests(root)
    payload = {
        "schema_version": "1",
        "record_type": "develop_open_inventory",
        "files": [
            {"path": rel, "digest": digest}
            for rel, digest in sorted(files.items())
        ],
    }
    directory.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, payload)
    return files


def load_open_inventory(directory: Path) -> dict[str, str] | None:
    path = directory / OPEN_INVENTORY_NAME
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("record_type") != "develop_open_inventory":
        return None
    rows = data.get("files")
    if not isinstance(rows, list):
        return None
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rel = str(row.get("path") or "").replace("\\", "/").strip().strip("/")
        digest = str(row.get("digest") or "").strip()
        if rel and digest:
            out[rel] = digest
    return out


def _inventory_skipped(rel: str, root: Path | None = None) -> bool:
    if rel in INVENTORY_SKIP_DIRS:
        return True
    if any(
        rel == name or rel.startswith(name + "/") for name in INVENTORY_SKIP_DIRS
    ):
        return True
    return root is not None and is_client_support_path(root, rel)


def path_kind(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_symlink():
        return "symlink"
    if path.is_file():
        return "regular_file"
    return "other"


def _workspace_overlay(root: Path, baseline: dict[str, Any]) -> dict[str, Any]:
    if baseline.get("kind") != "git":
        return {"coverage": "unavailable", "paths": []}
    observed = observe_scm(root)
    if not observed.ok or observed.kind != "git":
        return {"coverage": "unavailable", "paths": []}
    paths: list[dict[str, Any]] = []
    for entry in observed.entries:
        rel = str(entry.get("path") or "")
        if not rel:
            continue
        full = root / rel
        digest = file_sha256(full)
        paths.append(
            {
                "path": rel,
                "kind": path_kind(full),
                "digest": digest,
            }
        )
    return {"coverage": "complete", "paths": paths}


def _iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

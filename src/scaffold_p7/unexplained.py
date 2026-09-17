"""Host-level unexplained physical drift. Not a canonical development record.

Observation boundaries that must reconcile:

- Session open / bind (`bind_open_execution`) — new Session must not launder
- abort / `_blocked` abort — persist unresolved truth, then abort
- seal / run completion seal — persist before close
- Submit S2 — classify against durable facts, not only Session overlays
- successful S10 — accepted-anchor advancement may retire rows

These cover drift during a Session, between Sessions, with no Session open,
and through an imperfect client hook surface. Perfect pre-write interception
is not required.

Session S0 / open-inventory is physical starting observation, not the
accepted anchor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import read_yaml, sha256_text, write_yaml_atomic
from scaffold_p5.schemas import (
    COMPATIBILITY_BOUNDARY_GENERATION,
    CORE_MACHINE_ARTIFACTS,
)
from scaffold_p5.scm import observe_scm
from scaffold_p6.candidate import is_ext_support_path, RUNTIME_PREFIX
from scaffold_p7.models import SESSIONS_DIR, TASKS_DIR
from scaffold_p7.session import MUTATION_OBSERVED, file_sha256, load_files_yaml, path_kind


UNEXPLAINED_REL = ".scaffold/ext/develop/unexplained.yaml"
PROJECT_YAML_REL = ".scaffold/project.yaml"
RECORD_TYPE = "develop_unexplained_drift"
SCHEMA_VERSION = "1"
CLASS_UNEXPLAINED = "unexplained"
CLASS_INHERITED_INIT = "inherited-at-initialization"
KIND_MISSING = "missing"
KIND_FILE = "regular_file"
STATE_NEVER_INITIALIZED = "never_initialized"
STATE_VALID_INITIALIZED = "valid_initialized"
STATE_AUTHORITY_UNUSABLE = "authority_unusable"
_CANONICAL_AUTHORITY_PREFIXES = (
    TASKS_DIR.rstrip("/") + "/",
    ".scaffold/changes/",
    ".scaffold/finalizations/",
)

BOUNDARIES = frozenset(
    {"open", "resume", "seal", "abort", "submit_s2", "s10"}
)


def resolve_accepted_anchor(root: str | Path) -> dict[str, Any]:
    """Read accepted physical truth. Session snapshots are not this anchor."""
    host = Path(root)
    scm = observe_scm(host)
    if scm.kind == "git":
        if not scm.ok or not scm.revision:
            return {
                "ok": False,
                "kind": "git",
                "observation_state": "UNKNOWN",
                "blockers": list(scm.blockers)
                or ["Git accepted-anchor HEAD is UNKNOWN"],
            }
        return {
            "ok": True,
            "kind": "git",
            "revision": scm.revision,
            "observation_state": scm.observation_state,
            "blockers": [],
        }
    from scaffold_p8.noscms import load_noscms_baseline

    loaded = load_noscms_baseline(host)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "kind": "none",
            "observation_state": str(loaded.get("observation_state") or "UNKNOWN"),
            "blockers": list(loaded.get("blockers") or [
                "no-SCM accepted-anchor authority is UNKNOWN"
            ]),
        }
    inventory = loaded.get("inventory") or {}
    if not isinstance(inventory, dict):
        return {
            "ok": False,
            "kind": "none",
            "observation_state": "UNKNOWN",
            "blockers": ["no-SCM accepted inventory is unusable"],
        }
    return {
        "ok": True,
        "kind": "none",
        "revision": _noscms_revision(inventory, loaded),
        "inventory": inventory,
        "observation_state": scm.observation_state,
        "blockers": [],
    }


def load_unexplained_record(root: str | Path) -> dict[str, Any] | None:
    """Return the valid drift payload only. Malformed/unusable is not empty."""
    inspected = inspect_drift_authority(root)
    if inspected.get("state") != STATE_VALID_INITIALIZED:
        return None
    payload = inspected.get("payload")
    return payload if isinstance(payload, dict) else None


def initialization_completed(root: str | Path) -> bool:
    """True once the tracked project contract generation carries the boundary."""
    status, generation = _project_generation(Path(root))
    return status == "ok" and _boundary_consumed(generation)


def inspect_drift_authority(root: str | Path) -> dict[str, Any]:
    """Read the durable boundary from tracked project authority, then the payload.

    FA2-FND-005 FND5-E12: the one-time compatibility boundary is the tracked
    `project_contract_generation` advance owned by Understand / project-migration
    authority. Develop only consumes it. The disposable `.scaffold/ext/develop/`
    payload can never re-grant the boundary, so ordinary untracked cleanup
    downgrades a migrated host to unusable, never to never-initialized.
    """
    host = Path(root)
    generation_status, generation = _project_generation(host)
    if generation_status != "ok":
        return _unusable_authority(
            "project contract authority carrying the compatibility boundary "
            "is missing or unreadable"
        )
    payload_status, payload, payload_blocker = _load_unexplained_payload(host)
    if payload_status == "unusable":
        return _unusable_authority(payload_blocker)
    if not _boundary_consumed(generation):
        if payload_status == "valid":
            return _unusable_authority(
                "drift authority exists before the project contract "
                "compatibility boundary was consumed"
            )
        return {
            "state": STATE_NEVER_INITIALIZED,
            "ok": True,
            "blockers": [],
            "payload": None,
        }
    if payload_status == "absent":
        return _unusable_authority(
            "unexplained drift authority is missing after the project contract "
            "compatibility boundary was consumed"
        )
    return {
        "state": STATE_VALID_INITIALIZED,
        "ok": True,
        "blockers": [],
        "payload": payload,
    }


def physical_authority_issues(root: str | Path) -> list[str]:
    """Mutation requires known accepted truth and usable drift authority."""
    anchor = resolve_accepted_anchor(root)
    if not anchor.get("ok"):
        return list(anchor.get("blockers") or ["accepted physical authority is UNKNOWN"])
    inspected = inspect_drift_authority(root)
    if inspected.get("state") == STATE_AUTHORITY_UNUSABLE:
        return list(inspected.get("blockers") or ["durable drift authority is unusable"])
    if inspected.get("state") == STATE_NEVER_INITIALIZED:
        return ["cross-session develop authority is not initialized"]
    return []


def unexplained_matches_current(root: str | Path, rel: str) -> bool:
    """True when durable unexplained facts describe this path's current bytes."""
    if inspect_drift_authority(root).get("state") != STATE_VALID_INITIALIZED:
        return False
    wanted = _norm_path(rel)
    current = _current_row(Path(root), wanted)
    row = unexplained_path_map(root).get(wanted)
    if row is None:
        return False
    if str(row.get("classification") or "") != CLASS_UNEXPLAINED:
        return False
    return _row_state(row) == _row_state(current)


def unexplained_path_map(root: str | Path) -> dict[str, dict[str, Any]]:
    payload = load_unexplained_record(root)
    if payload is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("paths") or []:
        if not isinstance(row, dict) or not row.get("path"):
            continue
        out[_norm_path(str(row.get("path") or ""))] = row
    return out


def reconcile_unexplained_drift(
    root: str | Path,
    *,
    boundary: str,
) -> dict[str, Any]:
    """Reconcile accepted truth, current Diff, provenance, and durable facts.

    Unknown accepted-anchor authority is fail-closed for this function's
    `ok` flag. Abort / Session open treat `skipped=True` as an escape path.
    Unusable durable drift authority is `ok=False` without skip or rewrite.
    """
    host = Path(root)
    used_boundary = boundary if boundary in BOUNDARIES else "open"
    inspected = inspect_drift_authority(host)
    if inspected.get("state") == STATE_AUTHORITY_UNUSABLE:
        return {
            "ok": False,
            "skipped": False,
            "unusable": True,
            "observation_state": "UNUSABLE",
            "blockers": list(inspected.get("blockers") or [
                "durable drift authority is unusable"
            ]),
            "paths": [],
        }
    if inspected.get("state") == STATE_NEVER_INITIALIZED:
        # Develop is a consumer of the compatibility boundary. Ordinary Session
        # boundaries MUST NOT consume or recreate it, so a legacy host cannot
        # mint amnesty here. Skipping keeps abort an escape path; the mutation
        # gate still denies ordinary work until project migration completes.
        return {
            "ok": False,
            "skipped": True,
            "initialized": False,
            "observation_state": "NEVER_INITIALIZED",
            "blockers": [
                "project contract compatibility boundary has not been consumed"
            ],
            "paths": [],
        }
    anchor = resolve_accepted_anchor(host)
    if not anchor.get("ok"):
        return {
            "ok": False,
            "skipped": True,
            "observation_state": str(anchor.get("observation_state") or "UNKNOWN"),
            "blockers": list(anchor.get("blockers") or ["accepted anchor is UNKNOWN"]),
            "paths": [],
        }
    diffs = accepted_physical_diffs(host, anchor)
    provenance = host_wide_observed_success(host)
    existing = inspected.get("payload") if isinstance(inspected.get("payload"), dict) else None
    now = _iso_utc()
    previous = {
        _norm_path(str(row.get("path") or "")): row
        for row in (existing or {}).get("paths") or []
        if isinstance(row, dict) and row.get("path")
    }
    next_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in diffs:
        path = row["path"]
        seen.add(path)
        if _current_byte_attributed(row, provenance):
            continue
        prev = previous.get(path)
        if (
            isinstance(prev, dict)
            and str(prev.get("classification") or "") == CLASS_INHERITED_INIT
            and _row_state(prev) == (row["kind"], row.get("digest"))
        ):
            next_rows.append(prev)
            continue
        if (
            isinstance(prev, dict)
            and str(prev.get("classification") or "") == CLASS_UNEXPLAINED
        ):
            updated = dict(prev)
            updated["kind"] = row["kind"]
            updated["digest"] = row.get("digest")
            updated["accepted_kind"] = str(anchor.get("kind") or "")
            updated["accepted_revision"] = str(anchor.get("revision") or "")
            next_rows.append(updated)
            continue
        next_rows.append(
            _fact_row(
                row,
                classification=CLASS_UNEXPLAINED,
                accepted_kind=str(anchor.get("kind") or ""),
                accepted_revision=str(anchor.get("revision") or ""),
                boundary=used_boundary,
                observed_at=now,
            )
        )
    payload = _record_payload(
        initialization=(existing or {}).get("initialization")
        or {"completed": True, "completed_at": now},
        paths=next_rows,
    )
    _persist(host, payload)
    return {
        "ok": True,
        "skipped": False,
        "initialized": False,
        "blockers": [],
        "paths": list(payload["paths"]),
        "retired": sorted(set(previous) - seen),
    }


def establish_compatibility_boundary(
    root: str | Path,
    *,
    classify_inherited: bool,
) -> dict[str, Any]:
    """Consume the one-time FA2-FND-005 compatibility boundary exactly once.

    Owned by Understand / project-migration authority, called only after the
    tracked `project_contract_generation` already carries the boundary. Develop
    never calls this. `classify_inherited` is true only for an established
    legacy host completing a bounded project migration; a host adopted at the
    current generation is already post-boundary and receives no amnesty.
    """
    host = Path(root)
    generation_status, generation = _project_generation(host)
    if generation_status != "ok":
        return {
            "ok": False,
            "established": False,
            "blockers": [
                "project contract authority is unreadable; the compatibility "
                "boundary cannot be established"
            ],
            "paths": [],
        }
    if not _boundary_consumed(generation):
        return {
            "ok": False,
            "established": False,
            "blockers": [
                "project contract generation has not reached the compatibility "
                "boundary"
            ],
            "paths": [],
        }
    payload_status, _payload, payload_blocker = _load_unexplained_payload(host)
    if payload_status == "unusable":
        return {
            "ok": False,
            "established": False,
            "blockers": [payload_blocker],
            "paths": [],
        }
    if payload_status == "valid":
        return {"ok": True, "established": False, "blockers": [], "paths": []}
    now = _iso_utc()
    inherited: list[dict[str, Any]] = []
    if classify_inherited:
        anchor = resolve_accepted_anchor(host)
        if not anchor.get("ok"):
            return {
                "ok": False,
                "established": False,
                "blockers": list(anchor.get("blockers") or [
                    "accepted physical authority is UNKNOWN"
                ]),
                "paths": [],
            }
        provenance = host_wide_observed_success(host)
        for row in accepted_physical_diffs(host, anchor):
            if _current_byte_attributed(row, provenance):
                continue
            inherited.append(
                _fact_row(
                    row,
                    classification=CLASS_INHERITED_INIT,
                    accepted_kind=str(anchor.get("kind") or ""),
                    accepted_revision=str(anchor.get("revision") or ""),
                    boundary="open",
                    observed_at=now,
                )
            )
    payload = _record_payload(
        initialization={"completed": True, "completed_at": now},
        paths=inherited,
    )
    _persist(host, payload)
    return {
        "ok": True,
        "established": True,
        "blockers": [],
        "paths": list(payload["paths"]),
    }


def accepted_physical_diffs(
    root: Path, anchor: dict[str, Any]
) -> list[dict[str, Any]]:
    """Delta vs accepted truth. Not a whole-workspace duplicate inventory."""
    if str(anchor.get("kind") or "") == "git":
        return _git_accepted_diffs(root)
    inventory = anchor.get("inventory")
    if not isinstance(inventory, dict):
        return []
    from scaffold_p8.noscms import compare_workspace

    rows: list[dict[str, Any]] = []
    for entry in compare_workspace(root, inventory):
        path = _norm_path(str(entry.get("path") or ""))
        if not path or _ignored_physical_path(path):
            continue
        rows.append(_current_row(root, path))
    return rows


def host_wide_observed_success(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Trustworthy mutation provenance from any surviving Session, including ABORTED.

    authorized_pending / failed / cancelled are not provenance. ABORTED
    observed_success is attribution only, never DEVELOP_KNOWN.
    """
    folder = root / SESSIONS_DIR
    out: dict[str, list[dict[str, Any]]] = {}
    if not folder.is_dir():
        return out
    for directory in folder.iterdir():
        if not directory.is_dir():
            continue
        files, issues = load_files_yaml(directory)
        if issues or files is None:
            continue
        session_id = directory.name
        status = _session_status(directory)
        for item in files:
            if not isinstance(item, dict):
                continue
            if not _is_observed_success(item):
                continue
            path = _norm_path(str(item.get("path") or ""))
            if not path:
                continue
            kind, digest = _manifest_after(item)
            out.setdefault(path, []).append(
                {
                    "session_id": session_id,
                    "session_status": status,
                    "kind": kind,
                    "digest": digest,
                }
            )
    return out


def _git_accepted_diffs(root: Path) -> list[dict[str, Any]]:
    scm = observe_scm(root)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in scm.entries:
        for key in ("path", "orig_path"):
            path = _norm_path(str(entry.get(key) or ""))
            if not path or path in seen or _ignored_physical_path(path):
                continue
            seen.add(path)
            rows.append(_current_row(root, path))
    return rows


def _current_row(root: Path, rel: str) -> dict[str, Any]:
    dest = root / rel
    kind = path_kind(dest)
    if kind != KIND_FILE:
        return {"path": rel, "kind": KIND_MISSING, "digest": None}
    return {"path": rel, "kind": KIND_FILE, "digest": file_sha256(dest)}


def _current_byte_attributed(
    row: dict[str, Any], provenance: dict[str, list[dict[str, Any]]]
) -> bool:
    current = (row.get("kind"), row.get("digest"))
    for item in provenance.get(row["path"]) or []:
        if (item.get("kind"), item.get("digest")) == current:
            return True
    return False


def _is_observed_success(item: dict[str, Any]) -> bool:
    state = str(item.get("mutation_state") or "").strip()
    if state in {"authorized_pending", "failed", "cancelled"}:
        return False
    if state == MUTATION_OBSERVED:
        return True
    if item.get("change_kind") == "deleted":
        return True
    if item.get("after_kind") == KIND_MISSING and not item.get("after_digest"):
        return False
    return isinstance(item.get("after_digest"), str) and bool(item.get("after_digest"))


def _manifest_after(item: dict[str, Any]) -> tuple[str, str | None]:
    if item.get("change_kind") == "deleted" or item.get("after_kind") == KIND_MISSING:
        return KIND_MISSING, None
    digest = item.get("after_digest")
    if isinstance(digest, str) and digest:
        return KIND_FILE, digest if digest.startswith("sha256:") else "sha256:" + digest
    return KIND_FILE, None


def _row_state(row: dict[str, Any]) -> tuple[str, str | None]:
    kind = str(row.get("kind") or KIND_MISSING)
    digest = row.get("digest")
    if isinstance(digest, str) and digest:
        if not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        return kind, digest
    return kind, None


def _fact_row(
    physical: dict[str, Any],
    *,
    classification: str,
    accepted_kind: str,
    accepted_revision: str,
    boundary: str,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "path": physical["path"],
        "kind": physical["kind"],
        "digest": physical.get("digest"),
        "accepted_kind": accepted_kind,
        "accepted_revision": accepted_revision,
        "classification": classification,
        "first_observed_boundary": boundary,
        "first_observed_at": observed_at,
    }


def _record_payload(
    *,
    initialization: dict[str, Any],
    paths: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(paths, key=lambda row: str(row.get("path") or ""))
    return {
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "initialization": {
            "completed": bool(initialization.get("completed")),
            "completed_at": str(initialization.get("completed_at") or ""),
        },
        "paths": ordered,
    }


def _persist(root: Path, payload: dict[str, Any]) -> None:
    write_yaml_atomic(root / UNEXPLAINED_REL, payload)


def _project_generation(root: Path) -> tuple[str, str]:
    """Read the tracked project contract generation. Unreadable is never absent."""
    path = root / PROJECT_YAML_REL
    if not path.is_file():
        return "unusable", ""
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return "unusable", ""
    if not isinstance(data, dict):
        return "unusable", ""
    raw = data.get("project_contract_generation")
    generation = str(raw).strip() if raw is not None else ""
    if not generation or _generation_rank(generation) is None:
        return "unusable", ""
    return "ok", generation


def _generation_rank(generation: str) -> int | None:
    try:
        return int(str(generation).strip())
    except (TypeError, ValueError):
        return None


def _boundary_consumed(generation: str) -> bool:
    rank = _generation_rank(generation)
    boundary = _generation_rank(COMPATIBILITY_BOUNDARY_GENERATION)
    if rank is None or boundary is None:
        return False
    return rank >= boundary


def _load_unexplained_payload(root: Path) -> tuple[str, dict[str, Any] | None, str]:
    path = root / UNEXPLAINED_REL
    if not path.is_file():
        return "absent", None, ""
    try:
        payload = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return "unusable", None, "unexplained drift authority is unreadable"
    if not isinstance(payload, dict):
        return "unusable", None, "unexplained drift authority is malformed"
    if str(payload.get("record_type") or "") != RECORD_TYPE:
        return "unusable", None, "unexplained drift authority has a foreign record_type"
    if str(payload.get("schema_version") or "") != SCHEMA_VERSION:
        return "unusable", None, "unexplained drift authority schema is invalid"
    if not isinstance(payload.get("paths"), list):
        return "unusable", None, "unexplained drift authority paths are unusable"
    return "valid", payload, ""


def _unusable_authority(blocker: str) -> dict[str, Any]:
    return {
        "state": STATE_AUTHORITY_UNUSABLE,
        "ok": False,
        "blockers": [blocker],
        "payload": None,
    }


def _session_status(directory: Path) -> str:
    path = directory / "session.yaml"
    if not path.is_file():
        return ""
    try:
        session = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return ""
    if not isinstance(session, dict):
        return ""
    return str(session.get("status") or "")


def _noscms_revision(inventory: dict[str, Any], loaded: dict[str, Any]) -> str:
    explicit = loaded.get("representation_digest") or loaded.get("inventory_digest")
    if isinstance(explicit, str) and explicit:
        return explicit
    parts = []
    for path in sorted(inventory):
        row = inventory.get(path) or {}
        if not isinstance(row, dict):
            continue
        parts.append(f"{path}:{row.get('kind')}:{row.get('digest')}")
    return sha256_text("\n".join(parts))


def _ignored_physical_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if is_ext_support_path(normalized):
        return True
    if normalized in CORE_MACHINE_ARTIFACTS:
        return True
    if any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in _CANONICAL_AUTHORITY_PREFIXES
    ):
        return True
    if normalized.endswith(".pyc") or "/__pycache__/" in f"/{normalized}":
        return True
    return False


def _norm_path(rel: str) -> str:
    return rel.replace("\\", "/").strip().strip("/")


def _iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

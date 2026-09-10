"""True no-SCM baseline, physical Diff, and exact publication support.

Not a fourth canonical record. Lives only under `.scaffold/ext/submit/`.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Iterator

from scaffold_p5.io_util import file_digest, read_yaml, sha256_bytes, write_yaml_atomic
from scaffold_p5.ownership import resolve_ownership
from scaffold_p5.scm import observe_scm
from scaffold_p6.candidate import RUNTIME_PREFIX, observe_candidate
from scaffold_p8.schemas import (
    CHANGE_ID_RE,
    HEX_DIGEST_RE,
    noscms_lineage_shape_issues,
    validate_finalization_marker,
)


SUBMIT_EXT_PREFIX = ".scaffold/ext/submit/"
NOSCMS_ROOT = ".scaffold/ext/submit/noscms"
BASELINE_REL = ".scaffold/ext/submit/noscms/baseline.yaml"
PUBLICATIONS_REL = ".scaffold/ext/submit/noscms/publications"
OBJECTS_DIRNAME = "objects"
COMPLETE_NAME = "COMPLETE.yaml"
MANIFEST_NAME = "manifest.yaml"
HEAD_LOCK_REL = ".scaffold/runtime/submit-noscms-head.lock"
FORBIDDEN_FINALIZATIONS_DIR = ".scaffold/finalizations"
KIND_FILE = "regular_file"
KIND_DIRECTORY = "directory"

CHANGE_ADDED = "added"
CHANGE_MODIFIED = "modified"
CHANGE_DELETED = "deleted"
CHANGE_TYPE_CHANGED = "type_changed"
LINEAGE_FIELDS = (
    "baseline_generation",
    "parent_generation",
    "parent_representation_digest",
    "parent_change_id",
)


def is_noscms_support_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if normalized.startswith(SUBMIT_EXT_PREFIX) or normalized == ".scaffold/ext/submit":
        return True
    if normalized.endswith(".pyc") or "/__pycache__/" in f"/{normalized}":
        return True
    return False


def submit_namespace_write_allowed(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    return normalized == ".scaffold/ext/submit" or normalized.startswith(SUBMIT_EXT_PREFIX)


def initialize_noscms_baseline(root: Path) -> dict[str, Any]:
    scm = observe_scm(root)
    if scm.kind == "git":
        return {
            "ok": False,
            "blockers": ["Git host cannot initialize a no-SCM baseline"],
        }
    owned = _submit_namespace_owned(root)
    if not owned["ok"]:
        return owned
    inventory = inventory_workspace(root)
    payload = {
        "kind": "noscms_baseline",
        "record_class": "support_artifact",
        "schema_version": "1",
        "inventory": _sorted_inventory(inventory),
    }
    write_yaml_atomic(root / BASELINE_REL, payload)
    return {
        "ok": True,
        "path": BASELINE_REL,
        "path_count": len(inventory),
        "inventory_digest": _inventory_digest(inventory),
    }


def load_noscms_baseline(root: Path) -> dict[str, Any]:
    head = _resolve_committed_head(root)
    if head.get("status") == "ok":
        return {key: value for key, value in head.items() if key != "status"}
    if head.get("status") == "unknown":
        return {
            "ok": False,
            "present": True,
            "baseline_required": False,
            "observation_state": "UNKNOWN",
            "blockers": list(head.get("blockers") or [
                "no-SCM committed baseline head is UNKNOWN"
            ]),
        }
    return _load_baseline_file(root)


def observe_noscms_diff(root: Path) -> dict[str, Any]:
    scm = observe_scm(root)
    if scm.kind == "git":
        return {
            "ok": False,
            "kind": "git",
            "blockers": ["Git host cannot use the no-SCM Diff path"],
        }
    loaded = load_noscms_baseline(root)
    if not loaded.get("ok"):
        return {
            "ok": False,
            "kind": "none",
            "observation_state": "UNKNOWN",
            "observation_ok": False,
            "entries": [],
            "paths": [],
            "pathspecs": [],
            "project_root": ".",
            "scm_root": None,
            "blockers": list(loaded.get("blockers") or ["no-SCM baseline is UNKNOWN"]),
            "baseline_required": loaded.get("baseline_required", True),
        }
    entries = compare_workspace(root, loaded["inventory"])
    paths = sorted(
        {
            str(row.get("path") or "")
            for row in entries
            if row.get("path")
        }
    )
    return {
        "ok": True,
        "kind": "none",
        "observation_state": scm.observation_state,
        "observation_ok": True,
        "entries": entries,
        "paths": paths,
        "pathspecs": paths,
        "project_root": ".",
        "scm_root": None,
        "blockers": [],
        "baseline_required": False,
    }


def inventory_workspace(root: Path) -> dict[str, dict[str, str]]:
    inventory: dict[str, dict[str, str]] = {}
    if not root.exists():
        return inventory
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in {".git", "__pycache__"}
            and not is_noscms_support_path(
                str((Path(dirpath) / name).relative_to(root)).replace("\\", "/")
            )
        ]
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root)).replace("\\", "/")
            if is_noscms_support_path(rel):
                continue
            if full.is_file() and not full.is_symlink():
                inventory[rel] = {
                    "kind": KIND_FILE,
                    "digest": file_digest(full),
                }
    return inventory


def compare_workspace(
    root: Path, baseline: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    current_files = inventory_workspace(root)
    current_paths = set(current_files)
    baseline_paths = set(baseline)
    entries: list[dict[str, Any]] = []
    for path in sorted(baseline_paths | current_paths):
        before = baseline.get(path)
        after_file = current_files.get(path)
        physical = root / path
        if before and before.get("kind") == KIND_FILE and physical.is_dir():
            entries.append(
                {"path": path, "orig_path": "", "change": CHANGE_TYPE_CHANGED}
            )
            continue
        if before and after_file:
            if after_file.get("digest") != before.get("digest"):
                entries.append(
                    {"path": path, "orig_path": "", "change": CHANGE_MODIFIED}
                )
            continue
        if before and not after_file:
            entries.append({"path": path, "orig_path": "", "change": CHANGE_DELETED})
            continue
        if after_file and not before:
            entries.append({"path": path, "orig_path": "", "change": CHANGE_ADDED})
    return entries


def publication_dir(root: Path, record_id: str) -> Path:
    return root / PUBLICATIONS_REL / record_id


def complete_path(root: Path, record_id: str) -> Path:
    return publication_dir(root, record_id) / COMPLETE_NAME


def publish_noscms_finalization(
    root: Path,
    *,
    record_id: str,
    candidate_digest: str,
    change_record_digest: str,
    support_artifacts: list[dict[str, str]],
    marker: dict[str, Any],
    during_s10: Any = None,
    fail_before_complete: bool = False,
    fail_baseline_cache: bool = False,
) -> dict[str, Any]:
    owned = _submit_namespace_owned(root)
    if not owned["ok"]:
        return {"ok": False, "durable": False, "blockers": owned["blockers"]}
    try:
        with _noscms_head_lock(root):
            return _publish_noscms_locked(
                root,
                record_id=record_id,
                candidate_digest=candidate_digest,
                change_record_digest=change_record_digest,
                support_artifacts=support_artifacts,
                marker=marker,
                during_s10=during_s10,
                fail_before_complete=fail_before_complete,
                fail_baseline_cache=fail_baseline_cache,
            )
    except OSError as exc:
        return {
            "ok": False,
            "durable": False,
            "blockers": [
                f"no-SCM publication lock could not be established: {exc}"
            ],
        }


def _publish_noscms_locked(
    root: Path,
    *,
    record_id: str,
    candidate_digest: str,
    change_record_digest: str,
    support_artifacts: list[dict[str, str]],
    marker: dict[str, Any],
    during_s10: Any = None,
    fail_before_complete: bool = False,
    fail_baseline_cache: bool = False,
) -> dict[str, Any]:
    bind = _bind_publication_lineage(root)
    if not bind.get("ok"):
        return {
            "ok": False,
            "durable": False,
            "blockers": list(bind.get("blockers") or [
                "no-SCM publication cannot bind to the current baseline head"
            ]),
        }
    inventory = inventory_workspace(root)
    pub = publication_dir(root, record_id)
    objects = pub / OBJECTS_DIRNAME
    objects.mkdir(parents=True, exist_ok=True)
    representation_digest = ""
    try:
        for rel, row in inventory.items():
            digest = row["digest"]
            _write_bytes_atomic(objects / digest, (root / rel).read_bytes())
        representation_digest = _inventory_digest(inventory)
        lineage = {
            "baseline_generation": bind["next_generation"],
            "parent_generation": bind["parent_generation"],
            "parent_representation_digest": bind["parent_representation_digest"],
            "parent_change_id": bind["parent_change_id"],
        }
        manifest = {
            "kind": "noscms_publication_manifest",
            "record_class": "support_artifact",
            "change_id": record_id,
            "candidate_digest": candidate_digest,
            "change_record_digest": change_record_digest,
            "inventory": _sorted_inventory(inventory),
            "representation_digest": representation_digest,
            **lineage,
        }
        write_yaml_atomic(pub / MANIFEST_NAME, manifest)
        if callable(during_s10):
            during_s10()
        current = inventory_workspace(root)
        if _inventory_digest(current) != representation_digest:
            _remove_incomplete_publication(pub)
            return {
                "ok": False,
                "durable": False,
                "blockers": [
                    "workspace changed during no-SCM publication; "
                    "stale candidate was not published"
                ],
            }
        current_candidate = observe_candidate(root)
        if (
            not current_candidate.usable
            or current_candidate.digest != candidate_digest
        ):
            _remove_incomplete_publication(pub)
            return {
                "ok": False,
                "durable": False,
                "blockers": [
                    "workspace changed during no-SCM publication; "
                    "stale candidate was not published"
                ],
            }
        if fail_before_complete:
            _remove_incomplete_publication(pub)
            return {
                "ok": False,
                "durable": False,
                "blockers": [
                    "no-SCM publication failed before the durable completion boundary"
                ],
            }
        current_bind = _bind_publication_lineage(root)
        if not current_bind.get("ok") or _lineage_bind_key(current_bind) != _lineage_bind_key(bind):
            _remove_incomplete_publication(pub)
            return {
                "ok": False,
                "durable": False,
                "blockers": [
                    "no-SCM baseline head changed before COMPLETE; "
                    "stale publication lineage was not committed"
                ],
            }
        marker_payload = dict(marker)
        marker_payload["representation_digest"] = representation_digest
        marker_payload.update(lineage)
        write_yaml_atomic(complete_path(root, record_id), marker_payload)
        if fail_baseline_cache:
            raise OSError("injected no-SCM baseline cache write failure")
        _write_baseline_cache(
            root,
            current,
            record_id=record_id,
            baseline_generation=bind["next_generation"],
        )
        return _committed_publication_result(
            root, record_id, representation_digest
        )
    except OSError as exc:
        committed = _committed_publication_result(
            root, record_id, representation_digest
        )
        if committed.get("ok"):
            return committed
        _remove_incomplete_publication(pub)
        return {
            "ok": False,
            "durable": False,
            "blockers": [f"no-SCM publication I/O failed: {exc}"],
        }


def _marker_manifest_binding_blockers(
    marker: dict[str, Any], manifest: dict[str, Any]
) -> list[str]:
    blockers: list[str] = []
    if str(marker.get("change_id") or "") != str(manifest.get("change_id") or ""):
        blockers.append("COMPLETE marker change_id does not bind the publication manifest")
    marker_rep = marker.get("representation_digest")
    manifest_rep = manifest.get("representation_digest")
    if (
        isinstance(marker_rep, str)
        and marker_rep
        and isinstance(manifest_rep, str)
        and manifest_rep
        and marker_rep != manifest_rep
    ):
        blockers.append(
            "COMPLETE marker representation_digest does not bind the publication manifest"
        )
    marker_candidate = marker.get("candidate_digest")
    manifest_candidate = manifest.get("candidate_digest")
    if (
        isinstance(marker_candidate, str)
        and marker_candidate
        and isinstance(manifest_candidate, str)
        and manifest_candidate
        and marker_candidate != manifest_candidate
    ):
        blockers.append(
            "COMPLETE marker candidate_digest does not bind the publication manifest"
        )
    marker_record = marker.get("change_record_digest")
    manifest_record = manifest.get("change_record_digest")
    if (
        isinstance(marker_record, str)
        and marker_record
        and isinstance(manifest_record, str)
        and manifest_record
        and marker_record != manifest_record
    ):
        blockers.append(
            "COMPLETE marker change_record_digest does not bind the publication manifest"
        )
    return blockers


def verify_noscms_publication(
    root: Path,
    record_id: str,
    *,
    _stack: frozenset[str] | None = None,
) -> dict[str, Any]:
    marker_path = complete_path(root, record_id)
    if not marker_path.is_file():
        return {
            "ok": False,
            "durable": False,
            "blockers": ["no-SCM publication COMPLETE marker is missing"],
        }
    try:
        marker = read_yaml(marker_path)
        manifest = read_yaml(publication_dir(root, record_id) / MANIFEST_NAME)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "durable": False,
            "blockers": ["no-SCM publication support is malformed or unreadable"],
        }
    if not isinstance(marker, dict) or not isinstance(manifest, dict):
        return {
            "ok": False,
            "durable": False,
            "blockers": ["no-SCM publication support is malformed"],
        }
    marker_issues = validate_finalization_marker(marker, expected_id=record_id)
    if marker_issues:
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": [
                "no-SCM COMPLETE marker is not valid completion authority"
            ] + marker_issues,
            "marker": marker,
        }
    if marker.get("scm_kind") != "none":
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": ["no-SCM COMPLETE marker scm_kind must be none"],
            "marker": marker,
        }
    lineage_issues = noscms_publication_lineage_issues(marker)
    if lineage_issues:
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": lineage_issues,
            "marker": marker,
        }
    parent_issues = _parent_publication_lineage_issues(
        root,
        record_id,
        marker,
        _stack=_stack,
    )
    if parent_issues:
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": parent_issues,
            "marker": marker,
        }
    binding_blockers = _marker_manifest_binding_blockers(marker, manifest)
    if binding_blockers:
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": binding_blockers,
            "marker": marker,
        }
    inventory = manifest.get("inventory")
    if not isinstance(inventory, dict):
        return {
            "ok": False,
            "durable": False,
            "blockers": ["no-SCM publication manifest inventory is malformed"],
        }
    objects = publication_dir(root, record_id) / OBJECTS_DIRNAME
    blockers: list[str] = []
    reconstructed: dict[str, dict[str, str]] = {}
    for path, row in inventory.items():
        if not isinstance(path, str) or not isinstance(row, dict):
            blockers.append("publication inventory entry is malformed")
            continue
        kind = str(row.get("kind") or "")
        if kind != KIND_FILE:
            continue
        digest = str(row.get("digest") or "")
        blob = objects / digest
        if not blob.is_file():
            blockers.append(f"publication object is missing for {path}")
            continue
        actual = file_digest(blob)
        if actual != digest:
            blockers.append(f"publication object integrity does not hold for {path}")
            continue
        reconstructed[path] = {"kind": KIND_FILE, "digest": digest}
    expected = str(marker.get("representation_digest") or "")
    actual_digest = _inventory_digest(reconstructed)
    if expected and expected != actual_digest:
        blockers.append("publication representation digest does not match stored objects")
    if blockers:
        return {
            "ok": False,
            "durable": False,
            "observation_state": "UNKNOWN",
            "blockers": blockers,
            "marker": marker,
        }
    return {
        "ok": True,
        "durable": True,
        "marker": marker,
        "manifest": manifest,
        "representation_digest": actual_digest,
        "candidate_digest": marker.get("candidate_digest"),
    }


def _committed_publication_result(
    root: Path,
    record_id: str,
    representation_digest: str,
) -> dict[str, Any]:
    if not complete_path(root, record_id).is_file():
        return {"ok": False, "durable": False, "blockers": ["COMPLETE is absent"]}
    verified = verify_noscms_publication(root, record_id)
    if not verified.get("ok"):
        return {
            "ok": False,
            "durable": False,
            "blockers": list(verified.get("blockers") or [
                "no-SCM durable publication did not verify after write"
            ]),
        }
    resolved = load_noscms_baseline(root)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "durable": False,
            "blockers": list(resolved.get("blockers") or [
                "committed no-SCM publication did not resolve a finalized baseline"
            ]),
        }
    actual = _inventory_digest(resolved["inventory"])
    if representation_digest and actual != representation_digest:
        return {
            "ok": False,
            "durable": False,
            "blockers": [
                "committed publication does not resolve the finalized no-SCM baseline"
            ],
        }
    return {
        "ok": True,
        "durable": True,
        "representation_digest": verified.get("representation_digest"),
        "publication_path": complete_path(root, record_id)
        .relative_to(root)
        .as_posix(),
        "baseline_source": resolved.get("source"),
    }


def _resolve_committed_head(root: Path) -> dict[str, Any]:
    folder = root / PUBLICATIONS_REL
    if not folder.is_dir():
        return {"status": "absent"}
    lineage_pubs: list[dict[str, Any]] = []
    claimed = False
    for child in folder.iterdir():
        if not child.is_dir():
            continue
        if not complete_path(root, child.name).is_file():
            continue
        claimed = True
        verified = verify_noscms_publication(root, child.name)
        if not verified.get("ok"):
            return {
                "status": "unknown",
                "blockers": list(verified.get("blockers") or [
                    "no-SCM committed publication is unverifiable"
                ]) + [
                    "no-SCM committed publication is unverifiable; "
                    "baseline cache cannot substitute"
                ],
            }
        marker = verified.get("marker") or {}
        if not isinstance(marker, dict) or not _has_lineage_keys(marker):
            return {
                "status": "unknown",
                "blockers": [
                    "no-SCM committed baseline head is UNKNOWN; "
                    "publication lineage is missing"
                ],
            }
        parsed = _parse_lineage(marker)
        if parsed is None:
            return {
                "status": "unknown",
                "blockers": [
                    "no-SCM committed baseline head is UNKNOWN; "
                    "publication lineage is malformed"
                ],
            }
        parsed_inventory, _reason = _parse_inventory(
            (verified.get("manifest") or {}).get("inventory")
        )
        if parsed_inventory is None:
            return {
                "status": "unknown",
                "blockers": [
                    "no-SCM committed baseline head is UNKNOWN; "
                    "publication inventory is malformed"
                ],
            }
        lineage_pubs.append(
            {
                "change_id": child.name,
                "inventory": parsed_inventory,
                "representation_digest": str(
                    verified.get("representation_digest") or ""
                ),
                **parsed,
            }
        )
    if not lineage_pubs:
        if claimed:
            return {
                "status": "unknown",
                "blockers": [
                    "no-SCM committed publication authority exists but "
                    "could not be verified"
                ],
            }
        return {"status": "absent"}
    return _unique_head_from_lineage(lineage_pubs)


def _unique_head_from_lineage(pubs: list[dict[str, Any]]) -> dict[str, Any]:
    by_generation: dict[int, list[dict[str, Any]]] = {}
    for pub in pubs:
        by_generation.setdefault(pub["baseline_generation"], []).append(pub)
    if any(len(group) != 1 for group in by_generation.values()):
        return {
            "status": "unknown",
            "blockers": [
                "no-SCM committed baseline head is UNKNOWN; "
                "duplicate publication generation"
            ],
        }
    generations = set(by_generation)
    max_generation = max(generations)
    if generations != set(range(1, max_generation + 1)):
        return {
            "status": "unknown",
            "blockers": [
                "no-SCM committed baseline head is UNKNOWN; "
                "publication lineage is not a unique chain"
            ],
        }
    for generation in range(1, max_generation + 1):
        pub = by_generation[generation][0]
        if generation == 1:
            if pub["parent_generation"] != 0 or pub["parent_change_id"] != "":
                return {
                    "status": "unknown",
                    "blockers": [
                        "no-SCM committed baseline head is UNKNOWN; "
                        "lineage root is not unique"
                    ],
                }
            continue
        parent = by_generation[generation - 1][0]
        if (
            pub["parent_generation"] != generation - 1
            or pub["parent_change_id"] != parent["change_id"]
            or pub["parent_representation_digest"]
            != parent["representation_digest"]
        ):
            return {
                "status": "unknown",
                "blockers": [
                    "no-SCM committed baseline head is UNKNOWN; "
                    "publication parent identity does not match the prior commit"
                ],
            }
    head = by_generation[max_generation][0]
    return {
        "status": "ok",
        "ok": True,
        "present": True,
        "inventory": head["inventory"],
        "source": "publication",
        "change_id": head["change_id"],
        "baseline_generation": head["baseline_generation"],
        "representation_digest": head["representation_digest"],
        "data": {
            "kind": "noscms_baseline",
            "record_class": "support_artifact",
            "schema_version": "1",
            "source": "publication",
            "change_id": head["change_id"],
            "baseline_generation": head["baseline_generation"],
            "inventory": _sorted_inventory(head["inventory"]),
        },
    }


def _bind_publication_lineage(root: Path) -> dict[str, Any]:
    head = _resolve_committed_head(root)
    if head.get("status") == "unknown":
        return {
            "ok": False,
            "blockers": list(head.get("blockers") or [
                "no-SCM committed baseline head is UNKNOWN"
            ]),
        }
    if head.get("status") == "ok":
        generation = head.get("baseline_generation")
        if type(generation) is not int:
            return {
                "ok": False,
                "blockers": [
                    "committed no-SCM head is missing baseline generation"
                ],
            }
        return {
            "ok": True,
            "parent_generation": generation,
            "parent_representation_digest": head["representation_digest"],
            "parent_change_id": head["change_id"],
            "next_generation": generation + 1,
        }
    file_baseline = _load_baseline_file(root)
    if not file_baseline.get("ok"):
        return {
            "ok": False,
            "blockers": list(file_baseline.get("blockers") or [
                "no-SCM baseline is missing; explicit initialization is required"
            ]),
        }
    return {
        "ok": True,
        "parent_generation": 0,
        "parent_representation_digest": _inventory_digest(file_baseline["inventory"]),
        "parent_change_id": "",
        "next_generation": 1,
    }


def noscms_publication_lineage_issues(marker: Any) -> list[str]:
    """Canonical no-SCM lineage shape for durability. Missing fields are UNKNOWN."""
    if not isinstance(marker, dict):
        return ["no-SCM publication lineage is malformed"]
    missing = [field for field in LINEAGE_FIELDS if field not in marker]
    if missing:
        return [
            "no-SCM publication lineage is missing; COMPLETE is not durable"
        ]
    return noscms_lineage_shape_issues(marker)


def _parent_publication_lineage_issues(
    root: Path,
    record_id: str,
    marker: dict[str, Any],
    *,
    _stack: frozenset[str] | None = None,
) -> list[str]:
    parsed = _parse_lineage(marker)
    if parsed is None:
        return ["no-SCM publication lineage is malformed"]
    if parsed["parent_generation"] == 0:
        return []
    parent_id = parsed["parent_change_id"]
    if parent_id == record_id:
        return ["no-SCM publication parent identity is circular"]
    seen = set(_stack or ())
    if record_id in seen:
        return ["no-SCM publication lineage is circular"]
    if parent_id in seen:
        return ["no-SCM publication parent lineage is circular"]
    parent = verify_noscms_publication(
        root,
        parent_id,
        _stack=frozenset(seen | {record_id}),
    )
    if not parent.get("ok") or not parent.get("durable"):
        return list(parent.get("blockers") or []) + [
            "no-SCM publication parent is not a durable lineage predecessor"
        ]
    actual = str(parent.get("representation_digest") or "")
    expected = parsed["parent_representation_digest"]
    if actual != expected:
        return [
            "no-SCM publication parent representation digest does not match "
            "the durable parent"
        ]
    return []


def _has_lineage_keys(marker: dict[str, Any]) -> bool:
    return not (set(LINEAGE_FIELDS) - set(marker))


def _parse_lineage(marker: dict[str, Any]) -> dict[str, Any] | None:
    if noscms_publication_lineage_issues(marker):
        return None
    return {
        "baseline_generation": marker["baseline_generation"],
        "parent_generation": marker["parent_generation"],
        "parent_representation_digest": marker["parent_representation_digest"],
        "parent_change_id": marker["parent_change_id"],
    }


def _lineage_bind_key(bind: dict[str, Any]) -> tuple[Any, ...]:
    return (
        bind.get("next_generation"),
        bind.get("parent_generation"),
        bind.get("parent_representation_digest"),
        bind.get("parent_change_id"),
    )


def _load_baseline_file(root: Path) -> dict[str, Any]:
    path = root / BASELINE_REL
    if not path.is_file():
        return {
            "ok": False,
            "present": False,
            "blockers": [
                "no-SCM baseline is missing; explicit initialization is required"
            ],
        }
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "present": True,
            "blockers": ["no-SCM baseline is malformed or unreadable"],
        }
    if not isinstance(data, dict) or data.get("kind") != "noscms_baseline":
        return {
            "ok": False,
            "present": True,
            "blockers": ["no-SCM baseline support artifact is malformed"],
        }
    parsed, reason = _parse_inventory(data.get("inventory"))
    if parsed is None:
        return {
            "ok": False,
            "present": True,
            "blockers": [reason or "no-SCM baseline inventory is malformed"],
        }
    return {
        "ok": True,
        "present": True,
        "inventory": parsed,
        "source": "file",
        "data": data,
    }


def _parse_inventory(raw: Any) -> tuple[dict[str, dict[str, str]] | None, str]:
    if not isinstance(raw, dict):
        return None, "no-SCM baseline inventory is malformed"
    inventory: dict[str, dict[str, str]] = {}
    for path_key, row in raw.items():
        if not isinstance(path_key, str) or not isinstance(row, dict):
            return None, "no-SCM baseline inventory entry is malformed"
        kind = str(row.get("kind") or "")
        if kind not in {KIND_FILE, KIND_DIRECTORY}:
            return None, f"no-SCM baseline kind is UNKNOWN for {path_key}"
        entry = {"kind": kind}
        if kind == KIND_FILE:
            digest = str(row.get("digest") or "")
            if len(digest) != 64:
                return None, f"no-SCM baseline digest is malformed for {path_key}"
            entry["digest"] = digest
        inventory[path_key.replace("\\", "/")] = entry
    return inventory, ""


def _write_baseline_cache(
    root: Path,
    inventory: dict[str, dict[str, str]],
    *,
    record_id: str,
    baseline_generation: int | None = None,
) -> None:
    payload = {
        "kind": "noscms_baseline",
        "record_class": "support_artifact",
        "schema_version": "1",
        "source": "publication_cache",
        "change_id": record_id,
        "inventory": _sorted_inventory(inventory),
    }
    if type(baseline_generation) is int:
        payload["baseline_generation"] = baseline_generation
    write_yaml_atomic(root / BASELINE_REL, payload)


def _submit_namespace_owned(root: Path) -> dict[str, Any]:
    project_path = root / ".scaffold/project.yaml"
    if not project_path.is_file():
        return {"ok": True}
    try:
        project = read_yaml(project_path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "ok": False,
            "blockers": ["project.yaml is unreadable; Submit cannot write ext/submit"],
        }
    ownership = (project or {}).get("ownership") if isinstance(project, dict) else {}
    if not isinstance(ownership, dict):
        return {
            "ok": False,
            "blockers": ["project ownership registry is malformed"],
        }
    resolved = resolve_ownership(ownership, SUBMIT_EXT_PREFIX)
    if resolved.status != "RESOLVED" or resolved.mode not in {"GENERATED", "MANAGED"}:
        return {
            "ok": False,
            "blockers": [
                "Submit no-SCM support requires GENERATED or MANAGED ownership "
                "for .scaffold/ext/submit/"
            ],
        }
    return {"ok": True}


def _sorted_inventory(inventory: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return {path: dict(inventory[path]) for path in sorted(inventory)}


def _inventory_digest(inventory: dict[str, dict[str, str]]) -> str:
    parts: list[str] = []
    for path in sorted(inventory):
        row = inventory[path]
        parts.append(f"{path}\n{row.get('kind')}\n{row.get('digest') or ''}")
    return sha256_bytes(*(item.encode("utf-8") for item in parts)) if parts else sha256_bytes(b"empty")


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _remove_incomplete_publication(pub: Path) -> None:
    complete = pub / COMPLETE_NAME
    if complete.is_file():
        return
    for dirpath, dirnames, filenames in os.walk(pub, topdown=False):
        for name in filenames:
            try:
                (Path(dirpath) / name).unlink()
            except OSError:
                continue
        for name in dirnames:
            try:
                (Path(dirpath) / name).rmdir()
            except OSError:
                continue
    try:
        pub.rmdir()
    except OSError:
        pass


@contextlib.contextmanager
def _noscms_head_lock(root: Path) -> Iterator[None]:
    lock_path = root / HEAD_LOCK_REL
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"*")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

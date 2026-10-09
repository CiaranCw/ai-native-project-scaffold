"""S9 Change Record finalization. Candidate only until successful S10."""

from __future__ import annotations

import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import scm_baseline
from scaffold_p5.io_util import file_digest, read_yaml, sha256_text, write_yaml_atomic
from scaffold_p5 import yaml_lite
from scaffold_p5.scm import observe_scm, project_to_worktree_path

from scaffold_p8.models import CHANGES_DIR, PROVENANCE_CLASSES, RECORD_SCHEMA_VERSION
from scaffold_p8.noscms import complete_path, verify_noscms_publication, PUBLICATIONS_REL
from scaffold_p8.schemas import (
    CHANGE_ID_RE,
    TASK_ID_RE,
    validate_change_record,
    validate_finalization_marker,
)


def new_change_id(root: Path) -> str:
    used = {path.stem for path in (root / CHANGES_DIR).glob("*.yaml")} if (
        root / CHANGES_DIR
    ).is_dir() else set()
    utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for _ in range(32):
        candidate = f"change-{utc}-{secrets.token_hex(4)}"
        if candidate not in used:
            return candidate
        utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raise RuntimeError("unable to allocate a unique Change Record id")


def change_path(root: Path, record_id: str) -> Path:
    return root / CHANGES_DIR / f"{record_id}.yaml"


def is_durable(root: Path, record_id: str) -> bool:
    return durability_state(root, record_id)["state"] == "durable"


def durability_state(root: Path, record_id: str) -> dict[str, Any]:
    if observe_scm(root).kind == "git":
        return _git_durability_state(root, record_id)
    verified = verify_noscms_publication(root, record_id)
    if not verified.get("ok"):
        if not complete_path(root, record_id).exists():
            return {"state": "absent"}
        payload = {
            "state": "malformed",
            "blockers": list(verified.get("blockers") or [
                "no-SCM publication is malformed"
            ]),
            "data": verified.get("marker"),
        }
        if verified.get("observation_state"):
            payload["observation_state"] = verified["observation_state"]
        return payload
    data = verified.get("marker") or {}
    issues = validate_finalization_marker(data, expected_id=record_id)
    if not issues and isinstance(data, dict):
        if data.get("scm_kind") != "none":
            issues.append("no-SCM host cannot use a Git finalization marker")
        expected_binding = finalization_binding(
            record_id,
            str(data.get("scm_kind")),
            str(data.get("candidate_digest")),
            str(data.get("change_record_digest")),
            list(data.get("support_artifacts") or []),
        )
        if data.get("finalization_digest") != expected_binding:
            issues.append("finalization binding digest does not match its fields")
    record = change_path(root, record_id)
    if not record.is_file():
        issues.append("finalization refers to a missing Change Record")
    elif isinstance(data, dict) and data.get("change_record_digest") != file_digest(record):
        issues.append("finalization Change Record digest does not match durable bytes")
    if isinstance(data, dict):
        for item in data.get("support_artifacts") or []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "")
            target = root / rel
            if not target.is_file() or file_digest(target) != item.get("digest"):
                issues.append(
                    f"finalization durable support integrity does not hold: {rel}"
                )
    if issues:
        return {"state": "malformed", "blockers": issues, "data": data}
    return {"state": "durable", "data": data}


def finalization_binding(
    record_id: str,
    scm_kind: str,
    candidate_digest: str,
    record_digest: str,
    support_artifacts: list[dict[str, Any]] | None = None,
) -> str:
    parts = [
        record_id,
        "\n",
        scm_kind,
        "\n",
        candidate_digest,
        "\n",
        record_digest,
    ]
    if support_artifacts:
        parts.extend([
            "\n",
            yaml_lite.dump({"support_artifacts": support_artifacts}),
        ])
    return sha256_text(*parts)


def load_change_record(root: Path, record_id: str) -> dict[str, Any] | None:
    path = change_path(root, record_id)
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def load_durable_change_record(root: Path, record_id: str) -> dict[str, Any] | None:
    """Load the Change Record that was durably finalized at S10, not live WT bytes."""
    if observe_scm(root).kind == "git":
        state = durability_state(root, record_id)
        if state.get("state") != "durable":
            return None
        data = state.get("data")
        if not isinstance(data, dict):
            return None
        if validate_change_record(data, expected_id=record_id):
            return None
        return data
    if not is_durable(root, record_id):
        return None
    return load_change_record(root, record_id)


def frozen_cleanup_session_ids(record: dict[str, Any] | None) -> list[str] | None:
    if not isinstance(record, dict):
        return None
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return None
    ids = provenance.get("relevant_develop_session_ids")
    if not isinstance(ids, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for item in ids:
        if not isinstance(item, str) or not item:
            return None
        if item in seen:
            return None
        seen.add(item)
        out.append(item)
    return out


def build_change_record(
    *,
    record_id: str,
    task: dict[str, Any] | None,
    real_paths: list[str],
    delta: dict[str, Any],
    structural: dict[str, Any],
    knowledge: dict[str, Any],
    completeness: dict[str, Any],
    candidate_kind: str,
    baseline_value: Any,
    diff_entries: list[dict[str, Any]] | None = None,
    relevant_session_count: int = 0,
    cleanup_session_ids: list[str] | None = None,
) -> dict[str, Any]:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record_task = task or {}
    task_ids = (
        [str(record_task["record_id"])]
        if record_task.get("record_id")
        else []
    )
    if diff_entries is None:
        diff_entries = [
            {"path": path, "change": "modified"} for path in real_paths
        ]
    paths = []
    for entry in diff_entries:
        path = str(entry.get("path") or "")
        if not path or path.startswith(".scaffold/changes/"):
            continue
        row = {
            "path": path,
            "change": str(entry.get("change") or "modified"),
        }
        old_path = str(entry.get("orig_path") or "")
        if row["change"] in {"renamed", "copied"} and old_path:
            row["old_path"] = old_path
        paths.append(row)
    counts = delta.get("counts") or {}
    frozen_ids: list[str] = []
    seen_ids: set[str] = set()
    for item in cleanup_session_ids or []:
        text = str(item)
        if not text or text in seen_ids:
            continue
        seen_ids.add(text)
        frozen_ids.append(text)
    frozen_ids = sorted(frozen_ids)
    return {
        "record_type": "change_record",
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "created_at": created,
        "summary": str(record_task.get("title") or "Reviewed candidate"),
        "base": {"kind": candidate_kind or "none", "value": baseline_value},
        "affected": _affected(record_task, real_paths),
        "path_summary": {
            "representation": "exact",
            "total_changed_paths": len(paths),
            "paths": paths,
        },
        "structural_summary": (
            "STRUCTURAL_REVIEW_PASS"
            if structural.get("structural_review_pass")
            else "STRUCTURAL_REVIEW_BLOCKED"
        ),
        "knowledge_updates": (
            "knowledge consistent"
            if knowledge.get("knowledge_consistent")
            else "stale knowledge"
        ),
        "verification": {
            "summary": (
                f"TEST_PASS={completeness.get('test_pass')} "
                f"TEST_COMPLETE={completeness.get('test_complete')}"
            ),
            "evidence_refs": [
                {"locator": str(ref.get("locator"))}
                for ref in completeness.get("evidence_refs") or []
                if isinstance(ref, dict) and ref.get("locator")
            ],
        },
        "understand_involvement": {
            "refresh": bool(knowledge.get("needs_refresh")),
            "compatibility": bool(knowledge.get("needs_migration")),
        },
        "task_book_ids": task_ids,
        "provenance": {
            "relevant_develop_session_count": relevant_session_count,
            "relevant_develop_session_ids": frozen_ids,
            "classes": {
                name: {"path_count": int(counts.get(name) or 0)}
                for name in PROVENANCE_CLASSES
            },
        },
        "limitations": (
            [] if task_ids else ["No Task Book governed this candidate"]
        ),
    }


def _affected(task: dict[str, Any], real_paths: list[str]) -> dict[str, list[str]]:
    if task.get("record_id"):
        scope = task.get("scope") if isinstance(task.get("scope"), dict) else {}
        return {
            "modules": list(scope.get("modules") or []),
            "areas": list(scope.get("paths") or []),
        }
    areas: list[str] = []
    seen: set[str] = set()
    for path in real_paths:
        normalized = str(path or "").replace("\\", "/")
        if not normalized or normalized.startswith(".scaffold/"):
            continue
        area = normalized.split("/", 1)[0] + "/" if "/" in normalized else ""
        if area and area not in seen:
            seen.add(area)
            areas.append(area)
    return {"modules": [], "areas": areas}


def persist_candidate_change(
    root: Path, record: dict[str, Any]
) -> tuple[bool, list[str], Path | None]:
    record_id = str(record.get("record_id") or "")
    if not CHANGE_ID_RE.fullmatch(record_id):
        return False, ["Change Record identity is malformed"], None
    durable = durability_state(root, record_id)
    if durable["state"] == "durable":
        return False, ["historical durable Change Record must not be rewritten"], None
    if durable["state"] == "malformed":
        return False, [
            "Change Record durability authority is malformed; recovery is required"
        ] + list(durable.get("blockers") or []), None
    if durable["state"] == "unknown":
        return False, [
            "Change Record durability authority is UNKNOWN; publication is blocked"
        ] + list(durable.get("blockers") or []), None
    existing = load_change_record(root, record_id)
    issues = validate_change_record(record, expected_id=record_id)
    if issues:
        return False, ["Change Record is malformed"] + issues, None
    path = change_path(root, record_id)
    write_yaml_atomic(path, record)
    return True, [], path


def list_change_record_ids(root: Path) -> list[str]:
    base = root / CHANGES_DIR
    if not base.is_dir():
        return []
    return sorted(path.stem for path in base.glob("change-*.yaml") if path.is_file())


def reconstructable_change_record_ids(root: str | Path) -> dict[str, Any]:
    """Live Change Records plus S10 discovery surfaces.

    Git durability is repository history, not merely a live worktree file.
    no-SCM publications remain discoverable if the live Change Record is gone.
    """
    host = Path(root)
    ids = set(list_change_record_ids(host))
    blockers: list[str] = []
    scm = observe_scm(host)
    if scm.kind == "git":
        historical = _git_historical_change_record_ids(host)
        if not historical.get("ok"):
            blockers.extend(
                list(historical.get("blockers") or [
                    "Git history could not list Change Record durability"
                ])
            )
        ids.update(historical.get("ids") or [])
    elif scm.kind == "none":
        ids.update(_noscms_publication_record_ids(host))
    else:
        blockers.append(
            "SCM durability is UNKNOWN; Change Record lineage cannot be reconstructed"
        )
    return {
        "ok": not blockers,
        "ids": sorted(ids),
        "blockers": blockers,
    }


def _noscms_publication_record_ids(root: Path) -> list[str]:
    folder = root / PUBLICATIONS_REL
    if not folder.is_dir():
        return []
    return sorted(
        child.name
        for child in folder.iterdir()
        if child.is_dir() and CHANGE_ID_RE.fullmatch(child.name)
    )


def _git_historical_change_record_ids(root: Path) -> dict[str, Any]:
    scm = observe_scm(root)
    if not scm.ok or scm.kind != "git" or scm.worktree_root is None:
        return {
            "ok": False,
            "ids": [],
            "blockers": ["Git worktree relation could not list Change Record durability"],
        }
    rel = project_to_worktree_path(scm, CHANGES_DIR)
    if not rel:
        return {
            "ok": False,
            "ids": [],
            "blockers": ["Change Record path could not be resolved in Git"],
        }
    try:
        listed = subprocess.run(
            [
                "git",
                "-C",
                str(scm.worktree_root),
                "log",
                "--all",
                "--name-only",
                "--pretty=format:",
                "--",
                rel,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "ok": False,
            "ids": [],
            "blockers": ["Git history could not list Change Record durability"],
        }
    if listed.returncode != 0:
        return {
            "ok": False,
            "ids": [],
            "blockers": ["Git history could not list Change Record durability"],
        }
    ids: set[str] = set()
    for line in listed.stdout.splitlines():
        path = str(line or "").strip().replace("\\", "/")
        if not path:
            continue
        name = path.rsplit("/", 1)[-1]
        if not name.startswith("change-") or not name.endswith(".yaml"):
            continue
        record_id = name[: -len(".yaml")]
        if CHANGE_ID_RE.fullmatch(record_id):
            ids.add(record_id)
    return {"ok": True, "ids": sorted(ids), "blockers": []}


def durable_task_finalization(root: str | Path) -> dict[str, Any]:
    """Derive Task ids consumed by proven S10 Change Record durability.

    Resume may consume this derived truth. It does not reimplement S10.
    A present, non-durable, malformed, UNKNOWN, or conflicting Change Record
    does not retire a READY Task.
    """
    host = Path(root)
    blockers: list[str] = []
    owners: dict[str, str] = {}
    conflicts: set[str] = set()
    lineage_unreliable = False
    records: list[dict[str, Any]] = []
    discovered = reconstructable_change_record_ids(host)
    if discovered.get("blockers"):
        blockers.extend(list(discovered.get("blockers") or []))
        lineage_unreliable = True

    for record_id in discovered.get("ids") or []:
        if not CHANGE_ID_RE.fullmatch(record_id):
            blockers.append(f"Change Record identity is malformed: {record_id}")
            lineage_unreliable = True
            continue
        state = durability_state(host, record_id)
        status = str(state.get("state") or "")
        path = change_path(host, record_id)
        if status == "absent":
            if path.is_file():
                data = load_change_record(host, record_id)
                if data is None:
                    blockers.append(
                        f"Change Record {record_id} is present but unreadable"
                    )
                    lineage_unreliable = True
                else:
                    issues = validate_change_record(data, expected_id=record_id)
                    if issues:
                        blockers.append(f"Change Record {record_id} is malformed")
                        blockers.extend(issues)
                        lineage_unreliable = True
            continue
        if status == "unknown":
            blockers.append(f"Change Record {record_id} durability is UNKNOWN")
            blockers.extend(list(state.get("blockers") or []))
            lineage_unreliable = True
            continue
        if status == "malformed":
            blockers.append(f"Change Record {record_id} durability is malformed")
            blockers.extend(list(state.get("blockers") or []))
            lineage_unreliable = True
            continue
        if status != "durable":
            blockers.append(
                f"Change Record {record_id} durability is unrecognized: {status}"
            )
            lineage_unreliable = True
            continue
        data = load_durable_change_record(host, record_id)
        if data is None:
            blockers.append(
                f"Change Record {record_id} S10 durability is proven but "
                "the durable payload could not be loaded"
            )
            lineage_unreliable = True
            continue
        issues = validate_change_record(data, expected_id=record_id)
        if issues:
            blockers.append(
                f"Change Record {record_id} durable payload is malformed"
            )
            blockers.extend(issues)
            lineage_unreliable = True
            continue
        task_ids_raw = data.get("task_book_ids")
        if not isinstance(task_ids_raw, list):
            blockers.append(f"Change Record {record_id} task_book_ids is malformed")
            lineage_unreliable = True
            continue
        parsed: list[str] = []
        malformed_ids = False
        for item in task_ids_raw:
            if not isinstance(item, str) or not TASK_ID_RE.fullmatch(item):
                blockers.append(
                    f"Change Record {record_id} task_book_ids is malformed"
                )
                lineage_unreliable = True
                malformed_ids = True
                break
            parsed.append(item)
        if malformed_ids:
            continue
        records.append(
            {
                "record_id": record_id,
                "task_book_ids": list(parsed),
                "commit": state.get("commit"),
            }
        )
        for task_id in parsed:
            existing = owners.get(task_id)
            if existing and existing != record_id:
                conflicts.add(task_id)
                blockers.append(
                    f"Task {task_id} has conflicting durable Change Records "
                    f"{existing} and {record_id}"
                )
            else:
                owners[task_id] = record_id

    if lineage_unreliable:
        finalized: list[str] = []
    else:
        finalized = sorted(task_id for task_id in owners if task_id not in conflicts)
    return {
        "ok": not blockers,
        "durably_finalized_task_ids": finalized,
        "blockers": blockers,
        "records": records,
    }


def remove_non_durable_change_record(
    root: Path,
    record_id: str,
    *,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    """Delete one non-durable Change Record. Never deletes durable S10 history."""
    if not CHANGE_ID_RE.fullmatch(record_id):
        return {
            "ok": False,
            "removed": False,
            "blockers": ["Change Record identity is malformed"],
        }
    path = change_path(root, record_id)
    if not path.is_file():
        return {"ok": True, "removed": False, "blockers": []}
    durable = durability_state(root, record_id)
    state = str(durable.get("state") or "")
    if state == "durable":
        return {
            "ok": False,
            "removed": False,
            "blockers": ["durable Change Record must not be removed"],
        }
    if state != "absent":
        return {
            "ok": False,
            "removed": False,
            "blockers": list(durable.get("blockers") or [
                "Change Record durability is not proven absent"
            ]),
        }
    actual_digest = file_digest(path)
    if expected_digest and actual_digest != expected_digest:
        return {
            "ok": False,
            "removed": False,
            "blockers": ["Change Record digest does not match expected bytes"],
        }
    try:
        path.unlink()
    except OSError as exc:
        return {
            "ok": False,
            "removed": False,
            "blockers": [f"Change Record could not be removed: {exc}"],
        }
    if path.exists():
        return {
            "ok": False,
            "removed": False,
            "blockers": ["Change Record still present after removal"],
        }
    return {"ok": True, "removed": True, "blockers": []}


def scm_base_value(root: Path) -> tuple[str, Any]:
    baseline = scm_baseline(root)
    kind = str(baseline.get("kind") or "none")
    return kind, baseline.get("revision")


def _git_durability_state(root: Path, record_id: str) -> dict[str, Any]:
    if not CHANGE_ID_RE.fullmatch(record_id):
        return {"state": "malformed", "blockers": ["Change Record identity is malformed"]}
    scm = observe_scm(root)
    if not scm.ok or scm.kind != "git" or scm.worktree_root is None:
        return {
            "state": "unknown",
            "blockers": ["Git worktree relation could not verify durability"],
        }
    rel = project_to_worktree_path(scm, f"{CHANGES_DIR}/{record_id}.yaml")
    if not rel:
        return {
            "state": "unknown",
            "blockers": ["Change Record path could not be resolved in Git"],
        }
    try:
        history = subprocess.run(
            [
                "git",
                "-C",
                str(scm.worktree_root),
                "log",
                "--reverse",
                "--all",
                "--format=%H",
                "--",
                rel,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {
            "state": "unknown",
            "blockers": ["Git history could not verify Change Record durability"],
        }
    if history.returncode != 0:
        return {
            "state": "unknown",
            "blockers": ["Git history could not verify Change Record durability"],
        }
    for commit in history.stdout.splitlines():
        try:
            shown = subprocess.run(
                [
                    "git",
                    "-C",
                    str(scm.worktree_root),
                    "show",
                    f"{commit}:{rel}",
                ],
                capture_output=True,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return {
                "state": "unknown",
                "blockers": [
                    "Git history could not read Change Record durability"
                ],
            }
        if shown.returncode != 0:
            continue
        try:
            data = yaml_lite.load(shown.stdout.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError):
            continue
        if not validate_change_record(data, expected_id=record_id):
            return {"state": "durable", "commit": commit, "data": data}
    return {"state": "absent"}

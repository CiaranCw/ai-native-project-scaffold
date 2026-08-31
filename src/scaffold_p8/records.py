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

from scaffold_p8.models import CHANGES_DIR, FINALIZATIONS_DIR, RECORD_SCHEMA_VERSION
from scaffold_p8.schemas import (
    CHANGE_ID_RE,
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
    if (root / ".git").exists():
        return _git_durability_state(root, record_id)
    marker = root / FINALIZATIONS_DIR / f"{record_id}.yaml"
    if not marker.exists():
        return {"state": "absent"}
    if not marker.is_file():
        return {
            "state": "malformed",
            "blockers": ["finalization support artifact is not a regular file"],
        }
    try:
        data = read_yaml(marker)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {
            "state": "malformed",
            "blockers": ["finalization support artifact is malformed or unreadable"],
        }
    issues = validate_finalization_marker(data, expected_id=record_id)
    if not issues and isinstance(data, dict):
        if data.get("scm_kind") != "none":
            issues.append("no-SCM host cannot use a Git finalization marker")
        expected_binding = finalization_binding(
            record_id,
            str(data.get("scm_kind")),
            str(data.get("candidate_digest")),
            str(data.get("change_record_digest")),
        )
        if data.get("finalization_digest") != expected_binding:
            issues.append("finalization binding digest does not match its fields")
    record = change_path(root, record_id)
    if not record.is_file():
        issues.append("finalization refers to a missing Change Record")
    elif isinstance(data, dict) and data.get("change_record_digest") != file_digest(record):
        issues.append("finalization Change Record digest does not match durable bytes")
    if issues:
        return {"state": "malformed", "blockers": issues, "data": data}
    return {"state": "durable", "data": data}


def finalization_binding(
    record_id: str, scm_kind: str, candidate_digest: str, record_digest: str
) -> str:
    return sha256_text(
        record_id,
        "\n",
        scm_kind,
        "\n",
        candidate_digest,
        "\n",
        record_digest,
    )


def load_change_record(root: Path, record_id: str) -> dict[str, Any] | None:
    path = change_path(root, record_id)
    if not path.is_file():
        return None
    try:
        data = read_yaml(path)
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def build_change_record(
    *,
    record_id: str,
    task: dict[str, Any],
    real_paths: list[str],
    delta: dict[str, Any],
    structural: dict[str, Any],
    knowledge: dict[str, Any],
    completeness: dict[str, Any],
    candidate_kind: str,
    baseline_value: Any,
    diff_entries: list[dict[str, Any]] | None = None,
    relevant_session_count: int = 0,
) -> dict[str, Any]:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    return {
        "record_type": "change_record",
        "schema_version": RECORD_SCHEMA_VERSION,
        "record_id": record_id,
        "created_at": created,
        "summary": str(task.get("title") or "Reviewed candidate"),
        "base": {"kind": candidate_kind or "none", "value": baseline_value},
        "affected": {
            "modules": list((task.get("scope") or {}).get("modules") or []),
            "areas": list((task.get("scope") or {}).get("paths") or []),
        },
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
                {"locator": str(completeness.get("report_id"))}
            ]
            if completeness.get("report_id")
            else [],
        },
        "understand_involvement": {
            "refresh": bool(knowledge.get("needs_refresh")),
            "compatibility": bool(knowledge.get("needs_migration")),
        },
        "task_book_ids": [str(task["record_id"])] if task.get("record_id") else [],
        "provenance": {
            "relevant_develop_session_count": relevant_session_count,
            "classes": {
                name: {"path_count": int(counts.get(name) or 0)}
                for name in (
                    "DEVELOP_KNOWN",
                    "MIXED_CHANGE",
                    "PREEXISTING_CHANGE",
                    "POST_DEVELOP_ADDITIONAL",
                    "UNATTRIBUTED",
                )
            },
        },
        "limitations": [],
    }


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


def scm_base_value(root: Path) -> tuple[str, Any]:
    baseline = scm_baseline(root)
    kind = str(baseline.get("kind") or "none")
    return kind, baseline.get("revision")


def _git_durability_state(root: Path, record_id: str) -> dict[str, Any]:
    if not CHANGE_ID_RE.fullmatch(record_id):
        return {"state": "malformed", "blockers": ["Change Record identity is malformed"]}
    rel = f"{CHANGES_DIR}/{record_id}.yaml"
    history = subprocess.run(
        ["git", "-C", str(root), "log", "--all", "--format=%H", "--", rel],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if history.returncode != 0:
        return {
            "state": "unknown",
            "blockers": ["Git history could not verify Change Record durability"],
        }
    for commit in history.stdout.splitlines():
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:{rel}"],
            capture_output=True,
            check=False,
        )
        if shown.returncode != 0:
            continue
        try:
            data = yaml_lite.load(shown.stdout.decode("utf-8"))
        except (UnicodeError, ValueError, TypeError):
            continue
        if not validate_change_record(data, expected_id=record_id):
            return {"state": "durable", "commit": commit}
    return {"state": "absent"}

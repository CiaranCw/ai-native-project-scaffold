"""P6-owned candidate projection. Does not change P5 durable_inventory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import scm_baseline
from scaffold_p5.io_util import file_digest, sha256_text
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p5 import yaml_lite

from scaffold_p6.contract import generated_classification_prefixes, generated_output_exclusions
from scaffold_p6.models import CANDIDATE_SCHEMA_VERSION, CandidateIdentity


RUNTIME_PREFIX = ".scaffold/runtime/"
BYTECODE_NAMES = {"__pycache__"}


def observe_candidate(root: str | Path) -> CandidateIdentity:
    host = Path(root)
    baseline = scm_baseline(host)
    declared = generated_output_exclusions(host)
    classified = generated_classification_prefixes(host)
    exclusions = [item for item in declared if _classified_generated(item, classified)]
    if baseline.get("kind") == "git":
        binding = _git_projection(host, baseline, exclusions)
    else:
        binding = _noscms_projection(host, baseline, exclusions)
    binding["candidate_digest"] = sha256_text(yaml_lite.dump(binding))
    return CandidateIdentity(binding)


def candidates_match(before: CandidateIdentity, after: CandidateIdentity) -> bool:
    return before.digest == after.digest and bool(before.digest)


def report_usable_for(report: dict[str, Any], candidate: CandidateIdentity) -> bool:
    bound = ((report.get("candidate") or {}).get("candidate_digest") or "")
    return bool(bound) and bound == candidate.digest


def excluded_from_candidate(
    rel: str,
    exclusions: list[str],
    *,
    tracked: bool = False,
) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if normalized.endswith(".pyc") or "/__pycache__/" in f"/{normalized}":
        return True
    if normalized in CORE_MACHINE_ARTIFACTS:
        return False
    if any(
        normalized == item or normalized.startswith(item.rstrip("/") + "/")
        for item in CORE_MACHINE_ARTIFACTS
    ):
        return False
    if tracked:
        return False
    for item in exclusions:
        if normalized == item or normalized.startswith(item.rstrip("/") + "/"):
            return True
    return False


def _classified_generated(declared: str, classified: list[str]) -> bool:
    """Authorize a declared exclusion only as the GENERATED path or a descendant."""
    declared_n = declared.replace("\\", "/").strip("/")
    for item in classified:
        authority = item.replace("\\", "/").strip("/")
        if not authority:
            continue
        if declared_n == authority or declared_n.startswith(authority + "/"):
            return True
    return False


def _git_projection(
    root: Path,
    baseline: dict[str, Any],
    exclusions: list[str],
) -> dict[str, Any]:
    tracked, untracked = _git_dirty_paths(root, exclusions)
    authority = _authority_digests(root)
    dirty = bool(tracked or untracked)
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "kind": "git",
        "revision": baseline.get("revision"),
        "branch": baseline.get("branch"),
        "head_state": baseline.get("head_state"),
        "working_tree": "dirty" if dirty else "clean",
        "tracked_changes": "present" if tracked else "absent",
        "untracked_changes": "present" if untracked else "absent",
        "scm_root": baseline.get("scm_root"),
        "project_root": baseline.get("project_root"),
        "authority": authority,
        "tracked_paths": tracked,
        "untracked_paths": untracked,
        "workspace_fingerprint": sha256_text(
            str(baseline.get("revision") or ""),
            yaml_lite.dump({"tracked": tracked, "untracked": untracked, "authority": authority}),
        ),
    }


def _noscms_projection(
    root: Path,
    baseline: dict[str, Any],
    exclusions: list[str],
) -> dict[str, Any]:
    inventory = _noscms_inventory(root, exclusions)
    parts = [
        f"{path}\n{row.get('type')}\n{row.get('digest')}"
        for path, row in sorted(inventory.items())
    ]
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "kind": "none",
        "revision": None,
        "branch": None,
        "head_state": "not_applicable",
        "working_tree": baseline.get("working_tree"),
        "tracked_changes": "unknown",
        "untracked_changes": "unknown",
        "scm_root": None,
        "project_root": ".",
        "authority": _authority_digests(root),
        "tracked_paths": [],
        "untracked_paths": [],
        "file_count": len(inventory),
        "workspace_fingerprint": sha256_text(*parts) if parts else sha256_text("empty"),
    }


def _noscms_inventory(root: Path, exclusions: list[str]) -> dict[str, dict[str, str]]:
    inventory: dict[str, dict[str, str]] = {}
    if not root.exists():
        return inventory
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name != ".git" and name not in BYTECODE_NAMES
        ]
        for name in filenames:
            full = Path(dirpath) / name
            rel = str(full.relative_to(root)).replace("\\", "/")
            if excluded_from_candidate(rel, exclusions, tracked=False):
                continue
            if full.is_file():
                inventory[rel] = {"type": "file", "digest": file_digest(full)}
    return inventory


def _authority_digests(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in CORE_MACHINE_ARTIFACTS:
        path = root / rel
        out[rel] = file_digest(path) if path.is_file() else "ABSENT"
    return out


def _git_dirty_paths(
    root: Path,
    exclusions: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    tracked: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []
    ok, payload = _run_git_bytes(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all"
    )
    if not ok:
        return tracked, untracked
    entries = _parse_porcelain_z(payload)
    for entry in entries:
        dest = entry["path"]
        orig = entry.get("orig_path") or ""
        if entry["untracked"]:
            if excluded_from_candidate(dest, exclusions, tracked=False):
                continue
            untracked.append(
                {"path": dest, "digest": _path_digest(root / dest)}
            )
            continue
        paths = [dest]
        if orig and orig != dest:
            paths.append(orig)
        for path in paths:
            if excluded_from_candidate(path, exclusions, tracked=True):
                continue
            row = {"path": path, "digest": _path_digest(root / path)}
            if orig and path == dest:
                row["orig_path"] = orig
            tracked.append(row)
    return tracked, untracked


def _parse_porcelain_z(payload: bytes) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    parts = payload.split(b"\0")
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        try:
            text = raw.decode("utf-8", errors="replace")
        except UnicodeError:
            continue
        if len(text) < 3:
            continue
        code = text[:2]
        first = text[3:].replace("\\", "/").strip()
        rename = code[0] in {"R", "C"} or code[1] in {"R", "C"}
        orig = ""
        dest = first
        if rename:
            if index < len(parts) and parts[index]:
                orig = parts[index].decode("utf-8", errors="replace").replace("\\", "/").strip()
                dest = first
                index += 1
        out.append(
            {
                "code": code,
                "path": dest,
                "orig_path": orig,
                "untracked": code == "??",
            }
        )
    return out


def _path_digest(path: Path) -> str:
    if path.is_file():
        return file_digest(path)
    return "ABSENT"


def _run_git_bytes(root: Path, *args: str) -> tuple[bool, bytes]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False, b""
    return completed.returncode == 0, completed.stdout

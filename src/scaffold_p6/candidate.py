"""P6-owned candidate projection. Does not change P5 durable_inventory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scaffold_p5.client_support import is_client_support_path
from scaffold_p5.io_util import file_digest, sha256_text
from scaffold_p5.scm import ScmObservation, observe_scm
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p5 import yaml_lite

from scaffold_p6.contract import generated_classification_prefixes, generated_output_exclusions
from scaffold_p6.models import CANDIDATE_SCHEMA_VERSION, CandidateIdentity, TASKS_DIR


RUNTIME_PREFIX = ".scaffold/runtime/"
SUBMIT_EXT_PREFIX = ".scaffold/ext/submit/"
DEVELOP_EXT_PREFIX = ".scaffold/ext/develop/"
BYTECODE_NAMES = {"__pycache__"}
TASK_NEUTRAL_TASK_KEYS = frozenset(
    {
        "record_revision",
        "updated_at",
        "status",
        "develop_session_ids",
        "task_completion_decision",
        "result_summary",
        "progress_summary",
        "evidence_ref",
        "evidence_refs",
        "observed_outcome",
    }
)
TASK_NEUTRAL_STAGE_KEYS = frozenset(
    {
        "status",
        "completion_decision",
        "result_summary",
        "progress_summary",
        "evidence_ref",
        "evidence_refs",
        "observed_outcome",
        "develop_session_ids",
    }
)
TASK_NEUTRAL_REF_KEYS = frozenset(
    {
        "evidence_ref",
        "evidence_refs",
        "observed_outcome",
        "result_summary",
        "progress_summary",
    }
)
_DIGEST_OMIT = frozenset(
    {
        "observation_state",
        "observation_ok",
        "blockers",
        "candidate_digest",
    }
)
_DIGEST_OMIT_GIT = frozenset(
    {
        "working_tree",
        "tracked_changes",
        "untracked_changes",
        "workspace_fingerprint",
    }
)


def observe_candidate(
    root: str | Path,
    *,
    omit_paths: list[str] | None = None,
) -> CandidateIdentity:
    host = Path(root)
    scm = observe_scm(host)
    declared = generated_output_exclusions(host)
    classified = generated_classification_prefixes(host)
    exclusions = [item for item in declared if _classified_generated(item, classified)]
    omit = {
        str(item).replace("\\", "/").strip().strip("/")
        for item in (omit_paths or [])
        if str(item or "").strip()
    }
    if scm.kind == "git" and not scm.ok:
        binding = _unresolved_projection(scm)
    elif scm.kind == "git":
        binding = _git_projection(host, scm, exclusions, omit)
    else:
        binding = _noscms_projection(host, exclusions, omit)
    binding["task_authority"] = _task_authority_projection(host)
    binding["candidate_digest"] = (
        sha256_text(yaml_lite.dump(_semantic_identity_body(binding)))
        if binding.get("observation_ok") is True
        else ""
    )
    return CandidateIdentity(binding)


def observe_candidate_excluding(
    root: str | Path,
    omit_paths: list[str],
) -> CandidateIdentity:
    """Observe the current candidate as if exact relative paths were absent."""
    return observe_candidate(root, omit_paths=omit_paths)


def candidates_match(before: CandidateIdentity, after: CandidateIdentity) -> bool:
    return before.digest == after.digest and bool(before.digest)


def report_usable_for(report: dict[str, Any], candidate: CandidateIdentity) -> bool:
    bound = ((report.get("candidate") or {}).get("candidate_digest") or "")
    return bool(bound) and bound == candidate.digest


def is_ext_support_path(rel: str) -> bool:
    """True for namespaced .scaffold/ext support that is not candidate identity."""
    normalized = rel.replace("\\", "/")
    if normalized.startswith(SUBMIT_EXT_PREFIX) or normalized == ".scaffold/ext/submit":
        return True
    if normalized.startswith(DEVELOP_EXT_PREFIX) or normalized == ".scaffold/ext/develop":
        return True
    return False


def excluded_from_candidate(
    rel: str,
    exclusions: list[str],
    *,
    tracked: bool = False,
    root: str | Path | None = None,
) -> bool:
    normalized = rel.replace("\\", "/")
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if is_ext_support_path(normalized):
        return True
    if root is not None and is_client_support_path(root, normalized):
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
    scm: ScmObservation,
    exclusions: list[str],
    omit: set[str] | None = None,
) -> dict[str, Any]:
    tracked, untracked = _git_dirty_paths(root, scm, exclusions, omit)
    authority = _authority_digests(root)
    dirty = bool(tracked or untracked)
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "kind": "git",
        "observation_state": scm.observation_state,
        "observation_ok": True,
        "revision": scm.revision,
        "branch": scm.branch,
        "head_state": scm.head_state,
        "working_tree": "dirty" if dirty else "clean",
        "tracked_changes": "present" if tracked else "absent",
        "untracked_changes": "present" if untracked else "absent",
        "scm_root": scm.scm_root_label,
        "project_root": ".",
        "authority": authority,
        "tracked_paths": tracked,
        "untracked_paths": untracked,
        "workspace_fingerprint": sha256_text(
            str(scm.revision or ""),
            yaml_lite.dump({"tracked": tracked, "untracked": untracked, "authority": authority}),
        ),
    }


def _noscms_projection(
    root: Path,
    exclusions: list[str],
    omit: set[str] | None = None,
) -> dict[str, Any]:
    inventory = _noscms_inventory(root, exclusions, omit)
    parts = [
        f"{path}\n{row.get('type')}\n{row.get('digest')}"
        for path, row in sorted(inventory.items())
    ]
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "kind": "none",
        "observation_state": "SCM_ABSENT",
        "observation_ok": True,
        "revision": None,
        "branch": None,
        "head_state": "not_applicable",
        "working_tree": "unknown",
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


def _unresolved_projection(scm: ScmObservation) -> dict[str, Any]:
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "kind": scm.kind,
        "observation_state": scm.observation_state,
        "observation_ok": False,
        "revision": None,
        "branch": None,
        "head_state": "unavailable",
        "working_tree": "unknown",
        "tracked_changes": "unknown",
        "untracked_changes": "unknown",
        "scm_root": scm.scm_root_label,
        "project_root": ".",
        "authority": {},
        "tracked_paths": [],
        "untracked_paths": [],
        "workspace_fingerprint": "",
        "blockers": list(scm.blockers),
    }


def is_task_book_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    return (
        len(parts) == 3
        and parts[0] == ".scaffold"
        and parts[1] == "tasks"
        and parts[2].endswith(".yaml")
        and not parts[2].startswith(".")
    )


def _identity_body(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in binding.items()
        if key not in {"observation_state", "observation_ok", "blockers"}
    }


def _semantic_identity_body(binding: dict[str, Any]) -> dict[str, Any]:
    omit = set(_DIGEST_OMIT)
    if binding.get("kind") == "git":
        omit.update(_DIGEST_OMIT_GIT)
    body = {
        key: value
        for key, value in binding.items()
        if key not in omit
    }
    body["tracked_paths"] = _non_task_path_rows(body.get("tracked_paths") or [])
    body["untracked_paths"] = _non_task_path_rows(body.get("untracked_paths") or [])
    body["task_authority"] = dict(binding.get("task_authority") or {})
    return body


def _non_task_path_rows(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        if is_task_book_path(path):
            continue
        out.append(row)
    return out


def _task_authority_projection(root: Path) -> dict[str, str]:
    folder = root / TASKS_DIR
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.yaml")):
        rel = str(path.relative_to(root)).replace("\\", "/")
        if not is_task_book_path(rel) or not path.is_file():
            continue
        out[rel] = _task_book_semantic_digest(path)
    return out


def _task_book_semantic_digest(path: Path) -> str:
    try:
        data = yaml_lite.load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return file_digest(path)
    projected = project_task_authority(data)
    if projected is None:
        return file_digest(path)
    return sha256_text(yaml_lite.dump(projected))


def project_task_authority(data: Any) -> Any:
    """Public P6 Records §8.7 substantive Task authority projection."""
    return _project_task_authority(data)


def task_authority_digest(data: Any) -> str:
    """Digest of the P6 substantive Task authority projection.

    Uses the same YAML dump as Task contribution to candidate identity.
    """
    projected = _project_task_authority(data)
    if projected is None:
        return ""
    return sha256_text(yaml_lite.dump(projected))


def _project_task_authority(data: Any) -> Any:
    if not isinstance(data, dict):
        return None
    if data.get("record_type") not in {None, "task_book"}:
        return data
    projected = {
        key: value
        for key, value in data.items()
        if key not in TASK_NEUTRAL_TASK_KEYS
    }
    stages = projected.get("stages")
    if isinstance(stages, list):
        projected["stages"] = [
            _project_stage_authority(stage) for stage in stages
        ]
    finals = projected.get("final_tests")
    if isinstance(finals, list):
        projected["final_tests"] = [
            _project_requirement_authority(item) for item in finals
        ]
    return projected


def _project_stage_authority(stage: Any) -> Any:
    if not isinstance(stage, dict):
        return stage
    projected = {
        key: value
        for key, value in stage.items()
        if key not in TASK_NEUTRAL_STAGE_KEYS
    }
    tests = projected.get("required_tests")
    if isinstance(tests, list):
        projected["required_tests"] = [
            _project_requirement_authority(item) for item in tests
        ]
    return projected


def _project_requirement_authority(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    return {
        key: value
        for key, value in item.items()
        if key not in TASK_NEUTRAL_REF_KEYS
    }


def _path_omitted(rel: str, omitted: set[str]) -> bool:
    """Exact path or declared prefix. New in-scope files stay omitted."""
    if not omitted:
        return False
    target = str(rel or "").replace("\\", "/").strip().strip("/")
    if not target:
        return False
    if target in omitted:
        return True
    for item in omitted:
        if not item:
            continue
        if target == item or target.startswith(item.rstrip("/") + "/"):
            return True
    return False


def _noscms_inventory(
    root: Path,
    exclusions: list[str],
    omit: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    omitted = omit or set()
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
            if _path_omitted(rel, omitted):
                continue
            if excluded_from_candidate(rel, exclusions, tracked=False, root=root):
                continue
            if full.is_file():
                inventory[rel] = {
                    "type": "file",
                    "digest": _content_digest(root, rel, full),
                }
    return inventory


def _authority_digests(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in CORE_MACHINE_ARTIFACTS:
        path = root / rel
        out[rel] = file_digest(path) if path.is_file() else "ABSENT"
    return out


def _git_dirty_paths(
    root: Path,
    scm: ScmObservation,
    exclusions: list[str],
    omit: set[str] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    omitted = omit or set()
    tracked: list[dict[str, str]] = []
    untracked: list[dict[str, str]] = []
    for entry in scm.entries:
        dest = entry["path"]
        orig = entry.get("orig_path") or ""
        if _path_omitted(dest, omitted):
            continue
        if entry["untracked"]:
            if excluded_from_candidate(dest, exclusions, tracked=False, root=root):
                continue
            untracked.append(
                {"path": dest, "digest": _path_digest(root / dest)}
            )
            continue
        paths = [dest]
        if orig and orig != dest and not _path_omitted(orig, omitted):
            paths.append(orig)
        for path in paths:
            if excluded_from_candidate(path, exclusions, tracked=True, root=root):
                continue
            row = {"path": path, "digest": _path_digest(root / path)}
            if orig and path == dest:
                row["orig_path"] = orig
            tracked.append(row)
    return tracked, untracked


def _content_digest(root: Path, rel: str, path: Path) -> str:
    if is_task_book_path(rel) and path.is_file():
        return _task_book_semantic_digest(path)
    if path.is_file():
        return file_digest(path)
    return "ABSENT"


def _path_digest(path: Path) -> str:
    if path.is_file():
        return file_digest(path)
    return "ABSENT"

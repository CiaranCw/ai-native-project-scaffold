"""P6-owned candidate projection. Does not change P5 durable_inventory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scaffold_p5.agents import ALLOWED_AGENTS_REGIONS, parse_managed_regions
from scaffold_p5.client_support import is_client_support_path
from scaffold_p5.io_util import file_digest, sha256_bytes, sha256_text
from scaffold_p5.scm import ScmObservation, _run_git_bytes, observe_scm
from scaffold_p5.schemas import CORE_MACHINE_ARTIFACTS
from scaffold_p5 import yaml_lite

from scaffold_p6.contract import generated_classification_prefixes, generated_output_exclusions
from scaffold_p6.models import (
    CANDIDATE_SCHEMA_VERSION,
    PROJECTION_GENERATION_CURRENT,
    PROJECTION_GENERATION_LEGACY,
    CandidateIdentity,
    TASKS_DIR,
)


RUNTIME_PREFIX = ".scaffold/runtime/"
INSTALL_PREFIX = ".scaffold/install/"
SUBMIT_EXT_PREFIX = ".scaffold/ext/submit/"
DEVELOP_EXT_PREFIX = ".scaffold/ext/develop/"
MIXED_OWNERSHIP_PATHS = frozenset({"AGENTS.md", ".gitattributes"})
# Install-only Scaffold bytes on these hosts are omitted from the candidate
# when the shared human surface matches HEAD. Generation-2 digest projection
# stays limited to MIXED_OWNERSHIP_PATHS.
_SURFACE_NEUTRAL_PATHS = MIXED_OWNERSHIP_PATHS | {".cursor/hooks.json"}
_PROJECTION_GENERATIONS = frozenset(
    {PROJECTION_GENERATION_LEGACY, PROJECTION_GENERATION_CURRENT}
)
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
        "projection_inventory",
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
    generation: str | None = None,
) -> CandidateIdentity:
    host = Path(root)
    selected = generation or PROJECTION_GENERATION_CURRENT
    if selected not in _PROJECTION_GENERATIONS:
        binding = _unresolved_projection(
            observe_scm(host),
            blockers=[f"unknown candidate projection generation {selected!r}"],
        )
        binding["projection_generation"] = selected
        return CandidateIdentity(binding, host_root=str(host))
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
        binding = _git_projection(host, scm, exclusions, omit, selected)
    else:
        binding = _noscms_projection(host, exclusions, omit, selected)
    binding["projection_generation"] = selected
    binding["task_authority"] = _task_authority_projection(host)
    binding["candidate_digest"] = (
        sha256_text(yaml_lite.dump(_semantic_identity_body(binding)))
        if binding.get("observation_ok") is True
        else ""
    )
    inventory = binding.pop("projection_inventory", None)
    return CandidateIdentity(
        binding,
        host_root=str(host),
        inventory=inventory if isinstance(inventory, dict) else None,
    )


def observe_candidate_excluding(
    root: str | Path,
    omit_paths: list[str],
) -> CandidateIdentity:
    """Observe the current candidate as if exact relative paths were absent."""
    return observe_candidate(root, omit_paths=omit_paths)


def candidates_match(before: CandidateIdentity, after: CandidateIdentity) -> bool:
    return before.digest == after.digest and bool(before.digest)


def report_usable_for(report: dict[str, Any], candidate: CandidateIdentity) -> bool:
    stored = report.get("candidate") if isinstance(report.get("candidate"), dict) else {}
    bound = str((stored or {}).get("candidate_digest") or "")
    if not bound or not candidate.digest:
        return False
    if candidate.host_root is None:
        return bound == candidate.digest
    from scaffold_p6.projection import digest_is_current

    generation = (stored or {}).get("projection_generation")
    return digest_is_current(
        candidate.host_root,
        bound,
        candidate.digest,
        stored_generation=generation if isinstance(generation, str) else None,
    )


def is_ext_support_path(rel: str) -> bool:
    """True for namespaced .scaffold/ext support that is not candidate identity."""
    normalized = rel.replace("\\", "/")
    if normalized.startswith(SUBMIT_EXT_PREFIX) or normalized == ".scaffold/ext/submit":
        return True
    if normalized.startswith(DEVELOP_EXT_PREFIX) or normalized == ".scaffold/ext/develop":
        return True
    return False


def is_install_infrastructure(rel: str) -> bool:
    """Scaffold delivery bytes. Candidate-neutral only in generation 2."""
    normalized = rel.replace("\\", "/")
    return normalized == ".scaffold/install" or normalized.startswith(INSTALL_PREFIX)


def excluded_from_candidate(
    rel: str,
    exclusions: list[str],
    *,
    tracked: bool = False,
    root: str | Path | None = None,
    generation: str | None = None,
) -> bool:
    normalized = rel.replace("\\", "/")
    selected = generation or PROJECTION_GENERATION_CURRENT
    if normalized.startswith(RUNTIME_PREFIX) or normalized == ".scaffold/runtime":
        return True
    if is_ext_support_path(normalized):
        return True
    if root is not None and is_client_support_path(root, normalized):
        return True
    if normalized.endswith(".pyc") or "/__pycache__/" in f"/{normalized}":
        return True
    if selected == PROJECTION_GENERATION_CURRENT and is_install_infrastructure(normalized):
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
    generation: str = PROJECTION_GENERATION_LEGACY,
) -> dict[str, Any]:
    tracked, untracked = _git_dirty_paths(root, scm, exclusions, omit, generation)
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
    generation: str = PROJECTION_GENERATION_LEGACY,
) -> dict[str, Any]:
    inventory = _noscms_inventory(root, exclusions, omit, generation)
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
        "workspace_fingerprint": inventory_fingerprint(inventory),
        "projection_inventory": inventory,
    }


def _unresolved_projection(
    scm: ScmObservation,
    *,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
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
        "blockers": list(blockers) if blockers is not None else list(scm.blockers),
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


def semantic_body(binding: dict[str, Any]) -> dict[str, Any]:
    """Canonical hashed candidate body. Generation 1 omits projection metadata."""
    return _semantic_identity_body(binding)


def _semantic_identity_body(binding: dict[str, Any]) -> dict[str, Any]:
    omit = set(_DIGEST_OMIT)
    omit.add("projection_generation")
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
    if str(binding.get("projection_generation") or "") == PROJECTION_GENERATION_CURRENT:
        body["projection_generation"] = PROJECTION_GENERATION_CURRENT
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


def inventory_fingerprint(inventory: dict[str, dict[str, str]]) -> str:
    parts = [
        f"{path}\n{row.get('type')}\n{row.get('digest')}"
        for path, row in sorted(inventory.items())
    ]
    return sha256_text(*parts) if parts else sha256_text("empty")


def _noscms_inventory(
    root: Path,
    exclusions: list[str],
    omit: set[str] | None = None,
    generation: str = PROJECTION_GENERATION_LEGACY,
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
            if excluded_from_candidate(
                rel, exclusions, tracked=False, root=root, generation=generation
            ):
                continue
            if full.is_file():
                inventory[rel] = {
                    "type": "file",
                    "digest": _content_digest(root, rel, full, generation),
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
    generation: str = PROJECTION_GENERATION_LEGACY,
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
            if excluded_from_candidate(
                dest, exclusions, tracked=False, root=root, generation=generation
            ):
                continue
            untracked.append(
                {"path": dest, "digest": _path_digest(root / dest, rel=dest, generation=generation)}
            )
            continue
        paths = [dest]
        if orig and orig != dest and not _path_omitted(orig, omitted):
            paths.append(orig)
        for path in paths:
            if excluded_from_candidate(
                path, exclusions, tracked=True, root=root, generation=generation
            ):
                continue
            if (
                generation == PROJECTION_GENERATION_CURRENT
                and path in _SURFACE_NEUTRAL_PATHS
                and _mixed_projection_matches_head(root, scm, path)
            ):
                continue
            row = {
                "path": path,
                "digest": _path_digest(root / path, rel=path, generation=generation),
            }
            if orig and path == dest:
                row["orig_path"] = orig
            tracked.append(row)
    return tracked, untracked


def _content_digest(
    root: Path,
    rel: str,
    path: Path,
    generation: str = PROJECTION_GENERATION_LEGACY,
) -> str:
    if is_task_book_path(rel) and path.is_file():
        return _task_book_semantic_digest(path)
    return _path_digest(path, rel=rel, generation=generation)


def _path_digest(
    path: Path,
    *,
    rel: str = "",
    generation: str = PROJECTION_GENERATION_LEGACY,
) -> str:
    if not path.is_file():
        return "ABSENT"
    if generation == PROJECTION_GENERATION_CURRENT and rel in MIXED_OWNERSHIP_PATHS:
        projected = _projected_mixed_digest(path, rel)
        if projected is not None:
            return projected
    return file_digest(path)


def tracked_mixed_matches_head(root: str | Path, rel: str) -> bool:
    """True when the worktree projection of a tracked file matches HEAD."""
    host = Path(root)
    return _mixed_projection_matches_head(host, observe_scm(host), rel)


def _mixed_projection_matches_head(root: Path, scm: ScmObservation, rel: str) -> bool:
    """True when a dirty tracked file differs from HEAD only in neutral regions.

    The comparison uses the shared mixed-ownership human surface, so an
    installer-appended managed region and its separator newline agree with
    HEAD while a real human-byte edit does not.
    """
    from scaffold_p5.mixed_surface import human_owned_surface_matches

    try:
        live = (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    head = _head_text(scm, rel)
    if head is None:
        return False
    return human_owned_surface_matches(rel, live, head)


def _head_text(scm: ScmObservation, rel: str) -> str | None:
    if scm.worktree_root is None or not scm.revision:
        return None
    prefix = scm.project_prefix.strip("/")
    git_path = rel if prefix in {"", "."} else prefix + "/" + rel
    result = _run_git_bytes(scm.worktree_root, "show", f"{scm.revision}:{git_path}")
    if not result.ok:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeError:
        return None


def _head_projected_digest(scm: ScmObservation, rel: str) -> str | None:
    if scm.worktree_root is None or not scm.revision:
        return None
    prefix = scm.project_prefix.strip("/")
    if prefix in {"", "."}:
        git_path = rel
    else:
        git_path = prefix + "/" + rel
    result = _run_git_bytes(scm.worktree_root, "show", f"{scm.revision}:{git_path}")
    if not result.ok:
        return None
    try:
        text = result.stdout.decode("utf-8")
    except UnicodeError:
        return None
    projected = _project_mixed_text(rel, text)
    if projected is None:
        return None
    return sha256_bytes(projected.encode("utf-8"))


def projected_digest_of_bytes(rel: str, raw: bytes) -> str | None:
    """Generation-2 digest of mixed-ownership bytes, or None when not projected."""
    normalized = rel.replace("\\", "/")
    if normalized not in MIXED_OWNERSHIP_PATHS:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return None
    projected = _project_mixed_text(normalized, text)
    if projected is None:
        return None
    return sha256_bytes(projected.encode("utf-8"))


def projected_mixed_digest(root: str | Path, rel: str) -> str | None:
    """Generation-2 digest of a mixed-ownership file, or None when not projected."""
    normalized = rel.replace("\\", "/")
    if normalized not in MIXED_OWNERSHIP_PATHS:
        return None
    return _projected_mixed_digest(Path(root) / normalized, normalized)


def _projected_mixed_digest(path: Path, rel: str) -> str | None:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        return None
    projected = _project_mixed_text(rel, text)
    if projected is None:
        return None
    return sha256_bytes(projected.encode("utf-8"))


def _project_mixed_text(rel: str, text: str) -> str | None:
    if rel == "AGENTS.md":
        spans, issues = parse_managed_regions(text)
        if issues:
            return None
        allowed = {
            region_id: span
            for region_id, span in spans.items()
            if region_id in ALLOWED_AGENTS_REGIONS
        }
        return _blank_comment_regions(text, allowed)
    if rel == ".gitattributes":
        from scaffold_p5.consumer_install import (
            GITATTR_REGION,
            parse_gitattributes_region,
        )

        spans, issues = parse_gitattributes_region(text)
        if issues:
            return None
        span = spans.get(GITATTR_REGION)
        if span is None:
            return text
        return _blank_line_region(text, span)
    return None


def _blank_comment_regions(
    text: str,
    spans: dict[str, tuple[int, int]],
) -> str | None:
    updated = text
    for _region_id, (start, end) in sorted(
        spans.items(), key=lambda item: item[1][0], reverse=True
    ):
        blanked = _blank_comment_region(updated, start, end)
        if blanked is None:
            return None
        updated = blanked
    return updated


def _blank_comment_region(text: str, start: int, end: int) -> str | None:
    block = text[start:end]
    start_close = block.find("-->")
    end_open = block.rfind("<!--")
    if start_close < 0 or end_open < 0 or end_open <= start_close:
        return None
    inner_start = start + start_close + len("-->")
    inner_end = start + end_open
    return text[:inner_start] + text[inner_end:]


def _blank_line_region(text: str, span: tuple[int, int]) -> str | None:
    start, end = span
    block = text[start:end]
    first_newline = block.find("\n")
    last_newline = block.rfind("\n")
    if first_newline < 0 or last_newline <= first_newline:
        return None
    inner_start = start + first_newline + 1
    inner_end = start + last_newline + 1
    return text[:inner_start] + text[inner_end:]

"""Bounded host inventory. Adoption Baseline hashing authority.

Classifies roots as DEEP / BOUNDED / EXCLUDED by generic directory names.
Does not treat classification as content truth. Does not follow filesystem
indirection out of the project root. Mutation-envelope paths are exact-observed
even under an otherwise EXCLUDED root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from scaffold_p5.io_util import file_digest


CLASS_DEEP = "DEEP"
CLASS_BOUNDED = "BOUNDED"
CLASS_EXCLUDED = "EXCLUDED"

FULLY_OBSERVED = "FULLY_OBSERVED"
EXCLUDED_BY_POLICY = "EXCLUDED_BY_POLICY"
TRUNCATED_BY_BUDGET = "TRUNCATED_BY_BUDGET"
UNKNOWN = "UNKNOWN"
ABSENT = "ABSENT"

DEFAULT_MAX_FILES = 20000
DEFAULT_MAX_HASH_BYTES = 64 * 1024 * 1024

EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        "out",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        ".turbo",
        ".cache",
        "cache",
        "eggs",
        "bower_components",
        "jspm_packages",
    }
)

BOUNDED_DIR_NAMES = frozenset(
    {
        "artifacts",
        "datasets",
        "checkpoints",
        "generated",
        "outputs",
        "output",
        "testdata",
        "assets",
    }
)

RUNTIME_PREFIX = ".scaffold/runtime/"


@dataclass
class InventoryBudget:
    max_files: int = DEFAULT_MAX_FILES
    max_hash_bytes: int = DEFAULT_MAX_HASH_BYTES
    max_entries: int = DEFAULT_MAX_FILES


@dataclass
class RootRecord:
    path: str
    classification: str
    observation: str
    present: bool
    bounded_file_count: int | None = None
    reason: str = ""


@dataclass
class InventoryObservation:
    files: dict[str, dict[str, str]] = field(default_factory=dict)
    roots: list[RootRecord] = field(default_factory=list)
    exact_observed: list[str] = field(default_factory=list)
    files_traversed: int = 0
    files_hashed: int = 0
    bytes_hashed: int = 0
    entries_enumerated: int = 0
    truncated: bool = False
    truncated_paths: list[str] = field(default_factory=list)
    unknown: bool = False
    observation_failure: str = ""

    @property
    def in_scope_status(self) -> str:
        if self.unknown or self.observation_failure:
            return UNKNOWN
        if self.truncated:
            return TRUNCATED_BY_BUDGET
        return FULLY_OBSERVED

    @property
    def verified_complete(self) -> bool:
        return self.in_scope_status == FULLY_OBSERVED

    def coverage_dict(self) -> dict[str, Any]:
        excluded = [row.path for row in self.roots if row.classification == CLASS_EXCLUDED]
        truncated_roots = [
            row.path for row in self.roots if row.observation == TRUNCATED_BY_BUDGET
        ]
        for path in self.truncated_paths:
            if path not in truncated_roots:
                truncated_roots.append(path)
        return {
            "status": self.in_scope_status,
            "verified_complete": self.verified_complete,
            "files_traversed": self.files_traversed,
            "files_hashed": self.files_hashed,
            "bytes_hashed": self.bytes_hashed,
            "entries_enumerated": self.entries_enumerated,
            "excluded_roots": excluded,
            "truncated_roots": truncated_roots,
            "exact_observed": list(self.exact_observed),
            "roots": [root_as_dict(row) for row in self.roots],
            "observation_failure": self.observation_failure,
        }


def root_as_dict(row: RootRecord) -> dict[str, Any]:
    return {
        "path": row.path,
        "classification": row.classification,
        "observation": row.observation,
        "present": row.present,
        "bounded_file_count": row.bounded_file_count,
        "reason": row.reason,
    }


def classify_rel(rel: str) -> str:
    """Classify a repository-relative path by generic directory-name classes."""
    parts = [part.lower() for part in str(rel or "").replace("\\", "/").split("/") if part]
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return CLASS_EXCLUDED
    if any(part in BOUNDED_DIR_NAMES for part in parts):
        return CLASS_BOUNDED
    return CLASS_DEEP


def excluded_by_policy(rel: str) -> bool:
    return classify_rel(rel) == CLASS_EXCLUDED


def _norm(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip("/")


def project_relative_path(root: Path, rel: str) -> tuple[str | None, str]:
    """Accept only a path that stays inside root without `..` or drive/UNC forms."""
    raw = str(rel or "").replace("\\", "/")
    if not raw.strip():
        return None, "path is empty"
    if raw.startswith("/") or raw.startswith("//") or (len(raw) >= 2 and raw[1] == ":"):
        return None, "path is not project-relative"
    parts = [part for part in raw.strip("/").split("/") if part]
    if not parts or any(part == ".." for part in parts):
        return None, "path escapes project root"
    normalized = "/".join(part for part in parts if part != ".")
    if not normalized:
        return None, "path is empty"
    inside, reason = resolved_inside_root(root, root / normalized)
    if not inside:
        return None, reason or "filesystem indirection escapes project root"
    return normalized, ""


def _is_runtime(rel: str) -> bool:
    normalized = _norm(rel)
    return normalized.startswith(".scaffold/runtime/") or normalized == ".scaffold/runtime"


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
    except OSError:
        return True
    return False


def resolved_inside_root(root: Path, path: Path) -> tuple[bool, str]:
    """True when path resolves inside root. Fail-closed on observation errors."""
    try:
        root_resolved = root.resolve()
        path_resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        return False, f"path resolution failed: {exc}"
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError:
        return False, "filesystem indirection escapes project root"
    return True, ""


@dataclass
class MetadataWalk:
    """Bounded directory/file enumeration. Not a digest inventory."""

    files: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    truncated: bool = False
    unknown: bool = False
    reason: str = ""
    entries_enumerated: int = 0

    @property
    def observation(self) -> str:
        if self.unknown:
            return UNKNOWN
        if self.truncated:
            return TRUNCATED_BY_BUDGET
        return FULLY_OBSERVED


# At most one extra scandir yield after max_entries, for the whole walk.
ENUMERATION_OVERFLOW_PROBE = 1


def _directory_scandir(path: str | os.PathLike[str]):
    """Streaming directory iterator. Tests may wrap this primitive."""
    return os.scandir(path)


def directory_cache_key(directory: Path) -> str:
    try:
        return str(Path(directory).resolve())
    except (OSError, RuntimeError):
        return str(directory)


def _listing_from_cache(dir_cache: Any, directory: Path) -> tuple[list[str], bool, str] | None:
    if not dir_cache:
        return None
    rec = dir_cache.get(directory_cache_key(directory))
    if rec is None:
        return None
    status = getattr(rec, "status", None)
    if status == "TRUNCATED":
        return [], True, ""
    if status == "UNKNOWN":
        return [], False, "cached directory observation failed"
    if status == "COMPLETE":
        names = [
            name
            for names in getattr(rec, "by_lower", {}).values()
            for name in names
        ]
        names.sort()
        return names, False, ""
    return None


def bounded_metadata_walk(
    root: str | Path,
    *,
    start: str = "",
    budget: InventoryBudget | None = None,
    skip_dir_names: Iterable[str] | None = None,
    stop_dir_names: Iterable[str] | None = None,
    state: MetadataWalk | None = None,
    on_directory: Any | None = None,
    dir_cache: Any | None = None,
) -> MetadataWalk:
    """Enumerate files and directories with a deterministic entry budget.

    Counts listed directory entries, not hashed bytes. A directory-only
    explosion cannot bypass the budget. Underlying filesystem enumeration
    is streamed; a wide directory is not fully materialized before the
    budget is checked. Does not follow filesystem indirection out of
    project root and does not follow directory links.
    """
    host = Path(root)
    limits = budget or InventoryBudget()
    result = state or MetadataWalk()
    if result.truncated:
        return result
    skip = {str(name).lower() for name in (skip_dir_names if skip_dir_names is not None else EXCLUDED_DIR_NAMES)}
    stop = {str(name).lower() for name in (stop_dir_names or ())}
    if start:
        safe, reason = project_relative_path(host, start)
        if safe is None:
            result.unknown = True
            result.reason = result.reason or reason
            return result
        start_rel = safe
        start_path = host / safe
    else:
        start_rel = ""
        start_path = host
    inside, reason = resolved_inside_root(host, start_path)
    if not inside:
        result.unknown = True
        result.reason = result.reason or reason
        return result
    try:
        present = start_path.exists()
    except OSError as exc:
        result.unknown = True
        result.reason = str(exc)
        return result
    if not present:
        return result
    try:
        is_dir = start_path.is_dir()
        is_file = start_path.is_file()
    except OSError as exc:
        result.unknown = True
        result.reason = str(exc)
        return result
    if not is_dir:
        if is_file and start_rel:
            result.files.append(start_rel)
        return result

    seen_resolved: set[str] = set()
    try:
        seen_resolved.add(str(start_path.resolve()))
    except (OSError, RuntimeError) as exc:
        result.unknown = True
        result.reason = str(exc)
        return result
    stack: list[tuple[Path, str]] = [(start_path, start_rel)]
    while stack:
        remaining = limits.max_entries - result.entries_enumerated
        if remaining <= 0:
            result.truncated = True
            result.reason = result.reason or "metadata traversal exceeded entry budget"
            return result
        directory, rel = stack.pop()
        inside, reason = resolved_inside_root(host, directory)
        if not inside:
            result.unknown = True
            result.reason = result.reason or reason
            continue
        if rel and _is_link(directory):
            continue
        cached = _listing_from_cache(dir_cache, directory)
        if cached is not None:
            collected, overflow, scan_error = cached
        else:
            collected, overflow, scan_error = _stream_directory_names(
                directory,
                result=result,
                max_entries=limits.max_entries,
            )
            if on_directory is not None:
                on_directory(
                    directory,
                    collected=collected,
                    overflow=overflow,
                    error=scan_error,
                )
        if scan_error:
            result.unknown = True
            result.reason = result.reason or scan_error
            continue
        if overflow:
            result.truncated = True
            result.reason = result.reason or "metadata traversal exceeded entry budget"
            return result
        for name in collected:
            child = directory / name
            child_rel = name if not rel else f"{rel}/{name}"
            if name.lower() in skip:
                continue
            try:
                child_is_dir = child.is_dir()
                child_is_file = child.is_file()
            except OSError as exc:
                result.unknown = True
                result.reason = str(exc)
                continue
            if child_is_dir:
                result.directories.append(child_rel)
                if name.lower() in stop:
                    continue
                if _is_link(child):
                    inside, reason = resolved_inside_root(host, child)
                    if not inside:
                        result.unknown = True
                        result.reason = result.reason or reason
                    continue
                inside, reason = resolved_inside_root(host, child)
                if not inside:
                    result.unknown = True
                    result.reason = result.reason or reason
                    continue
                try:
                    resolved = str(child.resolve())
                except (OSError, RuntimeError) as exc:
                    result.unknown = True
                    result.reason = str(exc)
                    continue
                if resolved in seen_resolved:
                    continue
                seen_resolved.add(resolved)
                stack.append((child, child_rel))
                continue
            if _is_link(child):
                inside, reason = resolved_inside_root(host, child)
                if not inside:
                    result.unknown = True
                    result.reason = result.reason or reason
                    continue
            if child_is_file:
                result.files.append(child_rel)
    return result


def _stream_directory_names(
    directory: Path,
    *,
    result: Any,
    max_entries: int,
) -> tuple[list[str], bool, str]:
    """Shared streaming directory primitive. Full materialization is forbidden.

    Used by bounded_metadata_walk and observe_inventory/_walk. Yields count
    against max_entries before names are stored as authority. At most one
    overflow probe is consumed. An overflowing directory's prefix is
    discarded so filesystem order cannot become product truth. Exhausted
    directories are sorted only after the iterator ends.
    """
    collected: list[str] = []
    try:
        with _directory_scandir(directory) as scanner:
            for entry in scanner:
                result.entries_enumerated += 1
                if result.entries_enumerated > max_entries:
                    return [], True, ""
                collected.append(entry.name)
    except OSError as exc:
        return [], False, str(exc)
    collected.sort()
    return collected, False, ""


def observe_inventory(
    root: str | Path,
    *,
    exact_observe: Iterable[str] | None = None,
    budget: InventoryBudget | None = None,
    counter: Any | None = None,
    on_directory: Any | None = None,
    dir_cache: Any | None = None,
) -> InventoryObservation:
    host = Path(root)
    limits = budget or InventoryBudget()
    result = InventoryObservation()
    if not host.exists():
        result.unknown = True
        result.observation_failure = "project root is missing"
        return result
    if not host.is_dir():
        result.unknown = True
        result.observation_failure = "project root is not a directory"
        return result

    exact = sorted({_norm(item) for item in (exact_observe or []) if _norm(item)})
    seen_resolved: set[str] = set()
    recorded_roots: dict[str, RootRecord] = {}

    def record_root(rel: str, classification: str, observation: str, *, present: bool, reason: str, count: int | None = None) -> None:
        key = rel or "."
        if key in recorded_roots:
            return
        recorded_roots[key] = RootRecord(
            path=key,
            classification=classification,
            observation=observation,
            present=present,
            bounded_file_count=count,
            reason=reason,
        )

    def budget_exhausted() -> bool:
        return (
            result.files_traversed >= limits.max_files
            or result.bytes_hashed >= limits.max_hash_bytes
        )

    def hash_file(rel: str, path: Path, *, force: bool) -> None:
        nonlocal result
        if _is_runtime(rel):
            return
        result.files_traversed += 1
        if path.suffix.lower() in {".pyc", ".pyo"}:
            return
        try:
            size = path.stat().st_size
        except OSError as exc:
            result.unknown = True
            result.files[rel] = {
                "type": "file",
                "digest": "",
                "observation": UNKNOWN,
            }
            record_root(rel, classify_rel(rel), UNKNOWN, present=True, reason=str(exc))
            return
        if not force and (
            result.files_hashed >= limits.max_files
            or result.bytes_hashed + size > limits.max_hash_bytes
            or result.files_traversed > limits.max_files
        ):
            result.truncated = True
            if rel not in result.truncated_paths:
                result.truncated_paths.append(rel)
            result.files[rel] = {
                "type": "file",
                "digest": "",
                "observation": TRUNCATED_BY_BUDGET,
            }
            return
        try:
            digest = file_digest(path)
        except OSError as exc:
            result.unknown = True
            result.files[rel] = {
                "type": "file",
                "digest": "",
                "observation": UNKNOWN,
            }
            record_root(rel, classify_rel(rel), UNKNOWN, present=True, reason=str(exc))
            return
        result.files_hashed += 1
        result.bytes_hashed += size
        result.files[rel] = {
            "type": "file",
            "digest": digest,
            "observation": FULLY_OBSERVED,
        }

    def skip_dir(directory: Path, rel: str) -> tuple[bool, str]:
        if _is_link(directory):
            inside, reason = resolved_inside_root(host, directory)
            if not inside:
                result.unknown = True
                record_root(
                    rel or directory.name,
                    CLASS_EXCLUDED,
                    UNKNOWN,
                    present=True,
                    reason=reason or "symlink/junction skipped",
                )
                return True, reason or "filesystem indirection escapes project root"
            return True, "directory indirection is not followed"
        inside, reason = resolved_inside_root(host, directory)
        if not inside:
            result.unknown = True
            record_root(rel, CLASS_EXCLUDED, UNKNOWN, present=True, reason=reason)
            return True, reason
        try:
            resolved = str(directory.resolve())
        except (OSError, RuntimeError) as exc:
            result.unknown = True
            record_root(rel, CLASS_DEEP, UNKNOWN, present=True, reason=str(exc))
            return True, str(exc)
        if resolved in seen_resolved:
            return True, "cycle skipped"
        seen_resolved.add(resolved)
        return False, ""

    try:
        skip, reason = skip_dir(host, "")
        if skip and reason.startswith("filesystem"):
            result.observation_failure = reason
            result.roots = list(recorded_roots.values())
            return result
        _walk(
            host,
            "",
            result,
            recorded_roots,
            record_root,
            hash_file,
            skip_dir,
            budget_exhausted,
            limits,
            enum_state=counter if counter is not None else result,
            on_directory=on_directory,
            dir_cache=dir_cache,
        )
        enum_state = counter if counter is not None else result
        result.entries_enumerated = enum_state.entries_enumerated
    except OSError as exc:
        result.unknown = True
        result.observation_failure = str(exc)

    for rel in exact:
        safe, reason = project_relative_path(host, rel)
        if safe is None:
            result.unknown = True
            key = _norm(rel) or str(rel)
            result.files[key] = {
                "type": "file",
                "digest": "",
                "observation": UNKNOWN,
            }
            record_root(key, CLASS_EXCLUDED, UNKNOWN, present=False, reason=reason)
            continue
        _exact_observe(host, safe, result, hash_file)
        row = result.files.get(safe) or {}
        if row.get("observation") == FULLY_OBSERVED and safe not in result.exact_observed:
            result.exact_observed.append(safe)

    result.roots = [recorded_roots[key] for key in sorted(recorded_roots)]
    return result


def _mark_truncated(result: InventoryObservation, recorded_rel: str, record_root, classification: str) -> None:
    result.truncated = True
    key = recorded_rel or "."
    if key not in result.truncated_paths:
        result.truncated_paths.append(key)
    record_root(
        key,
        classification,
        TRUNCATED_BY_BUDGET,
        present=True,
        reason="in-scope traversal exceeded inventory budget",
    )


def _mark_enum_truncated(enum_state: Any) -> None:
    if hasattr(enum_state, "truncated"):
        enum_state.truncated = True


def _walk(
    directory: Path,
    rel: str,
    result: InventoryObservation,
    recorded_roots: dict[str, RootRecord],
    record_root,
    hash_file,
    skip_dir,
    budget_exhausted,
    limits: InventoryBudget,
    enum_state: Any | None = None,
    on_directory: Any | None = None,
    dir_cache: Any | None = None,
) -> None:
    enum_state = result if enum_state is None else enum_state
    if result.truncated:
        return
    classification = classify_rel(rel) if rel else CLASS_DEEP
    if rel and classification == CLASS_EXCLUDED:
        record_root(
            rel,
            CLASS_EXCLUDED,
            EXCLUDED_BY_POLICY,
            present=True,
            reason="generic heavy-root class; contents not recursively hashed",
            count=None,
        )
        return
    if enum_state.entries_enumerated >= limits.max_entries:
        _mark_truncated(result, rel or ".", record_root, classification)
        _mark_enum_truncated(enum_state)
        return
    cached = _listing_from_cache(dir_cache, directory)
    if cached is not None:
        collected, overflow, scan_error = cached
    else:
        collected, overflow, scan_error = _stream_directory_names(
            directory,
            result=enum_state,
            max_entries=limits.max_entries,
        )
        if on_directory is not None:
            on_directory(
                directory,
                collected=collected,
                overflow=overflow,
                error=scan_error,
            )
    if scan_error:
        result.unknown = True
        record_root(rel or ".", classification, UNKNOWN, present=True, reason=scan_error)
        return
    if overflow:
        _mark_truncated(result, rel or ".", record_root, classification)
        _mark_enum_truncated(enum_state)
        return
    bounded = bool(rel) and classification == CLASS_BOUNDED
    file_count = 0
    for name in collected:
        if result.truncated:
            return
        child = directory / name
        child_rel = name if not rel else f"{rel}/{name}"
        try:
            is_dir = child.is_dir()
            is_file = child.is_file()
        except OSError as exc:
            result.unknown = True
            record_root(child_rel, classify_rel(child_rel), UNKNOWN, present=True, reason=str(exc))
            continue
        child_class = classify_rel(child_rel)
        if budget_exhausted() and child_class != CLASS_EXCLUDED:
            _mark_truncated(result, rel or ".", record_root, classification)
            return
        if is_dir:
            skip, _reason = skip_dir(child, child_rel)
            if skip:
                continue
            if child_class == CLASS_EXCLUDED:
                record_root(
                    child_rel,
                    CLASS_EXCLUDED,
                    EXCLUDED_BY_POLICY,
                    present=True,
                    reason="generic heavy-root class; contents not recursively hashed",
                    count=None,
                )
                continue
            if bounded:
                record_root(
                    child_rel,
                    child_class,
                    EXCLUDED_BY_POLICY if child_class == CLASS_EXCLUDED else FULLY_OBSERVED,
                    present=True,
                    reason="bounded parent; child directory recorded without recursive hashing",
                    count=None,
                )
                continue
            _walk(
                child,
                child_rel,
                result,
                recorded_roots,
                record_root,
                hash_file,
                skip_dir,
                budget_exhausted,
                limits,
                enum_state,
                on_directory,
                dir_cache,
            )
            if result.truncated:
                return
            continue
        host = _host_from_child(child, child_rel)
        if _is_link(child):
            inside, reason = resolved_inside_root(host, child)
            if not inside:
                result.unknown = True
                record_root(
                    child_rel,
                    classify_rel(child_rel),
                    UNKNOWN,
                    present=True,
                    reason=reason,
                )
                continue
        if not is_file:
            continue
        if child_class == CLASS_EXCLUDED:
            continue
        file_count += 1
        hash_file(child_rel, child, force=False)
    if bounded and not result.truncated:
        record_root(
            rel,
            CLASS_BOUNDED,
            FULLY_OBSERVED,
            present=True,
            reason="generic bounded class; shallow file hash only",
            count=file_count,
        )


def _host_from_child(child: Path, child_rel: str) -> Path:
    parts = _norm(child_rel).split("/")
    current = child
    for _ in parts:
        current = current.parent
    return current


def _exact_observe(host: Path, rel: str, result: InventoryObservation, hash_file) -> None:
    path = host / rel
    if not path.exists():
        result.files[rel] = {
            "type": "absent",
            "digest": "",
            "observation": FULLY_OBSERVED,
        }
        return
    if _is_link(path):
        inside, reason = resolved_inside_root(host, path)
        if not inside:
            result.unknown = True
            result.files[rel] = {
                "type": "file" if not path.is_dir() else "directory",
                "digest": "",
                "observation": UNKNOWN,
            }
            result.observation_failure = result.observation_failure or reason
            return
    if path.is_dir():
        result.files.setdefault(
            rel if rel.endswith("/") else rel,
            {
                "type": "directory",
                "digest": "",
                "observation": FULLY_OBSERVED,
            },
        )
        return
    if path.is_file():
        hash_file(rel, path, force=True)


def list_observed_files(observation: InventoryObservation) -> list[str]:
    return sorted(
        path
        for path, row in observation.files.items()
        if row.get("type") == "file" and row.get("observation") == FULLY_OBSERVED
    )


def hashed_inventory(observation: InventoryObservation) -> dict[str, dict[str, str]]:
    """Digest map used as Adoption Baseline inventory (fully observed files)."""
    out: dict[str, dict[str, str]] = {}
    for path, row in observation.files.items():
        if row.get("type") == "absent":
            out[path] = {
                "type": "absent",
                "digest": "",
                "observation": str(row.get("observation") or FULLY_OBSERVED),
            }
            continue
        if row.get("type") == "directory":
            out[path] = {
                "type": "directory",
                "digest": "",
                "observation": str(row.get("observation") or FULLY_OBSERVED),
            }
            continue
        if row.get("observation") != FULLY_OBSERVED:
            continue
        if row.get("type") != "file":
            continue
        out[path] = {
            "type": "file",
            "digest": str(row.get("digest") or ""),
            "observation": FULLY_OBSERVED,
        }
    return out

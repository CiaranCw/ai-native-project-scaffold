"""Operation-scoped discovery observation authority.

Internal P5 runtime only. Not a canonical record. One discover()
operation shares one enumeration budget and one per-directory cache.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scaffold_p5.inventory import (
    InventoryBudget,
    MetadataWalk,
    _stream_directory_names,
    directory_cache_key,
    list_observed_files,
    observe_inventory,
    project_relative_path,
    resolved_inside_root,
)
from scaffold_p5.scm import tracked_project_paths


DIR_COMPLETE = "COMPLETE"
DIR_TRUNCATED = "TRUNCATED"
DIR_UNKNOWN = "UNKNOWN"

RESOLVE_FOUND = "FOUND"
RESOLVE_ABSENT = "ABSENT"
RESOLVE_UNKNOWN = "UNKNOWN"
RESOLVE_UNSAFE = "UNSAFE"
RESOLVE_AMBIGUOUS = "AMBIGUOUS"

_UNRESOLVED = {RESOLVE_UNKNOWN, RESOLVE_UNSAFE, RESOLVE_AMBIGUOUS}


@dataclass
class DirectoryRecord:
    status: str
    by_lower: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolveOutcome:
    status: str
    path: str | None = None
    reason: str = ""

    @property
    def found(self) -> bool:
        return self.status == RESOLVE_FOUND and bool(self.path)


@dataclass
class DiscoverySession:
    root: Path
    budget: InventoryBudget
    walk: MetadataWalk
    index: dict[str, str] = field(default_factory=dict)
    index_complete: bool = False
    directories: dict[str, DirectoryRecord] = field(default_factory=dict)

    @classmethod
    def start(cls, root: str | Path, budget: InventoryBudget | None = None) -> DiscoverySession:
        limits = budget or InventoryBudget()
        session = cls(root=Path(root), budget=limits, walk=MetadataWalk())
        observation = observe_inventory(
            session.root,
            budget=limits,
            counter=session.walk,
            on_directory=session.remember_directory,
            dir_cache=session.directories,
        )
        for rel in list_observed_files(observation):
            session.index[_norm_key(rel)] = rel.replace("\\", "/")
        for rel in tracked_project_paths(session.root):
            session.index[_norm_key(rel)] = rel.replace("\\", "/")
        session.index_complete = (
            not observation.truncated
            and not observation.unknown
            and not session.walk.truncated
        )
        return session

    @classmethod
    def ephemeral(
        cls,
        root: str | Path,
        index: dict[str, str] | None = None,
        budget: InventoryBudget | None = None,
    ) -> DiscoverySession:
        limits = budget or InventoryBudget()
        return cls(
            root=Path(root),
            budget=limits,
            walk=MetadataWalk(),
            index=dict(index or {}),
            index_complete=False,
        )

    def directory_key(self, directory: Path) -> str:
        return directory_cache_key(directory)

    def remember_directory(
        self,
        directory: Path,
        *,
        collected: list[str] | None = None,
        overflow: bool = False,
        error: str = "",
    ) -> None:
        key = self.directory_key(Path(directory))
        if key in self.directories:
            return
        if error:
            self.directories[key] = DirectoryRecord(status=DIR_UNKNOWN)
            return
        if overflow:
            self.walk.truncated = True
            self.directories[key] = DirectoryRecord(status=DIR_TRUNCATED)
            return
        by_lower: dict[str, list[str]] = {}
        for name in collected or []:
            by_lower.setdefault(name.lower(), []).append(name)
        self.directories[key] = DirectoryRecord(status=DIR_COMPLETE, by_lower=by_lower)


def observe_directory(session: DiscoverySession, directory: Path) -> DirectoryRecord:
    """Stream one directory under the operation budget. Never rescan."""
    key = session.directory_key(directory)
    cached = session.directories.get(key)
    if cached is not None:
        return cached
    if session.walk.truncated or session.walk.entries_enumerated >= session.budget.max_entries:
        record = DirectoryRecord(status=DIR_TRUNCATED)
        session.directories[key] = record
        return record
    collected, overflow, error = _stream_directory_names(
        directory,
        result=session.walk,
        max_entries=session.budget.max_entries,
    )
    if error:
        record = DirectoryRecord(status=DIR_UNKNOWN)
        session.directories[key] = record
        session.walk.unknown = True
        session.walk.reason = session.walk.reason or error
        return record
    if overflow:
        session.walk.truncated = True
        record = DirectoryRecord(status=DIR_TRUNCATED)
        session.directories[key] = record
        return record
    by_lower: dict[str, list[str]] = {}
    for name in collected:
        by_lower.setdefault(name.lower(), []).append(name)
    record = DirectoryRecord(status=DIR_COMPLETE, by_lower=by_lower)
    session.directories[key] = record
    return record


def resolve_outcome(
    root: Path,
    candidate: str,
    index: dict[str, str] | None = None,
    *,
    session: DiscoverySession | None = None,
    budget: InventoryBudget | None = None,
) -> ResolveOutcome:
    """Resolve a repository-relative candidate under operation-scoped authority."""
    host = Path(root)
    active = session or DiscoverySession.ephemeral(host, index=index, budget=budget)
    mapping = index if index is not None else active.index
    key = _norm_key(candidate)
    if not key:
        return ResolveOutcome(RESOLVE_ABSENT, reason="path is empty")
    if key in mapping:
        authorized = _authorized_rel(host, mapping[key])
        if authorized is None:
            return ResolveOutcome(RESOLVE_UNSAFE, reason="index identity escapes project root")
        return ResolveOutcome(RESOLVE_FOUND, authorized)
    parts = [
        part
        for part in Path(str(candidate).replace("\\", "/")).parts
        if part not in {".", ""}
    ]
    if not parts:
        return ResolveOutcome(RESOLVE_ABSENT, reason="path is empty")
    if any(part == ".." for part in parts):
        return ResolveOutcome(RESOLVE_UNSAFE, reason="path is not project-relative")
    exact = _try_exact_chain(host, parts)
    if exact is not None:
        return exact
    current = host
    actual_parts: list[str] = []
    for part in parts:
        inside, reason = resolved_inside_root(host, current)
        if not inside:
            return ResolveOutcome(RESOLVE_UNSAFE, reason=reason)
        try:
            is_dir = current.is_dir()
        except OSError as exc:
            return ResolveOutcome(RESOLVE_UNKNOWN, reason=str(exc))
        if not is_dir:
            return ResolveOutcome(RESOLVE_ABSENT, reason="parent is not a directory")
        observed = observe_directory(active, current)
        if observed.status == DIR_TRUNCATED:
            return ResolveOutcome(
                RESOLVE_UNKNOWN,
                reason="directory observation truncated by budget",
            )
        if observed.status == DIR_UNKNOWN:
            return ResolveOutcome(RESOLVE_UNKNOWN, reason="directory observation failed")
        matches = observed.by_lower.get(part.lower()) or []
        if not matches:
            return ResolveOutcome(RESOLVE_ABSENT, reason="name not present in complete directory")
        if len(matches) > 1:
            return ResolveOutcome(
                RESOLVE_AMBIGUOUS,
                reason="case-fold collision",
            )
        match = matches[0]
        nxt = current / match
        inside, reason = resolved_inside_root(host, nxt)
        if not inside:
            return ResolveOutcome(RESOLVE_UNSAFE, reason=reason)
        actual_parts.append(match)
        current = nxt
    authorized = _authorized_rel(host, "/".join(actual_parts))
    if authorized is None:
        return ResolveOutcome(RESOLVE_UNSAFE, reason="resolved path escapes project root")
    try:
        present = current.exists()
    except OSError as exc:
        return ResolveOutcome(RESOLVE_UNKNOWN, reason=str(exc))
    if not present:
        return ResolveOutcome(RESOLVE_ABSENT, reason="path is missing")
    return ResolveOutcome(RESOLVE_FOUND, authorized)


def _try_exact_chain(host: Path, parts: list[str]) -> ResolveOutcome | None:
    current = host
    actual_parts: list[str] = []
    for part in parts:
        inside, reason = resolved_inside_root(host, current)
        if not inside:
            return ResolveOutcome(RESOLVE_UNSAFE, reason=reason)
        child = current / part
        try:
            exists = child.exists()
        except OSError as exc:
            return ResolveOutcome(RESOLVE_UNKNOWN, reason=str(exc))
        if not exists:
            return None
        inside, reason = resolved_inside_root(host, child)
        if not inside:
            return ResolveOutcome(RESOLVE_UNSAFE, reason=reason)
        try:
            actual_name = child.resolve().name
        except (OSError, RuntimeError):
            actual_name = part
        actual_parts.append(actual_name)
        current = child
    authorized = _authorized_rel(host, "/".join(actual_parts))
    if authorized is None:
        return ResolveOutcome(RESOLVE_UNSAFE, reason="resolved path escapes project root")
    return ResolveOutcome(RESOLVE_FOUND, authorized)


def _authorized_rel(root: Path, rel: str) -> str | None:
    safe, _reason = project_relative_path(root, rel)
    return safe


def _norm_key(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/").lower()


def unresolved(outcome: ResolveOutcome) -> bool:
    return outcome.status in _UNRESOLVED

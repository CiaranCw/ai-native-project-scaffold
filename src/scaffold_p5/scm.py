"""Shared read-only SCM observation for project-root-scoped Git truth."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import sha256_text
from scaffold_p5 import yaml_lite


OBSERVED = "OBSERVED"
OBSERVATION_FAILED = "OBSERVATION_FAILED"
SCM_ABSENT = "SCM_ABSENT"

CURRENT = "CURRENT"
AHEAD = "AHEAD"
STALE = "STALE"
DIVERGED = "DIVERGED"
NOT_CONFIGURED = "NOT_CONFIGURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"

SAFE_CURRENTNESS = frozenset({CURRENT, AHEAD, NOT_CONFIGURED, NOT_APPLICABLE})


@dataclass(frozen=True)
class ScmObservation:
    kind: str
    observation_state: str
    project_root: Path
    worktree_root: Path | None
    project_prefix: str
    revision: str | None
    branch: str | None
    head_state: str
    entries: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.observation_state in {OBSERVED, SCM_ABSENT}

    @property
    def scm_root_label(self) -> str | None:
        if self.kind != "git" or self.worktree_root is None:
            return None
        return "." if self.worktree_root == self.project_root else "parent"

    def public(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "observation_state": self.observation_state,
            "observation_ok": self.ok,
            "project_root": ".",
            "scm_root": self.scm_root_label,
            "project_prefix": self.project_prefix,
            "revision": self.revision,
            "branch": self.branch,
            "head_state": self.head_state,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class UpstreamCurrentness:
    kind: str
    observation_state: str
    state: str
    configured: bool
    local_revision: str | None
    upstream_ref: str | None
    upstream_revision: str | None
    ahead: int | None
    behind: int | None
    blockers: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.observation_state in {OBSERVED, SCM_ABSENT}
            and self.state != UNKNOWN
        )

    @property
    def safe(self) -> bool:
        return self.ok and self.state in SAFE_CURRENTNESS

    @property
    def basis_digest(self) -> str:
        if not self.ok:
            return ""
        body = {
            "kind": self.kind,
            "state": self.state,
            "configured": self.configured,
            "local_revision": self.local_revision,
            "upstream_ref": self.upstream_ref,
            "upstream_revision": self.upstream_revision,
            "ahead": self.ahead,
            "behind": self.behind,
        }
        return sha256_text(yaml_lite.dump(body))

    def public(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "observation_state": self.observation_state,
            "observation_ok": self.ok,
            "state": self.state,
            "configured": self.configured,
            "local_revision": self.local_revision,
            "upstream_ref": self.upstream_ref,
            "upstream_revision": self.upstream_revision,
            "ahead": self.ahead,
            "behind": self.behind,
            "basis_digest": self.basis_digest,
            "blockers": list(self.blockers),
        }


def observe_scm(root: str | Path) -> ScmObservation:
    project_root = Path(root).resolve()
    marker = _nearest_git_marker(project_root)
    top = _run_git(project_root, "rev-parse", "--show-toplevel")
    if not top.ok:
        if marker is not None:
            return _failed(
                project_root,
                "Git repository membership is present but worktree-root "
                "observation failed",
            )
        return ScmObservation(
            kind="none",
            observation_state=SCM_ABSENT,
            project_root=project_root,
            worktree_root=None,
            project_prefix=".",
            revision=None,
            branch=None,
            head_state="not_applicable",
            entries=(),
        )

    raw_top = top.stdout.strip()
    if not raw_top:
        return _failed(project_root, "Git returned an empty worktree root")
    worktree_root = Path(raw_top).resolve()
    try:
        project_relative = project_root.relative_to(worktree_root)
    except ValueError:
        return _failed(
            project_root,
            "Git worktree root does not contain the Scaffold project root",
            worktree_root=worktree_root,
        )
    if not worktree_root.is_dir():
        return _failed(
            project_root,
            "Git worktree root is not a resolvable directory",
            worktree_root=worktree_root,
        )
    project_prefix = (
        "."
        if project_relative == Path(".")
        else project_relative.as_posix().strip("/")
    )

    status_args = [
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--",
    ]
    status_args.append("." if project_prefix == "." else project_prefix)
    status = _run_git_bytes(worktree_root, *status_args)
    if not status.ok:
        return _failed(
            project_root,
            "Git project status observation failed",
            worktree_root=worktree_root,
            project_prefix=project_prefix,
        )
    parsed, issues = parse_porcelain_z(status.stdout)
    if issues:
        return _failed(
            project_root,
            "Git project status output is invalid: " + "; ".join(issues),
            worktree_root=worktree_root,
            project_prefix=project_prefix,
        )
    entries = _project_entries(parsed, project_prefix)

    revision_result = _run_git(worktree_root, "rev-parse", "--verify", "HEAD")
    branch_result = _run_git(
        worktree_root, "symbolic-ref", "--quiet", "--short", "HEAD"
    )
    revision = revision_result.stdout.strip() if revision_result.ok else None
    branch = branch_result.stdout.strip() if branch_result.ok else None
    if revision is None:
        if branch:
            head_state = "unborn"
        else:
            return _failed(
                project_root,
                "Git HEAD revision/state could not be established",
                worktree_root=worktree_root,
                project_prefix=project_prefix,
            )
    elif branch:
        head_state = "attached"
    elif branch_result.returncode == 1:
        head_state = "detached"
    else:
        return _failed(
            project_root,
            "Git HEAD attachment state could not be established",
            worktree_root=worktree_root,
            project_prefix=project_prefix,
        )

    return ScmObservation(
        kind="git",
        observation_state=OBSERVED,
        project_root=project_root,
        worktree_root=worktree_root,
        project_prefix=project_prefix,
        revision=revision,
        branch=branch,
        head_state=head_state,
        entries=tuple(entries),
    )


def observe_upstream_currentness(
    root: str | Path,
    *,
    scm: ScmObservation | None = None,
) -> UpstreamCurrentness:
    observed = scm or observe_scm(root)
    if observed.kind == "none" and observed.ok:
        return UpstreamCurrentness(
            kind="none",
            observation_state=SCM_ABSENT,
            state=NOT_APPLICABLE,
            configured=False,
            local_revision=None,
            upstream_ref=None,
            upstream_revision=None,
            ahead=None,
            behind=None,
        )
    if not observed.ok or observed.worktree_root is None:
        return _unknown_currentness(
            observed,
            "SCM observation is unresolved; upstream currentness is UNKNOWN",
        )
    if observed.revision is None:
        return UpstreamCurrentness(
            kind="git",
            observation_state=OBSERVED,
            state=NOT_CONFIGURED,
            configured=False,
            local_revision=None,
            upstream_ref=None,
            upstream_revision=None,
            ahead=None,
            behind=None,
        )

    branch = observed.branch
    if not branch:
        return UpstreamCurrentness(
            kind="git",
            observation_state=OBSERVED,
            state=NOT_CONFIGURED,
            configured=False,
            local_revision=observed.revision,
            upstream_ref=None,
            upstream_revision=None,
            ahead=None,
            behind=None,
        )

    remote = _run_git(
        observed.worktree_root, "config", "--get", f"branch.{branch}.remote"
    )
    merge = _run_git(
        observed.worktree_root, "config", "--get", f"branch.{branch}.merge"
    )
    if remote.returncode == 1 and merge.returncode == 1:
        return UpstreamCurrentness(
            kind="git",
            observation_state=OBSERVED,
            state=NOT_CONFIGURED,
            configured=False,
            local_revision=observed.revision,
            upstream_ref=None,
            upstream_revision=None,
            ahead=None,
            behind=None,
        )
    if not remote.ok or not merge.ok:
        return _unknown_currentness(
            observed,
            "configured Git upstream metadata cannot be resolved",
            configured=True,
        )

    upstream = _run_git(
        observed.worktree_root,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if not upstream.ok or not upstream.stdout.strip():
        return _unknown_currentness(
            observed,
            "configured Git upstream reference cannot be resolved",
            configured=True,
        )
    upstream_ref = upstream.stdout.strip()
    upstream_revision_result = _run_git(
        observed.worktree_root, "rev-parse", "--verify", upstream_ref
    )
    if not upstream_revision_result.ok or not upstream_revision_result.stdout.strip():
        return _unknown_currentness(
            observed,
            "configured Git upstream revision cannot be observed",
            configured=True,
            upstream_ref=upstream_ref,
        )
    upstream_revision = upstream_revision_result.stdout.strip()

    counts = _run_git(
        observed.worktree_root,
        "rev-list",
        "--left-right",
        "--count",
        f"HEAD...{upstream_ref}",
    )
    if not counts.ok:
        return _unknown_currentness(
            observed,
            "Git upstream ancestry/currentness cannot be established",
            configured=True,
            upstream_ref=upstream_ref,
            upstream_revision=upstream_revision,
        )
    parts = counts.stdout.split()
    if len(parts) != 2:
        return _unknown_currentness(
            observed,
            "Git upstream currentness returned invalid counts",
            configured=True,
            upstream_ref=upstream_ref,
            upstream_revision=upstream_revision,
        )
    try:
        ahead, behind = (int(parts[0]), int(parts[1]))
    except ValueError:
        return _unknown_currentness(
            observed,
            "Git upstream currentness returned non-numeric counts",
            configured=True,
            upstream_ref=upstream_ref,
            upstream_revision=upstream_revision,
        )
    if ahead < 0 or behind < 0:
        return _unknown_currentness(
            observed,
            "Git upstream currentness returned invalid negative counts",
            configured=True,
            upstream_ref=upstream_ref,
            upstream_revision=upstream_revision,
        )
    if ahead and behind:
        state = DIVERGED
    elif behind:
        state = STALE
    elif ahead:
        state = AHEAD
    else:
        state = CURRENT
    return UpstreamCurrentness(
        kind="git",
        observation_state=OBSERVED,
        state=state,
        configured=True,
        local_revision=observed.revision,
        upstream_ref=upstream_ref,
        upstream_revision=upstream_revision,
        ahead=ahead,
        behind=behind,
    )


def tracked_project_paths(root: str | Path) -> tuple[str, ...]:
    """Return Git-tracked project-relative paths using repository spelling.

    Empty when SCM is absent or observation failed. This is path identity
    evidence, not a second Git implementation.
    """
    observed = observe_scm(root)
    if observed.kind != "git" or not observed.ok or observed.worktree_root is None:
        return ()
    listed = _run_git_bytes(observed.worktree_root, "ls-files", "-z", "-c")
    if not listed.ok:
        return ()
    paths: list[str] = []
    for raw in listed.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        relative = _strip_project_prefix(
            text.replace("\\", "/"), observed.project_prefix
        )
        if relative:
            paths.append(relative)
    return tuple(paths)


def project_to_worktree_path(observed: ScmObservation, project_path: str) -> str:
    """Translate a project-relative path for Git tree/index object operations."""
    normalized = str(project_path or "").replace("\\", "/").strip("/")
    if (
        not normalized
        or normalized == "."
        or normalized == ".."
        or normalized.startswith("../")
        or "/../" in f"/{normalized}/"
    ):
        return ""
    if observed.project_prefix == ".":
        return normalized
    return f"{observed.project_prefix.rstrip('/')}/{normalized}"


def parse_porcelain_z(payload: bytes) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    issues: list[str] = []
    parts = payload.split(b"\0")
    index = 0
    while index < len(parts):
        raw = parts[index]
        index += 1
        if not raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            issues.append("porcelain entry is not valid UTF-8")
            continue
        if len(text) < 4 or text[2] != " ":
            issues.append("porcelain entry is malformed")
            continue
        code = text[:2]
        path = text[3:].replace("\\", "/")
        if not path:
            issues.append("porcelain entry has an empty path")
            continue
        orig_path = ""
        if any(value in {"R", "C"} for value in code):
            if index >= len(parts) or not parts[index]:
                issues.append("rename/copy entry is missing its original path")
                continue
            try:
                orig_path = parts[index].decode("utf-8").replace("\\", "/")
            except UnicodeError:
                issues.append("rename/copy origin is not valid UTF-8")
                index += 1
                continue
            index += 1
        entries.append(
            {
                "code": code,
                "path": path,
                "orig_path": orig_path,
                "untracked": code == "??",
            }
        )
    return entries, issues


@dataclass(frozen=True)
class _GitResult:
    ok: bool
    returncode: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class _GitBytesResult:
    ok: bool
    returncode: int | None
    stdout: bytes
    stderr: bytes


def _run_git(root: Path, *args: str) -> _GitResult:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return _GitResult(False, None, "", str(exc))
    return _GitResult(
        completed.returncode == 0,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _run_git_bytes(root: Path, *args: str) -> _GitBytesResult:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _GitBytesResult(False, None, b"", str(exc).encode("utf-8"))
    return _GitBytesResult(
        completed.returncode == 0,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _nearest_git_marker(root: Path) -> Path | None:
    current = root
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _project_entries(
    entries: list[dict[str, Any]], project_prefix: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        path = _strip_project_prefix(str(entry.get("path") or ""), project_prefix)
        orig = _strip_project_prefix(
            str(entry.get("orig_path") or ""), project_prefix
        )
        if path is None and orig is None:
            continue
        if path is None and orig is not None:
            path = orig
            orig = ""
        row = dict(entry)
        row["path"] = path or ""
        row["orig_path"] = orig or ""
        out.append(row)
    return out


def _strip_project_prefix(value: str, prefix: str) -> str | None:
    normalized = value.replace("\\", "/").strip("/")
    if not normalized:
        return None
    if prefix == ".":
        return normalized
    if normalized == prefix:
        return ""
    marker = prefix.rstrip("/") + "/"
    if not normalized.startswith(marker):
        return None
    return normalized[len(marker) :]


def _failed(
    project_root: Path,
    reason: str,
    *,
    worktree_root: Path | None = None,
    project_prefix: str = ".",
) -> ScmObservation:
    return ScmObservation(
        kind="git",
        observation_state=OBSERVATION_FAILED,
        project_root=project_root,
        worktree_root=worktree_root,
        project_prefix=project_prefix,
        revision=None,
        branch=None,
        head_state="unavailable",
        entries=(),
        blockers=(reason,),
    )


def _unknown_currentness(
    observed: ScmObservation,
    reason: str,
    *,
    configured: bool = False,
    upstream_ref: str | None = None,
    upstream_revision: str | None = None,
) -> UpstreamCurrentness:
    return UpstreamCurrentness(
        kind=observed.kind,
        observation_state=(
            observed.observation_state
            if not observed.ok
            else OBSERVATION_FAILED
        ),
        state=UNKNOWN,
        configured=configured,
        local_revision=observed.revision,
        upstream_ref=upstream_ref,
        upstream_revision=upstream_revision,
        ahead=None,
        behind=None,
        blockers=(reason,),
    )

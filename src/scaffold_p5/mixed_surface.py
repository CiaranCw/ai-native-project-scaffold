"""Canonical mixed-ownership human surface.

One projection for ``.gitattributes``, ``AGENTS.md``, and
``.cursor/hooks.json``. Managed Scaffold bytes are removed per region.
The comparison ignores only the framing bytes the installer itself
writes around that region, by projecting HEAD through the same installer
function. It does not normalize arbitrary whitespace or human content.

Region identity is the canonical expected representation or an explicitly
supported predecessor digest, keyed by host path and region id. Every
Scaffold-owned region present in the live file must match one of those
identities. Every Scaffold-owned region present in the reference must
still be present. A new region may be added when its own identity
attests. No current lifecycle operation is authorized to delete one.
A mutable install.yaml region record is not a root of trust.

Hook events that contain no remaining human command after Scaffold
commands are removed are omitted. An empty list is not a human command.
Events that still contain a human command keep that command and its
fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from scaffold_p5.agents import (
    AGENTS_ROUTER_REGION,
    ALLOWED_AGENTS_REGIONS,
    CONSUMER_INSTALL_REGION,
    human_surface,
    integrated_agents_text,
    parse_managed_regions,
)
from scaffold_p5.consumer_install import (
    AGENTS_MD,
    FRAGMENT_HOST_PATHS,
    GITATTRIBUTES,
    GITATTR_REGION,
    REGION_HOST_PATHS,
    _live_region_slice,
    _manifest_format_ok,
    apply_consumer_install_region,
    apply_gitattributes_region,
    current_manifest,
    expected_managed_region_digest,
    is_install_managed_path,
    manifest_file_map,
    parse_gitattributes_region,
    predecessor_managed_region_digests,
)
from scaffold_p5.first_use import (
    HOOKS_JSON_REL,
    dumps_hooks_json,
    inspect_scaffold_hook_fragment,
    is_scaffold_hook_command,
    merge_scaffold_hooks,
)
from scaffold_p5.io_util import file_digest, sha256_bytes
from scaffold_p5.scm import _run_git_bytes, git_path_is_tracked, observe_scm


def human_owned_surface(rel: str, text: str) -> str | None:
    """Human-owned bytes of a mixed-ownership host file.

    ``None`` means the file cannot be projected safely and therefore cannot
    be treated as install-managed. Hooks return a canonical JSON document of
    the non-Scaffold entries, including their order.
    """
    normalized = rel.replace("\\", "/").strip("/")
    if normalized == GITATTRIBUTES:
        spans, issues = parse_gitattributes_region(text)
        if issues:
            return None
        return human_surface(text, spans)
    if normalized == AGENTS_MD:
        spans, issues = parse_managed_regions(text)
        if issues:
            return None
        owned = {
            region_id: span
            for region_id, span in spans.items()
            if region_id in ALLOWED_AGENTS_REGIONS
        }
        return human_surface(text, owned)
    if normalized == HOOKS_JSON_REL:
        return _hooks_human_surface(text)
    return None


def human_owned_surface_matches(
    rel: str,
    live_text: str,
    reference_text: str,
    *,
    adopt_router: bool = False,
) -> bool:
    """True when live human bytes equal the reference or its legal projection.

    Direct equality covers a region-interior edit that leaves every outside
    byte untouched. Equality with the installer projection of the reference
    covers the separator newline and trailing newline that
    ``apply_gitattributes_region`` / ``apply_consumer_install_region`` insert
    around a managed region. An adopted host also projects the
    ``agents-router`` region through ``integrated_agents_text``. Nothing else
    is normalized.
    """
    normalized = rel.replace("\\", "/").strip("/")
    live = human_owned_surface(normalized, live_text)
    if live is None:
        return False
    reference = reference_text
    if normalized == HOOKS_JSON_REL and reference == "":
        reference = dumps_hooks_json(merge_scaffold_hooks(None))
    ref_surface = human_owned_surface(normalized, reference)
    if ref_surface is not None and live == ref_surface:
        return True
    if normalized == HOOKS_JSON_REL:
        return False
    projected = _installer_projection(
        normalized, reference_text, adopt_router=adopt_router
    )
    if projected is None:
        return False
    projected_surface = human_owned_surface(normalized, projected)
    return projected_surface is not None and live == projected_surface


def install_managed_bytes_verified(
    root: str | Path, rel: str, *, adopt_router: bool | None = None
) -> bool:
    """True only when install authority attests these bytes.

    Whole-file MANAGED entries must match the manifest file digest. Every
    Scaffold-owned region present in the live file must match
    ``expected_managed_region_digest`` or
    ``predecessor_managed_region_digests`` for that path and region id.
    Every Scaffold-owned region present in HEAD must still be present.
    The human surface must match HEAD or the installer's projection of
    HEAD. A hooks file must have an undrifted Scaffold fragment and an
    unchanged human entry surface. Path shape alone never attests. A
    manifest digest never attests a region or a fragment. Silent deletion
    of a reference region is not install-only.
    """
    host = Path(root)
    normalized = rel.replace("\\", "/").strip("/")
    path = host / normalized
    if not path.is_file():
        return False
    manifest = current_manifest(host)
    manifest_ok = isinstance(manifest, dict) and _manifest_format_ok(manifest)
    if is_install_managed_path(normalized) and manifest_ok:
        try:
            if manifest_file_map(manifest).get(normalized) == file_digest(path):
                return True
        except OSError:
            return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if normalized in REGION_HOST_PATHS:
        if not manifest_ok or not _region_identity_attested(host, normalized, text):
            return False
        if not _region_presence_preserved(
            host, normalized, text, adopt_router=adopt_router
        ):
            return False
        return _human_surface_attested(
            host, normalized, text, adopt_router=adopt_router
        )
    if normalized in FRAGMENT_HOST_PATHS:
        if not manifest_ok or not _hook_fragment_attested(text):
            return False
        return _human_surface_attested(host, normalized, text)
    return False


def _region_presence_preserved(
    root: Path,
    rel: str,
    live_text: str,
    *,
    adopt_router: bool | None = None,
) -> bool:
    """True when every reference Scaffold region is still present.

    The reference is HEAD for a tracked file and empty text for an
    untracked file. A legal install may add a region. It may not drop
    one that the reference already contained. A malformed reference or
    live file fails closed. Identity of the surviving regions is a
    separate check.
    """
    tracked = git_path_is_tracked(root, rel)
    if tracked is True:
        reference = _head_file_text(root, rel)
        if reference is None:
            return False
    elif tracked is False:
        reference = ""
    else:
        return False
    reference_ids = _scaffold_owned_region_ids(rel, reference)
    live_ids = _scaffold_owned_region_ids(rel, live_text)
    if reference_ids is None or live_ids is None:
        return False
    require_router = (
        _agents_router_projection(root, rel)
        if adopt_router is None
        else bool(adopt_router)
    )
    if require_router and not {CONSUMER_INSTALL_REGION, AGENTS_ROUTER_REGION} <= live_ids:
        return False
    return reference_ids <= live_ids


def _scaffold_owned_region_ids(rel: str, text: str) -> set[str] | None:
    """Scaffold-owned region ids, or None when the markers are not parseable."""
    if rel == AGENTS_MD:
        spans, issues = parse_managed_regions(text)
        if issues:
            return None
        return {region_id for region_id in spans if region_id in ALLOWED_AGENTS_REGIONS}
    if rel == GITATTRIBUTES:
        spans, issues = parse_gitattributes_region(text)
        if issues:
            return None
        return {region_id for region_id in spans if region_id == GITATTR_REGION}
    return None


def _region_identity_attested(root: Path, rel: str, text: str) -> bool:
    slices = _scaffold_owned_region_slices(rel, text)
    if not slices:
        return False
    for region_id, slice_text in slices:
        live = sha256_bytes(slice_text.encode("utf-8"))
        if live in predecessor_managed_region_digests(rel, region_id):
            continue
        expected = expected_managed_region_digest(rel, region_id, host=root)
        if expected is None or live != expected:
            return False
    return True


def _scaffold_owned_region_slices(
    rel: str, text: str
) -> list[tuple[str, str]] | None:
    """Scaffold-owned slices the human surface removes, or None if unreadable.

    An empty list means the file has no Scaffold-owned region to attest.
    A region id with no expected or predecessor identity fails closed in
    ``_region_identity_attested`` because its digest cannot match.
    """
    if rel == AGENTS_MD:
        spans, issues = parse_managed_regions(text)
        if issues:
            return None
        owned: list[tuple[str, str]] = []
        for region_id, span in spans.items():
            if region_id not in ALLOWED_AGENTS_REGIONS:
                continue
            start, end = span
            owned.append((region_id, text[start:end]))
        return owned
    if rel == GITATTRIBUTES:
        slice_text, issues = _live_region_slice(rel, text)
        if issues or not slice_text:
            return None
        return [(GITATTR_REGION, slice_text)]
    return None


def _hook_fragment_attested(text: str) -> bool:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    fragment, missing, drifted, _incompat = inspect_scaffold_hook_fragment(data)
    return fragment is not None and not missing and not drifted


def _human_surface_attested(
    root: Path, rel: str, text: str, *, adopt_router: bool | None = None
) -> bool:
    use_router = (
        _agents_router_projection(root, rel) if adopt_router is None else adopt_router
    )
    tracked = git_path_is_tracked(root, rel)
    if tracked is True:
        head = _head_file_text(root, rel)
        if head is None:
            return False
        return human_owned_surface_matches(
            rel, text, head, adopt_router=use_router
        )
    if tracked is False:
        return human_owned_surface_matches(
            rel, text, "", adopt_router=use_router
        )
    return False


def _agents_adoption_applied(root: Path) -> bool:
    """True when Adoption has written the skills lock.

    ``project.yaml`` alone is not this signal. Structural Review fixtures
    write that file without performing the router integration. Ownership
    ``MANAGED`` and install.yaml digests are not this signal either.
    """
    return (root / ".scaffold" / "skills.lock").is_file()


def _agents_router_projection(root: Path, rel: str) -> bool:
    return rel == AGENTS_MD and _agents_adoption_applied(root)


def _installer_projection(
    rel: str, text: str, *, adopt_router: bool = False
) -> str | None:
    if rel == GITATTRIBUTES:
        return apply_gitattributes_region(text)
    if rel == AGENTS_MD:
        installed = apply_consumer_install_region(text)
        if installed is None:
            return None
        if not adopt_router:
            return installed
        return integrated_agents_text(installed)
    return None


def _hooks_human_surface(text: str) -> str | None:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    hooks = data.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        return None
    human_hooks: dict[str, list] = {}
    for event, items in hooks.items():
        if not isinstance(items, list):
            return None
        kept = [item for item in items if not is_scaffold_hook_command(item)]
        if not kept:
            continue
        human_hooks[str(event)] = kept
    extra = {
        key: data[key]
        for key in sorted(data)
        if key not in {"version", "hooks"}
    }
    payload = {
        "version": data.get("version"),
        "hooks": human_hooks,
        "extra": extra,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _head_file_text(root: Path, rel: str) -> str | None:
    scm = observe_scm(root)
    if scm.kind != "git" or not scm.ok or not scm.revision or scm.worktree_root is None:
        return None
    prefix = str(scm.project_prefix or "").strip("/")
    git_path = rel if prefix in {"", "."} else prefix + "/" + rel
    shown = _run_git_bytes(scm.worktree_root, "show", f"{scm.revision}:{git_path}")
    if not shown.ok:
        return None
    try:
        return shown.stdout.decode("utf-8")
    except UnicodeError:
        return None

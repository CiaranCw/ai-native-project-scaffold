"""P6 candidate projection-generation migration.

Generation 1 remains the published legacy projection. Generation 2 is the
current maintenance-neutral projection. A migration record is proof that one
observed tree's generation-1 body and generation-2 body differ only by that
reclassification. Callers cannot supply the digest pair.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scaffold_p5.io_util import sha256_bytes, sha256_text, write_yaml_atomic
from scaffold_p5 import yaml_lite

from scaffold_p6.candidate import (
    MIXED_OWNERSHIP_PATHS,
    inventory_fingerprint,
    is_install_infrastructure,
    observe_candidate,
    projected_digest_of_bytes,
    projected_mixed_digest,
    semantic_body,
    tracked_mixed_matches_head,
)
from scaffold_p6.models import (
    DURABLE_EVIDENCE_ROOT,
    PROJECTION_GENERATION_CURRENT,
    PROJECTION_GENERATION_LEGACY,
    SESSIONS_DIR,
    TASKS_DIR,
    TEST_RUNS,
)
MIGRATION_RECORD_TYPE = "candidate_projection_migration"
MIGRATION_SCHEMA_VERSION = "1"
MIGRATION_REASON = "projection_generation_boundary"
MIGRATION_DIR = ".scaffold/runtime/candidate-projection"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_NEUTRAL_BODY_KEYS = frozenset(
    {
        "projection_generation",
        "tracked_paths",
        "untracked_paths",
        "workspace_fingerprint",
        "file_count",
    }
)


def migration_dir(root: str | Path) -> Path:
    return Path(root) / ".scaffold" / "runtime" / "candidate-projection"


def establish_projection_migration(
    root: str | Path,
    *,
    automatic: bool = False,
) -> dict[str, Any]:
    """Observe this tree under both generations and record a 1→2 proof.

    Idempotent when the same proof is already durable. Refuses to overwrite a
    valid proof with a different target. Does not accept caller digests.
    Automatic install/update calls record a proof only when cited legacy
    generation-1 authority still needs one.
    """
    host = Path(root)
    cited = _legacy_authority_digests(host) if automatic else set()
    if automatic and not cited:
        return _skipped()
    legacy = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
    current = observe_candidate(host, generation=PROJECTION_GENERATION_CURRENT)
    if not legacy.usable or not current.usable:
        blockers = list(legacy.data.get("blockers") or []) + list(
            current.data.get("blockers") or []
        )
        return _blocked(blockers or ["candidate projection observation failed"])
    source_body = semantic_body(legacy.data)
    target_body = semantic_body(current.data)
    source_inventory = legacy.inventory if legacy.data.get("kind") == "none" else None
    target_inventory = current.inventory if current.data.get("kind") == "none" else None
    if not _creation_equivalent(
        host,
        source_body,
        target_body,
        source_inventory,
        target_inventory,
    ):
        return _blocked(
            [
                "generation-1 and generation-2 observations are not a "
                "projection reclassification of the same tree"
            ]
        )
    source_canonical = yaml_lite.dump(source_body)
    target_canonical = yaml_lite.dump(target_body)
    if sha256_text(source_canonical) != legacy.digest:
        return _blocked(["generation-1 canonical body does not match its digest"])
    if sha256_text(target_canonical) != current.digest:
        return _blocked(["generation-2 canonical body does not match its digest"])
    if automatic and not _cited_needs_new_record(
        host, cited, legacy.digest, current.digest
    ):
        return _skipped()
    mixed_bytes = _capture_mixed_bytes(host, source_body, source_inventory)
    mixed_issue = _mixed_bytes_issue(
        mixed_bytes,
        source_body,
        target_body,
        source_inventory,
        target_inventory,
        root=host,
    )
    if mixed_issue is not None:
        return _blocked([f"mixed-ownership boundary proof failed: {mixed_issue}"])
    record = {
        "record_type": MIGRATION_RECORD_TYPE,
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "source_generation": PROJECTION_GENERATION_LEGACY,
        "target_generation": PROJECTION_GENERATION_CURRENT,
        "source_digest": legacy.digest,
        "target_digest": current.digest,
        "source_body_canonical": source_canonical,
        "target_body_canonical": target_canonical,
        "source_inventory_canonical": _inventory_canonical(source_inventory),
        "target_inventory_canonical": _inventory_canonical(target_inventory),
        "mixed_source_bytes": mixed_bytes,
        "reason": MIGRATION_REASON,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = _record_path(host, legacy.digest)
    existing = _read_record(path)
    if existing is not None and _record_proof_ok(existing, host):
        if (
            existing.get("source_digest") == legacy.digest
            and existing.get("target_digest") == current.digest
        ):
            return _completed(existing, path, host, resumed=True)
        return _blocked(
            [
                "a projection migration for this generation-1 candidate "
                "already exists with a different target"
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_atomic(path, record)
    stored = _read_record(path)
    if stored is None:
        return _blocked(["projection migration record could not be read after write"])
    issue = _record_proof_issue(stored, host)
    if issue is not None:
        return _blocked(
            [f"projection migration record failed verification after write: {issue}"]
        )
    if stored.get("target_digest") != current.digest:
        return _blocked(["stored projection migration target does not match observation"])
    return _completed(stored, path, host, resumed=False)


def digest_is_current(
    root: str | Path,
    stored_digest: str,
    live_digest: str,
    *,
    stored_generation: str | None = None,
) -> bool:
    """True when stored authority matches the live candidate exactly or by one 1→2 proof."""
    stored = str(stored_digest or "").strip()
    live = str(live_digest or "").strip()
    if not stored or not live:
        return False
    if stored == live:
        return True
    generation = stored_generation or PROJECTION_GENERATION_LEGACY
    if generation != PROJECTION_GENERATION_LEGACY:
        return False
    host = Path(root)
    live_gen1 = observe_candidate(host, generation=PROJECTION_GENERATION_LEGACY)
    if live_gen1.usable and live_gen1.digest == stored:
        return True
    for record in _load_records(host):
        if not _record_proof_ok(record, host):
            continue
        if record.get("source_digest") != stored:
            continue
        if record.get("target_digest") != live:
            continue
        if record.get("source_generation") != PROJECTION_GENERATION_LEGACY:
            continue
        if record.get("target_generation") != PROJECTION_GENERATION_CURRENT:
            continue
        return True
    return False


def _projection_omitted(root: Path | None, path: str) -> bool:
    """Generation-2 omission is install infrastructure only.

    Client-delivery bytes are not omitted because a live runtime generator
    agrees with them. ``root`` is unused; callers still pass the host.
    """
    del root
    return is_install_infrastructure(path)


def _creation_equivalent(
    root: Path,
    source_body: dict[str, Any],
    target_body: dict[str, Any],
    source_inventory: dict[str, dict[str, str]] | None,
    target_inventory: dict[str, dict[str, str]] | None,
) -> bool:
    if not _bodies_structurally_related(source_body, target_body):
        return False
    if not _paths_match_projection(root, source_body.get("tracked_paths"), target_body.get("tracked_paths")):
        return False
    if not _paths_match_projection(
        root, source_body.get("untracked_paths"), target_body.get("untracked_paths")
    ):
        return False
    if source_body.get("kind") == "none":
        return _inventories_match_projection(
            root,
            source_body,
            target_body,
            source_inventory,
            target_inventory,
        )
    return True


def _bodies_structurally_related(
    source_body: dict[str, Any],
    target_body: dict[str, Any],
) -> bool:
    if not isinstance(source_body, dict) or not isinstance(target_body, dict):
        return False
    if "projection_generation" in source_body:
        return False
    if target_body.get("projection_generation") != PROJECTION_GENERATION_CURRENT:
        return False
    if source_body.get("kind") != target_body.get("kind"):
        return False
    keys = set(source_body) | set(target_body)
    for key in keys:
        if key in _NEUTRAL_BODY_KEYS:
            continue
        if source_body.get(key) != target_body.get(key):
            return False
    if source_body.get("kind") != "none":
        if source_body.get("file_count") != target_body.get("file_count"):
            return False
        if source_body.get("workspace_fingerprint") != target_body.get("workspace_fingerprint"):
            return False
    return True


def _paths_match_projection(
    root: Path,
    source_rows: Any,
    target_rows: Any,
) -> bool:
    if not isinstance(source_rows, list) or not isinstance(target_rows, list):
        return False
    if any(
        isinstance(row, dict) and _projection_omitted(root, str(row.get("path") or ""))
        for row in target_rows
    ):
        return False
    expected: list[dict[str, Any]] = []
    for row in source_rows:
        if not isinstance(row, dict):
            return False
        path = str(row.get("path") or "")
        if _projection_omitted(root, path):
            continue
        projected = dict(row)
        if path in MIXED_OWNERSHIP_PATHS:
            digest = projected_mixed_digest(root, path)
            if digest is not None:
                projected["digest"] = digest
        expected.append(projected)
    expected_by = {str(row.get("path") or ""): row for row in expected}
    target_by: dict[str, dict[str, Any]] = {}
    for row in target_rows:
        if not isinstance(row, dict):
            return False
        target_by[str(row.get("path") or "")] = row
    if set(target_by) - set(expected_by):
        return False
    for path, target_row in target_by.items():
        if expected_by[path] != target_row:
            return False
    for path in expected_by:
        if path in target_by:
            continue
        if path not in MIXED_OWNERSHIP_PATHS:
            return False
        if not tracked_mixed_matches_head(root, path):
            return False
    expected_order = [str(row.get("path") or "") for row in expected if str(row.get("path") or "") in target_by]
    return expected_order == list(target_by)


def _inventories_match_projection(
    root: Path,
    source_body: dict[str, Any],
    target_body: dict[str, Any],
    source_inventory: dict[str, dict[str, str]] | None,
    target_inventory: dict[str, dict[str, str]] | None,
) -> bool:
    if not isinstance(source_inventory, dict) or not isinstance(target_inventory, dict):
        return False
    expected: dict[str, dict[str, str]] = {}
    for path in sorted(source_inventory):
        row = source_inventory[path]
        if not isinstance(row, dict):
            return False
        if _projection_omitted(root, path):
            continue
        projected = dict(row)
        if path in MIXED_OWNERSHIP_PATHS:
            digest = projected_mixed_digest(root, path)
            if digest is not None:
                projected["digest"] = digest
        expected[path] = projected
    if expected != target_inventory:
        return False
    if inventory_fingerprint(source_inventory) != source_body.get("workspace_fingerprint"):
        return False
    if inventory_fingerprint(target_inventory) != target_body.get("workspace_fingerprint"):
        return False
    if source_body.get("file_count") != len(source_inventory):
        return False
    if target_body.get("file_count") != len(target_inventory):
        return False
    return True


def _record_proof_ok(record: dict[str, Any], root: Path | None = None) -> bool:
    return _record_proof_issue(record, root) is None


def _record_proof_issue(record: dict[str, Any], root: Path | None = None) -> str | None:
    if record.get("record_type") != MIGRATION_RECORD_TYPE:
        return "record_type"
    if record.get("schema_version") != MIGRATION_SCHEMA_VERSION:
        return "schema_version"
    if record.get("reason") != MIGRATION_REASON:
        return "reason"
    if record.get("source_generation") != PROJECTION_GENERATION_LEGACY:
        return "source_generation"
    if record.get("target_generation") != PROJECTION_GENERATION_CURRENT:
        return "target_generation"
    source_digest = str(record.get("source_digest") or "")
    target_digest = str(record.get("target_digest") or "")
    if not _HEX64.fullmatch(source_digest) or not _HEX64.fullmatch(target_digest):
        return "digest shape"
    source_canonical = record.get("source_body_canonical")
    target_canonical = record.get("target_body_canonical")
    if not isinstance(source_canonical, str) or not isinstance(target_canonical, str):
        return "canonical type"
    if sha256_text(source_canonical) != source_digest:
        return "source hash"
    if sha256_text(target_canonical) != target_digest:
        return "target hash"
    try:
        source_body = yaml_lite.load(source_canonical)
        target_body = yaml_lite.load(target_canonical)
    except (ValueError, TypeError) as exc:
        return f"body load: {exc}"
    if not _bodies_structurally_related(source_body, target_body):
        return "body relation"
    if not _paths_structurally_related(
        source_body.get("tracked_paths"),
        target_body.get("tracked_paths"),
        root,
    ):
        return "tracked paths"
    if not _paths_structurally_related(
        source_body.get("untracked_paths"),
        target_body.get("untracked_paths"),
        root,
    ):
        return "untracked paths"
    if source_body.get("kind") == "none":
        inventory_issue = _stored_inventory_issue(
            record, source_body, target_body, root
        )
        if inventory_issue is not None:
            return "inventory: " + inventory_issue
    mixed_issue = _mixed_bytes_issue(
        record.get("mixed_source_bytes"),
        source_body,
        target_body,
        _load_inventory(record.get("source_inventory_canonical")),
        _load_inventory(record.get("target_inventory_canonical")),
        root=root,
    )
    if mixed_issue is not None:
        return "mixed bytes: " + mixed_issue
    return None


def _paths_structurally_related(
    source_rows: Any,
    target_rows: Any,
    root: Path | None = None,
) -> bool:
    if not isinstance(source_rows, list) or not isinstance(target_rows, list):
        return False
    if any(
        isinstance(row, dict)
        and _projection_omitted(root, str(row.get("path") or ""))
        for row in target_rows
    ):
        return False
    filtered: list[dict[str, Any]] = []
    for row in source_rows:
        if not isinstance(row, dict):
            return False
        if _projection_omitted(root, str(row.get("path") or "")):
            continue
        filtered.append(row)
    target_clean = [row for row in target_rows if isinstance(row, dict)]
    if len(target_clean) != len(target_rows):
        return False
    target_by = {str(row.get("path") or ""): row for row in target_clean}
    filtered_by = {str(row.get("path") or ""): row for row in filtered}
    if set(target_by) - set(filtered_by):
        return False
    for path, target in target_by.items():
        source = filtered_by[path]
        if path in MIXED_OWNERSHIP_PATHS:
            source_rest = {key: value for key, value in source.items() if key != "digest"}
            target_rest = {key: value for key, value in target.items() if key != "digest"}
            if source_rest != target_rest:
                return False
            continue
        if source != target:
            return False
    for path in filtered_by:
        if path in target_by:
            continue
        if path not in MIXED_OWNERSHIP_PATHS:
            return False
    expected_order = [str(row.get("path") or "") for row in filtered if str(row.get("path") or "") in target_by]
    return expected_order == list(target_by)


def _stored_inventories_related(
    record: dict[str, Any],
    source_body: dict[str, Any],
    target_body: dict[str, Any],
    root: Path | None = None,
) -> bool:
    return _stored_inventory_issue(record, source_body, target_body, root) is None


def _stored_inventory_issue(
    record: dict[str, Any],
    source_body: dict[str, Any],
    target_body: dict[str, Any],
    root: Path | None = None,
) -> str | None:
    source_text = record.get("source_inventory_canonical")
    target_text = record.get("target_inventory_canonical")
    if not isinstance(source_text, str) or not isinstance(target_text, str):
        return "canonical type"
    try:
        source_inventory = yaml_lite.load(source_text)
        target_inventory = yaml_lite.load(target_text)
    except (ValueError, TypeError) as exc:
        return f"load: {exc}"
    if not isinstance(source_inventory, dict) or not isinstance(target_inventory, dict):
        return "shape"
    if any(_projection_omitted(root, str(path)) for path in target_inventory):
        return "neutral path in target"
    filtered: dict[str, Any] = {}
    for path in sorted(source_inventory):
        if _projection_omitted(root, str(path)):
            continue
        filtered[str(path)] = source_inventory[path]
    target_paths = [str(path) for path in target_inventory]
    if sorted(filtered) != sorted(target_paths):
        return "path set"
    for path, source_row in filtered.items():
        target_row = target_inventory.get(path)
        if not isinstance(source_row, dict) or not isinstance(target_row, dict):
            return f"row type {path}"
        if path in MIXED_OWNERSHIP_PATHS:
            if {k: v for k, v in source_row.items() if k != "digest"} != {
                k: v for k, v in target_row.items() if k != "digest"
            }:
                return f"mixed row {path}"
            continue
        if source_row != target_row:
            return f"row {path}"
    try:
        source_fp = inventory_fingerprint(source_inventory)
        target_fp = inventory_fingerprint(target_inventory)
    except (AttributeError, TypeError) as exc:
        return f"fingerprint: {exc}"
    if source_fp != source_body.get("workspace_fingerprint"):
        return "source fingerprint"
    if target_fp != target_body.get("workspace_fingerprint"):
        return "target fingerprint"
    if source_body.get("file_count") != len(source_inventory):
        return "source count"
    if target_body.get("file_count") != len(target_inventory):
        return "target count"
    return None


def _inventory_canonical(inventory: dict[str, dict[str, str]] | None) -> str:
    if inventory is None:
        return ""
    return yaml_lite.dump(inventory)


def _skipped() -> dict[str, Any]:
    return {
        "ok": True,
        "outcome": "SKIPPED",
        "resumed": False,
        "source_generation": "",
        "target_generation": "",
        "source_digest": "",
        "target_digest": "",
        "locator": "",
        "blockers": [],
    }


def _legacy_authority_digests(root: Path) -> set[str]:
    found: set[str] = set()
    folders = (
        root / TASKS_DIR,
        root / DURABLE_EVIDENCE_ROOT,
        root / TEST_RUNS,
        root / SESSIONS_DIR,
    )
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.yaml")):
            try:
                loaded = yaml_lite.load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError, TypeError):
                continue
            _collect_legacy_digests(loaded, found)
    return found


def _collect_legacy_digests(node: Any, found: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_legacy_digests(item, found)
        return
    if not isinstance(node, dict):
        return
    generation = node.get("projection_generation")
    legacy = generation in (None, "", PROJECTION_GENERATION_LEGACY)
    if legacy:
        if node.get("status") == "OPEN":
            _add_digest(node.get("observed_candidate_digest"), found)
        for key in ("candidate_digest",):
            if key in node:
                _add_digest(node.get(key), found)
    for value in node.values():
        if isinstance(value, (dict, list)):
            _collect_legacy_digests(value, found)


def _add_digest(value: Any, found: set[str]) -> None:
    if isinstance(value, str) and _HEX64.fullmatch(value):
        found.add(value)


def _cited_needs_new_record(
    root: Path,
    cited: set[str],
    source_digest: str,
    target_digest: str,
) -> bool:
    if source_digest not in cited:
        return False
    return not _valid_migration(root, source_digest, target_digest)


def _valid_migration(root: Path, source_digest: str, target_digest: str) -> bool:
    record = _read_record(_record_path(root, source_digest))
    return bool(
        record is not None
        and record.get("source_digest") == source_digest
        and record.get("target_digest") == target_digest
        and _record_proof_ok(record, root)
    )


def _git_mixed_paths(root: Path, revision: str) -> list[str]:
    if not revision:
        return []
    from scaffold_p5.scm import _run_git_bytes

    found: list[str] = []
    for path in sorted(MIXED_OWNERSHIP_PATHS):
        result = _run_git_bytes(root, "cat-file", "-e", f"{revision}:{path}")
        if result.ok:
            found.append(path)
    return found


def _git_blob(root: Path, revision: str, path: str) -> bytes | None:
    from scaffold_p5.scm import _run_git_bytes

    result = _run_git_bytes(root, "show", f"{revision}:{path}")
    if not result.ok:
        return None
    return result.stdout


def _mixed_source_paths(
    source_body: dict[str, Any],
    source_inventory: dict[str, Any] | None,
    root: Path | None = None,
) -> list[str]:
    paths: set[str] = set()
    for key in ("tracked_paths", "untracked_paths"):
        rows = source_body.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            if path in MIXED_OWNERSHIP_PATHS:
                paths.add(path)
    if isinstance(source_inventory, dict):
        for path in source_inventory:
            if str(path) in MIXED_OWNERSHIP_PATHS:
                paths.add(str(path))
    if root is not None and source_body.get("kind") == "git":
        revision = str(source_body.get("revision") or "")
        paths.update(_git_mixed_paths(root, revision))
    return sorted(paths)


def _row_digest(body: dict[str, Any], path: str) -> str | None:
    for key in ("tracked_paths", "untracked_paths"):
        rows = body.get(key) or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and str(row.get("path") or "") == path:
                digest = str(row.get("digest") or "")
                return digest if _HEX64.fullmatch(digest) else None
    return None


def _inventory_digest(inventory: dict[str, Any] | None, path: str) -> str | None:
    if not isinstance(inventory, dict) or path not in inventory:
        return None
    row = inventory.get(path)
    if not isinstance(row, dict):
        return None
    digest = str(row.get("digest") or "")
    return digest if _HEX64.fullmatch(digest) else None


def _capture_mixed_bytes(
    root: Path,
    source_body: dict[str, Any],
    source_inventory: dict[str, Any] | None,
) -> dict[str, str]:
    encoded: dict[str, str] = {}
    revision = str(source_body.get("revision") or "")
    for path in _mixed_source_paths(source_body, source_inventory, root):
        file_path = root / path
        try:
            raw = file_path.read_bytes()
        except OSError:
            blob = _git_blob(root, revision, path) if revision else None
            raw = blob if blob is not None else b""
        encoded[path] = base64.b64encode(raw).decode("ascii")
    return encoded


def _load_inventory(text: Any) -> dict[str, Any] | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        loaded = yaml_lite.load(text)
    except (ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _mixed_bytes_issue(
    encoded: Any,
    source_body: dict[str, Any],
    target_body: dict[str, Any],
    source_inventory: dict[str, Any] | None,
    target_inventory: dict[str, Any] | None = None,
    root: Path | None = None,
) -> str | None:
    if encoded is None:
        encoded = {}
    if not isinstance(encoded, dict):
        return "shape"
    required = _mixed_source_paths(source_body, source_inventory, root)
    if set(encoded) != set(required):
        return "path set"
    for path in required:
        token = encoded.get(path)
        if not isinstance(token, str):
            return f"encoding {path}"
        try:
            raw = base64.b64decode(token.encode("ascii"), validate=True)
        except (ValueError, UnicodeError):
            return f"encoding {path}"
        actual = sha256_bytes(raw)
        source_digest = _row_digest(source_body, path)
        inventory_digest = _inventory_digest(source_inventory, path)
        if source_digest is not None and actual != source_digest:
            return f"source hash {path}"
        if inventory_digest is not None and actual != inventory_digest:
            return f"inventory hash {path}"
        if source_digest is None and inventory_digest is None:
            if source_body.get("kind") != "git" or root is None:
                return f"source digest {path}"
            blob = _git_blob(root, str(source_body.get("revision") or ""), path)
            if blob is None or sha256_bytes(blob) != actual:
                return f"git blob {path}"
        projected = projected_digest_of_bytes(path, raw)
        expected = projected if projected is not None else actual
        target_digest = _row_digest(target_body, path)
        target_inventory_digest = _inventory_digest(target_inventory, path)
        if target_digest is not None and target_digest != expected:
            return f"target projection {path}"
        if target_inventory_digest is not None and target_inventory_digest != expected:
            return f"target inventory projection {path}"
        if target_digest is None and target_inventory_digest is None and projected is None:
            return f"target missing {path}"
    return None


def _record_path(root: Path, source_digest: str) -> Path:
    return migration_dir(root) / f"{source_digest}.yaml"


def _read_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = yaml_lite.load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _load_records(root: Path) -> list[dict[str, Any]]:
    folder = migration_dir(root)
    if not folder.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.yaml")):
        loaded = _read_record(path)
        if isinstance(loaded, dict):
            records.append(loaded)
    return records


def _locator(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return MIGRATION_DIR + "/" + path.name


def _completed(
    record: dict[str, Any],
    path: Path,
    root: Path,
    *,
    resumed: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "outcome": "COMPLETED",
        "resumed": resumed,
        "source_generation": record.get("source_generation"),
        "target_generation": record.get("target_generation"),
        "source_digest": record.get("source_digest"),
        "target_digest": record.get("target_digest"),
        "locator": _locator(root, path),
        "blockers": [],
    }


def _blocked(blockers: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "outcome": "BLOCKED",
        "resumed": False,
        "source_generation": PROJECTION_GENERATION_LEGACY,
        "target_generation": PROJECTION_GENERATION_CURRENT,
        "source_digest": "",
        "target_digest": "",
        "locator": "",
        "blockers": blockers,
    }

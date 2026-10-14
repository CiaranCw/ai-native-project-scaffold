"""Generic Core path classification. Core never asks which client produced a path."""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite


PRODUCT = "PRODUCT"
SCAFFOLD_AUTHORITY = "SCAFFOLD_AUTHORITY"
CLIENT_SUPPORT = "CLIENT_SUPPORT"
PATH_CLASSES = (PRODUCT, SCAFFOLD_AUTHORITY, CLIENT_SUPPORT)

PROJECT_YAML_REL = ".scaffold/project.yaml"
INSTALL_YAML_REL = ".scaffold/install/install.yaml"
CLIENT_SUPPORT_STRATEGY = "CLIENT_SUPPORT"
_MANAGED_MODES = frozenset(
    {"GENERATED", "MANAGED", "MANAGED_JSON_FRAGMENT", "MANAGED_REGION"}
)
_MANAGED_STRATEGIES = frozenset({"THIN_BRIDGE", "MANAGED_UPDATE"})

_AUTHORITY_NAMES = frozenset({".scaffold", ".git"})
_AUTHORITY_PREFIXES = (".scaffold/", ".git/")
_AUTHORITY_FILES = frozenset({"AGENTS.md", ".gitattributes"})
# Project required-test policy is governance, not ordinary Develop product.
# The string is shared with policy acceptance. It is not a generated artifact.
REQUIRED_TEST_POLICY = "docs/project/required-test-policy.yaml"

# host-key -> (project digest, install digest, declared client-support, enforcement prefixes)
_cache: dict[str, tuple[Any, Any, tuple[str, ...], tuple[str, ...]]] = {}


def normalize_rel(value: Any) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    normalized = raw.strip("/")
    if not normalized or normalized in {".", ".."}:
        return ""
    if Path(normalized).is_absolute() or (len(normalized) >= 2 and normalized[1] == ":"):
        return ""
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        return ""
    return normalized


def is_scaffold_authority_path(rel: str) -> bool:
    normalized = normalize_rel(rel)
    if not normalized:
        return False
    if normalized in _AUTHORITY_NAMES or normalized in _AUTHORITY_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in _AUTHORITY_PREFIXES)


def declared_client_support_paths(root: str | Path) -> tuple[str, ...]:
    """Project-local declared client-support paths from project.yaml clients[]."""
    declared, _prefixes = _host_index(root)
    return declared


def managed_enforcement_prefixes(root: str | Path) -> tuple[str, ...]:
    """Scaffold-managed client/enforcement prefixes recorded on this host.

    Comes from project.yaml ownership/clients[] and install.yaml managed
    records. Does not treat a whole declared client-support area as protected.
    """
    _declared, prefixes = _host_index(root)
    return prefixes


def is_protected_mutation_target(root: str | Path, rel: str) -> bool:
    """Direct ordinary mutation of Scaffold-owned governance/enforcement.

    Canonical authority paths plus specifically recorded managed client
    enforcement artifacts. Not an entire client-support area.
    """
    normalized = normalize_rel(rel)
    if not normalized:
        return False
    if normalized == REQUIRED_TEST_POLICY:
        return True
    if is_scaffold_authority_path(normalized):
        return True
    for prefix in managed_enforcement_prefixes(root):
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def mutation_consumes_protected_target(root: str | Path, rel: str) -> bool:
    """True if mutating ``rel`` would destroy or relocate a protected target.

    Exact protected paths match. An ancestor/container matches when a recorded
    protected path is a descendant of ``rel``. Unrelated siblings do not.
    """
    if is_protected_mutation_target(root, rel):
        return True
    normalized = normalize_rel(rel)
    if not normalized:
        return False
    needle = normalized + "/"
    for protected in _protected_consumption_records(root):
        if protected.startswith(needle):
            return True
    return False


def path_operand_has_glob(rel: str) -> bool:
    """True when a direct path operand uses glob/path-pattern metacharacters."""
    return any(char in str(rel or "") for char in "*?[")


def normalize_path_operand(rel: str) -> str:
    """Slash-normalize a direct path operand, including glob form."""
    return _normalize_path_operand(rel)


def path_operand_selects_protected_authority(
    root: str | Path,
    rel: str,
    *,
    consume_descendants: bool = False,
) -> bool:
    """True when a direct path operand can select or consume protected authority.

    Covers exact targets, ancestor consumption, and glob/path-pattern operands
    matched against host-recorded protected records. Does not expand the
    filesystem.
    """
    operand = _normalize_path_operand(rel)
    if not operand or operand == ".." or operand.startswith("../"):
        return False
    if path_operand_has_glob(operand):
        return _glob_operand_selects_protected(
            root, operand, consume_descendants=consume_descendants
        )
    if consume_descendants:
        return mutation_consumes_protected_target(root, operand)
    return is_protected_mutation_target(root, operand)


def is_client_support_path(root: str | Path, rel: str) -> bool:
    normalized = normalize_rel(rel)
    if not normalized or is_scaffold_authority_path(normalized):
        return False
    for declared in declared_client_support_paths(root):
        if declared.endswith("/"):
            base = declared.rstrip("/")
            if normalized == base or normalized.startswith(base + "/"):
                return True
        elif normalized == declared:
            return True
    return False


def classify_path(root: str | Path, rel: str) -> str:
    """PRODUCT | SCAFFOLD_AUTHORITY | CLIENT_SUPPORT. Authority always wins."""
    if is_scaffold_authority_path(rel):
        return SCAFFOLD_AUTHORITY
    if is_client_support_path(root, rel):
        return CLIENT_SUPPORT
    return PRODUCT


def client_support_row(path: str, *, area: bool = False) -> dict[str, Any]:
    """Adapter-facing helper for one declared client-support row."""
    normalized = normalize_rel(path)
    if not normalized:
        return {}
    return {
        "path": normalized + "/" if area else normalized,
        "strategy": CLIENT_SUPPORT_STRATEGY,
        "authoritative": False,
    }


def _protected_consumption_records(root: str | Path) -> tuple[str, ...]:
    records = set(managed_enforcement_prefixes(root))
    records.update(_AUTHORITY_NAMES)
    records.update(_AUTHORITY_FILES)
    records.add(REQUIRED_TEST_POLICY)
    return tuple(sorted(item for item in records if item))


def _normalize_path_operand(value: Any) -> str:
    raw = str(value or "").strip().strip('"').replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    parts: list[str] = []
    escaped = False
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if escaped or not parts or path_operand_has_glob(parts[-1]):
                parts.append("..")
                escaped = True
            else:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _glob_operand_selects_protected(
    root: str | Path,
    pattern: str,
    *,
    consume_descendants: bool,
) -> bool:
    records = _protected_consumption_records(root)
    for protected in records:
        if _pathname_glob_match(protected, pattern):
            return True
        if not consume_descendants:
            continue
        ancestor = protected
        while "/" in ancestor:
            ancestor = ancestor.rsplit("/", 1)[0]
            if _pathname_glob_match(ancestor, pattern):
                return True
    return False


def _pathname_glob_match(path: str, pattern: str) -> bool:
    return _match_glob_parts(path.split("/"), pattern.split("/"))


def _match_glob_parts(path_parts: list[str], pattern_parts: list[str]) -> bool:
    if not pattern_parts:
        return not path_parts
    pat = pattern_parts[0]
    if pat == "**":
        rest = pattern_parts[1:]
        if not rest:
            return True
        for index in range(len(path_parts) + 1):
            if _match_glob_parts(path_parts[index:], rest):
                return True
        return False
    if not path_parts:
        return False
    if not fnmatch.fnmatch(path_parts[0], pat):
        return False
    return _match_glob_parts(path_parts[1:], pattern_parts[1:])


def reset_cache() -> None:
    _cache.clear()


def _host_key(root: str | Path) -> str:
    host = Path(root)
    try:
        return str(host.resolve()) if host.is_absolute() else str(host)
    except OSError:
        return str(host)


def _digest_file(path: Path) -> Any:
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except OSError:
        return None


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml_lite.load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _host_index(root: str | Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    host = Path(root)
    key = _host_key(host)
    project_sig = _digest_file(host / PROJECT_YAML_REL)
    install_sig = _digest_file(host / INSTALL_YAML_REL)
    cached = _cache.get(key)
    if (
        cached is not None
        and cached[0] == project_sig
        and cached[1] == install_sig
    ):
        return cached[2], cached[3]
    project = _load_mapping(host / PROJECT_YAML_REL) if project_sig else {}
    declared = _parse_declared_from_project(project)
    managed = _parse_managed_client_paths(project, declared)
    managed += _parse_install_managed_paths(host, install_sig)
    prefixes = _enforcement_prefixes(managed, declared)
    _cache[key] = (project_sig, install_sig, declared, prefixes)
    return declared, prefixes


def _parse_declared_from_project(raw: dict[str, Any]) -> tuple[str, ...]:
    rows = raw.get("clients")
    if not isinstance(rows, list):
        return ()
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        declared = str(row.get("path") or "")
        area = declared.replace("\\", "/").rstrip().endswith("/") or bool(row.get("area"))
        normalized = normalize_rel(declared)
        if not normalized or is_scaffold_authority_path(normalized):
            continue
        out.append(normalized + "/" if area else normalized)
    return tuple(sorted(set(out)))


def _parse_managed_client_paths(
    project: dict[str, Any],
    declared: tuple[str, ...],
) -> tuple[str, ...]:
    out: list[str] = []
    rows = project.get("clients")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            declared_path = str(row.get("path") or "")
            area = declared_path.replace("\\", "/").rstrip().endswith("/") or bool(
                row.get("area")
            )
            normalized = normalize_rel(declared_path)
            if area or not normalized or is_scaffold_authority_path(normalized):
                continue
            mode = str(row.get("ownership") or "")
            strategy = str(row.get("strategy") or "")
            if mode in _MANAGED_MODES or strategy in _MANAGED_STRATEGIES:
                out.append(normalized)
    ownership = project.get("ownership")
    if isinstance(ownership, dict):
        for raw_key, mode in ownership.items():
            key = str(raw_key or "").replace("\\", "/").strip()
            if key.endswith("/"):
                continue
            normalized = normalize_rel(key)
            if not normalized or is_scaffold_authority_path(normalized):
                continue
            if str(mode) not in {"GENERATED", "MANAGED"}:
                continue
            if _covered_by_declared(normalized, declared):
                out.append(normalized)
    return tuple(sorted(set(out)))


def _parse_install_managed_paths(host: Path, install_sig: Any) -> tuple[str, ...]:
    if not install_sig:
        return ()
    raw = _load_mapping(host / INSTALL_YAML_REL)
    if not raw:
        return ()
    out: list[str] = []
    for collection in ("files", "json_fragments"):
        rows = raw.get(collection)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            normalized = normalize_rel(row.get("path"))
            if not normalized or is_scaffold_authority_path(normalized):
                continue
            ownership = str(row.get("ownership") or "MANAGED")
            if collection == "json_fragments" or ownership in _MANAGED_MODES:
                out.append(normalized)
    return tuple(sorted(set(out)))


def _covered_by_declared(rel: str, declared: tuple[str, ...]) -> bool:
    for item in declared:
        if item.endswith("/"):
            base = item.rstrip("/")
            if rel == base or rel.startswith(base + "/"):
                return True
        elif rel == item:
            return True
    return False


def _enforcement_prefixes(
    managed: tuple[str, ...],
    declared: tuple[str, ...],
) -> tuple[str, ...]:
    prefixes = set(managed)
    containers = {item.rstrip("/") for item in declared if item}
    for path in managed:
        if "/" not in path:
            continue
        parent = path.rsplit("/", 1)[0]
        # Keep shared client roots and two-level buckets mutable. Protect the
        # adapter directory of a nested managed file (three or more segments).
        if parent.count("/") < 2 or parent in containers:
            continue
        prefixes.add(parent)
    return tuple(sorted(prefixes))

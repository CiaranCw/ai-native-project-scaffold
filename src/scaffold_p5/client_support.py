"""Generic Core path classification. Core never asks which client produced a path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scaffold_p5 import yaml_lite


PRODUCT = "PRODUCT"
SCAFFOLD_AUTHORITY = "SCAFFOLD_AUTHORITY"
CLIENT_SUPPORT = "CLIENT_SUPPORT"
PATH_CLASSES = (PRODUCT, SCAFFOLD_AUTHORITY, CLIENT_SUPPORT)

PROJECT_YAML_REL = ".scaffold/project.yaml"
CLIENT_SUPPORT_STRATEGY = "CLIENT_SUPPORT"

_AUTHORITY_NAMES = frozenset({".scaffold", ".git"})
_AUTHORITY_PREFIXES = (".scaffold/", ".git/")
_AUTHORITY_FILES = frozenset({"AGENTS.md", ".gitattributes"})

_cache: dict[str, tuple[Any, tuple[str, ...]]] = {}


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
    host = Path(root)
    path = host / PROJECT_YAML_REL
    try:
        stat = path.stat()
        signature: Any = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        signature = None
    key = str(host.resolve()) if host.is_absolute() else str(host)
    cached = _cache.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    declared = _read_declared(path) if signature is not None else ()
    _cache[key] = (signature, declared)
    return declared


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


def reset_cache() -> None:
    _cache.clear()


def _read_declared(path: Path) -> tuple[str, ...]:
    try:
        raw = yaml_lite.load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return ()
    if not isinstance(raw, dict):
        return ()
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

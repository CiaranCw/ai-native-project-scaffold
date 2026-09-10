"""Shared P2 ownership resolution. Three modes; one project.yaml registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


OWNERSHIP_MODES = frozenset({"GENERATED", "MANAGED", "HUMAN_OWNED"})
BUSINESS_SOURCE_ROOTS = ("src", "lib", "app", "pkg")
P6_DURABLE_EVIDENCE_AREA = ".scaffold/ext/test/evidence/"
P6_DURABLE_EVIDENCE_PROBE = P6_DURABLE_EVIDENCE_AREA + "p6-durable-evidence.probe"


@dataclass(frozen=True)
class OwnershipResolution:
    status: str
    mode: str | None = None
    matched_key: str | None = None
    reason: str = ""


def normalize_project_path(value: Any, *, area: bool | None = None) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if raw.startswith("./"):
        raw = raw[2:]
    inferred_area = raw.endswith("/")
    normalized = raw.strip("/")
    if (
        not normalized
        or normalized in {".", ".."}
        or Path(normalized).is_absolute()
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        return ""
    use_area = inferred_area if area is None else area
    return normalized + "/" if use_area else normalized


def path_covered(path: Any, declared: Any) -> bool:
    target = normalize_project_path(path, area=False)
    raw = str(declared or "").strip().replace("\\", "/")
    prefix = normalize_project_path(raw, area=False)
    if not target or not prefix:
        return False
    return target == prefix or target.startswith(prefix + "/")


def source_area_key(value: Any) -> str:
    return normalize_project_path(value, area=True)


def source_area_ownership(
    ownership: dict[str, str],
    source_areas: list[Any],
) -> dict[str, str]:
    updated = dict(ownership)
    for value in source_areas:
        key = source_area_key(value)
        if key:
            updated.setdefault(key, "HUMAN_OWNED")
    return updated


def ownership_registry_issues(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["project.yaml ownership must be a mapping"]
    issues: list[str] = []
    normalized: dict[tuple[str, bool], str] = {}
    for key, mode in value.items():
        raw = str(key or "").strip().replace("\\", "/")
        area = raw.endswith("/")
        path = normalize_project_path(raw, area=area)
        if not isinstance(key, str) or not path:
            issues.append(f"project.yaml ownership path {key!r} is invalid")
            continue
        if mode not in OWNERSHIP_MODES:
            issues.append(f"project.yaml ownership mode for {key!r} is invalid")
            continue
        identity = (path.rstrip("/"), area)
        previous = normalized.get(identity)
        if previous is not None and previous != mode:
            issues.append(
                f"project.yaml ownership has conflicting normalized entries for {path}"
            )
        normalized[identity] = mode
    return issues


def resolve_ownership(ownership: Any, path: Any) -> OwnershipResolution:
    target = normalize_project_path(path, area=False)
    if not target:
        return OwnershipResolution(
            "CONFLICTING", reason="ownership target path is invalid"
        )
    if not isinstance(ownership, dict):
        return OwnershipResolution(
            "UNKNOWN", reason="project ownership registry is missing"
        )

    malformed = ownership_registry_issues(ownership)
    if malformed:
        return OwnershipResolution(
            "CONFLICTING", reason="; ".join(sorted(set(malformed)))
        )

    exact: list[tuple[str, str]] = []
    areas: list[tuple[int, str, str]] = []
    for raw_key, mode in ownership.items():
        raw = str(raw_key).replace("\\", "/").strip()
        is_area = raw.endswith("/")
        key = normalize_project_path(raw, area=is_area)
        if is_area and path_covered(target, key):
            areas.append((len(key.rstrip("/").split("/")), key, str(mode)))
        elif not is_area and key == target:
            exact.append((key, str(mode)))

    if exact:
        modes = {mode for _key, mode in exact}
        if len(modes) != 1:
            return OwnershipResolution(
                "CONFLICTING",
                reason=f"conflicting exact ownership entries for {target}",
            )
        key, mode = exact[0]
        return OwnershipResolution("RESOLVED", mode, key, "exact ownership")

    if not areas:
        return OwnershipResolution(
            "UNKNOWN", reason=f"missing ownership for {target}"
        )
    max_depth = max(depth for depth, _key, _mode in areas)
    closest = [(key, mode) for depth, key, mode in areas if depth == max_depth]
    modes = {mode for _key, mode in closest}
    if len(modes) != 1:
        return OwnershipResolution(
            "CONFLICTING",
            reason=f"conflicting area ownership entries for {target}",
        )
    key, mode = closest[0]
    return OwnershipResolution("RESOLVED", mode, key, "area ownership")


def ordinary_business_source(path: Any, source_areas: list[Any]) -> bool:
    target = normalize_project_path(path, area=False)
    if not target:
        return False
    if target == "AGENTS.md" or target.startswith(".scaffold/"):
        return False
    if target == "docs" or target.startswith("docs/"):
        return False
    areas = [source_area_key(value) for value in source_areas]
    return any(area and path_covered(target, area) for area in areas)

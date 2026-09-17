"""Adapter-layer integration profiles. Core never imports this module.

A profile describes one client integration: the artifacts an installation must
carry for that client. Installation completeness derives from the *declared*
profile set, never from argv. Profiles are not human-authority perimeters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scaffold_p5.first_use import FIRST_USE_RULE_REL, HOOKS_JSON_REL, HOOK_SCRIPT_REL


PROFILE_KEY = "adapter_profiles"
CURSOR_PROFILE = "cursor"

CURSOR_ADAPTERS = (
    "scaffold-understand",
    "scaffold-develop",
    "scaffold-test",
    "scaffold-submit",
)
CURSOR_ADAPTER_PATHS = tuple(
    f".cursor/skills/{name}/SKILL.md" for name in CURSOR_ADAPTERS
)


@dataclass(frozen=True)
class AdapterProfile:
    profile_id: str
    required_paths: tuple[str, ...] = ()
    client_support_areas: tuple[str, ...] = ()
    gitattributes_lines: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)


CURSOR = AdapterProfile(
    profile_id=CURSOR_PROFILE,
    required_paths=(
        *CURSOR_ADAPTER_PATHS,
        FIRST_USE_RULE_REL,
        HOOK_SCRIPT_REL,
    ),
    client_support_areas=(".cursor/",),
    gitattributes_lines=(
        ".cursor/skills/scaffold-understand/** -text",
        ".cursor/skills/scaffold-develop/** -text",
        ".cursor/skills/scaffold-test/** -text",
        ".cursor/skills/scaffold-submit/** -text",
        ".cursor/rules/scaffold-first-use.mdc -text",
        ".cursor/hooks.json -text",
    ),
    extras={"hooks_json": HOOKS_JSON_REL},
)

KNOWN_PROFILES: dict[str, AdapterProfile] = {CURSOR.profile_id: CURSOR}
DEFAULT_PROFILES: tuple[str, ...] = (CURSOR_PROFILE,)


def resolve_profiles(selected: Any) -> tuple[tuple[AdapterProfile, ...], list[str]]:
    """Resolve a requested profile id set. Unknown ids are refused, not ignored."""
    if selected is None:
        ids: tuple[str, ...] = DEFAULT_PROFILES
    elif isinstance(selected, (list, tuple)):
        ids = tuple(str(item).strip().lower() for item in selected if str(item).strip())
    else:
        return (), [f"adapter profile selection {selected!r} is not a list"]
    issues: list[str] = []
    out: list[AdapterProfile] = []
    for profile_id in dict.fromkeys(ids):
        profile = KNOWN_PROFILES.get(profile_id)
        if profile is None:
            issues.append(f"unsupported adapter profile {profile_id!r}")
            continue
        out.append(profile)
    return tuple(out), issues


def declared_profiles(manifest: Any) -> tuple[AdapterProfile, ...]:
    """Profiles declared by an installed host.

    A manifest written before adapter profiles existed but carrying the legacy
    Cursor bridge is read as a Cursor-profile installation.
    """
    bridges = {}
    if isinstance(manifest, dict) and isinstance(manifest.get("bridges"), dict):
        bridges = manifest["bridges"]
    declared = bridges.get(PROFILE_KEY)
    if isinstance(declared, list):
        resolved, _issues = resolve_profiles(declared)
        return resolved
    if bridges.get(CURSOR_PROFILE):
        return (CURSOR,)
    return ()


def profile_ids(profiles: tuple[AdapterProfile, ...]) -> list[str]:
    return [profile.profile_id for profile in profiles]


def required_paths(profiles: tuple[AdapterProfile, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for profile in profiles:
        for rel in profile.required_paths:
            if rel not in out:
                out.append(rel)
    return tuple(out)


def gitattributes_lines(profiles: tuple[AdapterProfile, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for profile in profiles:
        for line in profile.gitattributes_lines:
            if line not in out:
                out.append(line)
    return tuple(out)


def client_support_areas(profiles: tuple[AdapterProfile, ...]) -> tuple[str, ...]:
    out: list[str] = []
    for profile in profiles:
        for area in profile.client_support_areas:
            if area not in out:
                out.append(area)
    return tuple(out)

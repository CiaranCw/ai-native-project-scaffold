"""Existing AGENTS.md Layer-1 classification and bounded managed-region apply.

This is a P5 helper, not a new Skill, record, ownership mode, or client authority.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scaffold_p5.models import DiscoveryFact, PlanAction


AGENTS_ROUTER_REGION = "agents-router"
CONSUMER_INSTALL_REGION = "scaffold-consumer"
REGION_START = f"<!-- scaffold:managed:{AGENTS_ROUTER_REGION}:start -->"
REGION_END = f"<!-- scaffold:managed:{AGENTS_ROUTER_REGION}:end -->"
CONSUMER_REGION_START = (
    f"<!-- scaffold:managed:{CONSUMER_INSTALL_REGION}:start -->"
)
CONSUMER_REGION_END = f"<!-- scaffold:managed:{CONSUMER_INSTALL_REGION}:end -->"
ALLOWED_AGENTS_REGIONS = frozenset(
    {AGENTS_ROUTER_REGION, CONSUMER_INSTALL_REGION}
)
CONSUMER_AGENTS_INNER = """## Scaffold installation

This managed AGENTS region is first-contact routing for a Scaffold-enabled repository.

Scaffold is installed. Installation is not Adoption. Do not treat `.scaffold/install` as completed project understanding.

Exactly four Skills exist: Understand, Develop, Test, and Submit. Repair is a Develop mode. There is no fifth Skill and no generic Cursor Skill named scaffold.

Scaffold lifecycle gates are mandatory authorization boundaries, not advisory guidance.

If the host is NOT_ADOPTED, ordinary business work is not authorized. Do not modify project business, source, test, or documentation files. Do not implement the requested feature. Do not create an ad-hoc task outside Scaffold.

On a never-adopted host, ordinary business work starts with Understand bootstrap.

If the host is ACTIVE, ordinary HUMAN_OWNED business mutation is not authorized until Develop has a current IN_PROGRESS Task Book, a mutable Stage, and an OPEN Develop Session bound to that Task. Successful Adoption is not permission to edit project source. Do not implement the original business request by writing files directly. Required route: `python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>` to publish a bounded Task proposal through Develop intake. Intake creates no Develop Session. Continue with `python .scaffold/install/run.py develop session --task-id <task-id>` to open the execution window, then `python .scaffold/install/run.py develop seal --task-id <task-id>` or `develop abort` to close it. Do not write `.scaffold/tasks/` directly. Repair remains a Develop mode. There is no fifth Skill.

Required first-use route: `python .scaffold/install/run.py status`, then `python .scaffold/install/run.py understand bootstrap`. Preview is not apply. Continue with `--approved --plan-digest` of that exact Plan. Adoption apply is Agent lifecycle work; it is not Git Commit or Push. No project implementation may happen before Adoption completes.

If Understand compatibility reports `UNKNOWN` because `skills.lock` expected identity does not match an installed VALID package, do not edit `skills.lock` by hand and do not treat consumer UPDATE as a lock rewrite. Continue with `python .scaffold/install/run.py understand compatibility --action lock_update --new-expected <json>`, then apply that exact `--plan-digest`. `--new-expected-b64` is the same payload. That lock-update apply is Agent lifecycle work; it is not Git Commit or Push and is not `--approved` Adoption apply.

Do NOT bypass this gate because:

- Adoption appears cumbersome;
- the task appears simple;
- the task is only a feature or bug fix;
- no project-structure change appears necessary;
- direct implementation appears faster.

Launcher: `python .scaffold/install/run.py`
First-use: `python .scaffold/install/run.py understand bootstrap`

Canonical Skill packages: `.scaffold/install/packages/{understand,develop,test,submit}/`
Runtime: `.scaffold/install/runtime/`

Do not clone a second Scaffold repository and do not set PYTHONPATH to a developer checkout.
"""


def compose_consumer_agents_inner(adapter_block: str = "") -> str:
    """Core consumer AGENTS body plus optional declared-adapter guidance."""
    core = CONSUMER_AGENTS_INNER.strip()
    block = str(adapter_block or "").strip()
    if not block:
        return core
    needle = "Runtime: `.scaffold/install/runtime/`"
    idx = core.find(needle)
    if idx < 0:
        return core + "\n\n" + block
    at = idx + len(needle)
    return core[:at] + "\n\n" + block + core[at:]


_MARKER = re.compile(
    r"<!--\s*scaffold:managed:([a-z][a-z0-9-]*):(start|end)\s*-->"
)

GENERATED_AGENTS = """# Project router

This host is managed by AI-Native Project Scaffold.

- Project metadata: `.scaffold/project.yaml`
- Knowledge start: `docs/project/overview.md`
- Expected Skills: `.scaffold/skills.lock`
- Project Rule indexes: `.scaffold/project.yaml`, `.scaffold/modules.yaml`, `.scaffold/tests.yaml`

Zero-context resume: invoke Understand `refresh` with `action=resume`. Current Tasks, Sessions, Repair, Migration, Test, and Submit state are reconstructed from project-local records and supporting runtime artifacts. Chat history is not authority.

On an ACTIVE host, ordinary HUMAN_OWNED business mutation still requires Develop Task Book and OPEN Session authority. Do not treat Adoption as write permission.

Do not treat client-specific copies as authority.
"""

ROUTE_TOKENS = (
    ".scaffold/project.yaml",
    "docs/project/overview.md",
    ".scaffold/skills.lock",
)
POSITIVE_TOKENS = (
    "read ",
    "project metadata:",
    "knowledge start:",
    "expected skills:",
)
WHOLE_FILE_REJECTS = (
    "do not use scaffold",
    "ignore .scaffold",
    "do not read",
    "don't read",
    "legacy",
    "obsolete",
)
ANTI_INTEGRATION = (
    "do not use scaffold",
    "ignore .scaffold",
    "do not modify agents.md",
    "don't modify agents.md",
    "do not edit agents.md",
    "don't edit agents.md",
)

ABSENT = "absent"
GENUINE = "genuine"
SAFE_INTEGRATE = "safe_integrate"
UNSAFE = "unsafe"


def classify_agents_text(text: str | None) -> str:
    if text is None:
        return ABSENT
    spans, issues = parse_managed_regions(text)
    if issues:
        return UNSAFE
    if any(region_id not in ALLOWED_AGENTS_REGIONS for region_id in spans):
        return UNSAFE
    if _anti_integration(_human_surface(text, spans)):
        return UNSAFE
    if _bridge_ok(_router_text(text, spans)):
        return GENUINE
    return SAFE_INTEGRATE


def classify_agents_file(root: Path) -> str:
    path = Path(root) / "AGENTS.md"
    if not path.is_file():
        return ABSENT
    try:
        return classify_agents_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return UNSAFE


def agents_bridge_fact(
    text: str | None,
    *,
    missing: bool = False,
    registered_ids: list[str] | None = None,
    ownership: str | None = None,
) -> DiscoveryFact:
    if missing or text is None:
        return DiscoveryFact("agents_scaffold_bridge", None, "UNKNOWN")
    spans, issues = parse_managed_regions(text)
    if issues:
        return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
    if ownership == "MANAGED":
        registered = list(registered_ids or [])
        agreement = registry_marker_issues(spans, registered)
        if agreement:
            return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
        if _anti_integration(_human_surface(text, spans)):
            return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
        inner = _region_inner(
            text, spans.get(AGENTS_ROUTER_REGION), AGENTS_ROUTER_REGION
        )
        if inner is not None and _bridge_ok(inner):
            return DiscoveryFact("agents_scaffold_bridge", True, "VERIFIED", True)
        return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
    if any(region_id not in ALLOWED_AGENTS_REGIONS for region_id in spans):
        return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
    if _anti_integration(_human_surface(text, spans)):
        return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)
    if _bridge_ok(_router_text(text, spans)):
        return DiscoveryFact("agents_scaffold_bridge", True, "VERIFIED", True)
    return DiscoveryFact("agents_scaffold_bridge", False, "CONFLICTING", True)


def integrated_agents_text(
    original: str,
    *,
    insert_if_absent: bool = True,
    region_id: str = AGENTS_ROUTER_REGION,
) -> str | None:
    """Return human text plus the authorized managed router region, or None if unsafe."""
    if region_id != AGENTS_ROUTER_REGION:
        return None
    spans, issues = parse_managed_regions(original)
    if issues:
        return None
    authorized = region_id
    if any(existing not in ALLOWED_AGENTS_REGIONS for existing in spans):
        return None
    if _anti_integration(_human_surface(original, spans)):
        return None
    region = _region_block()
    span = spans.get(authorized)
    if span is not None:
        start, end = span
        return original[:start] + region.rstrip("\n") + original[end:]
    if not insert_if_absent:
        return None
    prefix = original
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    return prefix + region


def has_managed_router_region(text: str) -> bool:
    spans, issues = parse_managed_regions(text)
    return not issues and AGENTS_ROUTER_REGION in spans


def has_consumer_install_region(text: str) -> bool:
    spans, issues = parse_managed_regions(text)
    return not issues and CONSUMER_INSTALL_REGION in spans


def apply_consumer_install_region(
    text: str, *, inner: str | None = None
) -> str | None:
    """Insert or replace the scaffold-consumer region. Preserve all other text."""
    spans, issues = parse_managed_regions(text)
    if issues:
        return None
    if any(region_id not in ALLOWED_AGENTS_REGIONS for region_id in spans):
        return None
    if _anti_integration(_human_surface(text, spans)):
        return None
    body = CONSUMER_AGENTS_INNER.strip() if inner is None else str(inner).strip()
    block = (
        f"{CONSUMER_REGION_START}\n"
        f"{body}\n"
        f"{CONSUMER_REGION_END}"
    )
    span = spans.get(CONSUMER_INSTALL_REGION)
    if span is not None:
        start, end = span
        return text[:start] + block + text[end:]
    prefix = text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + block + "\n"


def human_forbids_agents_integration(text: str) -> bool:
    spans, issues = parse_managed_regions(text)
    if issues:
        return True
    return _anti_integration(_human_surface(text, spans))


def parse_managed_regions(text: str) -> tuple[dict[str, tuple[int, int]], list[str]]:
    starts: dict[str, list[int]] = {}
    ends: dict[str, list[tuple[int, int]]] = {}
    for match in _MARKER.finditer(text):
        region_id, kind = match.group(1), match.group(2)
        if kind == "start":
            starts.setdefault(region_id, []).append(match.start())
        else:
            ends.setdefault(region_id, []).append((match.start(), match.end()))
    issues: list[str] = []
    spans: dict[str, tuple[int, int]] = {}
    for region_id in sorted(set(starts) | set(ends)):
        start_hits = starts.get(region_id) or []
        end_hits = ends.get(region_id) or []
        if len(start_hits) != 1 or len(end_hits) != 1:
            issues.append(f"managed region {region_id} is missing, duplicate, or unpaired")
            continue
        start = start_hits[0]
        end_token, end = end_hits[0]
        if end_token <= start:
            issues.append(f"managed region {region_id} end precedes start")
            continue
        spans[region_id] = (start, end)
    return spans, issues


def registered_region_ids(project: Any, path: str) -> list[str]:
    if not isinstance(project, dict):
        return []
    index = project.get("managed_regions")
    if not isinstance(index, dict):
        return []
    raw = index.get(path)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item]


def managed_regions_from_actions(actions: list[PlanAction]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for action in actions:
        region_id = getattr(action, "managed_region", None)
        if action.ownership != "MANAGED" or not region_id:
            continue
        current = index.setdefault(action.target, [])
        if region_id not in current:
            current.append(region_id)
    return index


def registry_marker_issues(
    spans: dict[str, tuple[int, int]],
    registered_ids: list[str],
    *,
    surface: str = "AGENTS.md",
) -> list[str]:
    issues: list[str] = []
    registered = list(registered_ids)
    if not registered:
        issues.append(f"MANAGED {surface} has no registered managed region")
        return issues
    actual = set(spans)
    for region_id in registered:
        if region_id not in spans:
            issues.append(
                f"registered managed region {region_id} is absent from {surface}"
            )
    for region_id in sorted(actual):
        if region_id not in registered:
            issues.append(
                f"{surface} managed region {region_id} is not authorized by the registry"
            )
    return issues


def replace_managed_region(text: str, region_id: str, inner: str) -> str | None:
    """Replace one existing registered managed region. Do not insert or invent regions."""
    if not isinstance(region_id, str) or not region_id:
        return None
    spans, issues = parse_managed_regions(text)
    if issues or region_id not in spans:
        return None
    start, end = spans[region_id]
    start_marker = f"<!-- scaffold:managed:{region_id}:start -->"
    end_marker = f"<!-- scaffold:managed:{region_id}:end -->"
    body = inner.strip("\n")
    block = f"{start_marker}\n{body}\n{end_marker}"
    return text[:start] + block + text[end:]


def _region_block() -> str:
    return f"{REGION_START}\n{GENERATED_AGENTS.strip()}\n{REGION_END}\n"


def _router_text(text: str, spans: dict[str, tuple[int, int]] | None = None) -> str:
    if spans is None:
        spans, issues = parse_managed_regions(text)
        if issues:
            return text
    inner = _region_inner(text, spans.get(AGENTS_ROUTER_REGION))
    return inner if inner is not None else text


def _region_inner(
    text: str,
    span: tuple[int, int] | None,
    region_id: str = AGENTS_ROUTER_REGION,
) -> str | None:
    if span is None:
        return None
    start, end = span
    start_marker = f"<!-- scaffold:managed:{region_id}:start -->"
    end_marker = f"<!-- scaffold:managed:{region_id}:end -->"
    inner_start = start + len(start_marker)
    end_token_start = end - len(end_marker)
    return text[inner_start:end_token_start]


def _human_surface(text: str, spans: dict[str, tuple[int, int]]) -> str:
    if not spans:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans.values()):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _anti_integration(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ANTI_INTEGRATION)


def _bridge_ok(text: str) -> bool:
    lowered = text.lower()
    routes = all(token in lowered for token in ROUTE_TOKENS)
    positive = any(token in lowered for token in POSITIVE_TOKENS)
    rejects = any(token in lowered for token in WHOLE_FILE_REJECTS)
    return bool(routes and positive and not rejects)

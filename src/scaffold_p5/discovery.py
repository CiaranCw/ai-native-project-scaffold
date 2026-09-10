from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from scaffold_p5.agents import agents_bridge_fact, registered_region_ids
from scaffold_p5.discovery_context import (
    DIR_COMPLETE,
    DiscoverySession,
    ResolveOutcome,
    observe_directory,
    resolve_outcome,
    unresolved,
)
from scaffold_p5.host_state import existing_clients, scm_baseline
from scaffold_p5.inventory import (
    EXCLUDED_DIR_NAMES,
    InventoryBudget,
    MetadataWalk,
    UNKNOWN,
    _stream_directory_names,
    bounded_metadata_walk,
    project_relative_path,
    resolved_inside_root,
)
from scaffold_p5.io_util import list_files, read_yaml
from scaffold_p5.models import DiscoveryFact
from scaffold_p5.scm import tracked_project_paths


SKIP_DIR_NAMES = EXCLUDED_DIR_NAMES
SOURCE_HINTS = ("src", "lib", "app", "pkg")
TEST_HINTS = ("tests", "test", "spec")
TEST_DIR_NAMES = frozenset({"tests", "test", "spec", "__tests__"})
TEST_FILE_SUFFIXES = (
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".test.jsx",
    ".test.mjs",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
    "_test.py",
    "_test.go",
)
TEST_CONFIG_NAMES = (
    "vitest.config.ts",
    "vitest.config.js",
    "vitest.config.mts",
    "jest.config.ts",
    "jest.config.js",
    "jest.config.cjs",
    "pytest.ini",
    "conftest.py",
)
DOC_HINTS = ("README.md", "docs", "CONTRIBUTING.md")
ARCHITECTURE_LOOKUP = ("docs/architecture.md", "architecture.md")
README_LOOKUP = ("README.md", "README.markdown", "README.txt")


def discover(
    root: Path,
    extra_facts: list[DiscoveryFact] | None = None,
    *,
    budget: InventoryBudget | None = None,
) -> list[DiscoveryFact]:
    host = Path(root)
    limits = budget or InventoryBudget()
    session = DiscoverySession.start(host, limits)
    index = session.index
    facts: list[DiscoveryFact] = []
    facts.extend(_identity_facts(host, index, session=session))
    source = _dir_fact(host, index, "source_tree", SOURCE_HINTS, session=session)
    facts.append(source)
    source_areas = list(source.value or []) if isinstance(source.value, list) else []
    facts.append(_test_tree_fact(host, index, source_areas, budget=limits, session=session))
    docs, docs_unknown = _collect_hits(host, index, DOC_HINTS, session=session)
    if docs:
        facts.append(DiscoveryFact("documentation", docs, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("documentation", None, "UNKNOWN"))
    client_hints = existing_clients(host)
    clients, clients_unknown = _collect_hits(host, index, client_hints, session=session)
    if clients:
        facts.append(DiscoveryFact("existing_ai_clients", clients, "VERIFIED"))
    elif clients_unknown:
        facts.append(DiscoveryFact("existing_ai_clients", None, "UNKNOWN"))
    else:
        facts.append(DiscoveryFact("existing_ai_clients", [], "VERIFIED"))
    facts.append(_agents_bridge_fact(host, index, session=session))
    scm = scm_baseline(
        host,
        budget=limits,
        state=session.walk,
        on_directory=session.remember_directory,
        dir_cache=session.directories,
    )
    facts.append(DiscoveryFact("scm", scm["kind"], scm["confidence"]))
    facts.append(DiscoveryFact("workspace_baseline", scm, scm["confidence"]))
    package = _first_hit(host, index, ("package.json",), session=session)
    if package.found:
        facts.append(DiscoveryFact("declared_javascript_manifest", package.path, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("declared_javascript_manifest", None, "UNKNOWN"))
    python_manifest = _first_hit(host, index, ("pyproject.toml", "setup.py"), session=session)
    if python_manifest.found:
        facts.append(DiscoveryFact("declared_python_manifest", True, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("declared_python_manifest", None, "UNKNOWN"))
    facts.append(_declared_build(host, index, session=session))
    facts.append(_declared_commands_fact(host, index, session=session))
    facts.append(_architecture_fact(host, index, session=session))
    facts.append(
        DiscoveryFact("secrets_in_shared_knowledge", None, "UNKNOWN")
    )
    facts.append(_modules_fact(host, index, source_areas, budget=limits, session=session))
    if extra_facts:
        facts.extend(extra_facts)
    return facts


def path_identity_index(
    root: Path,
    *,
    budget: InventoryBudget | None = None,
    session: DiscoverySession | None = None,
) -> dict[str, str]:
    """Lowercased lookup key → actual repository-relative spelling."""
    if session is not None:
        return session.index
    index: dict[str, str] = {}
    for rel in list_files(root, budget=budget):
        index[_norm_key(rel)] = rel.replace("\\", "/")
    for rel in tracked_project_paths(root):
        index[_norm_key(rel)] = rel.replace("\\", "/")
    return index


def resolve_existing(
    root: Path,
    candidate: str,
    index: dict[str, str] | None = None,
    *,
    session: DiscoverySession | None = None,
    budget: InventoryBudget | None = None,
) -> str | None:
    """Locate candidate case-insensitively; emit actual in-root spelling.

    Both the path_identity_index fast path and the case-insensitive walk
    refuse filesystem indirection that escapes project authority. Callers
    must not read a path this function does not return. None means not
    found as a usable path; it is not a proof of absence when observation
    was truncated. Use resolve_outcome when UNKNOWN vs ABSENT matters.
    """
    outcome = resolve_outcome(
        Path(root), candidate, index, session=session, budget=budget
    )
    return outcome.path if outcome.found else None


def _authorized_rel(root: Path, rel: str) -> str | None:
    safe, _reason = project_relative_path(root, rel)
    return safe


def _collect_hits(
    root: Path,
    index: dict[str, str],
    hints: Iterable[str],
    *,
    session: DiscoverySession | None = None,
) -> tuple[list[str], bool]:
    found: list[str] = []
    unknown = False
    for hint in hints:
        outcome = resolve_outcome(root, hint, index, session=session)
        if outcome.found and outcome.path:
            _add_unique(found, outcome.path)
        elif unresolved(outcome):
            unknown = True
    return found, unknown


def _first_hit(
    root: Path,
    index: dict[str, str],
    hints: Iterable[str],
    *,
    session: DiscoverySession | None = None,
) -> ResolveOutcome:
    unknown: ResolveOutcome | None = None
    for hint in hints:
        outcome = resolve_outcome(root, hint, index, session=session)
        if outcome.found:
            return outcome
        if unresolved(outcome) and unknown is None:
            unknown = outcome
    return unknown or ResolveOutcome(status="ABSENT")


def _identity_facts(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> list[DiscoveryFact]:
    basename = root.name
    facts = [DiscoveryFact("workspace_basename", basename, "INFERRED")]
    sources: dict[str, str] = {}
    adopted = _adopted_identity(root, index, session=session)
    if adopted:
        facts.append(DiscoveryFact("declared_adopted_identity", adopted, "VERIFIED"))
        if adopted != basename:
            sources["adopted"] = adopted
    package_name = _package_identity(root, index, session=session)
    if package_name:
        facts.append(
            DiscoveryFact("declared_package_identity", package_name, "VERIFIED")
        )
        sources["package"] = package_name
    title = _readme_title(root, index, session=session)
    if title:
        facts.append(DiscoveryFact("declared_product_title", title, "INFERRED"))
        sources["title"] = title
    distinct = list(dict.fromkeys(sources.values()))
    if not distinct:
        facts.append(DiscoveryFact("project_name", basename, "INFERRED"))
    elif len(distinct) == 1:
        value = distinct[0]
        confidence = (
            "VERIFIED" if any(key in sources for key in ("adopted", "package")) else "INFERRED"
        )
        facts.append(DiscoveryFact("project_name", value, confidence))
    else:
        facts.append(DiscoveryFact("project_name", dict(sources), "CONFLICTING"))
    return facts


def _adopted_identity(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> str | None:
    rel = resolve_existing(root, ".scaffold/project.yaml", index, session=session)
    if not rel:
        return None
    try:
        data = read_yaml(root / rel)
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    name = data.get("name") if isinstance(data, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _package_identity(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> str | None:
    rel = resolve_existing(root, "package.json", index, session=session)
    data = _read_json(root / rel) if rel else None
    name = data.get("name") if isinstance(data, dict) else None
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _readme_title(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> str | None:
    for hint in README_LOOKUP:
        rel = resolve_existing(root, hint, index, session=session)
        if not rel:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                return title or None
            return None
    return None


def _dir_fact(
    root: Path,
    index: dict[str, str],
    name: str,
    hints: tuple[str, ...],
    unknown_if_missing: bool = False,
    *,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    found, unknown = _collect_hits(root, index, hints, session=session)
    found = [item for item in found if (root / item).is_dir()]
    if found:
        return DiscoveryFact(name, found, "VERIFIED")
    if unknown or unknown_if_missing:
        return DiscoveryFact(name, None, "UNKNOWN")
    return DiscoveryFact(name, [], "INFERRED")


def _test_tree_fact(
    root: Path,
    index: dict[str, str],
    source_areas: list[str],
    *,
    budget: InventoryBudget | None = None,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    locations: list[str] = []
    truncated = False
    unknown = False
    limits = budget or InventoryBudget()
    walk_state = session.walk if session is not None else None
    for hint in TEST_HINTS:
        outcome = resolve_outcome(root, hint, index, session=session)
        if outcome.found and outcome.path and (root / outcome.path).is_dir():
            _add_unique(locations, outcome.path)
        elif unresolved(outcome):
            unknown = True
    for _key, actual in index.items():
        path = actual.replace("\\", "/")
        if _ignored_rel(path):
            continue
        authorized = _authorized_rel(root, path)
        if authorized is None:
            unknown = True
            continue
        if not (root / authorized).exists():
            continue
        path = authorized
        name = Path(path).name
        if name.lower() in TEST_DIR_NAMES and (root / path).is_dir():
            _add_unique(locations, path)
            continue
        if _is_test_file(path):
            parent = str(Path(path).parent).replace("\\", "/")
            if parent in {".", ""}:
                _add_unique(locations, path)
            elif Path(path).parent.name.lower() in TEST_DIR_NAMES:
                _add_unique(locations, parent)
            else:
                _add_unique(locations, path)
        if name.lower() in {item.lower() for item in TEST_CONFIG_NAMES}:
            _add_unique(locations, path)
    for area in source_areas:
        area_rel = _authorized_rel(root, area)
        if area_rel is None:
            unknown = True
            continue
        area_path = root / area_rel
        if not area_path.is_dir():
            continue
        walked = bounded_metadata_walk(
            root,
            start=area_rel,
            budget=limits,
            skip_dir_names=SKIP_DIR_NAMES,
            state=walk_state,
            on_directory=session.remember_directory if session is not None else None,
            dir_cache=session.directories if session is not None else None,
        )
        walk_state = walked
        if walked.truncated:
            truncated = True
        if walked.unknown:
            unknown = True
        for directory in walked.directories:
            if Path(directory).name.lower() in TEST_DIR_NAMES:
                _add_unique(locations, directory)
        if walked.truncated:
            break
    for hint in ("docs/testing.md", "TESTING.md"):
        outcome = resolve_outcome(root, hint, index, session=session)
        if outcome.found and outcome.path:
            _add_unique(locations, outcome.path)
        elif unresolved(outcome):
            unknown = True
    if truncated or unknown:
        confidence = UNKNOWN
    elif locations:
        confidence = "VERIFIED"
    else:
        return DiscoveryFact("test_tree", None, "UNKNOWN")
    return DiscoveryFact("test_tree", locations or None, confidence)


def _is_test_file(rel: str) -> bool:
    name = Path(rel).name.lower()
    if any(name.endswith(suffix) for suffix in TEST_FILE_SUFFIXES):
        return True
    return name.startswith("test_") and name.endswith(".py")


def _declared_build(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    declared, unknown = _collect_hits(
        root, index, ("Makefile", "package.json"), session=session
    )
    if declared:
        return DiscoveryFact("declared_build_surface", declared, "INFERRED")
    if unknown:
        return DiscoveryFact("declared_build_surface", None, "UNKNOWN")
    return DiscoveryFact("declared_build_surface", None, "UNKNOWN")


def _declared_commands_fact(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    rel = resolve_existing(root, "package.json", index, session=session)
    data = _read_json(root / rel) if rel else None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict) or not scripts:
        return DiscoveryFact("declared_commands", [], "UNKNOWN")
    commands = []
    for name, body in scripts.items():
        if not isinstance(name, str) or not name.strip():
            continue
        script_id = name.strip()
        invocation = "npm test" if script_id == "test" else f"npm run {script_id}"
        kind = "test" if script_id == "test" or script_id.startswith("test") else "workflow"
        commands.append(
            {
                "id": f"package-json-{_command_slug(script_id)}",
                "invocation": invocation,
                "source": f"{rel}#scripts.{script_id}",
                "availability": "declared",
                "execution": "not_validated",
                "kind": kind,
                "confidence": "INFERRED",
            }
        )
    if not commands:
        return DiscoveryFact("declared_commands", [], "UNKNOWN")
    return DiscoveryFact("declared_commands", commands, "INFERRED")


def _architecture_fact(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    present: list[str] = []
    unknown = False
    for rel in index.values():
        path = rel.replace("\\", "/")
        lower = path.lower()
        if _ignored_rel(path) or lower == "docs/project/architecture.md":
            continue
        authorized = _authorized_rel(root, path)
        if authorized is None:
            continue
        path = authorized
        if Path(path).name.lower() != "architecture.md":
            continue
        parent = str(Path(path).parent).replace("\\", "/").lower()
        if path.lower() == "architecture.md" or parent == "docs" or parent.startswith("docs/"):
            _add_unique(present, path)
    for hint in ARCHITECTURE_LOOKUP:
        outcome = resolve_outcome(root, hint, index, session=session)
        if (
            outcome.found
            and outcome.path
            and outcome.path.lower() != "docs/project/architecture.md"
            and outcome.path not in present
        ):
            present.append(outcome.path)
        elif unresolved(outcome):
            unknown = True
    canonical = resolve_outcome(
        root, "docs/project/architecture.md", index, session=session
    )
    if unresolved(canonical):
        unknown = True
    if not present and canonical.found and canonical.path:
        try:
            canonical_text = (root / canonical.path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return DiscoveryFact("architecture", None, "UNKNOWN")
        pointer = re.search(
            r"Canonical architecture authority:\s*`([^`]+)`",
            canonical_text,
        )
        if pointer:
            target = pointer.group(1).replace("\\", "/")
            actual = resolve_outcome(root, target, index, session=session)
            if unresolved(actual):
                return DiscoveryFact("architecture", None, "UNKNOWN")
            if not actual.found:
                return DiscoveryFact("architecture", target, "CONFLICTING")
            return DiscoveryFact("architecture", actual.path, "VERIFIED")
        present = [canonical.path]
    if not present:
        return DiscoveryFact("architecture", None, "UNKNOWN")
    if unknown and not present:
        return DiscoveryFact("architecture", None, "UNKNOWN")
    if len(present) > 1:
        return DiscoveryFact("architecture", present, "CONFLICTING")
    return DiscoveryFact("architecture", present[0], "VERIFIED")


def _modules_fact(
    root: Path,
    index: dict[str, str],
    source_areas: list[str],
    *,
    budget: InventoryBudget | None = None,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    if not source_areas:
        return DiscoveryFact("modules", [], "UNKNOWN")
    limits = budget or InventoryBudget()
    state = session.walk if session is not None else MetadataWalk()
    modules: list[str] = []
    for area in source_areas:
        area_rel = _authorized_rel(root, area)
        if area_rel is None:
            continue
        area_path = root / area_rel
        if not area_path.is_dir():
            continue
        if session is not None:
            observed = observe_directory(session, area_path)
            if observed.status != DIR_COMPLETE:
                return DiscoveryFact("modules", None, "UNKNOWN")
            collected = [
                name
                for names in observed.by_lower.values()
                for name in names
            ]
            collected.sort()
        else:
            collected, overflow, error = _stream_directory_names(
                area_path,
                result=state,
                max_entries=limits.max_entries,
            )
            if error:
                continue
            if overflow:
                return DiscoveryFact("modules", None, "UNKNOWN")
        children = [
            name
            for name in collected
            if not name.startswith(".")
            and name.lower() not in SKIP_DIR_NAMES
            and (area_path / name).is_dir()
        ]
        candidates = [f"{area_rel}/{name}" for name in children]
        supported = [
            candidate
            for candidate in candidates
            if _module_corroborated(root, index, candidate, session=session)
        ]
        if len(supported) >= 2:
            for item in supported:
                _add_unique(modules, item)
        else:
            _add_unique(modules, area_rel)
    if not modules:
        return DiscoveryFact("modules", [], "UNKNOWN")
    return DiscoveryFact("modules", modules, "VERIFIED")


def _module_corroborated(
    root: Path,
    index: dict[str, str],
    rel: str,
    *,
    session: DiscoverySession | None = None,
) -> bool:
    needle = rel.replace("\\", "/").lower()
    for path in index.values():
        authorized = _authorized_rel(root, path)
        if authorized is None:
            continue
        lower = authorized.lower()
        if lower.startswith(".scaffold/") or _ignored_rel(authorized):
            continue
        if not lower.endswith((".md", ".yaml", ".yml")):
            continue
        try:
            text = (root / authorized).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if needle in text.replace("\\", "/").lower():
            return True
    package = resolve_existing(root, "package.json", index, session=session)
    data = _read_json(root / package) if package else None
    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    names: list[str] = []
    if isinstance(workspaces, list):
        names = [str(item) for item in workspaces]
    elif isinstance(workspaces, dict) and isinstance(workspaces.get("packages"), list):
        names = [str(item) for item in workspaces["packages"]]
    return any(
        needle == str(item).replace("\\", "/").strip("/").lower() for item in names
    )


def _agents_bridge_fact(
    root: Path,
    index: dict[str, str],
    *,
    session: DiscoverySession | None = None,
) -> DiscoveryFact:
    outcome = resolve_outcome(root, "AGENTS.md", index, session=session)
    if unresolved(outcome):
        return DiscoveryFact("agents_scaffold_bridge", None, "UNKNOWN")
    if not outcome.found:
        return agents_bridge_fact(None, missing=True)
    rel = outcome.path
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return DiscoveryFact("agents_scaffold_bridge", None, "UNKNOWN", True)
    project = None
    project_path = root / ".scaffold" / "project.yaml"
    if project_path.is_file():
        try:
            loaded = read_yaml(project_path)
        except (OSError, ValueError, TypeError, UnicodeError):
            loaded = None
        if isinstance(loaded, dict):
            project = loaded
    ownership = None
    registered = None
    if project is not None:
        ownership_map = project.get("ownership")
        if isinstance(ownership_map, dict):
            ownership = ownership_map.get("AGENTS.md")
        registered = registered_region_ids(project, "AGENTS.md")
    return agents_bridge_fact(
        text,
        registered_ids=registered,
        ownership=ownership,
    )


def observed_testing_surface(facts: list[DiscoveryFact]) -> bool:
    tests = next((fact for fact in facts if fact.name == "test_tree"), None)
    if tests and tests.confidence == "VERIFIED" and tests.value:
        return True
    commands = next((fact for fact in facts if fact.name == "declared_commands"), None)
    rows = commands.value if commands and isinstance(commands.value, list) else []
    return any(isinstance(row, dict) and row.get("kind") == "test" for row in rows)


def module_paths(facts: list[DiscoveryFact]) -> list[str]:
    modules = next((fact for fact in facts if fact.name == "modules"), None)
    if modules and isinstance(modules.value, list) and modules.value:
        out = [str(item) for item in modules.value if str(item)]
        if out:
            return out
    source = next((fact for fact in facts if fact.name == "source_tree"), None)
    return list(source.value or []) if source and isinstance(source.value, list) else []


def project_display_name(facts: list[dict[str, Any]]) -> str:
    fact = next((row for row in facts if row.get("name") == "project_name"), None)
    if not fact:
        return ""
    if fact.get("confidence") in {"VERIFIED", "INFERRED"} and isinstance(
        fact.get("value"), str
    ):
        return str(fact["value"])
    return ""


def critical_unresolved(facts: list[DiscoveryFact]) -> list[DiscoveryFact]:
    return [f for f in facts if f.critical and f.confidence in {"UNKNOWN", "CONFLICTING"}]


def facts_as_dicts(facts: list[DiscoveryFact]) -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "value": f.value,
            "confidence": f.confidence,
            "critical": f.critical,
        }
        for f in facts
    ]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _command_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "command"


def _add_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _norm_key(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/").lower()


def _ignored_rel(rel: str) -> bool:
    return any(
        part.lower() in SKIP_DIR_NAMES
        for part in str(rel or "").replace("\\", "/").split("/")
    )

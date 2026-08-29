from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import existing_clients, scm_baseline
from scaffold_p5.models import DiscoveryFact


SOURCE_HINTS = ("src", "lib", "app", "pkg")
TEST_HINTS = ("tests", "test", "spec")
DOC_HINTS = ("README.md", "docs", "CONTRIBUTING.md")


def discover(root: Path, extra_facts: list[DiscoveryFact] | None = None) -> list[DiscoveryFact]:
    facts: list[DiscoveryFact] = []
    name = root.name
    facts.append(DiscoveryFact("project_name", name, "INFERRED"))
    facts.append(_dir_fact(root, "source_tree", SOURCE_HINTS))
    facts.append(_dir_fact(root, "test_tree", TEST_HINTS, unknown_if_missing=True))
    docs = [p for p in DOC_HINTS if (root / p).exists()]
    if docs:
        facts.append(DiscoveryFact("documentation", docs, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("documentation", None, "UNKNOWN"))
    clients = existing_clients(root)
    if clients:
        facts.append(DiscoveryFact("existing_ai_clients", clients, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("existing_ai_clients", [], "VERIFIED"))
    facts.append(_agents_bridge_fact(root))
    scm = scm_baseline(root)
    facts.append(DiscoveryFact("scm", scm["kind"], scm["confidence"]))
    facts.append(
        DiscoveryFact(
            "workspace_baseline",
            scm,
            scm["confidence"],
        )
    )
    if (root / "package.json").exists():
        facts.append(DiscoveryFact("declared_javascript_manifest", "package.json", "VERIFIED"))
    else:
        facts.append(DiscoveryFact("declared_javascript_manifest", None, "UNKNOWN"))
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        facts.append(DiscoveryFact("declared_python_manifest", True, "VERIFIED"))
    else:
        facts.append(DiscoveryFact("declared_python_manifest", None, "UNKNOWN"))
    build = _declared_build(root)
    facts.append(build)
    facts.append(_architecture_fact(root))
    facts.append(DiscoveryFact("secrets_in_shared_knowledge", False, "VERIFIED", critical=True))
    if extra_facts:
        facts.extend(extra_facts)
    return facts


def _dir_fact(root: Path, name: str, hints: tuple[str, ...], unknown_if_missing: bool = False) -> DiscoveryFact:
    found = [h for h in hints if (root / h).exists() and (root / h).is_dir()]
    if found:
        return DiscoveryFact(name, found, "VERIFIED")
    if unknown_if_missing:
        return DiscoveryFact(name, None, "UNKNOWN")
    return DiscoveryFact(name, [], "INFERRED")


def _declared_build(root: Path) -> DiscoveryFact:
    declared: list[str] = []
    if (root / "Makefile").exists():
        declared.append("Makefile")
    if (root / "package.json").exists():
        declared.append("package.json")
    if declared:
        return DiscoveryFact("declared_build_surface", declared, "INFERRED")
    return DiscoveryFact("declared_build_surface", None, "UNKNOWN")


def _architecture_fact(root: Path) -> DiscoveryFact:
    external = [
        root / "docs" / "architecture.md",
        root / "ARCHITECTURE.md",
    ]
    present = [str(p.relative_to(root)).replace("\\", "/") for p in external if p.exists()]
    canonical = root / "docs" / "project" / "architecture.md"
    if not present and canonical.exists():
        try:
            canonical_text = canonical.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return DiscoveryFact("architecture", None, "UNKNOWN")
        pointer = re.search(
            r"Canonical architecture authority:\s*`([^`]+)`",
            canonical_text,
        )
        if pointer and not (root / pointer.group(1)).exists():
            return DiscoveryFact(
                "architecture",
                pointer.group(1),
                "CONFLICTING",
            )
        present = ["docs/project/architecture.md"]
    if not present:
        return DiscoveryFact("architecture", None, "UNKNOWN")
    if len(present) > 1:
        return DiscoveryFact("architecture", present, "CONFLICTING")
    return DiscoveryFact("architecture", present[0], "VERIFIED")


def _agents_bridge_fact(root: Path) -> DiscoveryFact:
    path = root / "AGENTS.md"
    if not path.exists():
        return DiscoveryFact("agents_scaffold_bridge", None, "UNKNOWN")
    try:
        text = path.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeError):
        return DiscoveryFact("agents_scaffold_bridge", None, "UNKNOWN", True)
    routes = all(
        token in text
        for token in (
            ".scaffold/project.yaml",
            "docs/project/overview.md",
            ".scaffold/skills.lock",
        )
    )
    positive = (
        "read " in text
        or "project metadata:" in text
        or "knowledge start:" in text
        or "expected skills:" in text
    )
    rejects = any(
        phrase in text
        for phrase in (
            "do not use scaffold",
            "ignore .scaffold",
            "do not read",
            "don't read",
            "legacy",
            "obsolete",
        )
    )
    if routes and positive and not rejects:
        return DiscoveryFact("agents_scaffold_bridge", True, "VERIFIED", True)
    return DiscoveryFact(
        "agents_scaffold_bridge",
        False,
        "CONFLICTING",
        True,
    )


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

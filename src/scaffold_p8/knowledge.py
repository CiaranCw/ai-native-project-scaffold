"""S4 Knowledge Consistency. Uses published P5 host facts. Does not Refresh itself."""

from __future__ import annotations

from typing import Any


def evaluate_knowledge(
    *,
    project: dict[str, Any] | None,
    maintenance: list[str],
) -> dict[str, Any]:
    needs_refresh = "NEEDS_REFRESH" in maintenance
    needs_migration = "NEEDS_MIGRATION" in maintenance
    stale = needs_refresh
    route = ""
    if needs_migration:
        route = "understand.compatibility"
    elif needs_refresh:
        route = "understand.refresh"
    return {
        "stale": stale,
        "needs_refresh": needs_refresh,
        "needs_migration": needs_migration,
        "route": route,
        "knowledge_consistent": not stale and not needs_migration,
        "project_name": (project or {}).get("name"),
    }

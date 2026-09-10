from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from scaffold_p5.distribution import load_fixture_distribution
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import read_yaml
from scaffold_p5.migration import apply_fresh_migration_execution
from scaffold_p5.packages import load_package


FIXTURE_DIST = REPO / "tests" / "fixtures" / "distribution"
REPO_UNDERSTAND = REPO / "skills" / "understand"
RELEASED_UNDERSTAND = FIXTURE_DIST / "packages" / "understand-2.0.0"


def distribution(actual_understand_version: str = "2.0.0"):
    return load_fixture_distribution(
        FIXTURE_DIST,
        selected_release_id="rel-r1",
        actual_understand_version=actual_understand_version,
        repo_understand=REPO_UNDERSTAND,
    )


def engine(host: Path, actual_understand_version: str = "2.0.0") -> UnderstandEngine:
    return UnderstandEngine(host, distribution(actual_understand_version))


class FreshMigrationApply:
    """Wraps canonical P5 apply_fresh_migration_execution for tests."""

    def __init__(self, payload: dict):
        self.outcome = payload.get("outcome")
        self.blockers = list(payload.get("blockers") or [])
        self.evidence = list(payload.get("evidence") or [])
        self.mutations = payload.get("mutations") or "none"
        self.compatibility = payload.get("compatibility")
        self.extras = dict(payload.get("extras") or {})
        self.completed = bool(payload.get("completed"))
        self.applied = bool(payload.get("applied"))


def apply_fresh_migration(
    host: Path,
    plan: dict,
    actual_understand_version: str = "2.1.0",
    **opts,
) -> FreshMigrationApply:
    """Canonical P5 helper fixture. Not Understand Skill authorization."""
    payload = apply_fresh_migration_execution(
        host,
        plan,
        distribution=opts.pop("distribution", None)
        or distribution(actual_understand_version),
        **opts,
    )
    return FreshMigrationApply(payload)


def live_understand_distribution():
    """Actual package is the live Understand candidate, not the released 2.0.0 fixture."""
    return load_fixture_distribution(
        FIXTURE_DIST,
        selected_release_id="rel-r1",
        actual_understand_dir=REPO_UNDERSTAND,
        repo_understand=REPO_UNDERSTAND,
    )


def live_understand_engine(host: Path) -> UnderstandEngine:
    return UnderstandEngine(host, live_understand_distribution())


def write(host: Path, rel: str, text: str, newline: str = "\n") -> None:
    path = host / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)


def adopt(host: Path, **opts):
    eng = engine(host)
    preview = {k: opts[k] for k in ("extra_facts", "derived_copy") if k in opts}
    planned = eng.run("bootstrap", **preview)
    digest = planned.extras["plan"]["digest"]
    opts.setdefault("approval", {"approved": True, "plan_digest": digest})
    return eng.run("bootstrap", **opts)


def files_under(host: Path) -> set[str]:
    out = set()
    for path in host.rglob("*"):
        if path.is_file():
            out.add(str(path.relative_to(host)).replace("\\", "/"))
    return out

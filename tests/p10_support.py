from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p6.candidate import observe_candidate
from p7_support import TASK_A, develop_engine
from support import REPO, distribution, live_understand_engine, write


def install_abc_modules(host: Path, *, register_knowledge: bool = True) -> None:
    write(host, "src/mod_a/core.py", "VALUE = 'A'\n")
    write(host, "src/mod_b/core.py", "VALUE = 'B'\n")
    write(host, "src/mod_c/core.py", "VALUE = 'C'\n")
    modules = [
        {
            "id": "mod_a",
            "path": "src/mod_a",
            "knowledge_entry": "docs/project/modules/src/mod_a.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
        {
            "id": "mod_b",
            "path": "src/mod_b",
            "knowledge_entry": "docs/project/modules/src/mod_b.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
        {
            "id": "mod_c",
            "path": "src/mod_c",
            "knowledge_entry": "docs/project/modules/src/mod_c.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
    ]
    write_yaml_atomic(
        host / ".scaffold/modules.yaml",
        {"schema_version": "1", "modules": modules},
    )
    if register_knowledge:
        register_module_knowledge_generated(host, modules)


def register_module_knowledge_generated(host: Path, modules: list[dict] | None = None) -> None:
    path = host / ".scaffold/project.yaml"
    if not path.is_file():
        return
    project = read_yaml(path)
    if not isinstance(project, dict):
        return
    if modules is None:
        index = read_yaml(host / ".scaffold/modules.yaml")
        modules = list((index or {}).get("modules") or []) if isinstance(index, dict) else []
    ownership = dict(project.get("ownership") or {})
    for row in modules:
        if not isinstance(row, dict):
            continue
        entry = str(row.get("knowledge_entry") or "").replace("\\", "/")
        if entry:
            ownership[entry] = "GENERATED"
    project["ownership"] = ownership
    write_yaml_atomic(path, project)


def persist_understanding(host: Path, *, incremental: bool = False, **opts):
    return live_understand_engine(host).run(
        "refresh",
        action="understand",
        incremental=incremental,
        **opts,
    )


def persist_currentness_without_completion(host: Path, *, incremental: bool = False, **opts):
    from scaffold_p5.understanding import persist_project_understanding

    return persist_project_understanding(
        host,
        mode="incremental" if incremental else "full",
        incremental=incremental,
        **opts,
    )


def resume(host: Path, **opts):
    return live_understand_engine(host).run("refresh", action="resume", **opts)


def snapshot_dirs(host: Path) -> list[str]:
    root = host / ".scaffold/runtime/understand-currentness"
    if not root.is_dir():
        return []
    return sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("uc-")
    )


def subprocess_resume(host: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(REPO / "src"), str(REPO / "tests")])
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from support import live_understand_engine\n"
        "host = Path(sys.argv[1])\n"
        "result = live_understand_engine(host).run('refresh', action='resume')\n"
        "understanding = result.extras.get('understanding') or {}\n"
        "work = result.extras.get('work') or {}\n"
        "print(json.dumps({\n"
        "  'next_route': result.next_route,\n"
        "  'currentness': understanding.get('currentness'),\n"
        "  'physical_digest': understanding.get('physical_digest'),\n"
        "  'locator': understanding.get('locator'),\n"
        "  'affected_module_ids': understanding.get('affected_module_ids'),\n"
        "  'reusable_module_ids': understanding.get('reusable_module_ids'),\n"
        "  'refreshed_module_ids': understanding.get('refreshed_module_ids'),\n"
        "  'reused_module_ids': understanding.get('reused_module_ids'),\n"
        "  'completion_locators': understanding.get('completion_locators') or [],\n"
        "  'task_ids': [row.get('record_id') for row in (work.get('tasks') or [])],\n"
        "  'ready_task_ids': work.get('ready_task_ids') or [],\n"
        "  'durably_finalized_task_ids': work.get('durably_finalized_task_ids') or [],\n"
        "  'continuable_ready_task_ids': work.get('continuable_ready_task_ids') or [],\n"
        "  'task_blockers': work.get('task_blockers') or [],\n"
        "  'session_blockers': work.get('session_blockers') or [],\n"
        "  'ambiguous_task_ids': result.extras.get('ambiguous_task_ids') or [],\n"
        "}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script, str(host)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            "subprocess resume failed:\n"
            + proc.stdout
            + "\n"
            + proc.stderr
        )
    line = [row for row in proc.stdout.splitlines() if row.strip()][-1]
    return json.loads(line)


def install_dive_shape(host: Path) -> None:
    write(host, "package.json", '{"name":"p10-prepilot","version":"0.0.1"}\n')
    write(host, "docs/README.md", "# Pre-pilot app\n")
    write(host, "tests/test_loop.py", "def test_ok():\n    assert True\n")
    write(host, "src/game/loop.py", "def tick():\n    return 1\n")
    write(host, "src/ui/hud.py", "def draw():\n    return 'hud'\n")
    write(host, "src/net/client.py", "def send():\n    return True\n")
    modules = [
        {
            "id": "game",
            "path": "src/game",
            "knowledge_entry": "docs/project/modules/src/game.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
        {
            "id": "ui",
            "path": "src/ui",
            "knowledge_entry": "docs/project/modules/src/ui.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
        {
            "id": "net",
            "path": "src/net",
            "knowledge_entry": "docs/project/modules/src/net.md",
            "kind": "source",
            "confidence": "VERIFIED",
        },
    ]
    write_yaml_atomic(
        host / ".scaffold/modules.yaml",
        {"schema_version": "1", "modules": modules},
    )
    register_module_knowledge_generated(host, modules)


def current_task(host: Path, task_id: str = TASK_A) -> dict:
    return read_yaml(host / ".scaffold/tasks" / f"{task_id}.yaml")


def bound_migration_approval(
    host: Path,
    plan: dict,
    task_id: str = TASK_A,
) -> dict:
    task = current_task(host, task_id)
    return {
        "approved": True,
        "plan_id": plan["plan_id"],
        "plan_digest": plan["digest"],
        "task_id": task["record_id"],
        "task_revision": task["record_revision"],
        "candidate_digest": observe_candidate(host).digest,
    }


def preview_migration(host: Path, task_id: str = TASK_A, dist=None):
    return develop_engine(host).run(
        "normal_task",
        task_id=task_id,
        execute_approved_migration=True,
        distribution=dist or distribution("2.1.0"),
    )

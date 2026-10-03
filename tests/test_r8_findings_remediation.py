"""R8 Real Consumer Findings Remediation. Focused regression tests.

Covers the four approved R8 findings:
- FND-A: S3 structural review must classify verified Scaffold install
  changes (gitattributes/AGENTS.md managed regions, hooks fragment,
  whole-file install-managed paths) separately from UNKNOWN ownership,
  sharing the same authoritative verification chain as P2/P6. Tampering,
  manifest loss, and diverged human bytes fail closed.
- FND-B: a READY Task whose scope escaped (undeclared paths or missing
  scoped source) gets a deterministic submit_to_develop repair handoff
  when the mapping is unambiguous (single-Stage Task); ambiguous multi
  Stage Tasks still fail closed to human.
- FND-C: dependency/cache trees are excluded from the Session open
  inventory by one canonical exclusion set; product files stay
  inventoried; pre-remediation inventories are canonicalized.
- FND-D: TEST_COMPLETE stays false whenever the required set is not
  authoritative; the S5 stop now carries authority guidance naming the
  real owner (Understand Refresh / GENERATED tests.yaml).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from p6_support import (
    CORE_OWNERSHIP,
    git,
    init_git,
    write_project,
)
from p7_support import (
    TASK_A,
    develop_engine,
    repair_handoff,
    submit_repair_handoff,
    satisfied_decision,
    write_task,
)
from p8_support import (
    bind_ready_completion_authority,
    run_submit,
    submit_engine,
    write_submit_host,
)
from support import REPO, write
from scaffold_p5.io_util import read_yaml, write_yaml_atomic
from scaffold_p5.scm import observe_scm
from scaffold_p6.candidate import observe_candidate
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.session import (
    OPEN_INVENTORY_NAME,
    execution_workspace_digests,
    load_open_inventory,
)
from scaffold_p8.completeness import evaluate_completeness
from scaffold_p8.structural import review_structure


REPO_TEST = REPO / "skills" / "test"


def _write_managed_gitattributes(host: Path) -> None:
    """Mirror the installer's planned .gitattributes region output."""
    from scaffold_p5.consumer_install import apply_gitattributes_region

    applied = apply_gitattributes_region("")
    assert applied is not None
    write(host, ".gitattributes", applied)


def _write_install_manifest(
    host: Path,
    *,
    include_region: bool = True,
    managed_file: str | None = None,
    wrong_file_digest: bool = False,
) -> str | None:
    """Write a minimal-but-format-valid Install Manifest.

    ``managed_file`` registers one extra whole-file MANAGED entry whose
    digest is computed from the live bytes (or deliberately wrong when
    ``wrong_file_digest`` is set, for the fail-closed test).
    """
    import hashlib

    from scaffold_p5.consumer_install import (
        GITATTR_REGION,
        expected_region_digest,
    )

    install_yaml = host / ".scaffold/install/install.yaml"
    install_yaml.parent.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    if managed_file:
        target = host / managed_file
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_text("managed runtime bytes\n", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if wrong_file_digest:
            digest = "0" * 64
        files.append(
            {"path": managed_file, "digest": digest, "ownership": "MANAGED"}
        )
    regions: list[dict] = []
    if include_region:
        expected = expected_region_digest(".gitattributes", host=host)
        if expected is not None:
            regions.append(
                {
                    "path": ".gitattributes",
                    "region_id": GITATTR_REGION,
                    "digest": expected,
                    "ownership": "MANAGED_REGION",
                }
            )
    payload = {
        "schema_version": "1",
        "install_format_version": "1",
        "kind": "scaffold_consumer_install",
        "ownership": "MANAGED",
        "files": files,
        "regions": regions,
    }
    write_yaml_atomic(install_yaml, payload)
    return managed_file


def _ensure_review_authority(host: Path) -> tuple[dict, dict]:
    """Task and project records for Structural Review without rewriting AGENTS.md."""
    from scaffold_p5.schemas import CURRENT_PROJECT_CONTRACT_GENERATION

    project_path = host / ".scaffold" / "project.yaml"
    project = read_yaml(project_path) if project_path.is_file() else {}
    if not isinstance(project, dict):
        project = {}
    project.setdefault("schema_version", "1")
    project["project_contract_generation"] = CURRENT_PROJECT_CONTRACT_GENERATION
    project.setdefault("lifecycle", "ACTIVE")
    project.setdefault("maintenance", [])
    ownership = dict(project.get("ownership") or {})
    ownership.setdefault("src/", "HUMAN_OWNED")
    for key, mode in CORE_OWNERSHIP.items():
        ownership.setdefault(key, mode)
    project["ownership"] = ownership
    areas = list(project.get("source_areas") or [])
    if "src" not in areas:
        areas.append("src")
    project["source_areas"] = areas
    write_yaml_atomic(project_path, project)
    task_path = host / ".scaffold" / "tasks" / f"{TASK_A}.yaml"
    if not task_path.is_file():
        write_task(host)
    return read_yaml(task_path), project


def _layer_view(host: Path, rel: str) -> dict:
    """Candidate, Structural Review, and unexplained classification for one path."""
    from scaffold_p6.candidate import observe_candidate, tracked_mixed_matches_head
    from scaffold_p7.unexplained import (
        establish_compatibility_boundary,
        reconcile_unexplained_drift,
        unexplained_path_map,
    )
    from scaffold_p8.delta import observe_real_diff

    candidate = observe_candidate(host)
    tracked = [
        row.get("path")
        for row in (candidate.data.get("tracked_paths") or [])
        if isinstance(row, dict)
    ]
    task, project = _ensure_review_authority(host)
    structural = review_structure(
        root=host,
        task=task,
        real_diff=observe_real_diff(host),
        project=project,
    )
    established = establish_compatibility_boundary(host, classify_inherited=False)
    if not established.get("ok"):
        raise AssertionError(established.get("blockers"))
    drift = reconcile_unexplained_drift(host, boundary="open")
    if not drift.get("ok"):
        raise AssertionError(drift.get("blockers"))
    row = unexplained_path_map(host).get(rel)
    return {
        "mixed": tracked_mixed_matches_head(host, rel),
        "tracked": tracked,
        "unknown": list(structural.get("unknown_ownership") or []),
        "undeclared": list(structural.get("undeclared") or []),
        "managed": [
            item.get("path")
            for item in (structural.get("install_managed_paths") or [])
            if isinstance(item, dict)
        ],
        "blockers": list(structural.get("blockers") or []),
        "passed": bool(structural.get("structural_review_pass")),
        "drift": None if row is None else row.get("classification"),
    }


def _commit_all(host: Path, message: str) -> None:
    git(host, "add", "-A")
    git(
        host,
        "-c",
        "user.name=P6 Test",
        "-c",
        "user.email=p6@example.invalid",
        "commit",
        "-m",
        message,
    )


def _without_agents_region(text: str, region_id: str) -> str:
    from scaffold_p5.agents import parse_managed_regions

    spans, issues = parse_managed_regions(text)
    if issues or region_id not in spans:
        raise AssertionError((issues, sorted(spans)))
    start, end = spans[region_id]
    return text[:start] + text[end:]


def _without_gitattributes_region(text: str) -> str:
    from scaffold_p5.consumer_install import GITATTR_REGION, parse_gitattributes_region

    spans, issues = parse_gitattributes_region(text)
    if issues or GITATTR_REGION not in spans:
        raise AssertionError((issues, sorted(spans)))
    start, end = spans[GITATTR_REGION]
    return text[:start] + text[end:]


def _strip_scaffold_hook_commands(node):
    from scaffold_p5.first_use import is_scaffold_hook_command

    if isinstance(node, list):
        return [
            _strip_scaffold_hook_commands(item)
            for item in node
            if not is_scaffold_hook_command(item)
        ]
    if isinstance(node, dict):
        return {
            key: _strip_scaffold_hook_commands(value) for key, value in node.items()
        }
    return node


def _rewrite_manifest_file(host: Path, rel: str) -> None:
    from scaffold_p5.io_util import file_digest

    manifest_path = host / ".scaffold" / "install" / "install.yaml"
    manifest = read_yaml(manifest_path)
    files = [row for row in (manifest.get("files") or []) if row.get("path") != rel]
    files.append(
        {"path": rel, "digest": file_digest(host / rel), "ownership": "MANAGED"}
    )
    manifest["files"] = files
    write_yaml_atomic(manifest_path, manifest)


def _install_managed_gitattributes_host(human: str = "*.md text\n") -> Path:
    """Tracked non-empty .gitattributes, then the real installer append.

    The committed human rules predate the managed region. The working tree
    is exactly ``apply_gitattributes_region`` of those HEAD bytes, including
    the separator newline the installer inserts.
    """
    host = Path(tempfile.mkdtemp())
    write_project(host)
    from p7_support import write_task

    write_task(host)
    write(host, "src/app.py", "value = 0\n")
    write(host, ".gitattributes", human)
    init_git(host)
    from scaffold_p5.consumer_install import apply_gitattributes_region

    applied = apply_gitattributes_region(
        (host / ".gitattributes").read_text(encoding="utf-8")
    )
    assert applied is not None
    write(host, ".gitattributes", applied)
    _write_install_manifest(host)
    return host


class R8FindingsRemediationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.host = Path(self._tmp.name) / "host"
        self.host.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _task(self) -> dict:
        return read_yaml(self.host / ".scaffold/tasks" / f"{TASK_A}.yaml")

    # ------------------------------------------------------------------
    # FND-A — S3 install-managed classification
    # ------------------------------------------------------------------

    def test_FND_A_01_verified_managed_region_passes_structural_review(self):
        host = _install_managed_gitattributes_host()
        task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        project = read_yaml(host / ".scaffold/project.yaml")
        from scaffold_p8.delta import observe_real_diff

        real_diff = observe_real_diff(host)
        self.assertIn(".gitattributes", real_diff.get("paths") or [])
        structural = review_structure(
            root=host,
            task=task,
            real_diff=real_diff,
            project=project,
        )
        self.assertNotIn(
            ".gitattributes",
            structural.get("unknown_ownership") or [],
        )
        self.assertNotIn(
            ".gitattributes",
            structural.get("undeclared") or [],
        )
        verified = {
            row.get("path")
            for row in structural.get("install_managed_paths") or []
        }
        self.assertIn(".gitattributes", verified)

    def test_FND_A_02_tampered_region_fails_closed(self):
        host = _install_managed_gitattributes_host()
        text = (host / ".gitattributes").read_text(encoding="utf-8")
        write(host, ".gitattributes", text + "*.tmp -text\n")
        task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        project = read_yaml(host / ".scaffold/project.yaml")
        from scaffold_p8.delta import observe_real_diff

        structural = review_structure(
            root=host,
            task=task,
            real_diff=observe_real_diff(host),
            project=project,
        )
        self.assertIn(
            ".gitattributes",
            structural.get("unknown_ownership") or [],
        )

    def test_FND_A_03_human_bytes_outside_region_stay_visible(self):
        host = _install_managed_gitattributes_host()
        text = (host / ".gitattributes").read_text(encoding="utf-8")
        write(host, ".gitattributes", "*.log -text\n" + text)
        task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        project = read_yaml(host / ".scaffold/project.yaml")
        from scaffold_p8.delta import observe_real_diff

        structural = review_structure(
            root=host,
            task=task,
            real_diff=observe_real_diff(host),
            project=project,
        )
        self.assertIn(
            ".gitattributes",
            structural.get("unknown_ownership") or [],
        )

    def test_FND_A_04_missing_manifest_fails_closed(self):
        host = _install_managed_gitattributes_host()
        write_yaml_atomic(
            host / ".scaffold/install/install.yaml",
            {"schema_version": "1", "kind": "self"},
        )
        task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        project = read_yaml(host / ".scaffold/project.yaml")
        from scaffold_p8.delta import observe_real_diff

        structural = review_structure(
            root=host,
            task=task,
            real_diff=observe_real_diff(host),
            project=project,
        )
        self.assertIn(
            ".gitattributes",
            structural.get("unknown_ownership") or [],
        )

    def test_FND_A_05_whole_file_install_managed_change_attested(self):
        host = _install_managed_gitattributes_host()
        managed = ".scaffold/install/runtime/probe.py"
        _write_install_manifest(host, managed_file=managed)
        from scaffold_p8.structural import _install_managed_change_verified

        self.assertTrue(_install_managed_change_verified(host, managed))
        write(host, managed, "tampered runtime bytes\n")
        self.assertFalse(_install_managed_change_verified(host, managed))

    def test_FND_A_06_agents_human_text_between_regions_stays_visible(self):
        host = _install_managed_gitattributes_host()
        from scaffold_p5.agents import (
            CONSUMER_REGION_END,
            CONSUMER_REGION_START,
            agents_router_region_text,
            apply_consumer_install_region,
        )
        from scaffold_p5.consumer_install import (
            expected_region_digest,
            expected_region_text,
        )
        from scaffold_p8.delta import observe_real_diff
        from scaffold_p8.structural import _install_managed_change_verified

        block = expected_region_text("AGENTS.md", host=host)
        assert block is not None
        inner = block[
            len(CONSUMER_REGION_START) + 1 : -(len(CONSUMER_REGION_END) + 1)
        ]
        base = (
            "HUMAN-BEFORE\n"
            f"{agents_router_region_text()}\n"
            "HUMAN-BETWEEN\n"
        )
        applied = apply_consumer_install_region(base, inner=inner)
        self.assertIsNotNone(applied)
        write(host, "AGENTS.md", applied)
        git(host, "add", "AGENTS.md")
        git(
            host,
            "-c",
            "user.name=P6 Test",
            "-c",
            "user.email=p6@example.invalid",
            "commit",
            "-m",
            "agents regions",
        )
        digest = expected_region_digest("AGENTS.md", host=host)
        self.assertIsNotNone(digest)
        write_yaml_atomic(
            host / ".scaffold/install/install.yaml",
            {
                "schema_version": "1",
                "install_format_version": "1",
                "kind": "scaffold_consumer_install",
                "ownership": "MANAGED",
                "files": [],
                "regions": [
                    {
                        "path": "AGENTS.md",
                        "region_id": "scaffold-consumer",
                        "digest": digest,
                        "ownership": "MANAGED_REGION",
                    }
                ],
            },
        )
        self.assertTrue(_install_managed_change_verified(host, "AGENTS.md"))
        changed = applied.replace("HUMAN-BETWEEN", "HUMAN-BETWEEN-EDITED")
        write(host, "AGENTS.md", changed)
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        task = read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml")
        project = read_yaml(host / ".scaffold/project.yaml")
        structural = review_structure(
            root=host,
            task=task,
            real_diff=observe_real_diff(host),
            project=project,
        )
        self.assertIn("AGENTS.md", structural.get("unknown_ownership") or [])
        self.assertTrue(
            any("AGENTS.md" in item for item in structural.get("blockers") or [])
        )
        self.assertNotIn(
            "AGENTS.md",
            {row.get("path") for row in structural.get("install_managed_paths") or []},
        )

    def test_FND_A_07_path_name_alone_never_attests(self):
        from scaffold_p5.first_use import canonical_hook_fragment
        from scaffold_p5.first_use import HOOK_SCHEMA_VERSION
        import json

        # A JSON file that merely carries a valid scaffold fragment is not
        # a fragment host: attestation requires the manifest-registered
        # host path, never path shape alone.
        write(
            self.host,
            "tools/other-hooks.json",
            json.dumps(
                {
                    "version": HOOK_SCHEMA_VERSION,
                    "hooks": canonical_hook_fragment(),
                }
            ),
        )
        from scaffold_p8.structural import _install_managed_change_verified

        self.assertFalse(
            _install_managed_change_verified(
                self.host, "tools/other-hooks.json"
            )
        )

    def test_FND_A_08_manifest_rewrite_does_not_attest_tampered_region(self):
        host = _install_managed_gitattributes_host()
        from scaffold_p5.consumer_install import GITATTR_END, GITATTR_START
        from scaffold_p5.io_util import sha256_bytes
        from scaffold_p8.delta import observe_real_diff
        from scaffold_p8.structural import _install_managed_change_verified

        text = (host / ".gitattributes").read_text(encoding="utf-8")
        start = text.find(GITATTR_START)
        end = text.find(GITATTR_END, start) + len(GITATTR_END)
        tampered_slice = text[start:end].replace("-text", "-text-evil", 1)
        write(host, ".gitattributes", text[:start] + tampered_slice + text[end:])
        live = sha256_bytes(tampered_slice.encode("utf-8"))
        _write_install_manifest(host)
        payload = read_yaml(host / ".scaffold/install/install.yaml")
        payload["regions"][0]["digest"] = live
        write_yaml_atomic(host / ".scaffold/install/install.yaml", payload)
        self.assertFalse(_install_managed_change_verified(host, ".gitattributes"))
        structural = review_structure(
            root=host,
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            real_diff=observe_real_diff(host),
            project=read_yaml(host / ".scaffold/project.yaml"),
        )
        self.assertIn(".gitattributes", structural.get("unknown_ownership") or [])
        self.assertNotIn(
            ".gitattributes",
            {row.get("path") for row in structural.get("install_managed_paths") or []},
        )

    def test_FND_A_09_predecessor_region_still_attests(self):
        host = _install_managed_gitattributes_host()
        from scaffold_p5.consumer_install import (
            GITATTR_END,
            GITATTR_START,
            RC2_GITATTR_INNER,
        )
        from scaffold_p8.structural import _install_managed_change_verified

        human = "*.md text\n"
        rc2 = f"{GITATTR_START}\n{RC2_GITATTR_INNER.strip()}\n{GITATTR_END}\n"
        write(host, ".gitattributes", human + "\n" + rc2)
        _write_install_manifest(host, include_region=False)
        payload = read_yaml(host / ".scaffold/install/install.yaml")
        payload["regions"] = [
            {
                "path": ".gitattributes",
                "region_id": "scaffold-consumer-git",
                "digest": "f" * 64,
                "ownership": "MANAGED_REGION",
            }
        ]
        write_yaml_atomic(host / ".scaffold/install/install.yaml", payload)
        self.assertTrue(_install_managed_change_verified(host, ".gitattributes"))

    def test_FND_A_10_hooks_human_entry_stays_observable(self):
        import json

        from scaffold_p5.first_use import HOOK_SCHEMA_VERSION, canonical_hook_fragment
        from scaffold_p8.delta import observe_real_diff
        from scaffold_p8.structural import _install_managed_change_verified

        host = _install_managed_gitattributes_host()
        from scaffold_p5.first_use import dumps_hooks_json, merge_scaffold_hooks

        _write_install_manifest(host)
        write(
            host,
            ".cursor/hooks.json",
            dumps_hooks_json(merge_scaffold_hooks(None)),
        )
        self.assertTrue(_install_managed_change_verified(host, ".cursor/hooks.json"))
        hooks = {
            "version": HOOK_SCHEMA_VERSION,
            "hooks": canonical_hook_fragment()["events"],
        }
        human = {"command": "./human-audit.sh"}
        hooks["hooks"]["preToolUse"] = [human] + list(hooks["hooks"]["preToolUse"])
        write(host, ".cursor/hooks.json", json.dumps(hooks, indent=2) + "\n")
        git(host, "add", "-A")
        git(
            host,
            "-c",
            "user.name=P6 Test",
            "-c",
            "user.email=p6@example.invalid",
            "commit",
            "-m",
            "hooks",
        )
        _write_install_manifest(host)
        self.assertTrue(_install_managed_change_verified(host, ".cursor/hooks.json"))
        hooks["hooks"]["preToolUse"][0] = {"command": "./human-audit-EDITED.sh"}
        write(host, ".cursor/hooks.json", json.dumps(hooks, indent=2) + "\n")
        self.assertFalse(_install_managed_change_verified(host, ".cursor/hooks.json"))
        structural = review_structure(
            root=host,
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            real_diff=observe_real_diff(host),
            project=read_yaml(host / ".scaffold/project.yaml"),
        )
        self.assertNotIn(
            ".cursor/hooks.json",
            {row.get("path") for row in structural.get("install_managed_paths") or []},
        )
        exposed = (
            ".cursor/hooks.json" in (structural.get("unknown_ownership") or [])
            or ".cursor/hooks.json" in (structural.get("undeclared") or [])
            or ".cursor/hooks.json" in (structural.get("conflicting_ownership") or [])
            or any(
                ".cursor/hooks.json" in item for item in (structural.get("blockers") or [])
            )
        )
        self.assertTrue(exposed, structural.get("blockers"))
        hooks["hooks"]["preToolUse"][0] = human
        hooks["hooks"]["preToolUse"][1]["command"] = "python tampered.py"
        write(host, ".cursor/hooks.json", json.dumps(hooks, indent=2) + "\n")
        self.assertFalse(_install_managed_change_verified(host, ".cursor/hooks.json"))

    def test_FND_A_11_fresh_install_agrees_across_layers(self):
        from scaffold_p5.consumer_install import (
            apply_consumer_install,
            plan_consumer_install,
            verify_consumer_install,
        )
        from scaffold_p6.candidate import tracked_mixed_matches_head
        from scaffold_p8.delta import observe_real_diff

        host = Path(tempfile.mkdtemp())
        write(host, "README.md", "# consumer\n")
        write(host, ".gitattributes", "*.md text\n")
        write(host, "src/app.py", "value = 0\n")
        init_git(host)
        plan = plan_consumer_install(host, REPO, mode="install")
        self.assertFalse(plan.blockers, plan.blockers)
        apply_consumer_install(plan)
        verify = verify_consumer_install(host)
        self.assertEqual(verify.get("status"), "VALID", verify)
        self.assertTrue(tracked_mixed_matches_head(host, ".gitattributes"))
        write_project(host)
        from p7_support import write_task

        write_task(host)
        structural = review_structure(
            root=host,
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            real_diff=observe_real_diff(host),
            project=read_yaml(host / ".scaffold/project.yaml"),
        )
        self.assertNotIn(".gitattributes", structural.get("unknown_ownership") or [])
        self.assertIn(
            ".gitattributes",
            {row.get("path") for row in structural.get("install_managed_paths") or []},
        )
        text = (host / ".gitattributes").read_text(encoding="utf-8")
        write(host, ".gitattributes", text.replace("-text", "-text-tamper", 1))
        verify_tamper = verify_consumer_install(host)
        self.assertNotEqual(verify_tamper.get("status"), "VALID")
        structural_tamper = review_structure(
            root=host,
            task=read_yaml(host / ".scaffold/tasks" / f"{TASK_A}.yaml"),
            real_diff=observe_real_diff(host),
            project=read_yaml(host / ".scaffold/project.yaml"),
        )
        self.assertIn(".gitattributes", structural_tamper.get("unknown_ownership") or [])
        self.assertNotIn(
            ".gitattributes",
            {
                row.get("path")
                for row in structural_tamper.get("install_managed_paths") or []
            },
        )
        human_edit = (host / ".gitattributes").read_text(encoding="utf-8")
        write(host, ".gitattributes", "*.human-edit text\n" + human_edit)
        self.assertFalse(tracked_mixed_matches_head(host, ".gitattributes"))

    def test_FND_A_12_tracked_human_hooks_install_is_not_unknown(self):
        """H1–H6. Real install into a tracked human-only hooks file."""
        import json

        from scaffold_p5.consumer_install import (
            apply_consumer_install,
            plan_consumer_install,
            verify_consumer_install,
        )
        from scaffold_p5.first_use import dumps_hooks_json
        from scaffold_p5.io_util import file_digest

        host = Path(tempfile.mkdtemp())
        write(host, "README.md", "# consumer\n")
        write(host, "src/app.py", "value = 0\n")
        write(
            host,
            ".cursor/hooks.json",
            dumps_hooks_json(
                {"version": 1, "hooks": {"preToolUse": [{"command": "./human-a.sh"}]}}
            ),
        )
        init_git(host)
        plan = plan_consumer_install(host, REPO, mode="install")
        self.assertFalse(plan.blockers, plan.blockers)
        apply_consumer_install(plan)
        installed = (host / ".cursor/hooks.json").read_text(encoding="utf-8")
        self.assertIn("./human-a.sh", installed)
        self.assertIn("cursor_first_use_hook.py", installed)
        verify = verify_consumer_install(host)
        self.assertEqual(verify.get("status"), "VALID", verify)
        clean = _layer_view(host, ".cursor/hooks.json")
        self.assertNotIn(".cursor/hooks.json", clean["tracked"])
        self.assertTrue(clean["mixed"])
        self.assertNotIn(".cursor/hooks.json", clean["unknown"])
        self.assertNotIn(".cursor/hooks.json", clean["undeclared"])
        self.assertIn(".cursor/hooks.json", clean["managed"])
        self.assertEqual(clean["drift"], "install-managed")

        edited = installed.replace("./human-a.sh", "./human-a-EDITED.sh", 1)
        write(host, ".cursor/hooks.json", edited)
        human_edit = _layer_view(host, ".cursor/hooks.json")
        self.assertIn("./human-a-EDITED.sh", edited)
        self.assertIn(".cursor/hooks.json", human_edit["tracked"])
        self.assertNotIn(".cursor/hooks.json", human_edit["managed"])
        self.assertTrue(
            ".cursor/hooks.json" in human_edit["unknown"]
            or ".cursor/hooks.json" in human_edit["undeclared"]
        )
        self.assertNotEqual(human_edit["drift"], "install-managed")

        added = json.loads(installed)
        added["hooks"]["postToolUse"] = list(added["hooks"]["postToolUse"]) + [
            {"command": "./human-added.sh"}
        ]
        write(host, ".cursor/hooks.json", dumps_hooks_json(added))
        added_view = _layer_view(host, ".cursor/hooks.json")
        self.assertIn("./human-added.sh", (host / ".cursor/hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn(".cursor/hooks.json", added_view["managed"])
        self.assertNotEqual(added_view["drift"], "install-managed")
        self.assertTrue(
            ".cursor/hooks.json" in added_view["unknown"]
            or ".cursor/hooks.json" in added_view["undeclared"]
        )

        tampered = installed.replace("cursor_first_use_hook.py", "tampered-hook.py", 1)
        write(host, ".cursor/hooks.json", tampered)
        tamper_view = _layer_view(host, ".cursor/hooks.json")
        self.assertNotEqual(verify_consumer_install(host).get("status"), "VALID")
        self.assertNotIn(".cursor/hooks.json", tamper_view["managed"])
        self.assertNotEqual(tamper_view["drift"], "install-managed")

        manifest_path = host / ".scaffold" / "install" / "install.yaml"
        manifest = read_yaml(manifest_path)
        files = list(manifest.get("files") or [])
        files.append(
            {
                "path": ".cursor/hooks.json",
                "digest": file_digest(host / ".cursor/hooks.json"),
                "ownership": "MANAGED",
            }
        )
        manifest["files"] = files
        write_yaml_atomic(manifest_path, manifest)
        rewrite_view = _layer_view(host, ".cursor/hooks.json")
        self.assertNotEqual(verify_consumer_install(host).get("status"), "VALID")
        self.assertNotIn(".cursor/hooks.json", rewrite_view["managed"])
        self.assertNotEqual(rewrite_view["drift"], "install-managed")

        write(host, ".cursor/hooks.json", installed)
        first = (host / ".cursor/hooks.json").read_text(encoding="utf-8")
        for _ in range(2):
            update = plan_consumer_install(host, REPO, mode="update")
            self.assertFalse(update.blockers, update.blockers)
            apply_consumer_install(update)
        second = (host / ".cursor/hooks.json").read_text(encoding="utf-8")
        third_plan = plan_consumer_install(host, REPO, mode="update")
        self.assertFalse(third_plan.blockers, third_plan.blockers)
        apply_consumer_install(third_plan)
        third = (host / ".cursor/hooks.json").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertIn("./human-a.sh", third)
        self.assertEqual(third.count("cursor_first_use_hook.py"), first.count("cursor_first_use_hook.py"))
        stable = _layer_view(host, ".cursor/hooks.json")
        self.assertEqual(verify_consumer_install(host).get("status"), "VALID")
        self.assertIn(".cursor/hooks.json", stable["managed"])
        self.assertNotIn(".cursor/hooks.json", stable["unknown"])
        self.assertNotIn(".cursor/hooks.json", stable["undeclared"])
        self.assertEqual(stable["drift"], "install-managed")

    def test_FND_A_13_agents_router_identity_is_attested(self):
        """A1–A7. Every removed AGENTS region must have its own authority."""
        from scaffold_p5.agents import (
            AGENTS_ROUTER_REGION,
            CONSUMER_INSTALL_REGION,
            agents_router_region_text,
            apply_consumer_install_region,
            parse_managed_regions,
        )
        from scaffold_p5.consumer_install import (
            RC2_CONSUMER_AGENTS_INNER,
            apply_consumer_install,
            expected_managed_region_digest,
            plan_consumer_install,
            predecessor_managed_region_digests,
            verify_consumer_install,
        )
        from scaffold_p5.io_util import file_digest, sha256_bytes

        self.assertEqual(
            predecessor_managed_region_digests("AGENTS.md", AGENTS_ROUTER_REGION),
            set(),
        )

        host = Path(tempfile.mkdtemp())
        write(host, "README.md", "# consumer\n")
        write(host, "src/app.py", "value = 0\n")
        human = "HUMAN-BEFORE\nHUMAN-BETWEEN\n"
        committed = human + agents_router_region_text() + "\n"
        write(host, "AGENTS.md", committed)
        init_git(host)
        plan = plan_consumer_install(host, REPO, mode="install")
        self.assertFalse(plan.blockers, plan.blockers)
        apply_consumer_install(plan)
        installed = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("HUMAN-BETWEEN", installed)
        self.assertIn(agents_router_region_text(), installed)
        self.assertEqual(verify_consumer_install(host).get("status"), "VALID")
        spans, issues = parse_managed_regions(installed)
        self.assertFalse(issues, issues)
        self.assertIn(AGENTS_ROUTER_REGION, spans)
        self.assertIn(CONSUMER_INSTALL_REGION, spans)
        legal = _layer_view(host, "AGENTS.md")
        self.assertIn("AGENTS.md", legal["managed"])
        self.assertNotIn("AGENTS.md", legal["unknown"])
        self.assertEqual(legal["drift"], "install-managed")

        between = installed.replace("HUMAN-BETWEEN", "HUMAN-BETWEEN-EDITED", 1)
        write(host, "AGENTS.md", between)
        human_view = _layer_view(host, "AGENTS.md")
        self.assertIn("HUMAN-BETWEEN-EDITED", (host / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotIn("AGENTS.md", human_view["managed"])
        self.assertIn("AGENTS.md", human_view["unknown"])
        self.assertFalse(human_view["mixed"])
        self.assertNotEqual(human_view["drift"], "install-managed")

        router_only = installed.replace(
            "Zero-context resume:", "Zero-context resume TAMPERED:", 1
        )
        self.assertNotEqual(router_only, installed)
        write(host, "AGENTS.md", router_only)
        router_view = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", router_view["managed"])
        self.assertIn("AGENTS.md", router_view["unknown"])
        self.assertTrue(any("AGENTS.md" in item for item in router_view["blockers"]))
        self.assertNotEqual(router_view["drift"], "install-managed")

        consumer_only = installed.replace(
            "Scaffold is installed.", "Scaffold is installed. TAMPERED.", 1
        )
        write(host, "AGENTS.md", consumer_only)
        consumer_view = _layer_view(host, "AGENTS.md")
        self.assertNotEqual(verify_consumer_install(host).get("status"), "VALID")
        self.assertNotIn("AGENTS.md", consumer_view["managed"])
        self.assertNotEqual(consumer_view["drift"], "install-managed")

        write(host, "AGENTS.md", router_only)
        manifest_path = host / ".scaffold" / "install" / "install.yaml"
        manifest = read_yaml(manifest_path)
        regions = list(manifest.get("regions") or [])
        start, end = parse_managed_regions(router_only)[0][AGENTS_ROUTER_REGION]
        live_router = sha256_bytes(router_only[start:end].encode("utf-8"))
        for row in regions:
            if row.get("path") == "AGENTS.md" and row.get("region_id") == AGENTS_ROUTER_REGION:
                row["digest"] = live_router
        manifest["regions"] = regions
        files = list(manifest.get("files") or [])
        files.append(
            {
                "path": "AGENTS.md",
                "digest": file_digest(host / "AGENTS.md"),
                "ownership": "MANAGED",
            }
        )
        manifest["files"] = files
        write_yaml_atomic(manifest_path, manifest)
        rewrite_view = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", rewrite_view["managed"])
        self.assertNotEqual(rewrite_view["drift"], "install-managed")
        self.assertIn("AGENTS.md", rewrite_view["unknown"])

        predecessor = apply_consumer_install_region(
            committed,
            inner=RC2_CONSUMER_AGENTS_INNER.strip(),
        )
        self.assertIsNotNone(predecessor)
        write(host, "AGENTS.md", predecessor)
        self.assertTrue(
            expected_managed_region_digest(
                "AGENTS.md", AGENTS_ROUTER_REGION, host=host
            )
        )
        predecessor_view = _layer_view(host, "AGENTS.md")
        self.assertIn("AGENTS.md", predecessor_view["managed"])
        self.assertEqual(predecessor_view["drift"], "install-managed")
        tampered_predecessor = predecessor.replace(
            "Zero-context resume:", "Zero-context resume TAMPERED:", 1
        )
        write(host, "AGENTS.md", tampered_predecessor)
        predecessor_tamper = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", predecessor_tamper["managed"])
        self.assertNotEqual(predecessor_tamper["drift"], "install-managed")

        fresh = Path(tempfile.mkdtemp())
        write(fresh, "README.md", "# consumer\n")
        write(fresh, "src/app.py", "value = 0\n")
        init_git(fresh)
        fresh_plan = plan_consumer_install(fresh, REPO, mode="install")
        self.assertFalse(fresh_plan.blockers, fresh_plan.blockers)
        apply_consumer_install(fresh_plan)
        fresh_text = (fresh / "AGENTS.md").read_text(encoding="utf-8")
        fresh_spans, fresh_issues = parse_managed_regions(fresh_text)
        self.assertFalse(fresh_issues, fresh_issues)
        self.assertTrue(fresh_spans, fresh_spans)
        for region_id, span in fresh_spans.items():
            start, end = span
            live = sha256_bytes(fresh_text[start:end].encode("utf-8"))
            expected = expected_managed_region_digest("AGENTS.md", region_id, host=fresh)
            predecessors = predecessor_managed_region_digests("AGENTS.md", region_id)
            self.assertTrue(
                live == expected or live in predecessors,
                region_id,
            )
        fresh_view = _layer_view(fresh, "AGENTS.md")
        self.assertEqual(verify_consumer_install(fresh).get("status"), "VALID")
        self.assertIn("AGENTS.md", fresh_view["managed"])
        self.assertNotIn("AGENTS.md", fresh_view["unknown"])
        self.assertEqual(fresh_view["drift"], "install-managed")
        first_agents = fresh_text
        for _ in range(2):
            update = plan_consumer_install(fresh, REPO, mode="update")
            self.assertFalse(update.blockers, update.blockers)
            apply_consumer_install(update)
        self.assertEqual((fresh / "AGENTS.md").read_text(encoding="utf-8"), first_agents)
        updated_view = _layer_view(fresh, "AGENTS.md")
        self.assertIn("AGENTS.md", updated_view["managed"])
        self.assertEqual(updated_view["drift"], "install-managed")

    def test_FND_A_14_managed_region_absence_fails_closed(self):
        """Deleting a Scaffold region that HEAD already contained is not install-only."""
        from scaffold_p5.agents import (
            AGENTS_ROUTER_REGION,
            CONSUMER_INSTALL_REGION,
            CONSUMER_REGION_START,
            agents_router_region_text,
        )
        from scaffold_p5.consumer_install import (
            apply_consumer_install,
            plan_consumer_install,
            verify_consumer_install,
        )
        from scaffold_p8.structural import _install_managed_change_verified

        host = Path(tempfile.mkdtemp())
        write(host, "README.md", "# consumer\n")
        write(host, "src/app.py", "value = 0\n")
        write(
            host,
            "AGENTS.md",
            "HUMAN-BEFORE\nHUMAN-BETWEEN\n" + agents_router_region_text() + "\n",
        )
        init_git(host)
        plan = plan_consumer_install(host, REPO, mode="install")
        self.assertFalse(plan.blockers, plan.blockers)
        apply_consumer_install(plan)
        installed = (host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(agents_router_region_text(), installed)
        self.assertIn(CONSUMER_REGION_START, installed)
        self.assertIn("HUMAN-BETWEEN", installed)
        added = _layer_view(host, "AGENTS.md")
        self.assertEqual(verify_consumer_install(host).get("status"), "VALID")
        self.assertIn("AGENTS.md", added["managed"])
        self.assertNotIn("AGENTS.md", added["unknown"])
        self.assertEqual(added["drift"], "install-managed")

        _commit_all(host, "installed agents regions")
        self.assertTrue(_install_managed_change_verified(host, "AGENTS.md"))
        unchanged = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", unchanged["unknown"])
        self.assertNotIn("AGENTS.md", unchanged["managed"])
        self.assertTrue(unchanged["passed"], unchanged["blockers"])

        router_deleted = _without_agents_region(installed, AGENTS_ROUTER_REGION)
        self.assertNotIn(agents_router_region_text(), router_deleted)
        self.assertIn(CONSUMER_REGION_START, router_deleted)
        write(host, "AGENTS.md", router_deleted)
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        router_view = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", router_view["managed"])
        self.assertIn("AGENTS.md", router_view["unknown"])
        self.assertFalse(router_view["passed"])
        self.assertNotEqual(router_view["drift"], "install-managed")
        self.assertTrue(any("AGENTS.md" in item for item in router_view["blockers"]))

        consumer_deleted = _without_agents_region(installed, CONSUMER_INSTALL_REGION)
        self.assertIn(agents_router_region_text(), consumer_deleted)
        self.assertNotIn(CONSUMER_REGION_START, consumer_deleted)
        write(host, "AGENTS.md", consumer_deleted)
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        self.assertNotEqual(verify_consumer_install(host).get("status"), "VALID")
        consumer_view = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", consumer_view["managed"])
        self.assertIn("AGENTS.md", consumer_view["unknown"])
        self.assertFalse(consumer_view["passed"])
        self.assertNotEqual(consumer_view["drift"], "install-managed")

        both_deleted = _without_agents_region(
            _without_agents_region(installed, AGENTS_ROUTER_REGION),
            CONSUMER_INSTALL_REGION,
        )
        self.assertIn("HUMAN-BETWEEN", both_deleted)
        self.assertNotIn(CONSUMER_REGION_START, both_deleted)
        self.assertNotIn("scaffold:managed:agents-router:start", both_deleted)
        write(host, "AGENTS.md", both_deleted)
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        both_view = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", both_view["managed"])
        self.assertFalse(both_view["passed"])
        self.assertNotEqual(both_view["drift"], "install-managed")

        write(host, "AGENTS.md", router_deleted)
        _rewrite_manifest_file(host, "AGENTS.md")
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        router_rewrite = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", router_rewrite["managed"])
        self.assertNotEqual(router_rewrite["drift"], "install-managed")
        self.assertFalse(router_rewrite["passed"])

        write(host, "AGENTS.md", consumer_deleted)
        _rewrite_manifest_file(host, "AGENTS.md")
        self.assertFalse(_install_managed_change_verified(host, "AGENTS.md"))
        consumer_rewrite = _layer_view(host, "AGENTS.md")
        self.assertNotIn("AGENTS.md", consumer_rewrite["managed"])
        self.assertNotEqual(consumer_rewrite["drift"], "install-managed")
        self.assertFalse(consumer_rewrite["passed"])

        fresh = Path(tempfile.mkdtemp())
        write(fresh, "README.md", "# consumer\n")
        write(fresh, "src/app.py", "value = 0\n")
        write(fresh, "AGENTS.md", "HUMAN-ONLY\n")
        init_git(fresh)
        fresh_plan = plan_consumer_install(fresh, REPO, mode="install")
        self.assertFalse(fresh_plan.blockers, fresh_plan.blockers)
        apply_consumer_install(fresh_plan)
        fresh_text = (fresh / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("HUMAN-ONLY", fresh_text)
        self.assertNotIn("scaffold:managed:agents-router:start", fresh_text)
        self.assertIn(CONSUMER_REGION_START, fresh_text)
        fresh_view = _layer_view(fresh, "AGENTS.md")
        self.assertEqual(verify_consumer_install(fresh).get("status"), "VALID")
        self.assertIn("AGENTS.md", fresh_view["managed"])
        self.assertEqual(fresh_view["drift"], "install-managed")
        _commit_all(fresh, "consumer only")
        self.assertTrue(_install_managed_change_verified(fresh, "AGENTS.md"))
        write(fresh, "AGENTS.md", _without_agents_region(fresh_text, CONSUMER_INSTALL_REGION))
        self.assertFalse(_install_managed_change_verified(fresh, "AGENTS.md"))
        deleted_only = _layer_view(fresh, "AGENTS.md")
        self.assertNotIn("AGENTS.md", deleted_only["managed"])
        self.assertFalse(deleted_only["passed"])
        self.assertNotEqual(deleted_only["drift"], "install-managed")

    def test_FND_A_15_gitattributes_and_hooks_absence_fail_closed(self):
        """Region addition stays legal. Deleting an installed region or fragment does not."""
        import json

        from scaffold_p5.consumer_install import (
            apply_consumer_install,
            plan_consumer_install,
            verify_consumer_install,
        )
        from scaffold_p5.first_use import dumps_hooks_json
        from scaffold_p8.structural import _install_managed_change_verified

        host = Path(tempfile.mkdtemp())
        write(host, "README.md", "# consumer\n")
        write(host, "src/app.py", "value = 0\n")
        write(host, ".gitattributes", "*.md text\n")
        init_git(host)
        plan = plan_consumer_install(host, REPO, mode="install")
        self.assertFalse(plan.blockers, plan.blockers)
        apply_consumer_install(plan)
        installed_attr = (host / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.md text", installed_attr)
        self.assertEqual(verify_consumer_install(host).get("status"), "VALID")
        attr_view = _layer_view(host, ".gitattributes")
        self.assertIn(".gitattributes", attr_view["managed"])
        self.assertNotIn(".gitattributes", attr_view["unknown"])
        self.assertEqual(attr_view["drift"], "install-managed")
        _commit_all(host, "installed gitattributes")
        self.assertTrue(_install_managed_change_verified(host, ".gitattributes"))
        write(host, ".gitattributes", _without_gitattributes_region(installed_attr))
        self.assertNotIn("scaffold:managed:scaffold-consumer-git:start", (host / ".gitattributes").read_text(encoding="utf-8"))
        self.assertFalse(_install_managed_change_verified(host, ".gitattributes"))
        deleted_attr = _layer_view(host, ".gitattributes")
        self.assertNotIn(".gitattributes", deleted_attr["managed"])
        self.assertFalse(deleted_attr["passed"])
        self.assertTrue(
            ".gitattributes" in deleted_attr["unknown"]
            or ".gitattributes" in deleted_attr["undeclared"]
        )
        self.assertNotEqual(deleted_attr["drift"], "install-managed")
        write(host, ".gitattributes", installed_attr.replace("*.md text", "*.md text=auto", 1))
        human_attr = _layer_view(host, ".gitattributes")
        self.assertIn("*.md text=auto", (host / ".gitattributes").read_text(encoding="utf-8"))
        self.assertNotIn(".gitattributes", human_attr["managed"])
        self.assertFalse(human_attr["passed"])
        self.assertNotEqual(human_attr["drift"], "install-managed")

        hooks_host = Path(tempfile.mkdtemp())
        write(hooks_host, "README.md", "# consumer\n")
        write(hooks_host, "src/app.py", "value = 0\n")
        write(
            hooks_host,
            ".cursor/hooks.json",
            dumps_hooks_json(
                {"version": 1, "hooks": {"preToolUse": [{"command": "./human-a.sh"}]}}
            ),
        )
        init_git(hooks_host)
        hooks_plan = plan_consumer_install(hooks_host, REPO, mode="install")
        self.assertFalse(hooks_plan.blockers, hooks_plan.blockers)
        apply_consumer_install(hooks_plan)
        installed_hooks = (hooks_host / ".cursor/hooks.json").read_text(encoding="utf-8")
        self.assertIn("./human-a.sh", installed_hooks)
        hooks_view = _layer_view(hooks_host, ".cursor/hooks.json")
        self.assertEqual(verify_consumer_install(hooks_host).get("status"), "VALID")
        self.assertIn(".cursor/hooks.json", hooks_view["managed"])
        self.assertEqual(hooks_view["drift"], "install-managed")
        _commit_all(hooks_host, "installed hooks")
        data = _strip_scaffold_hook_commands(json.loads(installed_hooks))
        write(hooks_host, ".cursor/hooks.json", dumps_hooks_json(data))
        self.assertIn("./human-a.sh", (hooks_host / ".cursor/hooks.json").read_text(encoding="utf-8"))
        self.assertNotIn("cursor_first_use_hook.py", (hooks_host / ".cursor/hooks.json").read_text(encoding="utf-8"))
        self.assertFalse(_install_managed_change_verified(hooks_host, ".cursor/hooks.json"))
        self.assertNotEqual(verify_consumer_install(hooks_host).get("status"), "VALID")
        fragment_view = _layer_view(hooks_host, ".cursor/hooks.json")
        self.assertNotIn(".cursor/hooks.json", fragment_view["managed"])
        self.assertFalse(fragment_view["passed"])
        self.assertNotEqual(fragment_view["drift"], "install-managed")

    # ------------------------------------------------------------------
    # FND-B — READY scope repair routing
    # ------------------------------------------------------------------

    def test_FND_B_01_ready_single_stage_undeclared_gets_repair_handoff(self):
        write_submit_host(self.host)
        write(self.host, "src/extra.py", "VALUE = 1\n")
        task = self._task()
        task["status"] = "READY_FOR_REVIEW"
        task["stages"][0]["status"] = "COMPLETE"
        task["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1",
            candidate_digest=observe_candidate(self.host).digest,
        )
        task["task_completion_decision"] = satisfied_decision(
            candidate_digest=observe_candidate(self.host).digest
        )
        write_yaml_atomic(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.next_route, "develop.repair")
        handoff = result.extras.get("repair_handoff")
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.get("kind"), "submit_to_develop")
        self.assertEqual(handoff.get("target_stage_ids"), ["stage-1"])
        self.assertEqual(handoff.get("target_mapping"), "single_stage")
        self.assertFalse(handoff.get("submit_authorized"))

    def test_FND_B_02_ready_multi_stage_undeclared_fails_closed(self):
        write_submit_host(self.host)
        write(self.host, "src/extra.py", "VALUE = 1\n")
        digest = observe_candidate(self.host).digest
        task = self._task()
        task["status"] = "READY_FOR_REVIEW"
        task["stages"] = [
            {
                "stage_id": "stage-1",
                "goal": "First.",
                "acceptance": "Done.",
                "status": "COMPLETE",
                "required_tests": [],
                "completion_decision": satisfied_decision(
                    stage_id="stage-1", candidate_digest=digest
                ),
            },
            {
                "stage_id": "stage-2",
                "goal": "Second.",
                "acceptance": "Done.",
                "status": "COMPLETE",
                "required_tests": [],
                "completion_decision": satisfied_decision(
                    stage_id="stage-2", candidate_digest=digest
                ),
            },
        ]
        task["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest
        )
        write_yaml_atomic(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task
        )
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertNotEqual(result.next_route, "develop.repair")
        self.assertEqual(result.next_route, "human")
        self.assertIsNone(result.extras.get("repair_handoff"))
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_FND_B_03_repair_handoff_is_develop_consumable(self):
        from p6_support import passing_profile, write_host
        from p7_support import (
            bind_develop_lock,
            ensure_noscms_accepted_anchor,
        )

        profile, command = passing_profile("unit-save-check")
        write_host(self.host, [(profile, command)])
        bind_develop_lock(self.host)
        payload = read_yaml(self.host / ".scaffold/project.yaml")
        payload["ownership"] = {**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"}
        payload["source_areas"] = ["src"]
        write_yaml_atomic(self.host / ".scaffold/project.yaml", payload)
        write(self.host, "src/app.py", "value = 0\n")
        ensure_noscms_accepted_anchor(self.host)
        write_task(self.host, TASK_A, status="READY_FOR_REVIEW")
        digest = observe_candidate(self.host).digest
        task = self._task()
        task["stages"][0]["status"] = "COMPLETE"
        task["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1", candidate_digest=digest
        )
        task["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest
        )
        write_yaml_atomic(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task
        )
        handoff = submit_repair_handoff(
            task_id=TASK_A,
            candidate_digest=digest,
            target_stage_ids=["stage-1"],
            blockers=[
                "real Diff contains undeclared Task Book paths: src/extra.py"
            ],
        )
        result = develop_engine(self.host).run(
            "repair",
            task_id=TASK_A,
            submit_to_develop=handoff,
        )
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        reopened = self._task()
        self.assertEqual(reopened["status"], "IN_PROGRESS")
        self.assertEqual(reopened["stages"][0]["status"], "IN_PROGRESS")

    def test_FND_B_04_no_silent_ready_mutation_without_handoff(self):
        write_submit_host(self.host)
        write(self.host, "src/extra.py", "VALUE = 1\n")
        digest = observe_candidate(self.host).digest
        task = self._task()
        task["status"] = "READY_FOR_REVIEW"
        task["stages"] = [
            {
                "stage_id": "stage-1",
                "goal": "First.",
                "acceptance": "Done.",
                "status": "COMPLETE",
                "required_tests": [],
                "completion_decision": satisfied_decision(
                    stage_id="stage-1", candidate_digest=digest
                ),
            },
            {
                "stage_id": "stage-2",
                "goal": "Second.",
                "acceptance": "Done.",
                "status": "COMPLETE",
                "required_tests": [],
                "completion_decision": satisfied_decision(
                    stage_id="stage-2", candidate_digest=digest
                ),
            },
        ]
        task["task_completion_decision"] = satisfied_decision(
            candidate_digest=digest
        )
        write_yaml_atomic(
            self.host / ".scaffold/tasks" / f"{TASK_A}.yaml", task
        )
        revision = self._task()["record_revision"]
        run_submit(self.host, task_id=TASK_A)
        reopened = self._task()
        self.assertEqual(reopened["status"], "READY_FOR_REVIEW")
        self.assertEqual(reopened["record_revision"], revision)

    def test_FND_B_05_missing_source_single_stage_routes_to_repair(self):
        write_submit_host(self.host)
        (self.host / "src/app.py").unlink()
        result = run_submit(self.host, task_id=TASK_A)
        self.assertEqual(result.next_route, "develop.repair")
        handoff = result.extras.get("repair_handoff")
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.get("target_stage_ids"), ["stage-1"])

    def test_FND_B_06_governance_path_does_not_ride_along(self):
        write_submit_host(self.host)
        write(self.host, "src/extra.py", "VALUE = 1\n")
        write(self.host, "CODEOWNERS", "* @human\n")
        task = self._task()
        task["status"] = "READY_FOR_REVIEW"
        task["stages"][0]["status"] = "COMPLETE"
        task["stages"][0]["required_tests"] = []
        digest = observe_candidate(self.host).digest
        task["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1", candidate_digest=digest
        )
        task["task_completion_decision"] = satisfied_decision(candidate_digest=digest)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        write_yaml_atomic(task_path, task)
        before = task_path.read_bytes()
        result = run_submit(self.host, task_id=TASK_A, bind_ready_authority=False)
        self.assertEqual(result.next_route, "stop")
        self.assertIsNone(result.extras.get("repair_handoff"))
        joined = " ".join(result.blockers)
        self.assertIn("src/extra.py", joined)
        self.assertIn("CODEOWNERS", joined)
        self.assertEqual(task_path.read_bytes(), before)
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")

    def test_FND_B_07_missing_source_plus_codeowners_stops(self):
        from p8_support import bind_ready_completion_authority

        write_submit_host(self.host)
        (self.host / "src/app.py").unlink()
        write(self.host, "CODEOWNERS", "* @human\n")
        bind_ready_completion_authority(self.host)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        before = task_path.read_bytes()
        result = run_submit(self.host, task_id=TASK_A, bind_ready_authority=False)
        self.assertEqual(result.next_route, "stop", result.blockers)
        self.assertIsNone(result.extras.get("repair_handoff"))
        joined = " ".join(result.blockers)
        self.assertIn("src/app.py", joined)
        self.assertIn("CODEOWNERS", joined)
        self.assertEqual(task_path.read_bytes(), before)

    def test_FND_B_08_repair_handoff_is_atomic(self):
        write_submit_host(self.host)
        write(self.host, "src/extra.py", "VALUE = 1\n")
        task = self._task()
        task["status"] = "READY_FOR_REVIEW"
        task["stages"][0]["status"] = "COMPLETE"
        task["stages"][0]["required_tests"] = []
        digest = observe_candidate(self.host).digest
        task["stages"][0]["completion_decision"] = satisfied_decision(
            stage_id="stage-1", candidate_digest=digest
        )
        task["task_completion_decision"] = satisfied_decision(candidate_digest=digest)
        task_path = self.host / ".scaffold/tasks" / f"{TASK_A}.yaml"
        write_yaml_atomic(task_path, task)
        before = task_path.read_bytes()
        submitted = run_submit(self.host, task_id=TASK_A, bind_ready_authority=False)
        self.assertEqual(submitted.next_route, "develop.repair", submitted.blockers)
        self.assertEqual(task_path.read_bytes(), before)
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        handoff = submitted.extras.get("repair_handoff")
        self.assertIsNotNone(handoff)
        stale = dict(handoff)
        stale["candidate_digest"] = "sha256:" + ("ab" * 32)
        rejected = develop_engine(self.host).run(
            "repair", task_id=TASK_A, submit_to_develop=stale
        )
        self.assertNotEqual(rejected.outcome, "COMPLETED")
        self.assertEqual(task_path.read_bytes(), before)
        self.assertEqual(self._task()["status"], "READY_FOR_REVIEW")
        consumed = develop_engine(self.host).run(
            "repair", task_id=TASK_A, submit_to_develop=handoff
        )
        self.assertEqual(consumed.outcome, "COMPLETED", consumed.blockers)
        reopened = self._task()
        self.assertNotEqual(task_path.read_bytes(), before)
        self.assertEqual(reopened["status"], "IN_PROGRESS")
        self.assertEqual(reopened["stages"][0]["status"], "IN_PROGRESS")
        self.assertEqual(
            reopened["stages"][0]["completion_decision"]["outcome"], "UNKNOWN"
        )
        self.assertEqual(reopened["task_completion_decision"]["outcome"], "UNKNOWN")

    # ------------------------------------------------------------------
    # FND-C — Session inventory scale
    # ------------------------------------------------------------------

    def test_FND_C_01_dependency_tree_excluded_from_inventory(self):
        from p7_support import write_active_host

        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        (self.host / "node_modules" / "left-pad").mkdir(parents=True)
        write(self.host, "node_modules/left-pad/index.js", "module.exports = 1\n")
        write(self.host, "node_modules/.package-lock.json", "{}\n")
        digests = execution_workspace_digests(self.host)
        self.assertIn("src/app.py", digests)
        self.assertNotIn("node_modules/left-pad/index.js", digests)
        self.assertNotIn("node_modules/.package-lock.json", digests)

    def test_FND_C_02_open_inventory_and_reconcile_share_envelope(self):
        from p7_support import write_active_host

        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        (self.host / "node_modules" / "pkg").mkdir(parents=True)
        write(self.host, "node_modules/pkg/index.js", "x\n")
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        from p7_support import ensure_noscms_accepted_anchor

        ensure_noscms_accepted_anchor(self.host)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session = (opened.extras or {}).get("session") or {}
        session_id = str(session.get("record_id") or "")
        self.assertTrue(session_id)
        directory = self.host / SESSIONS_DIR / session_id
        inventory = load_open_inventory(directory)
        self.assertIn("src/app.py", inventory or {})
        self.assertNotIn("node_modules/pkg/index.js", inventory or {})
        write(self.host, "src/app.py", "value = 2\n")
        from scaffold_p7.develop_authority import reconcile_session_changes

        reconciliation = reconcile_session_changes(
            self.host, directory, task=self._task()
        )
        self.assertTrue(reconciliation.ok, reconciliation.blockers)

    def test_FND_C_03_legacy_inventory_rows_are_canonicalized(self):
        from p7_support import write_active_host

        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        from scaffold_p7.session import snapshot_open_inventory
        from scaffold_p7.models import SESSIONS_DIR

        directory = self.host / SESSIONS_DIR / "dev-20260830T180000Z-ffff0001"
        directory.mkdir(parents=True)
        snapshot_open_inventory(self.host, directory)
        write_yaml_atomic(
            directory / OPEN_INVENTORY_NAME,
            {
                "schema_version": "1",
                "record_type": "develop_open_inventory",
                "files": [
                    {"path": "src/app.py", "digest": "sha256:aa"},
                    {
                        "path": "node_modules/legacy/index.js",
                        "digest": "sha256:bb",
                    },
                ],
            },
        )
        loaded = load_open_inventory(directory)
        self.assertIn("src/app.py", loaded or {})
        self.assertNotIn("node_modules/legacy/index.js", loaded or {})

    def test_FND_C_04_product_files_stay_inventoried(self):
        from p7_support import write_active_host

        write_active_host(self.host)
        write(self.host, "src/app.py", "value = 1\n")
        write(self.host, "src/deep/module.py", "VALUE = 3\n")
        write(self.host, "docs/manual.md", "# manual\n")
        digests = execution_workspace_digests(self.host)
        self.assertIn("src/app.py", digests)
        self.assertIn("src/deep/module.py", digests)
        self.assertIn("docs/manual.md", digests)

    def test_FND_C_05_product_output_dirs_stay_inventoried(self):
        from p7_support import write_active_host

        write_active_host(self.host)
        kept = {
            "src/app.py": "value = 1\n",
            "tests/test_app.py": "def test_ok():\n    assert True\n",
            "tools/run.py": "print(1)\n",
            "artifacts/evidence/shot.png": "png",
            "dist/app.js": "bundle\n",
            "build/out.js": "build\n",
            "out/bar.txt": "out\n",
            "target/foo.txt": "rust\n",
            "vendor/lib.js": "vendor\n",
            "coverage/lcov.info": "TN:\n",
            "cache/data.bin": "cache\n",
            "src/node_modules_backup/keep.js": "keep\n",
            "mycache/data.txt": "mine\n",
            "vendor_src/lib.js": "vendored source\n",
        }
        for rel, body in kept.items():
            write(self.host, rel, body)
        write(self.host, "node_modules/pkg/index.js", "skip\n")
        write(self.host, "packages/ui/node_modules/left/index.js", "skip\n")
        write(self.host, "src/__pycache__/mod.cpython-313.pyc", "pyc")
        write(self.host, "loose.pyc", "pyc")
        write(self.host, "native.pyd", "pyd")
        digests = execution_workspace_digests(self.host)
        for rel in kept:
            self.assertIn(rel, digests, rel)
        self.assertIn("native.pyd", digests)
        self.assertNotIn("node_modules/pkg/index.js", digests)
        self.assertNotIn("packages/ui/node_modules/left/index.js", digests)
        self.assertNotIn("src/__pycache__/mod.cpython-313.pyc", digests)
        self.assertNotIn("loose.pyc", digests)
        write_task(self.host, TASK_A, status="IN_PROGRESS")
        from p7_support import ensure_noscms_accepted_anchor

        ensure_noscms_accepted_anchor(self.host)
        opened = develop_engine(self.host).open_develop_session(task_id=TASK_A)
        self.assertEqual(opened.outcome, "COMPLETED", opened.blockers)
        session_id = str((opened.extras or {}).get("session", {}).get("record_id") or "")
        directory = self.host / SESSIONS_DIR / session_id
        inventory = load_open_inventory(directory)
        self.assertEqual(inventory, digests)
        legacy = [{"path": rel, "digest": digest} for rel, digest in digests.items()]
        legacy.extend(
            [
                {"path": "node_modules/legacy/index.js", "digest": "sha256:bb"},
                {"path": "packages/ui/node_modules/left/index.js", "digest": "sha256:cc"},
                {"path": "src/__pycache__/mod.cpython-313.pyc", "digest": "sha256:dd"},
                {"path": "loose.pyc", "digest": "sha256:11"},
                {"path": "nested/mod.pyo", "digest": "sha256:22"},
                {"path": "pkg.egg-info/PKG-INFO", "digest": "sha256:33"},
                {"path": "dist/app.js", "digest": digests["dist/app.js"]},
                {"path": "vendor/lib.js", "digest": digests["vendor/lib.js"]},
            ]
        )
        write_yaml_atomic(
            directory / OPEN_INVENTORY_NAME,
            {
                "schema_version": "1",
                "record_type": "develop_open_inventory",
                "files": legacy,
            },
        )
        loaded = load_open_inventory(directory)
        self.assertIsNotNone(loaded)
        self.assertNotIn("node_modules/legacy/index.js", loaded)
        self.assertNotIn("packages/ui/node_modules/left/index.js", loaded)
        self.assertNotIn("src/__pycache__/mod.cpython-313.pyc", loaded)
        self.assertNotIn("loose.pyc", loaded)
        self.assertNotIn("nested/mod.pyo", loaded)
        self.assertNotIn("pkg.egg-info/PKG-INFO", loaded)
        self.assertIn("dist/app.js", loaded)
        self.assertIn("vendor/lib.js", loaded)
        self.assertIn("src/app.py", loaded)
        false_deletions = sorted(set(loaded) - set(execution_workspace_digests(self.host)))
        self.assertEqual(false_deletions, [])

    # ------------------------------------------------------------------
    # FND-D — TEST_COMPLETE authority guidance
    # ------------------------------------------------------------------

    def test_FND_D_01_unknown_authority_blocks_test_complete_with_guidance(self):
        from p6_support import write_tests
        from p8_support import rebind_noscms_baseline

        write_submit_host(self.host)
        # No top-level required_authority: the derived empty set is not
        # authoritative, so TEST_COMPLETE must stay false and the S5 stop
        # must carry authority guidance.
        write_tests(self.host, [], applicable=True, confidence="VERIFIED")
        rebind_noscms_baseline(self.host)
        result = run_submit(self.host, task_id=TASK_A, invoke_test=True)
        self.assertEqual(result.outcome, "BLOCKED")
        self.assertEqual(result.extras["stage"], "S5")
        completeness = result.extras["completeness"]
        self.assertFalse(completeness["test_complete"])
        guidance = list(completeness.get("authority_blockers") or [])
        self.assertTrue(guidance)
        joined = " ".join(guidance)
        self.assertIn("not authoritative", joined)
        self.assertIn("Understand Refresh", joined)
        self.assertIn("tests.yaml", joined)

    def test_FND_D_02_authoritative_zero_required_keeps_semantics(self):
        from p6_support import write_tests
        from p8_support import rebind_noscms_baseline

        write_submit_host(self.host)
        write_tests(
            self.host,
            [],
            applicable=True,
            confidence="VERIFIED",
            required_authority="VERIFIED",
        )
        rebind_noscms_baseline(self.host)
        result = run_submit(self.host, task_id=TASK_A, invoke_test=True)
        self.assertEqual(result.outcome, "COMPLETED", result.blockers)
        self.assertTrue(result.extras["test_complete"])

    def test_FND_D_03_unauthoritative_report_object_still_not_complete(self):
        from p6_support import write_tests
        from p7_support import write_active_host

        write_active_host(self.host)
        write_tests(self.host, [], applicable=True, confidence="VERIFIED")
        task = write_task(self.host, TASK_A)
        report = {
            "report_id": "tr-r8-fnd-d3",
            "completeness": {
                "test_pass": True,
                "test_complete": False,
                "required_set_authoritative": False,
                "required_policy": "UNKNOWN",
                "required_total": 0,
                "verified_no_required_tests": True,
                "required_fail": 0,
                "required_not_run": 0,
                "required_blocked": 0,
                "candidate_match": True,
            },
            "profiles": [],
        }
        judged = evaluate_completeness(
            self.host,
            task=task,
            report=report,
            invoke=False,
            selected=[],
            test_package=REPO_TEST,
        )
        self.assertFalse(judged["test_complete"])


def write_active_host_fresh(host: Path) -> None:
    from p7_support import write_active_host

    write_active_host(host)
    write(host, "src/app.py", "value = 1\n")


if __name__ == "__main__":
    unittest.main()

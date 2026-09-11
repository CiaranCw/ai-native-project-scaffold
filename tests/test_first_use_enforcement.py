from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import REPO
from test_consumer_installation import (
    EXPECTED_PACKAGES,
    _assert_raw_byte_round_trip,
    _clean_env,
    _clone_repo,
    _commit_host,
    _empty_host,
    _install,
    _manifest_bytes,
    _run_installed,
)

from scaffold_p5.consumer_install import (
    CURSOR_ADAPTERS,
    FIRST_USE_RULE_REL,
    GENERIC_CURSOR_ADAPTER,
    GITATTRIBUTES,
    HOOK_SCRIPT_REL,
    HOOKS_JSON_REL,
    OWNERSHIP_MANAGED_JSON_FRAGMENT,
    expected_hook_fragment_digest,
    first_use_decision,
    load_installed_distribution,
    manifest_file_map,
    manifest_fragment_records,
    plan_consumer_install,
    verify_consumer_install,
)
from scaffold_p5.engine import UnderstandEngine
from scaffold_p5.first_use import (
    DECISION_ALLOW,
    DECISION_BLOCK,
    FRAGMENT_ID,
    HOOK_COMMAND,
    HOOK_EVENTS,
    PRETOOL_APPLY_CONTINUE_REASON,
    REQUIRED_ROUTE_BOOTSTRAP,
    evaluate_cursor_hook,
    is_scaffold_hook_command,
    parse_always_apply_rule,
)
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import file_digest, sha256_bytes
from scaffold_p5.models import CORE_SKILLS
from scaffold_p5.packages import load_package
from scaffold_p5.result import result_dict
from scaffold_p5 import yaml_lite


PC_STYLE_GITATTRIBUTES = """* text=auto
*.md text eol=lf
*.json text eol=lf
*.yaml text eol=lf
*.yml text eol=lf
"""
BUSINESS_REQUEST = "implement the requested feature in the host business tree"
CHINESE_BUSINESS_REQUEST = (
    "按照 3C.md 帮我完善一下现在的 3C 功能，这次先把翻越做出来。"
)
AGENT_APPROVAL_TEXT = "I approve the Adoption"
CONSUMER_PILOT = Path(r"F:\NewResearch\Project-City-consumer-pilot")
CANONICAL_PROJECT_CITY = Path(r"F:\NewResearch\Project-City")


def _tree_bytes(host: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path in host.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        out[path.relative_to(host).as_posix()] = path.read_bytes()
    return out


def _hook_payload(host: Path, **fields: object) -> dict:
    payload = {
        "cwd": str(host),
        "workspace_roots": [str(host)],
    }
    payload.update(fields)
    return payload


def _run_hook(host: Path, payload: dict) -> dict:
    script = host / HOOK_SCRIPT_REL
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(host),
        env=_clean_env(),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if not proc.stdout.strip():
        raise AssertionError(proc.stdout + proc.stderr + f" code={proc.returncode}")
    return json.loads(proc.stdout)


def _apply_command(digest: str) -> str:
    return (
        "python .scaffold/install/run.py understand bootstrap "
        f"--approved --plan-digest {digest}"
    )


def _shell_pretool(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="preToolUse",
        tool_name="Shell",
        tool_input={"command": command},
    )


def _shell_before(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="beforeShellExecution",
        command=command,
        sandbox=False,
    )


def _bootstrap_plan_digest(host: Path) -> tuple[str, dict]:
    proc = _run_installed(host, "understand", "bootstrap")
    payload = json.loads(proc.stdout)
    digest = payload["extras"]["plan"]["digest"]
    return digest, payload


def _assert_ask(test: unittest.TestCase, result: dict) -> None:
    test.assertEqual(result["permission"], "ask", result)
    test.assertNotEqual(result["permission"], "allow")
    test.assertIn("agent_message", result)
    test.assertIn("user_message", result)
    message = result.get("agent_message") or ""
    test.assertIn("APPLY REQUEST", message)
    test.assertNotIn("needs_human", result)
    test.assertNotIn("approval_token", result)
    test.assertNotIn("approved_by_user", result)


def _simulate_rc2(host: Path) -> None:
    for rel in (FIRST_USE_RULE_REL, HOOK_SCRIPT_REL, HOOKS_JSON_REL):
        path = host / rel
        if path.is_file():
            path.unlink()
    manifest_path = host / ".scaffold" / "install" / "install.yaml"
    manifest = yaml_lite.load(manifest_path.read_text(encoding="utf-8"))
    skip = {FIRST_USE_RULE_REL, HOOK_SCRIPT_REL, HOOKS_JSON_REL}
    manifest["files"] = [
        row
        for row in (manifest.get("files") or [])
        if not (isinstance(row, dict) and str(row.get("path") or "").replace("\\", "/") in skip)
    ]
    manifest.pop("json_fragments", None)
    bridges = dict(manifest.get("bridges") or {})
    bridges.pop("cursor_first_use_rule", None)
    bridges.pop("cursor_hooks_fragment", None)
    bridges.pop("cursor_hook_command", None)
    manifest["bridges"] = bridges
    manifest_path.write_text(yaml_lite.dump(manifest), encoding="utf-8")


class FirstUseEnforcementTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def _fresh(self):
        plan, result = _install(self.host)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        return plan, result

    def test_FU01_fresh_installed_host_is_not_adopted(self):
        self._fresh()
        snap = snapshot_host(self.host)
        decision = first_use_decision(self.host)
        self.assertEqual(snap.host_class, "NOT_ADOPTED")
        self.assertEqual(decision["decision"], DECISION_BLOCK)
        self.assertEqual(decision["required_route"], REQUIRED_ROUTE_BOOTSTRAP)
        self.assertFalse(decision["project_mutation_allowed"])
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        self.assertFalse((self.host / ".scaffold" / "skills.lock").exists())

    def test_FU02_write_denied_before_execution(self):
        self._fresh()
        before = _tree_bytes(self.host)
        target = self.host / "src" / "feature.py"
        payload = _hook_payload(
            self.host,
            hook_event_name="preToolUse",
            tool_name="Write",
            tool_input={"path": str(target), "contents": "mutated\n"},
        )
        result = _run_hook(self.host, payload)
        self.assertEqual(result["permission"], "deny")
        self.assertFalse(target.exists())
        self.assertEqual(_tree_bytes(self.host), before)

    def test_FU03_delete_denied(self):
        self._fresh()
        readme = self.host / "README.md"
        before = readme.read_bytes()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": str(readme)},
            ),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertEqual(readme.read_bytes(), before)

    def test_FU04_arbitrary_mutating_shell_denied(self):
        self._fresh()
        before = _tree_bytes(self.host)
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Shell",
                tool_input={
                    "command": "python -c \"open('mutated.txt','w').write('nope')\""
                },
            ),
        )
        self.assertEqual(result["permission"], "deny")
        chained = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Shell",
                tool_input={
                    "command": "python .scaffold/install/run.py verify && python -c \"open('x','w').write('n')\""
                },
            ),
        )
        self.assertEqual(chained["permission"], "deny")
        self.assertFalse((self.host / "mutated.txt").exists())
        self.assertEqual(_tree_bytes(self.host), before)

    def test_FU05_task_subagent_denied(self):
        self._fresh()
        task = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Task",
                tool_input={"description": BUSINESS_REQUEST, "prompt": BUSINESS_REQUEST},
            ),
        )
        sub = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="subagentStart",
                subagent_type="generalPurpose",
                task=BUSINESS_REQUEST,
            ),
        )
        self.assertEqual(task["permission"], "deny")
        self.assertEqual(sub["permission"], "deny")

    def test_FU06_unknown_mcp_fail_closed(self):
        self._fresh()
        mcp = _run_hook(
            self.host,
            {
                "hook_event_name": "beforeMCPExecution",
                "tool_name": "write_file",
                "mcp_server_name": "unknown",
                "tool_input": "{}",
                "workspace_roots": [str(self.host)],
            },
        )
        prefixed = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MCP:external_write",
                tool_input={},
            ),
        )
        self.assertEqual(mcp["permission"], "deny", mcp)
        self.assertIn("NOT_ADOPTED", mcp.get("agent_message") or "")
        self.assertEqual(prefixed["permission"], "deny")
        in_process = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeMCPExecution",
                "tool_name": "write_file",
                "mcp_server_name": "linear",
                "tool_input": "{\"title\":\"x\"}",
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(in_process["permission"], "deny")
        self.assertIn("NOT_ADOPTED", in_process.get("agent_message") or "")

    def test_FU07_read_grep_inspection_allowed(self):
        self._fresh()
        for tool in ("Read", "Grep", "Glob"):
            result = _run_hook(
                self.host,
                _hook_payload(
                    self.host,
                    hook_event_name="preToolUse",
                    tool_name=tool,
                    tool_input={"path": "README.md", "pattern": "Sample"},
                ),
            )
            self.assertEqual(result["permission"], "allow", tool)

    def test_FU08_official_status_allowed(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Shell",
                tool_input={"command": "python .scaffold/install/run.py status"},
            ),
        )
        self.assertEqual(result["permission"], "allow")
        proc = _run_installed(self.host, "status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_FU09_official_verify_allowed(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Shell",
                tool_input={"command": "python .scaffold/install/run.py verify"},
            ),
        )
        self.assertEqual(result["permission"], "allow")
        proc = _run_installed(self.host, "verify")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_FU10_official_understand_bootstrap_allowed(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Shell",
                tool_input={
                    "command": "python .scaffold/install/run.py understand bootstrap"
                },
            ),
        )
        self.assertEqual(result["permission"], "allow")
        proc = _run_installed(self.host, "understand", "bootstrap")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)

    def test_FU11_bootstrap_needs_human_mutation_still_denied(self):
        self._fresh()
        proc = _run_installed(self.host, "understand", "bootstrap")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        denied = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={"path": "src/app.py", "contents": "x\n"},
            ),
        )
        self.assertEqual(denied["permission"], "deny")
        self.assertFalse((self.host / "src" / "app.py").exists())

    def test_FU12_ordinary_business_request_is_not_approval(self):
        self._fresh()
        dist = load_installed_distribution(self.host)
        result = UnderstandEngine(self.host, dist).run(
            "bootstrap",
            approval={"approved": True, "plan_digest": sha256_bytes(BUSINESS_REQUEST.encode("utf-8"))},
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result_dict(result))
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())

    def test_FU13_approved_adoption_command_is_not_unconditional_allow(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        command = _apply_command(digest)
        pre = _run_hook(self.host, _shell_pretool(self.host, command))
        before = _run_hook(self.host, _shell_before(self.host, command))
        self.assertEqual(pre["permission"], "allow", pre)
        self.assertEqual(pre.get("reason"), PRETOOL_APPLY_CONTINUE_REASON)
        _assert_ask(self, before)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_FU14_after_adoption_first_use_gate_inactive(self):
        self._fresh()
        dist = load_installed_distribution(self.host)
        engine = UnderstandEngine(self.host, dist)
        planned = engine.run("bootstrap")
        digest = planned.extras["plan"]["digest"]
        applied = engine.run(
            "bootstrap",
            approval={"approved": True, "plan_digest": digest},
        )
        self.assertEqual(applied.outcome, "COMPLETED", result_dict(applied))
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_ALLOW)
        self.assertTrue(decision["project_mutation_allowed"])
        write = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={"path": "notes.md", "contents": "ok\n"},
            ),
        )
        self.assertEqual(write["permission"], "allow")

    def test_FU15_denial_returns_required_route(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={"path": "x.py", "contents": "x\n"},
            ),
        )
        message = result.get("agent_message") or ""
        self.assertEqual(result["permission"], "deny")
        self.assertIn("NOT_ADOPTED", message)
        self.assertIn("understand bootstrap", message)
        self.assertIn("NEEDS_HUMAN", message)
        self.assertNotEqual(message.strip().lower(), "permission denied")

    def test_FU16_cannot_rewrite_hook_config_before_adoption(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={
                    "path": str(self.host / HOOKS_JSON_REL),
                    "contents": "{}\n",
                },
            ),
        )
        deleted = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Delete",
                tool_input={"path": str(self.host / HOOKS_JSON_REL)},
            ),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertEqual(deleted["permission"], "deny")
        self.assertTrue((self.host / HOOKS_JSON_REL).is_file())

    def test_FU17_cannot_rewrite_always_applied_rule_before_adoption(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={
                    "path": str(self.host / FIRST_USE_RULE_REL),
                    "contents": "---\nalwaysApply: false\n---\n",
                },
            ),
        )
        self.assertEqual(result["permission"], "deny")
        meta = parse_always_apply_rule(
            (self.host / FIRST_USE_RULE_REL).read_text(encoding="utf-8")
        )
        self.assertTrue(meta["alwaysApply"])

    def test_FU18_cannot_rewrite_agents_before_adoption(self):
        self._fresh()
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={"path": str(self.host / "AGENTS.md"), "contents": "nope\n"},
            ),
        )
        self.assertEqual(result["permission"], "deny")
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("mandatory authorization boundaries", text)

    def test_FU19_existing_unrelated_hooks_survive_install(self):
        cursor = self.host / ".cursor"
        cursor.mkdir()
        original = {
            "version": 1,
            "hooks": {
                "preToolUse": [{"command": "./human-audit.sh"}],
                "afterFileEdit": [{"command": "./format.sh"}],
            },
        }
        (cursor / "hooks.json").write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
        self._fresh()
        data = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        pre = data["hooks"]["preToolUse"]
        self.assertTrue(any(item.get("command") == "./human-audit.sh" for item in pre))
        self.assertTrue(any(is_scaffold_hook_command(item) for item in pre))
        self.assertEqual(data["hooks"]["afterFileEdit"], [{"command": "./format.sh"}])
        self.assertEqual(data["version"], 1)

    def test_FU20_unrelated_hooks_survive_update(self):
        self.test_FU19_existing_unrelated_hooks_survive_install()
        extra = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        extra["hooks"]["sessionStart"] = [{"command": "./human-session.sh"}]
        (self.host / HOOKS_JSON_REL).write_text(json.dumps(extra, indent=2) + "\n", encoding="utf-8")
        plan, result = _install(self.host, mode="update")
        self.assertEqual(result["outcome"], "COMPLETED", result)
        data = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        self.assertEqual(data["hooks"]["sessionStart"], [{"command": "./human-session.sh"}])
        self.assertTrue(
            any(item.get("command") == "./human-audit.sh" for item in data["hooks"]["preToolUse"])
        )

    def test_FU21_scaffold_hook_fragment_drift_detected(self):
        self._fresh()
        data = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        for item in data["hooks"]["preToolUse"]:
            if is_scaffold_hook_command(item):
                item["failClosed"] = False
                item["command"] = "python .scaffold/install/cursor_first_use_hook.py --changed"
        (self.host / HOOKS_JSON_REL).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        verify = verify_consumer_install(self.host)
        self.assertIn(verify["status"], {"DRIFTED", "INCOMPLETE"}, verify)
        self.assertTrue(
            HOOKS_JSON_REL in verify["drifted"] or HOOKS_JSON_REL in verify["missing"],
            verify,
        )
        if verify["status"] == "DRIFTED":
            plan = plan_consumer_install(self.host, REPO, mode="update")
            self.assertFalse(plan.allowed)

    def test_FU22_unrelated_hook_addition_is_not_scaffold_drift(self):
        self._fresh()
        data = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        data["hooks"]["preToolUse"].append({"command": "./later-human.sh"})
        (self.host / HOOKS_JSON_REL).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "VALID", verify)

    def test_FU23_exactly_four_skills_remain(self):
        self._fresh()
        self.assertEqual(tuple(CORE_SKILLS), ("understand", "develop", "test", "submit"))
        installed = sorted(
            path.name
            for path in (self.host / ".scaffold" / "install" / "packages").iterdir()
            if path.is_dir()
        )
        self.assertEqual(installed, ["develop", "submit", "test", "understand"])
        adapters = sorted(
            path.name
            for path in (self.host / ".cursor" / "skills").iterdir()
            if (path / "SKILL.md").is_file()
        )
        self.assertEqual(adapters, sorted(CURSOR_ADAPTERS))

    def test_FU24_no_generic_fifth_skill(self):
        self._fresh()
        self.assertFalse((self.host / GENERIC_CURSOR_ADAPTER).exists())
        self.assertFalse((self.host / ".cursor" / "skills" / "scaffold-first-use").exists())
        self.assertFalse((REPO / "skills" / "first-use").exists())
        self.assertTrue((self.host / FIRST_USE_RULE_REL).is_file())
        self.assertNotEqual(FIRST_USE_RULE_REL.endswith("SKILL.md"), True)

    def test_FU25_canonical_skill_identities_unchanged(self):
        self._fresh()
        for skill_id, (version, digest) in EXPECTED_PACKAGES.items():
            pkg = load_package(self.host / ".scaffold" / "install" / "packages" / skill_id)
            self.assertEqual(pkg.ref.skill_version, version, skill_id)
            self.assertEqual(pkg.ref.package_digest, digest, skill_id)
            live = load_package(REPO / "skills" / skill_id)
            self.assertEqual(live.ref.package_digest, digest, skill_id)

    def test_FU26_git_clone_preserves_managed_first_use_files(self):
        self._fresh()
        before = _manifest_bytes(self.host)
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "clone-fu26", "true")
        self.assertEqual(verify_consumer_install(clone)["status"], "VALID")
        _assert_raw_byte_round_trip(self, before, clone)
        self.assertEqual(
            file_digest(clone / FIRST_USE_RULE_REL),
            file_digest(self.host / FIRST_USE_RULE_REL),
        )
        self.assertEqual(
            file_digest(clone / HOOK_SCRIPT_REL),
            file_digest(self.host / HOOK_SCRIPT_REL),
        )

    def test_FU27_project_city_style_text_auto_does_not_break_new_files(self):
        (self.host / GITATTRIBUTES).write_text(PC_STYLE_GITATTRIBUTES, encoding="utf-8")
        self._fresh()
        before = _manifest_bytes(self.host)
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "clone-fu27", "true")
        self.assertEqual(verify_consumer_install(clone)["status"], "VALID")
        _assert_raw_byte_round_trip(self, before, clone)
        meta = parse_always_apply_rule(
            (clone / FIRST_USE_RULE_REL).read_text(encoding="utf-8")
        )
        self.assertTrue(meta["alwaysApply"])

    def test_FU28_install_remains_distinct_from_adoption(self):
        self._fresh()
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        self.assertFalse((self.host / ".scaffold" / "skills.lock").exists())

    def test_FU29_install_creates_no_task_change_develop_records(self):
        self._fresh()
        self.assertFalse((self.host / ".scaffold" / "tasks").exists())
        self.assertFalse((self.host / ".scaffold" / "changes").exists())
        self.assertFalse((self.host / ".scaffold" / "sessions").exists())

    def test_FU30_pc_consumer_001_direct_mutation_leaves_bytes_identical(self):
        self._fresh()
        before = _tree_bytes(self.host)
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={
                    "path": "src/game/vault.py",
                    "contents": BUSINESS_REQUEST,
                },
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny")
        self.assertIn("NOT_ADOPTED", result.get("agent_message") or "")
        self.assertEqual(_tree_bytes(self.host), before)
        self.assertFalse((self.host / "src" / "game" / "vault.py").exists())

    def test_FU_always_apply_metadata(self):
        self._fresh()
        text = (self.host / FIRST_USE_RULE_REL).read_text(encoding="utf-8")
        meta = parse_always_apply_rule(text)
        self.assertTrue(meta["alwaysApply"])
        self.assertTrue(meta["is_rule"])
        self.assertFalse(meta["is_skill"])
        self.assertIn("alwaysApply: true", text.split("---")[1])

    def test_FU_hook_contract_fields(self):
        self._fresh()
        data = json.loads((self.host / HOOKS_JSON_REL).read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        for event in HOOK_EVENTS:
            found = [item for item in data["hooks"][event] if is_scaffold_hook_command(item)]
            self.assertEqual(len(found), 1, event)
            self.assertEqual(found[0]["command"], HOOK_COMMAND)
            self.assertTrue(found[0]["failClosed"])
            self.assertEqual(found[0]["timeout"], 60)
            self.assertNotIn("matcher", found[0])
        manifest = yaml_lite.load(
            (self.host / ".scaffold" / "install" / "install.yaml").read_text(encoding="utf-8")
        )
        records = manifest_fragment_records(manifest)
        self.assertEqual(records[0]["ownership"], OWNERSHIP_MANAGED_JSON_FRAGMENT)
        self.assertEqual(records[0]["fragment_id"], FRAGMENT_ID)
        self.assertEqual(records[0]["digest"], expected_hook_fragment_digest())
        self.assertNotIn(HOOKS_JSON_REL, manifest_file_map(manifest))
        self.assertIn(FIRST_USE_RULE_REL, manifest_file_map(manifest))

    def test_FU_unknown_lifecycle_does_not_authorize_mutation(self):
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "tool_input": {"path": "x", "contents": "x"},
            },
            self.tmp / "missing-host",
        )
        self.assertEqual(result["permission"], "deny")

    def test_FU_rc2_update_adds_first_use_without_adopting(self):
        self._fresh()
        _simulate_rc2(self.host)
        verify = verify_consumer_install(self.host)
        self.assertEqual(verify["status"], "INCOMPLETE", verify)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        plan, result = _install(self.host, mode="update")
        self.assertTrue(plan.allowed, plan.blockers)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertEqual(verify_consumer_install(self.host)["status"], "VALID")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertTrue((self.host / FIRST_USE_RULE_REL).is_file())
        denied = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                tool_name="Write",
                tool_input={"path": "x.py", "contents": "x\n"},
            ),
        )
        self.assertEqual(denied["permission"], "deny")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())

    def test_FU_self_contained_clone_replay(self):
        self._fresh()
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "self-contained", "true")
        env = _clean_env()
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(clone / ".scaffold" / "install" / "run.py"), "verify"],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "VALID", payload)
        self.assertEqual(snapshot_host(clone).host_class, "NOT_ADOPTED")
        denied = evaluate_cursor_hook(
            _hook_payload(clone, tool_name="Write", tool_input={"path": "x", "contents": "x"}),
            clone,
        )
        self.assertEqual(denied["permission"], "deny")
        allowed = evaluate_cursor_hook(
            _hook_payload(
                clone,
                tool_name="Shell",
                tool_input={"command": "python .scaffold/install/run.py understand bootstrap"},
            ),
            clone,
        )
        self.assertEqual(allowed["permission"], "allow")
        self.assertNotIn("PYTHONPATH", env)
        self.assertFalse(str(REPO.resolve()) in (clone / ".scaffold" / "install" / "run.py").read_text(encoding="utf-8"))

    def test_FU_agents_anti_rationalization_language(self):
        self._fresh()
        text = (self.host / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("mandatory authorization boundaries", text)
        self.assertIn("not Adoption approval", text)
        self.assertIn("APPLY REQUEST", text)
        self.assertIn("beforeShellExecution", text)
        self.assertIn("I approve the Adoption", text)
        self.assertIn("Adoption appears cumbersome", text)
        self.assertIn("direct implementation appears faster", text)
        self.assertNotIn("Project-City", text)
        self.assertNotIn("Vault", text)
        self.assertNotIn("3C", text)
        self.assertNotIn("Agent2", text)

    def test_FU_human_approval_path_end_to_end(self):
        self._fresh()
        self.assertEqual(first_use_decision(self.host)["decision"], DECISION_BLOCK)
        dist = load_installed_distribution(self.host)
        engine = UnderstandEngine(self.host, dist)
        planned = engine.run("bootstrap")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN")
        digest = planned.extras["plan"]["digest"]
        still_denied = evaluate_cursor_hook(
            _hook_payload(self.host, tool_name="Write", tool_input={"path": "x", "contents": "x"}),
            self.host,
        )
        self.assertEqual(still_denied["permission"], "deny")
        command = _apply_command(digest)
        pre = evaluate_cursor_hook(_shell_pretool(self.host, command), self.host)
        before = evaluate_cursor_hook(_shell_before(self.host, command), self.host)
        self.assertEqual(pre["permission"], "allow", pre)
        self.assertEqual(pre.get("reason"), PRETOOL_APPLY_CONTINUE_REASON)
        _assert_ask(self, before)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        # Simulated Cursor user-acceptance continuation / human CLI outside Agent.
        # This is human_approved_execution, not the Agent apply request.
        proc = _run_installed(
            self.host,
            "understand",
            "bootstrap",
            "--approved",
            "--plan-digest",
            digest,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "COMPLETED", payload)
        self.assertEqual(first_use_decision(self.host)["decision"], DECISION_ALLOW)

    def test_FU31_bootstrap_returns_needs_human_and_digest(self):
        self._fresh()
        digest, payload = _bootstrap_plan_digest(self.host)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)
        self.assertEqual(len(digest), 64)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_FU32_agent_originated_apply_is_not_unconditional_allow(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        command = _apply_command(digest)
        agent_apply_request = _run_hook(self.host, _shell_before(self.host, command))
        self.assertNotEqual(agent_apply_request["permission"], "allow", agent_apply_request)
        _assert_ask(self, agent_apply_request)

    def test_FU33_before_shell_returns_ask_for_exact_digest_apply(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        command = _apply_command(digest)
        pre = _run_hook(self.host, _shell_pretool(self.host, command))
        before = _run_hook(self.host, _shell_before(self.host, command))
        self.assertEqual(pre["permission"], "allow", pre)
        self.assertIn("beforeShellExecution", pre.get("reason") or "")
        _assert_ask(self, before)
        self.assertEqual(before.get("reason"), "digest-bound Adoption apply requires Cursor beforeShellExecution ask")

    def test_FU34_without_user_approval_host_remains_not_adopted(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        after_preview = _tree_bytes(self.host)
        command = _apply_command(digest)
        asked = _run_hook(self.host, _shell_before(self.host, command))
        _assert_ask(self, asked)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())
        self.assertEqual(_tree_bytes(self.host), after_preview)

    def test_FU35_business_task_prompt_is_not_approval(self):
        self._fresh()
        dist = load_installed_distribution(self.host)
        planned = UnderstandEngine(self.host, dist).run("bootstrap")
        self.assertEqual(planned.outcome, "NEEDS_HUMAN")
        result = UnderstandEngine(self.host, dist).run(
            "bootstrap",
            approval={
                "approved": True,
                "plan_digest": sha256_bytes(CHINESE_BUSINESS_REQUEST.encode("utf-8")),
            },
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result_dict(result))
        write = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={"path": "src/game.py", "contents": CHINESE_BUSINESS_REQUEST},
            ),
        )
        self.assertEqual(write["permission"], "deny")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / "src" / "game.py").exists())

    def test_FU36_agent_generated_approval_text_is_not_approval(self):
        self._fresh()
        dist = load_installed_distribution(self.host)
        result = UnderstandEngine(self.host, dist).run(
            "bootstrap",
            approval={
                "approved": True,
                "plan_digest": sha256_bytes(AGENT_APPROVAL_TEXT.encode("utf-8")),
            },
        )
        self.assertEqual(result.outcome, "NEEDS_HUMAN", result_dict(result))
        echo = _run_hook(
            self.host,
            _shell_before(self.host, f'python -c "print({AGENT_APPROVAL_TEXT!r})"'),
        )
        self.assertEqual(echo["permission"], "deny")
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_FU37_stale_digest_does_not_complete_adoption(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        stale = "0" * 64
        self.assertNotEqual(stale, digest)
        asked = _run_hook(self.host, _shell_before(self.host, _apply_command(stale)))
        _assert_ask(self, asked)
        invalid = _run_hook(
            self.host,
            _shell_before(self.host, _apply_command("not-a-digest")),
        )
        self.assertEqual(invalid["permission"], "deny", invalid)
        proc = _run_installed(
            self.host,
            "understand",
            "bootstrap",
            "--approved",
            "--plan-digest",
            stale,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        self.assertFalse((self.host / ".scaffold" / "project.yaml").exists())

    def test_FU38_after_user_acceptance_exact_apply_completes(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        command = _apply_command(digest)
        agent_apply_request = _run_hook(self.host, _shell_before(self.host, command))
        _assert_ask(self, agent_apply_request)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        human_approved_execution = _run_installed(
            self.host,
            "understand",
            "bootstrap",
            "--approved",
            "--plan-digest",
            digest,
        )
        payload = json.loads(human_approved_execution.stdout)
        self.assertEqual(payload["outcome"], "COMPLETED", payload)
        self.assertNotEqual(agent_apply_request["permission"], "allow")

    def test_FU39_after_valid_apply_host_is_established(self):
        self._fresh()
        digest, _payload = _bootstrap_plan_digest(self.host)
        asked = _run_hook(self.host, _shell_before(self.host, _apply_command(digest)))
        _assert_ask(self, asked)
        proc = _run_installed(
            self.host,
            "understand",
            "bootstrap",
            "--approved",
            "--plan-digest",
            digest,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "COMPLETED", payload)
        self.assertEqual(snapshot_host(self.host).host_class, "ESTABLISHED_HOST")
        decision = first_use_decision(self.host)
        self.assertEqual(decision["decision"], DECISION_ALLOW)
        self.assertFalse(decision["first_use_gate_active"])

    def test_FU40_direct_write_remains_denied_before_approval(self):
        self._fresh()
        _bootstrap_plan_digest(self.host)
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={"path": "src/app.py", "contents": "x\n"},
            ),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertFalse((self.host / "src" / "app.py").exists())

    def test_FU41_arbitrary_shell_remains_denied_before_approval(self):
        self._fresh()
        _bootstrap_plan_digest(self.host)
        result = _run_hook(
            self.host,
            _shell_before(self.host, "python -c \"open('mutated.txt','w').write('nope')\""),
        )
        self.assertEqual(result["permission"], "deny")
        self.assertFalse((self.host / "mutated.txt").exists())

    def test_FU42_task_subagent_remains_denied(self):
        self._fresh()
        _bootstrap_plan_digest(self.host)
        task = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Task",
                tool_input={"description": BUSINESS_REQUEST, "prompt": BUSINESS_REQUEST},
            ),
        )
        sub = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="subagentStart",
                subagent_type="generalPurpose",
                task=BUSINESS_REQUEST,
            ),
        )
        self.assertEqual(task["permission"], "deny")
        self.assertEqual(sub["permission"], "deny")

    def test_FU43_mcp_b1_real_payload_fail_closed_without_crash(self):
        self._fresh()
        mcp = _run_hook(
            self.host,
            {
                "hook_event_name": "beforeMCPExecution",
                "tool_name": "write_file",
                "mcp_server_name": "unknown",
                "tool_input": "{}",
                "workspace_roots": [str(self.host)],
            },
        )
        self.assertEqual(mcp["permission"], "deny", mcp)
        self.assertIn("NOT_ADOPTED", mcp.get("agent_message") or "")
        self.assertNotIn("Traceback", mcp.get("agent_message") or "")

    def test_FU44_hook_rule_agents_rewrite_remains_denied(self):
        self._fresh()
        for rel in (HOOKS_JSON_REL, FIRST_USE_RULE_REL, "AGENTS.md", HOOK_SCRIPT_REL):
            result = _run_hook(
                self.host,
                _hook_payload(
                    self.host,
                    hook_event_name="preToolUse",
                    tool_name="Write",
                    tool_input={"path": str(self.host / rel), "contents": "bypass\n"},
                ),
            )
            self.assertEqual(result["permission"], "deny", rel)
            self.assertNotEqual((self.host / rel).read_text(encoding="utf-8"), "bypass\n")

    def test_FU45_exact_four_skills_unchanged(self):
        self.test_FU23_exactly_four_skills_remain()
        self.test_FU25_canonical_skill_identities_unchanged()

    def test_FU46_rc2_update_remains_safe(self):
        self.test_FU_rc2_update_adds_first_use_without_adopting()
        digest, _payload = _bootstrap_plan_digest(self.host)
        asked = _run_hook(self.host, _shell_before(self.host, _apply_command(digest)))
        _assert_ask(self, asked)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_FU47_clone_only_host_retains_ask_behavior(self):
        self._fresh()
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "clone-fu47", "true")
        digest, payload = _bootstrap_plan_digest(clone)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN")
        asked = _run_hook(clone, _shell_before(clone, _apply_command(digest)))
        _assert_ask(self, asked)
        self.assertEqual(snapshot_host(clone).host_class, "NOT_ADOPTED")

    def test_FU48_no_distribution_pythonpath_dependency(self):
        self._fresh()
        _commit_host(self.host, "true")
        clone = _clone_repo(self.host, self.tmp / "clone-fu48", "true")
        env = _clean_env()
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, str(clone / ".scaffold" / "install" / "run.py"), "understand", "bootstrap"],
            cwd=str(clone),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)
        digest = payload["extras"]["plan"]["digest"]
        asked = evaluate_cursor_hook(_shell_before(clone, _apply_command(digest)), clone)
        _assert_ask(self, asked)
        self.assertNotIn("PYTHONPATH", env)
        self.assertFalse(
            str(REPO.resolve())
            in (clone / ".scaffold" / "install" / "run.py").read_text(encoding="utf-8")
        )

    def test_FU_forensic_and_canonical_project_city_untouched(self):
        if CANONICAL_PROJECT_CITY.is_dir():
            self.assertFalse(CANONICAL_PROJECT_CITY.joinpath(".scaffold", "install").exists())
        if not CONSUMER_PILOT.is_dir():
            return
        agents_path = CONSUMER_PILOT / "AGENTS.md"
        before = agents_path.read_bytes() if agents_path.is_file() else None
        plan_consumer_install(CONSUMER_PILOT, REPO, mode="install")
        if before is not None:
            self.assertEqual(agents_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

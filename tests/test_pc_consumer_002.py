from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from test_consumer_installation import _install, _run_installed
from test_first_use_enforcement import (
    _apply_command,
    _assert_ask,
    _empty_host,
    _hook_payload,
    _run_hook,
    _shell_before,
    _shell_pretool,
)

from scaffold_p5.first_use import (
    evaluate_cursor_hook,
    hook_main,
)
from scaffold_p5.host_state import snapshot_host
from scaffold_p5.models import CORE_SKILLS


STATUS_CMD = "python .scaffold/install/run.py status"
BOOTSTRAP_CMD = "python .scaffold/install/run.py understand bootstrap"
WIN_STATUS_CMD = r"python .scaffold\install\run.py status"
WIN_BOOTSTRAP_CMD = r"python .scaffold\install\run.py understand bootstrap"


class PcConsumer002Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = _empty_host(self.tmp)
        (self.host / "docs" / "design").mkdir(parents=True)
        (self.host / "docs" / "design" / "3C.md").write_text(
            "# 3C\n", encoding="utf-8"
        )
        plan, result = _install(self.host)
        self.assertEqual(result["outcome"], "COMPLETED", result)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def tearDown(self):
        self._tmp.cleanup()

    def test_PC002_01_read_ordinary_project_file_allowed(self):
        documented = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Read",
                tool_input={"path": str(self.host / "docs" / "design" / "3C.md")},
            ),
        )
        realistic = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeReadFile",
                "file_path": str(self.host / "docs" / "design" / "3C.md"),
                "content": "# 3C\n",
                "workspace_roots": [str(self.host)],
            }
        )
        aliased = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="ReadFile",
                tool_input={"target_file": "docs/design/3C.md"},
            )
        )
        nameless = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_input={"path": "docs/design/3C.md"},
            )
        )
        for result, label in (
            (documented, "Read"),
            (realistic, "beforeReadFile"),
            (aliased, "ReadFile"),
        ):
            self.assertEqual(result["permission"], "allow", (label, result))
        self.assertEqual(nameless["permission"], "deny", nameless)

    def test_PC002_02_read_scaffold_skill_adapter_allowed(self):
        path = self.host / ".cursor" / "skills" / "scaffold-understand" / "SKILL.md"
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Read",
                "tool_input": {"path": str(path)},
                "workspace_roots": [str(self.host)],
            }
        )
        develop = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeReadFile",
                "file_path": str(
                    self.host / ".cursor" / "skills" / "scaffold-develop" / "SKILL.md"
                ),
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(result["permission"], "allow", result)
        self.assertEqual(develop["permission"], "allow", develop)
        self.assertTrue(path.is_file())

    def test_PC002_03_status_command_allowed_to_execute(self):
        shapes = [
            _shell_pretool(self.host, STATUS_CMD),
            _shell_before(self.host, STATUS_CMD),
            _shell_before(self.host, WIN_STATUS_CMD),
            _hook_payload(
                self.host,
                hook_event_name="beforeShellExecution",
                command=f"cmd.exe /c {STATUS_CMD}",
                sandbox=False,
            ),
        ]
        for payload in shapes:
            result = evaluate_cursor_hook(payload, self.host)
            self.assertEqual(result["permission"], "allow", (payload, result))
        bom = self._hook_main_bytes(
            _shell_before(self.host, STATUS_CMD), bom=True
        )
        self.assertEqual(bom["permission"], "allow", bom)
        proc = _run_installed(self.host, "status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["project"]["host_class"], "NOT_ADOPTED", payload)

    def test_PC002_04_plain_bootstrap_executes_needs_human(self):
        pre = evaluate_cursor_hook(_shell_pretool(self.host, BOOTSTRAP_CMD), self.host)
        before = evaluate_cursor_hook(_shell_before(self.host, WIN_BOOTSTRAP_CMD), self.host)
        self.assertEqual(pre["permission"], "allow", pre)
        self.assertEqual(before["permission"], "allow", before)
        proc = _run_installed(self.host, "understand", "bootstrap")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)
        digest = payload["extras"]["plan"]["digest"]
        self.assertEqual(len(digest), 64)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_PC002_05_exact_apply_before_shell_ask(self):
        proc = _run_installed(self.host, "understand", "bootstrap")
        digest = json.loads(proc.stdout)["extras"]["plan"]["digest"]
        command = _apply_command(digest)
        pre = evaluate_cursor_hook(_shell_pretool(self.host, command), self.host)
        before = evaluate_cursor_hook(_shell_before(self.host, command), self.host)
        self.assertEqual(pre["permission"], "allow", pre)
        _assert_ask(self, before)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_PC002_06_write_denied(self):
        result = _run_hook(
            self.host,
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={"path": "src/app.py", "contents": "x\n"},
            ),
        )
        self.assertEqual(result["permission"], "deny", result)
        self.assertFalse((self.host / "src" / "app.py").exists())

    def test_PC002_07_arbitrary_mutating_shell_denied(self):
        result = evaluate_cursor_hook(
            _shell_before(self.host, "python -c print(1)"),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_PC002_08_unknown_mutating_mcp_denied(self):
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeMCPExecution",
                "tool_name": "write_file",
                "mcp_server_name": "unknown",
                "tool_input": "{}",
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_PC002_fresh_host_replay(self):
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        read = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeReadFile",
                "file_path": str(self.host / "docs" / "design" / "3C.md"),
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(read["permission"], "allow", read)
        deleted = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": str(self.host / "docs" / "design" / "3C.md")},
            ),
            self.host,
        )
        self.assertEqual(deleted["permission"], "deny", deleted)
        unknown = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MysteryTool",
                tool_input={"path": str(self.host / "docs" / "design" / "3C.md")},
            ),
            self.host,
        )
        self.assertEqual(unknown["permission"], "deny", unknown)
        status_hook = evaluate_cursor_hook(_shell_before(self.host, WIN_STATUS_CMD), self.host)
        self.assertEqual(status_hook["permission"], "allow", status_hook)
        status = _run_installed(self.host, "status")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        bootstrap_hook = evaluate_cursor_hook(
            _shell_before(self.host, BOOTSTRAP_CMD), self.host
        )
        self.assertEqual(bootstrap_hook["permission"], "allow", bootstrap_hook)
        bootstrap = json.loads(_run_installed(self.host, "understand", "bootstrap").stdout)
        self.assertEqual(bootstrap["outcome"], "NEEDS_HUMAN", bootstrap)
        digest = bootstrap["extras"]["plan"]["digest"]
        asked = evaluate_cursor_hook(
            _shell_before(self.host, _apply_command(digest)), self.host
        )
        _assert_ask(self, asked)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")
        write = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Write",
                tool_input={"path": "mutated.py", "contents": "x\n"},
            ),
            self.host,
        )
        self.assertEqual(write["permission"], "deny", write)
        self.assertEqual(tuple(CORE_SKILLS), ("understand", "develop", "test", "submit"))

    def test_B1_01_delete_path_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": "docs/design/3C.md"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_02_deletefile_target_file_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="DeleteFile",
                tool_input={"target_file": "docs/design/3C.md"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_03_write_top_level_file_path_denied(self):
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "preToolUse",
                "tool_name": "Write",
                "file_path": str(self.host / "docs" / "design" / "3C.md"),
                "workspace_roots": [str(self.host)],
            },
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_04_editnotebook_path_only_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="EditNotebook",
                tool_input={"path": "notes.ipynb"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_05_unknown_path_only_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MysteryTool",
                tool_input={"path": "docs/design/3C.md"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_06_unknown_path_and_content_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="MysteryTool",
                tool_input={"path": "src/app.py", "content": "x\n"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_07_bom_prefixed_delete_path_only_denied(self):
        result = self._hook_main_bytes(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": "docs/design/3C.md"},
            ),
            bom=True,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B1_08_before_read_file_allowed(self):
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeReadFile",
                "file_path": str(self.host / "docs" / "design" / "3C.md"),
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_B1_09_readfile_alias_allowed(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="ReadFile",
                tool_input={"path": "docs/design/3C.md"},
            )
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_B1_10_status_allowed_and_executes(self):
        hook = evaluate_cursor_hook(_shell_before(self.host, STATUS_CMD), self.host)
        self.assertEqual(hook["permission"], "allow", hook)
        proc = _run_installed(self.host, "status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_B1_11_plain_bootstrap_needs_human(self):
        hook = evaluate_cursor_hook(_shell_before(self.host, BOOTSTRAP_CMD), self.host)
        self.assertEqual(hook["permission"], "allow", hook)
        payload = json.loads(_run_installed(self.host, "understand", "bootstrap").stdout)
        self.assertEqual(payload["outcome"], "NEEDS_HUMAN", payload)
        self.assertEqual(len(payload["extras"]["plan"]["digest"]), 64)

    def test_B1_12_digest_bound_apply_ask(self):
        digest = json.loads(_run_installed(self.host, "understand", "bootstrap").stdout)[
            "extras"
        ]["plan"]["digest"]
        before = evaluate_cursor_hook(
            _shell_before(self.host, _apply_command(digest)), self.host
        )
        _assert_ask(self, before)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_B2_01_nameless_file_path_denied(self):
        result = evaluate_cursor_hook(
            {"file_path": "docs/design/3C.md"},
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B2_02_explicit_before_read_file_allowed(self):
        result = evaluate_cursor_hook(
            {
                "hook_event_name": "beforeReadFile",
                "file_path": "docs/design/3C.md",
                "workspace_roots": [str(self.host)],
            }
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_B2_03_readfile_alias_allowed(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="ReadFile",
                tool_input={"target_file": "docs/design/3C.md"},
            )
        )
        self.assertEqual(result["permission"], "allow", result)

    def test_B2_04_delete_path_only_denied(self):
        result = evaluate_cursor_hook(
            _hook_payload(
                self.host,
                hook_event_name="preToolUse",
                tool_name="Delete",
                tool_input={"path": "docs/design/3C.md"},
            ),
            self.host,
        )
        self.assertEqual(result["permission"], "deny", result)

    def test_B2_05_digest_bound_apply_ask(self):
        digest = "0" * 64
        before = evaluate_cursor_hook(
            _shell_before(self.host, _apply_command(digest)), self.host
        )
        _assert_ask(self, before)
        self.assertEqual(snapshot_host(self.host).host_class, "NOT_ADOPTED")

    def test_B2_bootstrap_hook_still_allow(self):
        result = evaluate_cursor_hook(
            _shell_before(self.host, BOOTSTRAP_CMD), self.host
        )
        self.assertEqual(result["permission"], "allow", result)

    def _hook_main_bytes(self, payload: dict, *, bom: bool) -> dict:
        raw = json.dumps(payload).encode("utf-8")
        if bom:
            raw = b"\xef\xbb\xbf" + raw
        stdout = io.StringIO()
        code = hook_main(stdin=io.BytesIO(raw), stdout=stdout)
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

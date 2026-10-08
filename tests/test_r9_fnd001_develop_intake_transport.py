"""R9-FND-001: pre-session Develop Intake file transport."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from p6_support import CORE_OWNERSHIP
from p7_support import ensure_noscms_accepted_anchor, write_active_host
from support import REPO, write
from test_first_use_enforcement import _hook_payload

from scaffold_p5.client_support import is_protected_mutation_target
from scaffold_p5.io_util import write_yaml_atomic
from scaffold_p5.consumer_install import RUNNER_TEXT, SRC_MODULES, SRC_PACKAGES, installed_main
from scaffold_p5.first_use import (
    HOOK_SCRIPT_REL,
    HOOK_SCRIPT_TEXT,
    SHELL_ALLOW,
    SHELL_DENY,
    classify_first_use_shell,
)
from scaffold_p7.intake import INTAKE_STAGING_REL, load_intake_envelope_flags
from scaffold_p7.models import SESSIONS_DIR
from scaffold_p7.mutation import hard_mutation_boundary_reason


REALISTIC_REQUEST = (
    "Add the customer's email check (RFC-like) when the value is $email "
    "and the tag is <user>. Don't drop O'Brien."
)
PROPOSAL = {
    "title": "Implement fixture source",
    "goal": "Change src/app.py under Task authority.",
    "acceptance": "src/app.py contains the expected line.",
    "scope": {
        "paths": ["src/app.py"],
        "modules": [],
        "exclude": [],
    },
    "stages": [
        {
            "stage_id": "stage-1",
            "goal": "Write the fixture source.",
            "acceptance": "src/app.py has the expected content.",
            "required_tests": [],
        }
    ],
    "final_tests": [],
}
FILE_COMMAND = (
    "python .scaffold/install/run.py enter develop --intake-json-file "
    + INTAKE_STAGING_REL
)


def _envelope(request: str = REALISTIC_REQUEST) -> dict:
    return {
        "structured_intent": {
            "kind": "develop",
            "action": "implement",
            "request": request,
            "explicit_implementation": True,
            "authorized_proposal": PROPOSAL,
        },
        "proposal": PROPOSAL,
        "grounding": {
            "intent_fields": ["goal", "scope", "acceptance", "stages", "tests"],
            "knowledge_fields": ["scope", "rules", "ownership", "tests"],
            "uncertainties": [],
            "material_decisions": [],
        },
    }


def _b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _vendor_installed_surface(host: Path) -> None:
    install = host / ".scaffold" / "install"
    runtime = install / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    src = REPO / "src"
    for package in SRC_PACKAGES:
        shutil.copytree(
            src / package,
            runtime / package,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    for name in SRC_MODULES:
        shutil.copy2(src / name, runtime / name)
    for skill_id in ("understand", "develop", "test", "submit"):
        shutil.copytree(
            REPO / "skills" / skill_id,
            install / "packages" / skill_id,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    (install / "run.py").write_text(RUNNER_TEXT, encoding="utf-8", newline="\n")
    (install / "cursor_first_use_hook.py").write_text(
        HOOK_SCRIPT_TEXT, encoding="utf-8", newline="\n"
    )
    marker = install / "install.yaml"
    if not marker.is_file():
        marker.write_text("product: scaffold\n", encoding="utf-8")


def _run_hook(host: Path, payload: dict) -> dict:
    script = host / HOOK_SCRIPT_REL
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(host),
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if not proc.stdout.strip():
        raise AssertionError(proc.stderr + f" code={proc.returncode}")
    return json.loads(proc.stdout)


def _run_py(host: Path, *args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(host / ".scaffold" / "install" / "run.py"), *args],
        cwd=str(host),
        capture_output=True,
        text=True,
        timeout=180,
    )
    text = proc.stdout.strip()
    if not text:
        raise AssertionError(proc.stderr + f" code={proc.returncode}")
    return proc.returncode, json.loads(text)


def _write_payload(host: Path, rel: str, tool_name: str = "Write") -> dict:
    return _hook_payload(
        host,
        hook_event_name="preToolUse",
        tool_name=tool_name,
        tool_input={"path": rel, "contents": "{}\n"},
    )


def _shell_payload(host: Path, command: str) -> dict:
    return _hook_payload(
        host,
        hook_event_name="beforeShellExecution",
        command=command,
    )


class R9Fnd001TransportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.host = self.tmp / "host"
        self.host.mkdir()
        write_active_host(
            self.host,
            ownership={**CORE_OWNERSHIP, "src/": "HUMAN_OWNED"},
            source_areas=["src"],
        )
        write(self.host, "src/app.py", "value = 0\n")
        write(self.host, "tests/test_app.py", "def test_ok():\n    assert True\n")
        write(self.host, "tools/gen.py", "print('tool')\n")
        write_yaml_atomic(
            self.host / ".scaffold" / "tests.yaml",
            {"schema_version": "1", "profiles": []},
        )
        write_yaml_atomic(
            self.host / ".scaffold" / "commands.yaml",
            {"schema_version": "1", "commands": []},
        )
        ensure_noscms_accepted_anchor(self.host)
        _vendor_installed_surface(self.host)

    def tearDown(self):
        self._tmp.cleanup()

    def _stage(self, payload: dict | str) -> Path:
        path = self.host / INTAKE_STAGING_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def _tasks(self) -> list[Path]:
        root = self.host / ".scaffold" / "tasks"
        if not root.is_dir():
            return []
        return list(root.glob("task-*.yaml"))

    def test_bootstrap_write_boundary_and_file_intake(self):
        product = _run_hook(self.host, _write_payload(self.host, "src/app.py"))
        tests = _run_hook(self.host, _write_payload(self.host, "tests/test_app.py"))
        tools = _run_hook(self.host, _write_payload(self.host, "tools/gen.py"))
        agents = _run_hook(self.host, _write_payload(self.host, "AGENTS.md"))
        cursor = _run_hook(
            self.host,
            _write_payload(self.host, ".cursor/rules/scaffold-first-use.mdc"),
        )
        governance = _run_hook(
            self.host,
            _write_payload(self.host, ".scaffold/project.yaml"),
        )
        arbitrary = _run_hook(self.host, _write_payload(self.host, "tmp/intake.json"))
        outside = _run_hook(
            self.host,
            _write_payload(self.host, str(self.tmp / "outside.json")),
        )
        for denied in (
            product,
            tests,
            tools,
            agents,
            cursor,
            governance,
            arbitrary,
            outside,
        ):
            self.assertEqual(denied["permission"], "deny", denied)
        self.assertIn("develop-intake.json", product.get("agent_message") or "")

        staged = _run_hook(self.host, _write_payload(self.host, INTAKE_STAGING_REL))
        edited = _run_hook(
            self.host,
            _write_payload(self.host, INTAKE_STAGING_REL, tool_name="StrReplace"),
        )
        absolute = _run_hook(
            self.host,
            _write_payload(self.host, str(self.host / INTAKE_STAGING_REL)),
        )
        removed = _run_hook(
            self.host,
            _write_payload(self.host, INTAKE_STAGING_REL, tool_name="Delete"),
        )
        self.assertEqual(staged["permission"], "allow", staged)
        self.assertIn("not Develop product authority", staged.get("reason") or "")
        self.assertEqual(edited["permission"], "allow", edited)
        self.assertEqual(absolute["permission"], "allow", absolute)
        self.assertEqual(removed["permission"], "deny", removed)

        shell = _run_hook(self.host, _shell_payload(self.host, FILE_COMMAND))
        self.assertEqual(shell["permission"], "allow", shell)
        chained = _run_hook(
            self.host,
            _shell_payload(self.host, FILE_COMMAND + "; Remove-Item src"),
        )
        self.assertEqual(chained["permission"], "deny", chained)
        self.assertIn("metacharacter", chained.get("reason") or "")

        text = json.dumps(_envelope(), indent=2)
        path = self._stage(text)
        self.assertIn("O'Brien", path.read_text(encoding="utf-8"))
        self.assertIn("$email", path.read_text(encoding="utf-8"))
        self.assertIn("<user>", path.read_text(encoding="utf-8"))
        self.assertFalse(self._tasks())
        self.assertFalse((self.host / SESSIONS_DIR).exists())

        code, payload = _run_py(
            self.host,
            "enter",
            "develop",
            "--intake-json-file",
            INTAKE_STAGING_REL,
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        task = (payload.get("extras") or {}).get("task") or {}
        self.assertTrue(task.get("record_id"))
        self.assertEqual(task.get("status"), "IN_PROGRESS")
        self.assertFalse((payload.get("extras") or {}).get("session"))
        self.assertFalse((self.host / SESSIONS_DIR).exists())
        self.assertEqual(len(self._tasks()), 1)
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        parsed, error = load_intake_envelope_flags(text, None)
        self.assertIsNone(error)
        self.assertEqual(parsed["structured_intent"]["request"], REALISTIC_REQUEST)
        still_blocked = _run_hook(self.host, _write_payload(self.host, "src/app.py"))
        self.assertEqual(still_blocked["permission"], "deny", still_blocked)

    def test_develop_intake_file_command_and_session_then_product_write(self):
        self._stage(_envelope())
        code, payload = _run_py(
            self.host,
            "develop",
            "intake",
            "--intake-json-file",
            INTAKE_STAGING_REL,
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        task_id = (payload.get("extras") or {})["task"]["record_id"]
        self.assertFalse((self.host / INTAKE_STAGING_REL).exists())
        opened_code, opened = _run_py(
            self.host, "develop", "session", "--task-id", task_id
        )
        self.assertEqual(opened_code, 0, opened)
        self.assertEqual(opened.get("outcome"), "COMPLETED", opened)
        product = _run_hook(self.host, _write_payload(self.host, "src/app.py"))
        governance = _run_hook(
            self.host, _write_payload(self.host, ".scaffold/project.yaml")
        )
        staging = _run_hook(self.host, _write_payload(self.host, INTAKE_STAGING_REL))
        self.assertEqual(product["permission"], "allow", product)
        self.assertEqual(governance["permission"], "deny", governance)
        self.assertEqual(staging["permission"], "deny", staging)

    def test_safety_boundaries_reject_noncanonical_paths(self):
        self._stage(_envelope())
        outside = self.tmp / "outside.json"
        outside.write_text(json.dumps(_envelope()), encoding="utf-8")
        cases = [
            str(outside),
            "../outside.json",
            "tmp/intake.json",
            ".scaffold/project.yaml",
            "src/app.py",
            ".scaffold/transport/../project.yaml",
        ]
        for argument in cases:
            kind, detail = classify_first_use_shell(
                "python .scaffold/install/run.py enter develop --intake-json-file "
                + argument,
                self.host,
                adopted=True,
            )
            self.assertEqual(kind, SHELL_DENY, (argument, detail))
            code, payload = _run_py(
                self.host,
                "enter",
                "develop",
                "--intake-json-file",
                argument,
            )
            self.assertEqual(code, 1, payload)
            self.assertEqual(payload.get("outcome"), "BLOCKED", payload)
            self.assertFalse(self._tasks())
            self.assertTrue((self.host / INTAKE_STAGING_REL).is_file())

    def test_symlink_staging_path_is_rejected(self):
        outside_dir = self.tmp / "outside"
        outside_dir.mkdir()
        outside = outside_dir / "develop-intake.json"
        outside.write_text(json.dumps(_envelope()), encoding="utf-8")
        transport = self.host / ".scaffold" / "transport"
        linked = False
        staging = self.host / INTAKE_STAGING_REL
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            staging.symlink_to(outside)
            linked = staging.is_symlink()
        except OSError:
            if transport.exists():
                shutil.rmtree(transport)
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(transport), str(outside_dir)],
                capture_output=True,
                text=True,
            )
            linked = proc.returncode == 0 and transport.is_junction()
        self.assertTrue(linked, "could not create a symlink or directory junction")
        code, payload = _run_py(
            self.host,
            "enter",
            "develop",
            "--intake-json-file",
            INTAKE_STAGING_REL,
        )
        self.assertEqual(code, 1, payload)
        self.assertIn("symlink", " ".join(payload.get("blockers") or []))
        self.assertFalse(self._tasks())
        self.assertTrue(outside.is_file())

    def test_invalid_envelopes_fail_closed_and_keep_the_file(self):
        samples = [
            "{",
            "[]",
            json.dumps(
                {
                    "structured_intent": "implement",
                    "proposal": {},
                    "grounding": {},
                }
            ),
        ]
        for sample in samples:
            path = self._stage(sample)
            code, payload = _run_py(
                self.host,
                "enter",
                "develop",
                "--intake-json-file",
                INTAKE_STAGING_REL,
            )
            self.assertEqual(code, 1, payload)
            self.assertNotEqual(payload.get("outcome"), "COMPLETED", payload)
            self.assertFalse(self._tasks())
            self.assertFalse((self.host / SESSIONS_DIR).exists())
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), sample)
        denied = _run_hook(self.host, _write_payload(self.host, "src/app.py"))
        self.assertEqual(denied["permission"], "deny", denied)

    def test_existing_transports_stay_compatible(self):
        literal = _run_hook(
            self.host,
            _shell_payload(
                self.host,
                "python .scaffold/install/run.py enter develop --intake-json-b64 "
                + _b64(_envelope()),
            ),
        )
        self.assertEqual(literal["permission"], "allow", literal)
        code, payload = _run_py(
            self.host,
            "enter",
            "develop",
            "--intake-json-b64",
            _b64(_envelope("Implement the fixture source change now.")),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload.get("outcome"), "COMPLETED", payload)
        self.assertEqual(len(self._tasks()), 1)
        self.assertFalse((self.host / SESSIONS_DIR).exists())

        self._stage(_envelope())
        inline = classify_first_use_shell(
            "python .scaffold/install/run.py enter develop --intake-json "
            + """'{"structured_intent":{"kind":"develop"},"proposal":{},"grounding":{}}'""",
            self.host,
            adopted=True,
        )
        self.assertEqual(inline[0], SHELL_ALLOW, inline)
        parenthetical = classify_first_use_shell(
            "python .scaffold/install/run.py enter develop --intake-json "
            + """'{"note":"(ok)"}'""",
            self.host,
            adopted=True,
        )
        self.assertEqual(parenthetical[0], SHELL_ALLOW, parenthetical)
        code, payload = _run_py(
            self.host,
            "enter",
            "develop",
            "--intake-json",
            INTAKE_STAGING_REL,
        )
        self.assertEqual(code, 1, payload)
        self.assertIn("not parseable", " ".join(payload.get("blockers") or []))
        self.assertEqual(len(self._tasks()), 1)
        self.assertTrue((self.host / INTAKE_STAGING_REL).is_file())

    def test_staging_file_is_not_authority(self):
        payload = _envelope()
        payload["TEST_PASS"] = True
        payload["TEST_COMPLETE"] = True
        payload["session"] = {"status": "OPEN"}
        self._stage(payload)
        self.assertTrue(is_protected_mutation_target(self.host, INTAKE_STAGING_REL))
        boundary = hard_mutation_boundary_reason(self.host, INTAKE_STAGING_REL)
        self.assertIn("protected Scaffold governance", boundary or "")
        self.assertFalse(self._tasks())
        self.assertFalse((self.host / SESSIONS_DIR).exists())
        project = (self.host / ".scaffold" / "project.yaml").read_text(encoding="utf-8")
        self.assertIn("HUMAN_OWNED", project)
        denied = _run_hook(self.host, _write_payload(self.host, "src/app.py"))
        self.assertEqual(denied["permission"], "deny", denied)
        kind, detail = classify_first_use_shell(
            "python .scaffold/install/run.py develop session --task-id task-none",
            self.host,
            adopted=True,
        )
        self.assertEqual(kind, SHELL_ALLOW, detail)
        self.assertNotEqual(detail, "pre-session Develop intake transport write")

    def test_backslashes_normalize_and_metacharacters_do_not(self):
        windows_path = INTAKE_STAGING_REL.replace("/", "\\")
        kind, detail = classify_first_use_shell(
            "python .scaffold/install/run.py develop intake --intake-json-file "
            + windows_path,
            self.host,
            adopted=True,
        )
        self.assertEqual(kind, SHELL_ALLOW, detail)
        expression = classify_first_use_shell(
            "python .scaffold/install/run.py enter develop --intake-json-file "
            "$(Get-Content envelope.json)",
            self.host,
            adopted=True,
        )
        self.assertEqual(expression[0], SHELL_DENY, expression)
        self.assertIn("metacharacter", expression[1])
        both = classify_first_use_shell(
            "python .scaffold/install/run.py enter develop --intake-json-file "
            + INTAKE_STAGING_REL
            + " --intake-json-b64 e30",
            self.host,
            adopted=True,
        )
        self.assertEqual(both[0], SHELL_DENY, both)


class R9Fnd001DirectRunnerTests(unittest.TestCase):
    def test_installed_main_file_flag_on_the_wrong_command_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = Path(tmp) / "host"
            host.mkdir()
            install = host / ".scaffold" / "install"
            install.mkdir(parents=True)
            (install / "install.yaml").write_text("product: scaffold\n", encoding="utf-8")
            code_buf = []

            from io import StringIO
            from contextlib import redirect_stdout

            buf = StringIO()
            with redirect_stdout(buf):
                code = installed_main(
                    install,
                    ["status", "--intake-json-file", INTAKE_STAGING_REL],
                )
            code_buf.append(code)
            payload = json.loads(buf.getvalue())
            self.assertEqual(code_buf[0], 1)
            self.assertIn("only valid", " ".join(payload.get("blockers") or []))

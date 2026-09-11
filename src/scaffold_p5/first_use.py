"""Client-neutral first-use mutation authority and Cursor hook adapter.

Not a Skill. Host lifecycle remains `snapshot_host` / classify_host.
Cursor-specific allow/deny/ask translation lives here as an adapter, not as
canonical Skill meaning. `--approved` is an APPLY REQUEST, not human
provenance; Agent-originated apply is authorized only by Cursor
beforeShellExecution permission=ask.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import snapshot_host
from scaffold_p5.io_util import sha256_bytes


DECISION_BLOCK = "BLOCK_PROJECT_MUTATION"
DECISION_ALLOW = "ALLOW_PROJECT_MUTATION"
REQUIRED_ROUTE_BOOTSTRAP = "understand.bootstrap"
FRAGMENT_ID = "scaffold-first-use"
HOOKS_JSON_REL = ".cursor/hooks.json"
FIRST_USE_RULE_REL = ".cursor/rules/scaffold-first-use.mdc"
HOOK_SCRIPT_REL = ".scaffold/install/cursor_first_use_hook.py"
HOOK_COMMAND = "python .scaffold/install/cursor_first_use_hook.py"
RUNNER_REL = ".scaffold/install/run.py"
HOOK_SCHEMA_VERSION = 1
HOOK_TIMEOUT_SECONDS = 60
HOOK_EVENTS = (
    "preToolUse",
    "beforeShellExecution",
    "subagentStart",
    "beforeMCPExecution",
)
OWNERSHIP_MANAGED_JSON_FRAGMENT = "MANAGED_JSON_FRAGMENT"

READ_ONLY_TOOLS = frozenset(
    {
        "Read",
        "Grep",
        "Glob",
        "SemanticSearch",
        "codebase_search",
        "WebSearch",
        "WebFetch",
        "ReadLints",
        "AskQuestion",
        "SwitchMode",
        "list_dir",
        "ListDir",
        "TabRead",
        "ReadFile",
    }
)
READ_EVENTS = frozenset({"beforeReadFile", "beforeTabFileRead"})
SHELL_EVENTS = frozenset({"beforeShellExecution"})
TOOL_ALIASES = {
    "read": "Read",
    "readfile": "Read",
    "tabread": "Read",
    "grep": "Grep",
    "glob": "Glob",
    "semanticsearch": "SemanticSearch",
    "codebasesearch": "codebase_search",
    "websearch": "WebSearch",
    "webfetch": "WebFetch",
    "readlints": "ReadLints",
    "listdir": "ListDir",
    "shell": "Shell",
    "bash": "Shell",
    "terminal": "Shell",
    "write": "Write",
    "writefile": "Write",
    "delete": "Delete",
    "deletefile": "Delete",
    "strreplace": "StrReplace",
    "applypatch": "ApplyPatch",
    "edit": "Edit",
    "editfile": "EditFile",
    "editnotebook": "EditNotebook",
    "notebookedit": "NotebookEdit",
    "task": "Task",
    "callmcptool": "CallMcpTool",
    "fetchmcpresource": "FetchMcpResource",
}
CMD_NAMES = frozenset({"cmd", "cmd.exe"})
MUTATION_EVENTS = frozenset({"afterFileEdit", "afterTabFileEdit"})
MUTATION_TOOLS = frozenset(
    {
        "Write",
        "Delete",
        "StrReplace",
        "ApplyPatch",
        "EditNotebook",
        "DeleteFile",
        "WriteFile",
        "EditFile",
        "Task",
        "CallMcpTool",
        "FetchMcpResource",
        "GenerateImage",
        "Edit",
        "NotebookEdit",
    }
)
PYTHON_NAMES = frozenset({"python", "python.exe", "python3", "python3.exe"})
PLAN_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
SHELL_METACHAR_RE = re.compile(r"""[;&|`$<>\n\r()]|&&|\|\|""")
ALLOWED_RUN_ARGV = {
    (): "verify",
    ("verify",): "verify",
    ("status",): "status",
    ("first-use",): "first-use",
    ("enter",): "enter",
    ("enter", "status"): "enter",
    ("understand",): "understand.bootstrap",
    ("understand", "bootstrap"): "understand.bootstrap",
}

SHELL_ALLOW = "allow"
SHELL_DENY = "deny"
SHELL_ASK_APPLY = "ask_apply"
BOOTSTRAP_ARGV = frozenset({("understand",), ("understand", "bootstrap")})

AGENT_DENY_MESSAGE = (
    "Project mutation is blocked because this host is NOT_ADOPTED. "
    "Run the Scaffold Understand bootstrap route: "
    "`python .scaffold/install/run.py understand bootstrap`. "
    "If bootstrap returns NEEDS_HUMAN, stop and request explicit human "
    "approval of that exact Adoption Plan digest. "
    "Do not implement the business task before Adoption completes. "
    "The user business request is not Adoption approval."
)
ASK_AGENT_MESSAGE = (
    "This command is an Adoption APPLY REQUEST, not human authorization. "
    "`--approved --plan-digest` is only the apply-request spelling. "
    "It is not proof that a human approved Adoption. "
    "STOP. Cursor must obtain interactive user confirmation via "
    "beforeShellExecution permission=ask before this command may execute. "
    "The Agent cannot satisfy that confirmation with ordinary tool calls. "
    "The user business request is not Adoption approval. "
    "Agent-generated approval text is not Adoption approval. "
    "Do not retry this command as self-approval, and do not implement "
    "the business task while waiting."
)
ASK_USER_MESSAGE = (
    "Scaffold Adoption apply requires your confirmation. "
    "The Agent requested `understand bootstrap --approved --plan-digest`. "
    "That flag is an apply request, not proof you approved. "
    "Allow this command only if you intend to adopt this project now."
)
PRETOOL_APPLY_CONTINUE_REASON = (
    "digest-bound Adoption apply request continues to beforeShellExecution; "
    "not execution authorization"
)
ASK_APPLY_REASON = (
    "digest-bound Adoption apply requires Cursor beforeShellExecution ask"
)
UNKNOWN_DENY_MESSAGE = (
    "Project mutation is blocked because Scaffold first-use lifecycle state "
    "could not be determined. Run `python .scaffold/install/run.py status` "
    "and `python .scaffold/install/run.py understand bootstrap`. "
    "UNKNOWN lifecycle state does not authorize ordinary project mutation."
)
USER_DENY_MESSAGE = (
    "Scaffold first-use gate blocked a project mutation on a host that is "
    "not yet adopted."
)

FIRST_USE_RULE_TEXT = """---
description: Scaffold first-use authorization boundary. Always apply.
alwaysApply: true
---

# Scaffold first-use gate

This is a Cursor client rule, not a fifth Skill. Scaffold lifecycle
authority remains `python .scaffold/install/run.py status`.

If the host is NOT_ADOPTED, ordinary project mutation is not authorized.

Required route: `python .scaffold/install/run.py understand bootstrap`.

NEEDS_HUMAN means STOP. Tell the user that Adoption requires approval.
Do not implement the user task while waiting.

`--approved --plan-digest` is an APPLY REQUEST, not proof of human
approval. On Cursor, Agent-originated apply is authorized only by the
interactive confirmation from beforeShellExecution permission=ask.
The Agent cannot satisfy that confirmation with ordinary tool calls.

The ordinary user task is not Adoption approval. Agent-generated text
such as "I approve the Adoption" has no authority.

Do not bypass this gate because Adoption appears cumbersome, the task
looks simple or non-structural, or direct implementation appears faster.
"""

HOOK_SCRIPT_TEXT = '''#!/usr/bin/env python3
"""Cursor first-use pre-tool adapter. Not a Skill."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
INSTALL_ROOT = Path(__file__).resolve().parent
RUNTIME = INSTALL_ROOT / "runtime"
sys.path.insert(0, str(RUNTIME))

_DENY = {
    "permission": "deny",
    "agent_message": (
        "Project mutation is blocked because this host is NOT_ADOPTED. "
        "Run the Scaffold Understand bootstrap route: "
        "`python .scaffold/install/run.py understand bootstrap`. "
        "If bootstrap returns NEEDS_HUMAN, stop and request explicit human "
        "approval of that exact Adoption Plan digest. "
        "Do not implement the business task before Adoption completes. "
        "The user business request is not Adoption approval."
    ),
    "user_message": (
        "Scaffold first-use gate blocked a project mutation on a host that "
        "is not yet adopted."
    ),
}

try:
    from scaffold_p5.first_use import hook_main
except Exception:
    sys.stdout.write(json.dumps(_DENY, ensure_ascii=True))
    sys.stdout.write("\\n")
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(hook_main())
'''


def scaffold_hook_entry() -> dict[str, Any]:
    return {
        "command": HOOK_COMMAND,
        "failClosed": True,
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def canonical_hook_fragment() -> dict[str, Any]:
    entry = scaffold_hook_entry()
    return {
        "schema": "scaffold-managed-json-fragment/v1",
        "fragment_id": FRAGMENT_ID,
        "path": HOOKS_JSON_REL,
        "events": {event: [entry] for event in HOOK_EVENTS},
    }


def expected_hook_fragment_digest() -> str:
    payload = json.dumps(
        canonical_hook_fragment(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256_bytes(payload.encode("utf-8"))


def is_scaffold_hook_command(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    command = str(item.get("command") or "").strip().replace("\\", "/")
    return HOOK_COMMAND == command or command.endswith(
        "/.scaffold/install/cursor_first_use_hook.py"
    ) or "cursor_first_use_hook.py" in command


def first_use_decision(host: str | Path) -> dict[str, Any]:
    """Authoritative first-use mutation decision from existing host state."""
    try:
        snapshot = snapshot_host(host)
        host_class = str(snapshot.host_class or "")
        known = True
        reason = "existing Scaffold lifecycle authority"
    except Exception as exc:
        snapshot = None
        host_class = "UNKNOWN"
        known = False
        reason = f"lifecycle snapshot failed: {type(exc).__name__}"
    if not known or not host_class:
        return _block_decision(
            host_class="UNKNOWN",
            known=False,
            reason=reason,
            message=UNKNOWN_DENY_MESSAGE,
        )
    if host_class == "NOT_ADOPTED":
        return _block_decision(
            host_class=host_class,
            known=True,
            reason=reason,
            message=AGENT_DENY_MESSAGE,
            required_route=REQUIRED_ROUTE_BOOTSTRAP,
            snapshot=snapshot,
        )
    return {
        "decision": DECISION_ALLOW,
        "host_class": host_class,
        "required_route": None,
        "project_mutation_allowed": True,
        "lifecycle_known": True,
        "first_use_gate_active": False,
        "reason": reason,
        "agent_message": None,
        "preflight_context": getattr(snapshot, "preflight_context", None),
    }


def evaluate_cursor_hook(
    payload: dict[str, Any] | None,
    host: str | Path | None = None,
) -> dict[str, Any]:
    """Translate first-use authority into a Cursor hook permission object."""
    data = payload if isinstance(payload, dict) else {}
    event = _hook_event(data)
    tool_name = _tool_name(data, event)
    if not _is_mutation_operation(event, tool_name, data) and _is_read_only_action(
        event, tool_name, data
    ):
        return _allow("read-only first-use inspection")
    host_root = resolve_hook_host(data, host)
    if host_root is None:
        return _deny(UNKNOWN_DENY_MESSAGE, reason="host root could not be resolved")
    authority = first_use_decision(host_root)
    if authority.get("project_mutation_allowed"):
        return _allow("first-use NOT_ADOPTED gate is not active")
    if event in {"subagentStart"} or tool_name == "Task":
        return _deny(
            authority.get("agent_message") or AGENT_DENY_MESSAGE,
            reason="subagent/Task bypass is not authorized before Adoption",
        )
    if _is_mcp_action(event, tool_name, data):
        return _deny(
            authority.get("agent_message") or AGENT_DENY_MESSAGE,
            reason="unknown MCP/external tool is fail-closed before Adoption",
        )
    if _is_shell_action(event, tool_name, data):
        command = _shell_command(data)
        kind, detail = classify_first_use_shell(command, host_root)
        if kind == SHELL_ASK_APPLY:
            if authority.get("host_class") != "NOT_ADOPTED":
                return _deny(
                    authority.get("agent_message") or UNKNOWN_DENY_MESSAGE,
                    reason=detail,
                )
            if event == "beforeShellExecution":
                return _ask(reason=detail)
            return _allow(PRETOOL_APPLY_CONTINUE_REASON)
        if kind == SHELL_ALLOW:
            return _allow(detail)
        return _deny(
            authority.get("agent_message") or AGENT_DENY_MESSAGE,
            reason=detail,
        )
    return _deny(
        authority.get("agent_message") or AGENT_DENY_MESSAGE,
        reason=f"{tool_name or event or 'tool'} is not authorized before Adoption",
    )


def classify_first_use_shell(
    command: str | None,
    host: str | Path,
) -> tuple[str, str]:
    """Classify a Shell command while NOT_ADOPTED.

    Preview/status/verify remain allow. The digest-bound Adoption apply
    request is not execution authorization; it is an APPLY REQUEST that
    must reach beforeShellExecution permission=ask.
    """
    raw = str(command or "").strip()
    if raw.startswith("& "):
        raw = raw[2:].strip()
    if not raw:
        return SHELL_DENY, "empty shell command is not a first-use lifecycle command"
    if SHELL_METACHAR_RE.search(raw):
        return SHELL_DENY, "shell metacharacters are not allowed before Adoption"
    argv = _split_shell_argv(raw)
    if argv is None:
        return SHELL_DENY, "shell command could not be parsed exactly"
    argv = _unwrap_cmd_prefix(argv)
    if len(argv) < 2:
        return SHELL_DENY, "shell command is not an official Scaffold launcher invocation"
    if not _is_python_token(argv[0]):
        return SHELL_DENY, "shell interpreter is not the official python launcher"
    runner = _official_runner_path(argv[1], host)
    if runner is None:
        return SHELL_DENY, "shell command is not python .scaffold/install/run.py"
    rest = argv[2:]
    positional, flags, flag_error = _split_runner_flags(rest)
    if flag_error:
        return SHELL_DENY, flag_error
    host_flag = flags.get("host")
    if host_flag is not None and not _same_host(host_flag, host):
        return SHELL_DENY, "shell --host does not resolve to this project"
    if positional not in ALLOWED_RUN_ARGV:
        return SHELL_DENY, "shell command is not a first-use Scaffold lifecycle command"
    if flags.get("approved") and positional not in BOOTSTRAP_ARGV:
        return SHELL_DENY, "approval flags are only valid on Understand bootstrap"
    if flags.get("plan_digest") and not flags.get("approved"):
        return SHELL_DENY, "plan digest without --approved is not an official apply command"
    if flags.get("approved") and flags.get("plan_digest"):
        return SHELL_ASK_APPLY, ASK_APPLY_REASON
    return SHELL_ALLOW, "official first-use Scaffold lifecycle command"


def first_use_shell_allowed(
    command: str | None,
    host: str | Path,
) -> tuple[bool, str]:
    kind, detail = classify_first_use_shell(command, host)
    return kind == SHELL_ALLOW, detail


def resolve_hook_host(
    payload: dict[str, Any],
    explicit: str | Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(Path(explicit))
    cwd = payload.get("cwd")
    tool_input = _tool_input_object(payload)
    if not cwd:
        cwd = tool_input.get("working_directory")
    if cwd:
        candidates.append(Path(str(cwd)))
    for root in payload.get("workspace_roots") or []:
        if root:
            candidates.append(Path(str(root)))
    file_path = payload.get("file_path") or tool_input.get("file_path") or tool_input.get(
        "path"
    ) or tool_input.get("target_file")
    if file_path:
        candidates.append(Path(str(file_path)))
    seen: set[Path] = set()
    for start in candidates:
        try:
            resolved = start.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        found = _find_install_root(resolved)
        if found is not None:
            return found
    return None


def decode_hook_stdin(stdin) -> str:
    """Decode Cursor hook stdin. Windows may prefix UTF-8 JSON with a BOM."""
    buffer = getattr(stdin, "buffer", None)
    raw: bytes | str
    if buffer is not None:
        try:
            raw = buffer.read()
        except (OSError, ValueError, AttributeError):
            raw = stdin.read() if hasattr(stdin, "read") else ""
    elif hasattr(stdin, "read"):
        raw = stdin.read()
    else:
        raw = ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8-sig")
    text = str(raw or "")
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def hook_main(
    argv: list[str] | None = None,
    stdin=None,
    stdout=None,
) -> int:
    del argv
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        raw = decode_hook_stdin(stdin)
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not an object")
        result = evaluate_cursor_hook(payload)
        _write_hook_result(stdout, result)
        return 0
    except (json.JSONDecodeError, ValueError, TypeError, OSError, AttributeError, KeyError):
        result = _deny(UNKNOWN_DENY_MESSAGE, reason="invalid or unusable hook input")
        _write_hook_result(stdout, result)
        return 2
    except Exception:
        result = _deny(UNKNOWN_DENY_MESSAGE, reason="hook adapter failure")
        _write_hook_result(stdout, result)
        return 2


def merge_scaffold_hooks(existing: Any | None) -> dict[str, Any]:
    """Insert or replace only Scaffold-owned hook entries."""
    if existing is None:
        data: dict[str, Any] = {"version": HOOK_SCHEMA_VERSION, "hooks": {}}
    elif isinstance(existing, dict):
        data = json.loads(json.dumps(existing))
    else:
        raise ValueError("hooks.json root is not an object")
    version = data.get("version", HOOK_SCHEMA_VERSION)
    if version != HOOK_SCHEMA_VERSION:
        raise ValueError("hooks.json schema version is incompatible")
    data["version"] = HOOK_SCHEMA_VERSION
    hooks = data.get("hooks")
    if hooks is None:
        hooks = {}
        data["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("hooks.json hooks field is not an object")
    entry = scaffold_hook_entry()
    for event in HOOK_EVENTS:
        current = hooks.get(event)
        if current is None:
            hooks[event] = [dict(entry)]
            continue
        if not isinstance(current, list):
            raise ValueError(f"hooks.json {event} is not a list")
        kept: list[Any] = []
        inserted = False
        for item in current:
            if is_scaffold_hook_command(item):
                if not inserted:
                    kept.append(dict(entry))
                    inserted = True
                continue
            kept.append(item)
        if not inserted:
            kept.insert(0, dict(entry))
        hooks[event] = kept
    return data


def dumps_hooks_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=True) + "\n"


def inspect_scaffold_hook_fragment(
    data: Any,
) -> tuple[dict[str, Any] | None, list[str], list[str], list[str]]:
    """Return (fragment, missing, drifted, incompatible) for mixed-ownership hooks."""
    missing: list[str] = []
    drifted: list[str] = []
    incompat: list[str] = []
    if not isinstance(data, dict):
        incompat.append(".cursor/hooks.json is not a JSON object")
        return None, missing, drifted, incompat
    if data.get("version") != HOOK_SCHEMA_VERSION:
        incompat.append(".cursor/hooks.json schema version is incompatible")
        return None, missing, drifted, incompat
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        incompat.append(".cursor/hooks.json hooks field is malformed")
        return None, missing, drifted, incompat
    expected_entry = scaffold_hook_entry()
    events: dict[str, list[dict[str, Any]]] = {}
    for event in HOOK_EVENTS:
        arr = hooks.get(event)
        if arr is None:
            missing.append(HOOKS_JSON_REL)
            continue
        if not isinstance(arr, list):
            incompat.append(f".cursor/hooks.json {event} is malformed")
            continue
        found = [item for item in arr if is_scaffold_hook_command(item)]
        if not found:
            missing.append(HOOKS_JSON_REL)
            continue
        if len(found) > 1:
            missing.append(HOOKS_JSON_REL)
            continue
        item = found[0]
        if not isinstance(item, dict) or not _hook_entry_matches(item, expected_entry):
            drifted.append(HOOKS_JSON_REL)
            continue
        events[event] = [expected_entry]
    if missing or drifted or incompat:
        return None, sorted(set(missing)), sorted(set(drifted)), incompat
    fragment = {
        "schema": "scaffold-managed-json-fragment/v1",
        "fragment_id": FRAGMENT_ID,
        "path": HOOKS_JSON_REL,
        "events": events,
    }
    return fragment, [], [], []


def parse_always_apply_rule(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {"alwaysApply": False, "is_rule": False, "is_skill": False}
    end = text.find("\n---", 3)
    if end < 0:
        return {"alwaysApply": False, "is_rule": True, "is_skill": False}
    front = text[3:end]
    always = False
    for raw in front.splitlines():
        line = raw.strip()
        if line.startswith("alwaysApply:"):
            value = line.split(":", 1)[1].strip().lower()
            always = value in {"true", "yes"}
    return {
        "alwaysApply": always,
        "is_rule": True,
        "is_skill": False,
        "path": FIRST_USE_RULE_REL,
    }


def _block_decision(
    *,
    host_class: str,
    known: bool,
    reason: str,
    message: str,
    required_route: str | None = REQUIRED_ROUTE_BOOTSTRAP,
    snapshot: Any = None,
) -> dict[str, Any]:
    return {
        "decision": DECISION_BLOCK,
        "host_class": host_class,
        "required_route": required_route,
        "project_mutation_allowed": False,
        "lifecycle_known": known,
        "first_use_gate_active": True,
        "reason": reason,
        "agent_message": message,
        "preflight_context": getattr(snapshot, "preflight_context", None),
    }


def _allow(reason: str) -> dict[str, Any]:
    return {"permission": "allow", "reason": reason}


def _ask(*, reason: str) -> dict[str, Any]:
    return {
        "permission": "ask",
        "agent_message": ASK_AGENT_MESSAGE,
        "user_message": ASK_USER_MESSAGE,
        "reason": reason,
    }


def _deny(agent_message: str, *, reason: str) -> dict[str, Any]:
    return {
        "permission": "deny",
        "agent_message": agent_message,
        "user_message": USER_DENY_MESSAGE,
        "reason": reason,
    }


def _write_hook_result(stdout, result: dict[str, Any]) -> None:
    stdout.write(json.dumps(result, ensure_ascii=True))
    stdout.write("\n")


def _hook_event(payload: dict[str, Any]) -> str:
    name = str(payload.get("hook_event_name") or "").strip()
    if name:
        return name
    if payload.get("subagent_type") and "tool_name" not in payload:
        return "subagentStart"
    if payload.get("mcp_server_name") is not None:
        return "beforeMCPExecution"
    if "tool_name" in payload or "tool" in payload:
        return "preToolUse"
    if "command" in payload:
        return "beforeShellExecution"
    return "unknown"


def _canonical_tool_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    if raw.lower().startswith("mcp:"):
        rest = raw.split(":", 1)[1].strip()
        return "MCP:" + (rest or "unknown")
    compact = raw.replace("_", "").replace("-", "").replace(" ", "").lower()
    return TOOL_ALIASES.get(compact, raw)


def _tool_name(payload: dict[str, Any], event: str) -> str:
    if event == "subagentStart":
        return "Task"
    name = _canonical_tool_name(
        str(payload.get("tool_name") or payload.get("tool") or "").strip()
    )
    if name:
        return name
    if event in SHELL_EVENTS:
        return "Shell"
    if event == "beforeMCPExecution":
        return "MCP:" + str(payload.get("tool_name") or "unknown")
    if event in READ_EVENTS:
        return "Read"
    return ""


def _is_mcp_action(event: str, tool_name: str, payload: dict[str, Any]) -> bool:
    if event == "beforeMCPExecution":
        return True
    if tool_name.startswith("MCP:"):
        return True
    if tool_name in {"CallMcpTool", "FetchMcpResource"}:
        return True
    if payload.get("mcp_server_name"):
        return True
    return False


def _is_mutation_operation(event: str, tool_name: str, payload: dict[str, Any]) -> bool:
    if event in READ_EVENTS:
        return False
    if event in MUTATION_EVENTS or event == "subagentStart":
        return True
    if _is_mcp_action(event, tool_name, payload):
        return True
    if tool_name in MUTATION_TOOLS or tool_name == "Task":
        return True
    return False


def _is_read_only_action(event: str, tool_name: str, payload: dict[str, Any]) -> bool:
    if _is_mutation_operation(event, tool_name, payload):
        return False
    if event in {"subagentStart", "beforeMCPExecution"}:
        return False
    if _is_mcp_action(event, tool_name, payload):
        return False
    if _is_shell_action(event, tool_name, payload):
        return False
    if event in READ_EVENTS:
        return True
    if tool_name in READ_ONLY_TOOLS:
        return True
    return False


def _is_shell_action(event: str, tool_name: str, payload: dict[str, Any]) -> bool:
    if _is_mcp_action(event, tool_name, payload):
        return False
    if event in SHELL_EVENTS or tool_name == "Shell":
        return True
    return bool(_shell_command(payload))


def _tool_input_object(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _shell_command(payload: dict[str, Any]) -> str:
    tool_input = _tool_input_object(payload)
    if tool_input.get("command") is not None:
        return str(tool_input.get("command") or "")
    if payload.get("command") is not None and payload.get("mcp_server_name") is None:
        return str(payload.get("command") or "")
    return ""


def _split_shell_argv(raw: str) -> list[str] | None:
    posix = "\\" not in raw
    try:
        argv = shlex.split(raw, posix=posix)
    except ValueError:
        if posix:
            try:
                argv = shlex.split(raw, posix=False)
            except ValueError:
                return None
        else:
            return None
    return argv


def _unwrap_cmd_prefix(argv: list[str]) -> list[str]:
    if len(argv) >= 3 and Path(argv[0]).name.lower() in CMD_NAMES:
        if argv[1].lower() in {"/c", "/k"}:
            return argv[2:]
    return argv


def _is_python_token(token: str) -> bool:
    name = Path(str(token)).name.lower()
    if name in PYTHON_NAMES:
        return True
    try:
        return Path(token).name.lower() == Path(sys.executable).name.lower()
    except (OSError, TypeError):
        return False


def _official_runner_path(token: str, host: str | Path) -> Path | None:
    host_root = Path(host)
    expected = (host_root / RUNNER_REL).resolve()
    raw = str(token).replace("\\", "/")
    candidates = [Path(token)]
    if not Path(token).is_absolute():
        candidates.append(host_root / raw)
        candidates.append(Path.cwd() / raw)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved == expected and resolved.is_file():
            return resolved
    normalized = raw.lstrip("./")
    if normalized == RUNNER_REL and expected.is_file():
        return expected
    return None


def _split_runner_flags(
    rest: list[str],
) -> tuple[tuple[str, ...], dict[str, Any], str | None]:
    positional: list[str] = []
    flags: dict[str, Any] = {}
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--approved":
            flags["approved"] = True
            i += 1
            continue
        if token == "--plan-digest":
            if i + 1 >= len(rest):
                return tuple(), flags, "--plan-digest requires a 64-character hex digest"
            digest = rest[i + 1]
            if not PLAN_DIGEST_RE.fullmatch(digest):
                return tuple(), flags, "plan digest is not an exact 64-character hex digest"
            flags["plan_digest"] = digest.lower()
            i += 2
            continue
        if token == "--host":
            if i + 1 >= len(rest):
                return tuple(), flags, "--host requires a path"
            flags["host"] = rest[i + 1]
            i += 2
            continue
        if token.startswith("-"):
            return tuple(), flags, f"unsupported launcher flag {token}"
        positional.append(token)
        i += 1
    return tuple(positional), flags, None


def _same_host(path: str, host: str | Path) -> bool:
    try:
        left = Path(path).resolve()
        right = Path(host).resolve()
    except OSError:
        return False
    return left == right


def _find_install_root(start: Path) -> Path | None:
    current = start
    if current.is_file():
        current = current.parent
    for _ in range(8):
        marker = current / ".scaffold" / "install" / "install.yaml"
        if marker.is_file():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _hook_entry_matches(item: dict[str, Any], expected: dict[str, Any]) -> bool:
    extra = set(item) - set(expected)
    if extra:
        return False
    return (
        str(item.get("command") or "").strip().replace("\\", "/") == expected["command"]
        and item.get("failClosed") is True
        and int(item.get("timeout") or 0) == expected["timeout"]
        and "matcher" not in item
    )

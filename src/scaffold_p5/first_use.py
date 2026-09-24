"""Client-neutral first-use mutation authority and Cursor hook adapter.

Not a Skill. Host lifecycle remains `snapshot_host` / classify_host.
Cursor-specific allow/deny/ask translation lives here as an adapter, not as
canonical Skill meaning. `--approved` is an APPLY REQUEST, not human
provenance; Agent-originated apply is authorized only by Cursor
beforeShellExecution permission=ask.
"""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from scaffold_p5.host_state import (
    ADOPTION_SESSIONS,
    AGENTS_MD,
    COMMANDS_YAML,
    MIGRATION_EXECS,
    MODULES_YAML,
    PROJECT_YAML,
    SKILLS_LOCK,
    TESTS_YAML,
    classify_host,
    inspect_adoption_recovery,
    inspect_lock,
    inspect_migration_recovery,
    inspect_project,
    snapshot_host,
)
from scaffold_p5.io_util import sha256_bytes
from scaffold_p5.shell_boundary import ordinary_shell_hard_boundary


DECISION_BLOCK = "BLOCK_PROJECT_MUTATION"
DECISION_ALLOW = "ALLOW_PROJECT_MUTATION"
REQUIRED_ROUTE_BOOTSTRAP = "understand.bootstrap"
REQUIRED_ROUTE_DEVELOP = "develop"
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
    "postToolUse",
    "postToolUseFailure",
    "beforeShellExecution",
    "subagentStart",
    "beforeMCPExecution",
    "afterFileEdit",
    "afterTabFileEdit",
)
OBSERVATION_HOOK_EVENTS = frozenset(
    {"postToolUse", "postToolUseFailure", "afterFileEdit", "afterTabFileEdit"}
)
INTERCEPTION_HOOK_EVENTS = frozenset(
    {"preToolUse", "beforeShellExecution", "subagentStart", "beforeMCPExecution"}
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
    "move": "Move",
    "rename": "Rename",
    "multiedit": "MultiEdit",
    "task": "Task",
    "callmcptool": "CallMcpTool",
    "fetchmcpresource": "FetchMcpResource",
}
CMD_NAMES = frozenset({"cmd", "cmd.exe"})
MUTATION_EVENTS = frozenset({"afterFileEdit", "afterTabFileEdit"})
TERMINAL_EVENTS = frozenset({"postToolUse", "postToolUseFailure"})
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
        "Move",
        "Rename",
        "MultiEdit",
    }
)
NON_EDITOR_MUTATION_TOOLS = frozenset(
    {
        "Task",
        "CallMcpTool",
        "FetchMcpResource",
        "GenerateImage",
    }
)
EDITOR_MUTATION_TOOLS = MUTATION_TOOLS - NON_EDITOR_MUTATION_TOOLS
PYTHON_NAMES = frozenset({"python", "python.exe", "python3", "python3.exe"})
PLAN_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
INTAKE_B64_RE = re.compile(r"^[A-Za-z0-9+/_-]+=*$")
SHELL_METACHAR_RE = re.compile(r"""[;&|`$<>\n\r()]|&&|\|\|""")
PATCH_FILE_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+)$",
    re.MULTILINE,
)
MUTATION_PATH_KEYS = (
    "path",
    "file_path",
    "target_file",
    "target_notebook",
    "old_path",
    "new_path",
    "destination",
    "src",
    "dest",
)
KNOWN_HOST_CLASSES = frozenset(
    {
        "NOT_ADOPTED",
        "ESTABLISHED_HOST",
        "ESTABLISHED_HOST_CONSISTENCY",
        "PRIOR_FOOTPRINT",
        "INTERRUPTED_INITIAL_ADOPTION",
    }
)
GATE_BOOTSTRAP = "bootstrap"
GATE_DEVELOP = "develop"
GATE_RECOVERY = "recovery"
GATE_FAIL_CLOSED = "fail_closed"
REQUIRED_ROUTE_RECOVERY = "understand.compatibility"
CONSUMER_UPDATE_RUN_ARGV = ("consumer", "update")
CONSUMER_PROJECTION_MIGRATION_RUN_ARGV = ("consumer", "projection-migration")
ALLOWED_RUN_ARGV = {
    (): "verify",
    ("verify",): "verify",
    ("status",): "status",
    ("first-use",): "first-use",
    ("enter",): "enter",
    ("enter", "status"): "enter",
    ("understand",): "understand.bootstrap",
    ("understand", "bootstrap"): "understand.bootstrap",
    CONSUMER_UPDATE_RUN_ARGV: "consumer.update",
    CONSUMER_PROJECTION_MIGRATION_RUN_ARGV: "consumer.projection-migration",
}
POST_ADOPTION_RUN_ARGV = {
    **ALLOWED_RUN_ARGV,
    ("understand", "full"): "understand.full",
    ("understand", "refresh"): "understand.refresh",
    ("understand", "compatibility"): "understand.compatibility",
    ("develop",): "develop",
    ("develop", "normal_task"): "develop",
    ("develop", "repair"): "develop",
    ("test",): "test",
    ("test", "scoped_verification"): "test",
    ("submit",): "submit",
    ("enter", "develop"): "enter",
    ("enter", "understand"): "enter",
    ("enter", "test"): "enter",
    ("enter", "submit"): "enter",
    ("develop", "intake"): "develop",
    ("develop", "session"): "develop",
    ("develop", "seal"): "develop",
    ("develop", "abort"): "develop",
    ("develop", "bind"): "develop",
    ("develop", "complete"): "develop",
}
RECOVERY_RUN_ARGV = {
    **ALLOWED_RUN_ARGV,
    ("understand", "refresh"): "understand.refresh",
    ("understand", "compatibility"): "understand.compatibility",
    ("enter", "understand"): "enter",
}
FAIL_CLOSED_RUN_ARGV = {
    (): "verify",
    ("verify",): "verify",
    ("status",): "status",
    ("first-use",): "first-use",
    CONSUMER_UPDATE_RUN_ARGV: "consumer.update",
    CONSUMER_PROJECTION_MIGRATION_RUN_ARGV: "consumer.projection-migration",
}
INTAKE_POSITIONALS = frozenset({("enter", "develop"), ("develop", "intake")})
BIND_RUN_ARGV = ("develop", "bind")
COMPLETE_RUN_ARGV = ("develop", "complete")
COMPATIBILITY_RUN_ARGV = ("understand", "compatibility")
REFRESH_RUN_ARGV = ("understand", "refresh")
COMPATIBILITY_PUBLIC_ACTIONS = frozenset({"evaluate", "lock_update"})
REFRESH_PUBLIC_ACTIONS = frozenset({"resume", "understand"})

SHELL_ALLOW = "allow"
SHELL_DENY = "deny"
SHELL_ASK_APPLY = "ask_apply"
BOOTSTRAP_ARGV = frozenset({("understand",), ("understand", "bootstrap")})

AGENT_DENY_MESSAGE = (
    "Project mutation is blocked because this host is NOT_ADOPTED. "
    "Run the Scaffold Understand bootstrap route: "
    "`python .scaffold/install/run.py understand bootstrap`. "
    "If bootstrap returns a preview, continue with that exact plan apply "
    "request (`--approved --plan-digest`). Adoption apply is Agent lifecycle "
    "work; it is not Git Commit or Push. "
    "Do not implement the business task before Adoption completes."
)
ASK_AGENT_MESSAGE = (
    "This command is an Adoption apply request. Continue the official "
    "bootstrap apply. It is not Git Commit or Push."
)
ASK_USER_MESSAGE = (
    "Scaffold is applying an exact Adoption Plan. This is not Git Commit or Push."
)
PRETOOL_APPLY_CONTINUE_REASON = (
    "digest-bound Adoption apply request is an official lifecycle command"
)
ASK_APPLY_REASON = (
    "digest-bound Adoption apply is an official lifecycle command"
)
UNKNOWN_DENY_MESSAGE = (
    "Scaffold blocked this operation because host lifecycle state could "
    "not be determined. Run `python .scaffold/install/run.py status`. "
    "This is not a statement that the host is unadopted. UNKNOWN lifecycle "
    "state does not authorize ordinary project mutation."
)
FAIL_CLOSED_USER_MESSAGE = (
    "Scaffold first-use gate blocked this operation because host lifecycle "
    "state could not be determined. This is not a statement that the host "
    "is unadopted."
)
GENERIC_DENY_USER_MESSAGE = "Scaffold first-use gate blocked this operation."
HARD_BOUNDARY_USER_MESSAGE = (
    "Scaffold blocked a shell command at a hard safety or governance "
    "boundary (workspace escape, protected Scaffold governance, destructive "
    "or history-rewriting SCM, irrecoverable deletion, inline eval, or a "
    "prohibited security/attack operation)."
)
USER_DENY_MESSAGE = (
    "Scaffold first-use gate blocked a project mutation on a host that is "
    "not yet adopted."
)
SHELL_ORDINARY_ALLOW_REASON = "ordinary in-project development command"
DEVELOP_DENY_MESSAGE = (
    "Project mutation is blocked because this ACTIVE host has no current "
    "Develop authority (IN_PROGRESS Task Book, mutable Stage, and OPEN "
    "Develop Session bound to that Task). "
    "Run `python .scaffold/install/run.py enter develop --intake-json-b64 "
    "<envelope>` to publish a bounded Task proposal through Develop intake. "
    "Continue an existing Task with `python .scaffold/install/run.py develop "
    "session --task-id <task-id>`. "
    "Successful Adoption is not permission to edit HUMAN_OWNED project source. "
    "Do not implement the business task outside Develop, and do not write "
    ".scaffold/tasks/ directly."
)
DEVELOP_USER_DENY_MESSAGE = (
    "Scaffold Develop gate blocked a project mutation that crosses a hard "
    "boundary (workspace escape, protected Scaffold governance, destructive "
    "SCM, or irrecoverable deletion), or that has no current Develop Task, "
    "mutable Stage, and OPEN Session."
)
RECOVERY_DENY_MESSAGE = (
    "Project mutation is blocked because this adopted host is degraded or "
    "unresolved. Ordinary Develop mutation is not authorized. "
    "Run `python .scaffold/install/run.py status`, then "
    "`python .scaffold/install/run.py understand compatibility` or "
    "`python .scaffold/install/run.py understand refresh` as required. "
    "Do not implement the business task until the host is a healthy ACTIVE "
    "ESTABLISHED_HOST."
)
RECOVERY_USER_DENY_MESSAGE = (
    "Scaffold blocked a project mutation on a degraded or unresolved adopted "
    "host. Recover the host before ordinary Develop work."
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

If the host is ACTIVE / ESTABLISHED_HOST, editor and file mutation is
not authorized until Develop has a current IN_PROGRESS Task Book, a
mutable Stage, and an OPEN Develop Session bound to that Task. Task
scope is semantic intent, not a pre-write file allowlist. An OPEN
Session is not a repository-global unlock. Session seal ends that
Develop execution; it does not mean the host is unadopted.

Ordinary in-project development commands are autonomous. They do not
need to be predeclared in commands.yaml, and they do not require a
Develop Session merely to inspect tools, run local build/test/lint/
typecheck, or inspect SCM. The shell gate denies hard boundaries only:
writes outside this workspace, destructive or history-rewriting SCM,
irrecoverable deletion, protected Scaffold governance mutation, inline
eval, and prohibited security/attack operations. Git Commit and Git
Push remain separate publication operations.

Required editor-mutation route: `python .scaffold/install/run.py enter
develop --intake-json-b64 <envelope>`, then continue with
`python .scaffold/install/run.py develop session --task-id <task-id>`.
Zero-context resume is
`python .scaffold/install/run.py understand refresh --action resume`.
Bind an existing Task requirement with
`python .scaffold/install/run.py develop bind --task-id <task-id>
--requirement-id <id> --profile-id <id>`. Request Test execution,
Completion Decisions, Stage COMPLETE, and Task READY_FOR_REVIEW with
`python .scaffold/install/run.py develop complete --task-id <task-id>
--complete-json-b64 <envelope>`. Do not write `.scaffold/tasks/`
directly and do not import private runtime APIs to manufacture READY.

Observation hooks (postToolUse / afterFileEdit and equivalents) are
optional. Their absence or failure must not stop ordinary in-workspace
Develop. Physical reconciliation is the Session change set.

Degraded adopted hosts (consistency, prior footprint, unresolved recovery)
deny ordinary mutation. Recover with status / verify / understand
compatibility or refresh.

On an adopted host, `python .scaffold/install/run.py understand
compatibility` evaluates expected vs installed identity. An explicit
lock update is `--action lock_update --new-expected <json>` (or
`--new-expected-b64`) then the same command with that exact
`--plan-digest`. That apply is Agent lifecycle work. It is not
`--approved` Adoption apply and not Git Commit or Push.

Installed Consumer self-update is
`python .scaffold/install/run.py consumer update --distribution <path>`.
It is install/runtime maintenance for this host. The current host is
implicit. It is not Develop product mutation and does not rewrite
`skills.lock`.

Successful Adoption is not permission to edit project source. Repair
remains a Develop mode. There is no fifth Skill.

NEEDS_HUMAN on preview means continue with the exact plan apply request.
Do not implement the user task before Adoption completes.

`--approved --plan-digest` is an APPLY REQUEST for that exact Plan. It is
not Git Commit or Push. Auto-Adoption outside this explicit bootstrap
route remains out of scope.

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
        "Scaffold blocked this operation because the first-use hook could "
        "not load host lifecycle authority. Run "
        "`python .scaffold/install/run.py status`. This is not a statement "
        "that the host is unadopted."
    ),
    "user_message": (
        "Scaffold first-use gate blocked this operation because host "
        "lifecycle state could not be determined. This is not a statement "
        "that the host is unadopted."
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


def scaffold_hook_entry(event: str | None = None) -> dict[str, Any]:
    fail_closed = event not in OBSERVATION_HOOK_EVENTS
    return {
        "command": HOOK_COMMAND,
        "failClosed": fail_closed,
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def canonical_hook_fragment() -> dict[str, Any]:
    return {
        "schema": "scaffold-managed-json-fragment/v1",
        "fragment_id": FRAGMENT_ID,
        "path": HOOKS_JSON_REL,
        "events": {event: [scaffold_hook_entry(event)] for event in HOOK_EVENTS},
    }


def legacy_canonical_hook_fragment() -> dict[str, Any]:
    """Pre-autonomy uniform failClosed=true fragment. Still VERIFY-readable."""
    entry = {
        "command": HOOK_COMMAND,
        "failClosed": True,
        "timeout": HOOK_TIMEOUT_SECONDS,
    }
    return {
        "schema": "scaffold-managed-json-fragment/v1",
        "fragment_id": FRAGMENT_ID,
        "path": HOOKS_JSON_REL,
        "events": {event: [dict(entry)] for event in HOOK_EVENTS},
    }


def expected_hook_fragment_digest() -> str:
    payload = json.dumps(
        canonical_hook_fragment(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return sha256_bytes(payload.encode("utf-8"))


def legacy_hook_fragment_digest() -> str:
    payload = json.dumps(
        legacy_canonical_hook_fragment(),
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


def first_use_decision(
    host: str | Path,
    *,
    cheap: bool = False,
) -> dict[str, Any]:
    """Authoritative first-use mutation decision from existing host state.

    ``cheap=True`` is the editor hot path: no whole-project inventory, Git
    status, or candidate observation. Full ``snapshot_host`` remains the
    status/preflight authority.
    """
    try:
        if cheap:
            snapshot = _cheap_host_snapshot(host)
        else:
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
            required_route=None,
            gate_policy=GATE_FAIL_CLOSED,
            user_message=FAIL_CLOSED_USER_MESSAGE,
        )
    if host_class == "NOT_ADOPTED":
        return _block_decision(
            host_class=host_class,
            known=True,
            reason=reason,
            message=AGENT_DENY_MESSAGE,
            required_route=REQUIRED_ROUTE_BOOTSTRAP,
            snapshot=snapshot,
            gate_policy=GATE_BOOTSTRAP,
            user_message=USER_DENY_MESSAGE,
        )
    policy = _mutation_gate_policy(snapshot)
    if policy == GATE_FAIL_CLOSED:
        return _block_decision(
            host_class=host_class or "UNKNOWN",
            known=False,
            reason=reason if not known else f"unrecognized host class {host_class}",
            message=UNKNOWN_DENY_MESSAGE,
            required_route=None,
            snapshot=snapshot,
            gate_policy=GATE_FAIL_CLOSED,
            user_message=FAIL_CLOSED_USER_MESSAGE,
        )
    if policy == GATE_RECOVERY:
        return _block_decision(
            host_class=host_class,
            known=True,
            reason="adopted host requires recovery before ordinary mutation",
            message=RECOVERY_DENY_MESSAGE,
            required_route=REQUIRED_ROUTE_RECOVERY,
            snapshot=snapshot,
            gate_policy=GATE_RECOVERY,
            user_message=RECOVERY_USER_DENY_MESSAGE,
        )
    from scaffold_p7.develop_authority import resolve_current_develop_authority

    authority = resolve_current_develop_authority(
        Path(host), require_provenance=False
    )
    if not authority.ok:
        return _block_decision(
            host_class=host_class,
            known=True,
            reason=authority.reason,
            message=DEVELOP_DENY_MESSAGE,
            required_route=REQUIRED_ROUTE_DEVELOP,
            snapshot=snapshot,
            gate_policy=GATE_DEVELOP,
            user_message=DEVELOP_USER_DENY_MESSAGE,
        )
    return {
        "decision": DECISION_BLOCK,
        "host_class": host_class,
        "required_route": None,
        "project_mutation_allowed": False,
        "lifecycle_known": True,
        "first_use_gate_active": True,
        "gate_policy": GATE_DEVELOP,
        "reason": authority.reason,
        "agent_message": DEVELOP_DENY_MESSAGE,
        "user_message": DEVELOP_USER_DENY_MESSAGE,
        "preflight_context": getattr(snapshot, "preflight_context", None),
        "develop_authority": {
            "ok": True,
            "task_id": authority.task_id,
            "session_id": authority.session_id,
            "mutable_stage_ids": list(authority.mutable_stage_ids),
        },
        "current_authority": authority,
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
        return _deny(
            UNKNOWN_DENY_MESSAGE,
            reason="host root could not be resolved",
            user_message=FAIL_CLOSED_USER_MESSAGE,
        )
    authority = first_use_decision(host_root, cheap=True)
    policy = str(authority.get("gate_policy") or GATE_FAIL_CLOSED)
    deny_message = authority.get("agent_message") or AGENT_DENY_MESSAGE
    deny_user = authority.get("user_message") or _default_deny_user_message(policy)
    if policy == GATE_DEVELOP:
        deny_when = "without current Develop Task/Stage/Session or across a hard boundary"
    elif policy == GATE_RECOVERY:
        deny_when = "before host recovery"
    elif policy == GATE_FAIL_CLOSED:
        deny_when = "because host state is unrecognized"
    else:
        deny_when = "before Adoption"
    if event in {"subagentStart"} or tool_name == "Task":
        return _deny(
            deny_message,
            reason=f"subagent/Task bypass is not authorized {deny_when}",
            user_message=deny_user,
        )
    if _is_mcp_action(event, tool_name, data):
        return _deny(
            deny_message,
            reason=f"unknown MCP/external tool is fail-closed {deny_when}",
            user_message=deny_user,
        )
    if _is_shell_action(event, tool_name, data):
        command = _shell_command(data)
        kind, detail = classify_first_use_shell(
            command,
            host_root,
            policy=policy,
        )
        if kind == SHELL_ASK_APPLY:
            if authority.get("host_class") != "NOT_ADOPTED":
                return _deny(
                    deny_message,
                    reason=detail,
                    user_message=deny_user,
                )
            if event == "beforeShellExecution":
                return _ask(reason=detail)
            return _allow(PRETOOL_APPLY_CONTINUE_REASON)
        if kind == SHELL_ALLOW:
            return _allow(detail)
        return _deny(
            _shell_deny_agent_message(policy, deny_message, detail),
            reason=detail,
            user_message=_shell_deny_user_message(policy, deny_user),
        )
    if event in TERMINAL_EVENTS or event in MUTATION_EVENTS:
        return _handle_mutation_terminal(
            host_root,
            data,
            event,
            tool_name,
            policy=policy,
            authority=authority,
        )
    if policy != GATE_DEVELOP:
        return _deny(
            deny_message,
            reason=f"{tool_name or event or 'tool'} is not authorized {deny_when}",
            user_message=deny_user,
        )
    paths, path_error = _mutation_target_paths(data, host_root)
    if path_error and "outside the host" in path_error:
        return _deny(deny_message, reason=path_error, user_message=deny_user)
    if path_error:
        paths = []
    from scaffold_p7.develop_authority import authorize_mutation_paths

    current_authority = authority.get("current_authority")
    allowed, detail = authorize_mutation_paths(
        host_root,
        paths,
        authority=current_authority,
        deleting=False,
    )
    if allowed:
        deletion_paths = _deletion_target_paths(tool_name, data, host_root, paths)
        if deletion_paths:
            allowed, detail = authorize_mutation_paths(
                host_root,
                deletion_paths,
                authority=current_authority,
                deleting=True,
            )
    if allowed:
        return _allow(detail)
    return _deny(deny_message, reason=detail, user_message=deny_user)


def _handle_mutation_terminal(
    host_root: Path,
    data: dict[str, Any],
    event: str,
    tool_name: str,
    *,
    policy: str,
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record terminal/after-file observations. Never manufacture authority."""
    if policy != GATE_DEVELOP:
        return _allow("terminal mutation observation without current Develop authority")
    from scaffold_p7.develop_authority import (
        fail_authorized_mutation,
        observe_authorized_mutation,
    )
    from scaffold_p7.session import MUTATION_CANCELLED, MUTATION_FAILED

    paths, path_error = _mutation_target_paths(data, host_root)
    tool_use_id = _tool_use_id(data)
    if event == "postToolUseFailure":
        if path_error:
            paths = []
        failure_type = str(data.get("failure_type") or "").strip()
        state = (
            MUTATION_CANCELLED
            if data.get("is_interrupt") is True or failure_type == "permission_denied"
            else MUTATION_FAILED
        )
        fail_authorized_mutation(
            host_root,
            paths,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            state=state,
        )
        return _allow("mutation observation failed; physical reconciliation remains authoritative")
    if path_error:
        paths = []
    _recorded, detail = observe_authorized_mutation(
        host_root,
        paths,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        observation_scope=_observation_scope(event),
        authority=(authority or {}).get("current_authority") if isinstance(authority, dict) else None,
    )
    return _allow(detail)


def _observation_scope(event: str) -> str:
    """Adapter translation. Core never sees a client event name."""
    from scaffold_p7.develop_authority import (
        OBSERVATION_ATTEMPT_SCOPE,
        OBSERVATION_SINGLE_PATH,
    )

    if event in MUTATION_EVENTS:
        return OBSERVATION_SINGLE_PATH
    return OBSERVATION_ATTEMPT_SCOPE


def _tool_use_id(payload: dict[str, Any]) -> str:
    for key in ("tool_use_id", "toolCallId", "tool_call_id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    tool_input = _tool_input_object(payload)
    for key in ("tool_use_id", "toolCallId", "tool_call_id"):
        value = str(tool_input.get(key) or "").strip()
        if value:
            return value
    return ""


def classify_first_use_shell(
    command: str | None,
    host: str | Path,
    *,
    adopted: bool = False,
    policy: str | None = None,
) -> tuple[str, str]:
    """Classify a Shell command while a mutation gate is active.

    Official Scaffold launcher invocations keep exact-shape allowlisting.
    After Adoption, ordinary in-project development commands are autonomous
    unless they cross a hard safety/governance boundary. An OPEN Develop
    Session is not a blanket mutating-shell permission, and a missing
    Session is not a blanket shell deny. Preview/status/verify remain
    allow. The digest-bound Adoption apply request is not execution
    authorization; it is an APPLY REQUEST that must reach
    beforeShellExecution permission=ask.
    """
    raw = str(command or "").strip()
    if raw.startswith("& "):
        raw = raw[2:].strip()
    if not raw:
        return SHELL_DENY, "empty shell command is not a first-use lifecycle command"
    if "--intake-json" not in raw and SHELL_METACHAR_RE.search(raw):
        return SHELL_DENY, "shell metacharacters are not allowed by the mutation gate"
    argv = _split_shell_argv(raw)
    if argv is None:
        return SHELL_DENY, "shell command could not be parsed exactly"
    argv = _unwrap_cmd_prefix(argv)
    gate = policy or (GATE_DEVELOP if adopted else GATE_BOOTSTRAP)
    if len(argv) >= 2 and _is_python_token(argv[0]):
        runner = _official_runner_path(argv[1], host)
        if runner is not None:
            rest = argv[2:]
            positional, flags, flag_error = _split_runner_flags(rest)
            if flag_error:
                return SHELL_DENY, flag_error
            host_flag = flags.get("host")
            if host_flag is not None and not _same_host(host_flag, host):
                return SHELL_DENY, "shell --host does not resolve to this project"
            allowed = _runner_argv_for_policy(gate)
            if positional not in allowed:
                return SHELL_DENY, "shell command is not a first-use Scaffold lifecycle command"
            if flags.get("intake_json") or flags.get("intake_json_b64"):
                if positional not in INTAKE_POSITIONALS:
                    return (
                        SHELL_DENY,
                        "intake JSON flags are only valid on enter develop or develop intake",
                    )
                intake_error = _intake_flag_error(flags)
                if intake_error:
                    return SHELL_DENY, intake_error
            compat_error = _compatibility_flag_error(positional, flags)
            if compat_error:
                return SHELL_DENY, compat_error
            lifecycle_error = _lifecycle_flag_error(positional, flags)
            if lifecycle_error:
                return SHELL_DENY, lifecycle_error
            consumer_error = _consumer_flag_error(positional, flags)
            if consumer_error:
                return SHELL_DENY, consumer_error
            if flags.get("approved") and positional not in BOOTSTRAP_ARGV:
                return SHELL_DENY, "approval flags are only valid on Understand bootstrap"
            if flags.get("plan_digest") and not flags.get("approved"):
                lock_update_apply = (
                    positional == COMPATIBILITY_RUN_ARGV
                    and flags.get("action") == "lock_update"
                )
                if not lock_update_apply:
                    return SHELL_DENY, "plan digest without --approved is not an official apply command"
            if flags.get("approved") and flags.get("plan_digest"):
                return SHELL_ALLOW, ASK_APPLY_REASON
            return SHELL_ALLOW, "official first-use Scaffold lifecycle command"
    if gate == GATE_FAIL_CLOSED:
        return (
            SHELL_DENY,
            "host lifecycle state could not be determined; only official "
            "Scaffold inspection/update commands are allowed",
        )
    if gate == GATE_BOOTSTRAP:
        return SHELL_DENY, "shell command is not an official Scaffold launcher invocation"
    boundary = ordinary_shell_hard_boundary(argv, host)
    if boundary:
        return SHELL_DENY, boundary
    return SHELL_ALLOW, SHELL_ORDINARY_ALLOW_REASON


def first_use_shell_allowed(
    command: str | None,
    host: str | Path,
    *,
    adopted: bool = False,
    policy: str | None = None,
) -> tuple[bool, str]:
    kind, detail = classify_first_use_shell(
        command, host, adopted=adopted, policy=policy
    )
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
        found = _find_project_root(resolved)
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
    raw = ""
    event = ""
    try:
        raw = decode_hook_stdin(stdin)
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("hook payload is not an object")
        event = _hook_event(payload)
        result = evaluate_cursor_hook(payload)
        _write_hook_result(stdout, result)
        return 0
    except (json.JSONDecodeError, ValueError, TypeError, OSError, AttributeError, KeyError):
        if event in OBSERVATION_HOOK_EVENTS or _raw_looks_like_observation(raw):
            result = _allow("invalid observation is non-blocking")
            _write_hook_result(stdout, result)
            return 0
        result = _deny(
            UNKNOWN_DENY_MESSAGE,
            reason="invalid or unusable hook input",
            user_message=FAIL_CLOSED_USER_MESSAGE,
        )
        _write_hook_result(stdout, result)
        return 2
    except Exception:
        if event in OBSERVATION_HOOK_EVENTS or _raw_looks_like_observation(raw):
            result = _allow("observation hook failure is non-blocking")
            _write_hook_result(stdout, result)
            return 0
        result = _deny(
            UNKNOWN_DENY_MESSAGE,
            reason="hook adapter failure",
            user_message=FAIL_CLOSED_USER_MESSAGE,
        )
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
    for event in HOOK_EVENTS:
        current = hooks.get(event)
        if current is None:
            hooks[event] = [scaffold_hook_entry(event)]
            continue
        if not isinstance(current, list):
            raise ValueError(f"hooks.json {event} is not a list")
        kept: list[Any] = []
        inserted = False
        for item in current:
            if is_scaffold_hook_command(item):
                if not inserted:
                    kept.append(scaffold_hook_entry(event))
                    inserted = True
                continue
            kept.append(item)
        if not inserted:
            kept.insert(0, scaffold_hook_entry(event))
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
        if not isinstance(item, dict) or not _hook_entry_matches(item, event=event):
            drifted.append(HOOKS_JSON_REL)
            continue
        events[event] = [_normalized_hook_entry(item, event)]
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
    gate_policy: str = GATE_BOOTSTRAP,
    user_message: str | None = None,
) -> dict[str, Any]:
    return {
        "decision": DECISION_BLOCK,
        "host_class": host_class,
        "required_route": required_route,
        "project_mutation_allowed": False,
        "lifecycle_known": known,
        "first_use_gate_active": True,
        "gate_policy": gate_policy,
        "reason": reason,
        "agent_message": message,
        "user_message": user_message,
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


def _deny(
    agent_message: str,
    *,
    reason: str,
    user_message: str | None = None,
) -> dict[str, Any]:
    return {
        "permission": "deny",
        "agent_message": agent_message,
        "user_message": user_message or GENERIC_DENY_USER_MESSAGE,
        "reason": reason,
    }


def _default_deny_user_message(policy: str) -> str:
    if policy == GATE_BOOTSTRAP:
        return USER_DENY_MESSAGE
    if policy == GATE_FAIL_CLOSED:
        return FAIL_CLOSED_USER_MESSAGE
    if policy == GATE_RECOVERY:
        return RECOVERY_USER_DENY_MESSAGE
    return DEVELOP_USER_DENY_MESSAGE


def _shell_deny_agent_message(policy: str, lifecycle_message: str, detail: str) -> str:
    if policy == GATE_BOOTSTRAP:
        return lifecycle_message
    return f"Scaffold blocked this shell command at a hard boundary: {detail}"


def _shell_deny_user_message(policy: str, lifecycle_user: str) -> str:
    if policy == GATE_BOOTSTRAP:
        return lifecycle_user
    if policy == GATE_FAIL_CLOSED:
        return FAIL_CLOSED_USER_MESSAGE
    return HARD_BOUNDARY_USER_MESSAGE


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
    if event in MUTATION_EVENTS or event in TERMINAL_EVENTS or event == "subagentStart":
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
        if token == "--task-id":
            if i + 1 >= len(rest):
                return tuple(), flags, "--task-id requires a Task Book identity"
            flags["task_id"] = rest[i + 1]
            i += 2
            continue
        if token == "--intake-json":
            if i + 1 >= len(rest):
                return tuple(), flags, "--intake-json requires a JSON object"
            flags["intake_json"] = rest[i + 1]
            i += 2
            continue
        if token == "--intake-json-b64":
            if i + 1 >= len(rest):
                return tuple(), flags, "--intake-json-b64 requires a base64 payload"
            flags["intake_json_b64"] = rest[i + 1]
            i += 2
            continue
        if token == "--action":
            if i + 1 >= len(rest):
                return tuple(), flags, "--action requires a value"
            flags["action"] = rest[i + 1]
            i += 2
            continue
        if token == "--new-expected":
            if i + 1 >= len(rest):
                return tuple(), flags, "--new-expected requires a JSON object"
            flags["new_expected"] = rest[i + 1]
            i += 2
            continue
        if token == "--new-expected-b64":
            if i + 1 >= len(rest):
                return tuple(), flags, "--new-expected-b64 requires a base64 payload"
            flags["new_expected_b64"] = rest[i + 1]
            i += 2
            continue
        if token == "--distribution":
            if i + 1 >= len(rest):
                return tuple(), flags, "--distribution requires a Distribution path"
            flags["distribution"] = rest[i + 1]
            i += 2
            continue
        if token == "--requirement-id":
            if i + 1 >= len(rest):
                return tuple(), flags, "--requirement-id requires a Task requirement identity"
            flags["requirement_id"] = rest[i + 1]
            i += 2
            continue
        if token == "--profile-id":
            if i + 1 >= len(rest):
                return tuple(), flags, "--profile-id requires a Test profile identity"
            flags["profile_id"] = rest[i + 1]
            i += 2
            continue
        if token == "--kind":
            if i + 1 >= len(rest):
                return tuple(), flags, "--kind requires test_profile"
            flags["kind"] = rest[i + 1]
            i += 2
            continue
        if token == "--complete-json":
            if i + 1 >= len(rest):
                return tuple(), flags, "--complete-json requires a JSON object"
            flags["complete_json"] = rest[i + 1]
            i += 2
            continue
        if token == "--complete-json-b64":
            if i + 1 >= len(rest):
                return tuple(), flags, "--complete-json-b64 requires a base64 payload"
            flags["complete_json_b64"] = rest[i + 1]
            i += 2
            continue
        if token.startswith("-"):
            return tuple(), flags, f"unsupported launcher flag {token}"
        positional.append(token)
        i += 1
    return tuple(positional), flags, None


def _runner_argv_for_policy(policy: str) -> dict[tuple[str, ...], str]:
    if policy == GATE_DEVELOP:
        return POST_ADOPTION_RUN_ARGV
    if policy == GATE_RECOVERY:
        return RECOVERY_RUN_ARGV
    if policy == GATE_FAIL_CLOSED:
        return FAIL_CLOSED_RUN_ARGV
    return ALLOWED_RUN_ARGV


def _consumer_flag_error(
    positional: tuple[str, ...],
    flags: dict[str, Any],
) -> str | None:
    has_distribution = flags.get("distribution") is not None
    if positional == CONSUMER_PROJECTION_MIGRATION_RUN_ARGV:
        if flags.get("action") or flags.get("new_expected") or flags.get("new_expected_b64"):
            return "compatibility flags are only valid on understand compatibility"
        if flags.get("approved") or flags.get("plan_digest"):
            return "approval flags are only valid on Understand bootstrap"
        if flags.get("intake_json") or flags.get("intake_json_b64"):
            return "intake JSON flags are only valid on enter develop or develop intake"
        if flags.get("requirement_id") or flags.get("profile_id") or flags.get("kind"):
            return "binding flags are only valid on develop bind"
        if flags.get("complete_json") or flags.get("complete_json_b64"):
            return "completion flags are only valid on develop complete"
        if flags.get("task_id"):
            return "--task-id is not valid on consumer projection-migration"
        if flags.get("host") is not None:
            return (
                "consumer projection-migration does not accept --host; "
                "the current host is implicit"
            )
        if flags.get("distribution") is not None:
            return "--distribution is only valid on consumer update"
        return None
    if positional == CONSUMER_UPDATE_RUN_ARGV:
        if flags.get("action") or flags.get("new_expected") or flags.get("new_expected_b64"):
            return "compatibility flags are only valid on understand compatibility"
        if flags.get("approved") or flags.get("plan_digest"):
            return "approval flags are only valid on Understand bootstrap"
        if flags.get("intake_json") or flags.get("intake_json_b64"):
            return "intake JSON flags are only valid on enter develop or develop intake"
        if flags.get("requirement_id") or flags.get("profile_id") or flags.get("kind"):
            return "binding flags are only valid on develop bind"
        if flags.get("complete_json") or flags.get("complete_json_b64"):
            return "completion flags are only valid on develop complete"
        if flags.get("task_id"):
            return "--task-id is not valid on consumer update"
        if flags.get("host") is not None:
            return "consumer update does not accept --host; the current host is implicit"
        if not has_distribution:
            return "consumer update requires --distribution"
        dist = str(flags.get("distribution") or "").strip()
        if not dist or dist.startswith("-"):
            return "--distribution requires a Distribution path"
        return None
    if has_distribution:
        return "--distribution is only valid on consumer update"
    if positional and positional[0] == "consumer":
        return "unsupported consumer action"
    return None


def _compatibility_flag_error(
    positional: tuple[str, ...],
    flags: dict[str, Any],
) -> str | None:
    action = flags.get("action")
    has_expected = bool(flags.get("new_expected") or flags.get("new_expected_b64"))
    if positional == REFRESH_RUN_ARGV:
        if has_expected:
            return "--new-expected is only valid on understand compatibility"
        if action is None:
            return None
        if action in REFRESH_PUBLIC_ACTIONS:
            return None
        if action in COMPATIBILITY_PUBLIC_ACTIONS:
            return "compatibility flags are only valid on understand compatibility"
        return f"unsupported refresh action {action}"
    has_compat_flag = action is not None or has_expected
    if (
        flags.get("plan_digest")
        and not flags.get("approved")
        and positional == COMPATIBILITY_RUN_ARGV
    ):
        has_compat_flag = True
    if not has_compat_flag:
        return None
    if positional != COMPATIBILITY_RUN_ARGV:
        return "compatibility flags are only valid on understand compatibility"
    if action is None:
        if has_expected:
            return "--new-expected requires --action lock_update"
        if flags.get("plan_digest") and not flags.get("approved"):
            return "--plan-digest is only valid with --action lock_update on understand compatibility"
        return None
    if action not in COMPATIBILITY_PUBLIC_ACTIONS:
        return f"unsupported compatibility action {action}"
    if has_expected and action != "lock_update":
        return "--new-expected is only valid with --action lock_update"
    if flags.get("plan_digest") and not flags.get("approved") and action != "lock_update":
        return "--plan-digest is only valid with --action lock_update on understand compatibility"
    if flags.get("new_expected") and flags.get("new_expected_b64"):
        return "provide only one of --new-expected or --new-expected-b64"
    raw_json = flags.get("new_expected")
    if raw_json is not None:
        try:
            payload = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            return "new-expected JSON is not parseable"
        if not isinstance(payload, dict) or not payload:
            return "new-expected JSON must be a nonempty object"
    raw_b64 = flags.get("new_expected_b64")
    if raw_b64 is not None:
        if not INTAKE_B64_RE.fullmatch(str(raw_b64)):
            return "new-expected base64 is malformed"
        try:
            decoded = base64.b64decode(str(raw_b64), validate=True).decode("utf-8")
            payload = json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return "new-expected base64 is malformed"
        if not isinstance(payload, dict) or not payload:
            return "new-expected JSON must be a nonempty object"
    return None


def _lifecycle_flag_error(
    positional: tuple[str, ...],
    flags: dict[str, Any],
) -> str | None:
    has_bind = bool(
        flags.get("requirement_id") or flags.get("profile_id") or flags.get("kind")
    )
    has_complete = bool(flags.get("complete_json") or flags.get("complete_json_b64"))
    if has_bind and positional != BIND_RUN_ARGV:
        return "binding flags are only valid on develop bind"
    if has_complete and positional != COMPLETE_RUN_ARGV:
        return "completion flags are only valid on develop complete"
    if positional == BIND_RUN_ARGV:
        if flags.get("intake_json") or flags.get("intake_json_b64"):
            return "intake JSON flags are only valid on enter develop or develop intake"
        kind = flags.get("kind")
        if kind is not None and kind != "test_profile":
            return "develop bind --kind must be test_profile"
        return None
    if positional == COMPLETE_RUN_ARGV:
        if flags.get("intake_json") or flags.get("intake_json_b64"):
            return "intake JSON flags are only valid on enter develop or develop intake"
        if flags.get("complete_json") and flags.get("complete_json_b64"):
            return "provide only one of --complete-json or --complete-json-b64"
        raw_b64 = flags.get("complete_json_b64")
        if raw_b64 is not None and not INTAKE_B64_RE.fullmatch(str(raw_b64)):
            return "completion JSON base64 is malformed"
        return None
    return None


def _intake_flag_error(flags: dict[str, Any]) -> str | None:
    json_text = flags.get("intake_json")
    b64_text = flags.get("intake_json_b64")
    if json_text and b64_text:
        return "provide only one of --intake-json or --intake-json-b64"
    if json_text:
        try:
            payload = json.loads(json_text)
        except (json.JSONDecodeError, TypeError, ValueError):
            return "intake JSON is not parseable"
        if not isinstance(payload, dict):
            return "intake JSON must be an object"
        return None
    if b64_text:
        if not INTAKE_B64_RE.fullmatch(str(b64_text)):
            return "intake JSON base64 is malformed"
        return None
    return None


def _mutation_gate_policy(snapshot: Any) -> str:
    host_class = str(getattr(snapshot, "host_class", "") or "")
    if host_class not in KNOWN_HOST_CLASSES:
        return GATE_FAIL_CLOSED
    if host_class == "NOT_ADOPTED":
        return GATE_BOOTSTRAP
    if host_class != "ESTABLISHED_HOST":
        return GATE_RECOVERY
    project = getattr(snapshot, "project", None) or {}
    lifecycle = str(
        (project.get("lifecycle") if isinstance(project, dict) else None)
        or getattr(snapshot, "lifecycle", "")
        or ""
    )
    maintenance = list(
        (project.get("maintenance") if isinstance(project, dict) else None)
        or []
    )
    if lifecycle == "ACTIVE" and not any(
        item in {"NEEDS_REFRESH", "NEEDS_MIGRATION"} for item in maintenance
    ):
        return GATE_DEVELOP
    return GATE_RECOVERY


def _deletion_target_paths(
    tool_name: str,
    payload: dict[str, Any],
    host: Path,
    paths: list[str],
) -> list[str]:
    """Paths the client is asking to remove. Cheap; no project scan."""
    if tool_name in {"Delete", "DeleteFile"}:
        return list(paths)
    if tool_name not in {"Move", "Rename"}:
        return []
    tool_input = _tool_input_object(payload)
    raw = (
        payload.get("old_path")
        or tool_input.get("old_path")
        or payload.get("src")
        or tool_input.get("src")
    )
    rel, error = _relative_mutation_path(host, raw)
    if error or not rel:
        return []
    return [rel]


def _mutation_target_paths(
    payload: dict[str, Any],
    host: Path,
) -> tuple[list[str], str | None]:
    tool_input = _tool_input_object(payload)
    found: list[str] = []
    for key in MUTATION_PATH_KEYS:
        raw = payload.get(key)
        if raw in (None, ""):
            raw = tool_input.get(key)
        if raw in (None, ""):
            continue
        rel, error = _relative_mutation_path(host, raw)
        if error:
            return [], error
        if rel:
            found.append(rel)
    patch = tool_input.get("patch")
    if isinstance(patch, str) and patch.strip():
        for match in PATCH_FILE_RE.finditer(patch):
            rel, error = _relative_mutation_path(host, match.group(1))
            if error:
                return [], error
            if rel:
                found.append(rel)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for item in edits:
            if not isinstance(item, dict):
                continue
            raw = item.get("path") or item.get("file_path") or item.get("target_file")
            if raw in (None, ""):
                continue
            rel, error = _relative_mutation_path(host, raw)
            if error:
                return [], error
            if rel:
                found.append(rel)
    unique: list[str] = []
    seen: set[str] = set()
    for item in found:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    if not unique:
        return [], "mutation target path is missing; fail closed"
    return unique, None


def _relative_mutation_path(host: Path, raw: Any) -> tuple[str | None, str | None]:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return None, None
    try:
        host_root = host.resolve()
        candidate = Path(text)
        resolved = candidate.resolve() if candidate.is_absolute() else (host_root / text).resolve()
        relative = resolved.relative_to(host_root)
    except (OSError, ValueError):
        return None, "mutation target is outside the host; fail closed"
    out = relative.as_posix()
    if out.startswith("../") or out == "..":
        return None, "mutation target is outside the host; fail closed"
    return out, None


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


def _find_project_root(start: Path) -> Path | None:
    current = start
    if current.is_file():
        current = current.parent
    for _ in range(8):
        if (current / ".scaffold" / "project.yaml").is_file():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _normalized_hook_entry(item: dict[str, Any], event: str) -> dict[str, Any]:
    fail_closed = item.get("failClosed")
    if event in OBSERVATION_HOOK_EVENTS:
        fail_closed = bool(fail_closed)
    else:
        fail_closed = True
    return {
        "command": HOOK_COMMAND,
        "failClosed": fail_closed,
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def _hook_entry_matches(item: dict[str, Any], event: str | None = None, expected: dict[str, Any] | None = None) -> bool:
    wanted = expected if expected is not None else scaffold_hook_entry(event)
    extra = set(item) - {"command", "failClosed", "timeout"}
    if extra:
        return False
    command = str(item.get("command") or "").strip().replace("\\", "/")
    if command != wanted["command"]:
        return False
    if int(item.get("timeout") or 0) != wanted["timeout"]:
        return False
    if "matcher" in item:
        return False
    fail_closed = item.get("failClosed")
    if event in OBSERVATION_HOOK_EVENTS:
        return fail_closed in {True, False}
    return fail_closed is True


def _raw_looks_like_observation(raw: str) -> bool:
    text = str(raw or "")
    return any(name in text for name in OBSERVATION_HOOK_EVENTS)


_CHEAP_IDENTITY_RELS = (
    MODULES_YAML,
    COMMANDS_YAML,
    TESTS_YAML,
    AGENTS_MD,
    SKILLS_LOCK,
)


def _cheap_host_snapshot(host: str | Path):
    """Lifecycle class without whole-project inventory or Git status.

    Reads bounded authority files and small recovery directories so the
    established recovery gate (missing authoritative skills.lock, unresolved
    Adoption/Migration evidence, RECOVERY_REQUIRED) still fail-closes.
    """
    from types import SimpleNamespace

    root = Path(host)
    view = inspect_project(root / PROJECT_YAML)
    lock = inspect_lock(root / SKILLS_LOCK)
    adoption_recovery = inspect_adoption_recovery(root / ADOPTION_SESSIONS)
    migration_recovery = inspect_migration_recovery(root / MIGRATION_EXECS)
    files = [rel for rel in _CHEAP_IDENTITY_RELS if (root / rel).exists()]
    host_class, context, _blockers, _evidence = classify_host(
        root,
        files,
        view,
        lock,
        adoption_recovery,
        migration_recovery,
    )
    project = view.data if isinstance(view.data, dict) else None
    lifecycle = str((project or {}).get("lifecycle") or "") if project else None
    return SimpleNamespace(
        host_class=host_class,
        project=project,
        lifecycle=lifecycle,
        preflight_context=context,
    )

# First-use enforcement — design

PC-CONSUMER-001 correction. Installation/client surface, **not** a fifth Skill.

Related: [FIRST_USE_WALKTHROUGH.md](FIRST_USE_WALKTHROUGH.md),
[CONSUMER_INSTALLATION_DESIGN.md](CONSUMER_INSTALLATION_DESIGN.md),
[../CONSUMER_INSTALLATION.md](../CONSUMER_INSTALLATION.md).

## Why

A fresh Consumer Agent can discover Scaffold, read repository-local
instructions, recognize `NOT_ADOPTED`, and still decide that Adoption is
cumbersome and that direct feature work is more efficient. Soft wording is
not an authorization boundary. `NOT_ADOPTED` is.

## Three layers

| Layer | What it is | What it is not |
| --- | --- | --- |
| Client-neutral authority | `snapshot_host` / `first_use_decision()` answers host class, required route, and whether ordinary project mutation is authorized | A parallel lifecycle state machine |
| Normative project instructions | Managed `AGENTS.md` `scaffold-consumer` region | Sufficient enforcement by itself |
| Cursor client adapter | Always Apply `.cursor/rules/scaffold-first-use.mdc` plus project `preToolUse` / `beforeShellExecution` / `subagentStart` / `beforeMCPExecution` hooks | A fifth Skill; not canonical Skill meaning |

Future clients may implement equivalent adapters. This Distribution does not
claim hard enforcement on clients that do not.

## Client-neutral decision

For `host_class == NOT_ADOPTED`:

- `decision = BLOCK_PROJECT_MUTATION`
- `required_route = understand.bootstrap`
- ordinary project mutation is not authorized

The ordinary user business request is not Adoption approval. `NEEDS_HUMAN`
means STOP. UNKNOWN lifecycle state does not authorize mutation.

After valid Adoption, this first-use gate no longer blocks solely because of
`NOT_ADOPTED`. Post-Adoption Develop enforcement is out of scope.

## Cursor adapter

- Always Apply rule: `.cursor/rules/scaffold-first-use.mdc` (`alwaysApply: true`).
- Hook executable: `.scaffold/install/cursor_first_use_hook.py` (fully MANAGED).
- Shared `.cursor/hooks.json` is mixed-ownership. Scaffold owns only the
  `scaffold-first-use` JSON fragment (`install.yaml` `json_fragments:`).
- Documented Cursor contract: `version: 1`, `failClosed: true` on Scaffold
  entries. Deny via `{ "permission": "deny", "agent_message": "..." }`.
  `beforeShellExecution` ASK via `{ "permission": "ask", "user_message": "...",
  "agent_message": "..." }`. Current Cursor docs and local agent-exec map
  that ASK to `ShellHookApprovalRequirement.KIND_FORCE_PROMPT`.
  `preToolUse` `permission: "ask"` is schema-accepted but **not** enforced
  (runtime treats it as unimplemented / reject). Do not rely on it for human
  confirmation.
- Project hooks run in **Trusted** workspaces. Cloud/project hooks follow
  current Cursor loading rules; this is not a general security scanner.

While `NOT_ADOPTED`:

- Allow read-only inspection (`Read` / `Grep` / `Glob` and equivalents).
- Allow exact official first-use launcher commands:
  `python .scaffold/install/run.py` `verify` | `status` | `first-use` |
  `understand` | `understand bootstrap` (preview). Preview is not approval.
- The digest-bound apply request
  `python .scaffold/install/run.py understand bootstrap --approved --plan-digest <hex>`
  is **not** unconditional ALLOW. `preToolUse` Shell allows it only so the
  command can reach `beforeShellExecution`. `beforeShellExecution` returns
  `permission = ask`. `--approved` is an APPLY REQUEST, not human provenance.
  Human authorization for an Agent-originated apply is the Cursor interactive
  confirmation produced by that ASK / FORCE_PROMPT. The Agent cannot satisfy
  it with ordinary tool calls.
- A human invoking the same CLI outside an Agent session is a different
  situation. Other clients need an equivalent adapter to claim hard
  enforcement. This Distribution does not claim universal client hard
  enforcement.
- Deny Write, Delete, arbitrary Shell, Task/subagent, and unknown MCP/external
  mutation-capable tools.

## Ownership

| Path | Ownership |
| --- | --- |
| `.cursor/rules/scaffold-first-use.mdc` | whole-file MANAGED |
| `.scaffold/install/cursor_first_use_hook.py` | whole-file MANAGED |
| `.cursor/hooks.json` | `MANAGED_JSON_FRAGMENT` `scaffold-first-use` |
| Unrelated host hooks / rules / skills | preserved |

VERIFY detects missing/duplicate/changed Scaffold hook command or matcher,
malformed hooks JSON, and incompatible schema. Unrelated human hook additions
are not Scaffold drift. UPDATE merges the Scaffold fragment and leaves
unrelated entries.

RC2 installations UPDATE to this surface without becoming Adopted.

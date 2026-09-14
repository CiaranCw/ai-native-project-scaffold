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
| Cursor client adapter | Always Apply `.cursor/rules/scaffold-first-use.mdc` plus project `preToolUse` / `postToolUse` / `postToolUseFailure` / `beforeShellExecution` / `subagentStart` / `beforeMCPExecution` / `afterFileEdit` / `afterTabFileEdit` hooks | A fifth Skill; not canonical Skill meaning |

Future clients may implement equivalent adapters. This Distribution does not
claim hard enforcement on clients that do not.

## Client-neutral decision

For `host_class == NOT_ADOPTED`:

- `decision = BLOCK_PROJECT_MUTATION`
- `required_route = understand.bootstrap`
- ordinary project mutation is not authorized

The ordinary user business request is not Adoption approval. `NEEDS_HUMAN`
means STOP. UNKNOWN lifecycle state does not authorize mutation.

After valid Adoption (`ESTABLISHED_HOST` / `ACTIVE`), this first-use gate no
longer blocks solely because of `NOT_ADOPTED`. Ordinary HUMAN_OWNED business
mutation remains unauthorized until Develop has a current `IN_PROGRESS` Task
Book, a mutable Stage, and an explicit current execution pointer bound to a
valid OPEN Session. A raw OPEN Session without that pointer is not editor
authority. Mutation is then authorized only inside that Task's product or
supporting scope, and only for paths the current execution records. An OPEN
Session is not a repository-global unlock.

The installed Consumer establishes first Task authority through:

`python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>`

or `python .scaffold/install/run.py develop intake --intake-json-b64 <envelope>`.
That envelope is the structured proposal `DevelopEngine.intake` requires.
`--intake-json` is also accepted. Bare `enter develop` without a proposal
fails closed. Intake creates no Develop Session and does not transition
Stage merely to manufacture editor authority. After Task publication, the
installed Consumer opens execution with
`python .scaffold/install/run.py develop session --task-id <task-id>` and
closes it with `develop seal` or `develop abort`. Do not write
`.scaffold/tasks/` directly.

Supporting scope is Task affiliation, never an ownership override: a
declared supporting path still requires underlying path authority.
MANAGED, HUMAN_OWNED, and protected governance cannot be smuggled through
`supporting_paths`.

P6 may ingest evidence whose source file sits inside the current Task's
declared supporting scope when the runtime caller supplies canonical
`task_id` (installed test route, Develop handoff, Submit completeness).
Candidate binding remains authoritative. Supporting-path membership never
manufactures `TEST_PASS` or `TEST_COMPLETE`, and requirement → Test still
requires explicit `execution_binding`.

Degraded adopted hosts (`ESTABLISHED_HOST_CONSISTENCY`, `PRIOR_FOOTPRINT`,
interrupted or unresolved recovery, `RECOVERY_REQUIRED` / `NEEDS_REFRESH` /
`NEEDS_MIGRATION`) deny ordinary mutation. Status, verify, and Understand
compatibility/refresh remain reachable so recovery is not deadlocked.
Unrecognized host classes fail closed.

Successful Adoption is not write permission. Repair remains a Develop mode.
There is no fifth Skill.

## Project ownership vs Task scope

| Authority | What it is | What it is not |
| --- | --- | --- |
| Project ownership | `project.yaml` `ownership` registry: GENERATED / MANAGED / HUMAN_OWNED | Task permission to mutate |
| Task product scope | `scope.paths` / `scope.modules` of the current Task | Supporting tests/tools/evidence |
| Task supporting scope | Explicit `scope.supporting_paths` on the current Task | Product/module ownership |

Supporting paths must be explicit, bounded prefixes (no wildcards, no
repository-wide claim, no `.scaffold` / `.cursor` governance). They must be
grounded in discovered project facts (existing trees or tests/commands
indexes), not an arbitrary nonexistent multi-segment prefix. They do not
become `project.yaml` ownership. Submit S2/S3 distinguish inherited
baseline, Task product delta, Task supporting delta, and unrelated delta.
S3 uses the same path-authority model as Develop.

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

- Classify Cursor hook payloads by **known operation identity**, then
  payload shape. A path-like field (`path` / `file_path` / `target_file`)
  is not evidence that the operation is a Read. Known mutators
  (`Write` / `Delete` / `EditNotebook` and aliases) are denied before any
  read-only check. Unknown tools fail closed, including path-only and
  path+content shapes. Windows hook stdin may include a UTF-8 BOM;
  documented `beforeReadFile` event plus `file_path`, aliased Read
  names, JSON-string `tool_input`, `cmd /c` wrappers, and Windows path
  separators remain the same operations after identity is established.
- Allow read-only inspection (`Read` / `Grep` / `Glob` / `beforeReadFile`
  and equivalents). Do not require human approval to inspect the project or
  generate an Adoption Plan.
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

While `ACTIVE` / `ESTABLISHED_HOST` without current Develop authority:

- Read-only inspection remains ALLOW.
- Official launcher commands for `understand`, `develop`, `test`, `submit`,
  `enter`, `status`, `verify`, and `first-use` remain ALLOW so the Agent can
  establish Task Book and Session authority, including
  `enter develop --intake-json-b64` and `develop intake --intake-json-b64`.
- Direct Write / Delete / StrReplace / arbitrary Shell / Task / unknown MCP
  remain DENY until the current Task/Stage/Session tuple exists. Then editor
  mutation is authorized only for targets inside that Task's product or
  supporting scope after an explicit current execution pointer is bound.
  `preToolUse` authorizes the attempt and records a pending mutation
  transaction. `postToolUse` observes the actual resulting filesystem state
  and is the success provenance terminal. `postToolUseFailure` fails or
  cancels that pending row and leaves no whitelist. `afterFileEdit` /
  `afterTabFileEdit` may enrich observation only when a unique pending
  authorization belongs to the current Develop execution and the same
  path. Protected `.scaffold` governance stays denied. Arbitrary mutating
  shell stays denied; an OPEN Session is not a blanket shell grant.
  Pending authorization is not `DEVELOP_KNOWN` and is not stamped successful
  at seal.

## Cursor hook coverage and environment limitation

Current hard enforcement is validated for the supported Cursor hook surface
listed above. Cursor environments do not all expose identical hooks; in
particular cloud-agent / early read-only surfaces may omit `postToolUse`,
`postToolUseFailure`, or after-file events. Those environments cannot claim
the same live mutation-enforcement guarantee. Unrecorded changes still fail
closed at Develop seal where provenance reconciliation observes them. This
is input to a later Client Adapter Capability Matrix. This Distribution does
not implement multi-client or Cursor-cloud portability in this patch.

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

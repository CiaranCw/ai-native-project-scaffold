# Project-local consumer installation — design

Productization of clone-and-use Scaffold for existing host repositories.
Installation is distribution lifecycle infrastructure, not a Skill.

Related: [FIRST_USE_WALKTHROUGH.md](FIRST_USE_WALKTHROUGH.md),
[../../docs/CONSUMER_INSTALLATION.md](../CONSUMER_INSTALLATION.md).

## Why

Frozen RC `d12a4cd84b615617f6de5a33f51889e5507b3807` returned
`SCAFFOLD_CONSUMER_INSTALLATION_CONTRACT_MISSING` on a real fresh-consumer
setup: four Skill packages and P5–P8 runtime existed, but a teammate clone
had no product-supported way to discover or execute them without a second
Distribution checkout and an operator-provided absolute path.

## Architectural clarification (not a blocker)

P1 said the Distribution MUST NOT be copied **wholesale** into a host.
That remains true:

- Do not vendor docs, tests, research notes, freeze/review artifacts, caches,
  or git history.
- Do vendor the **bounded consumer subset**: four Skill packages, P5–P8
  runtime modules, `scaffold_entry.py`, install provenance, and thin client
  adapters.

This is a defined product surface, not a dump of the Scaffold repository.

## Canonical project-local layout

```text
<project-root>/
  AGENTS.md                          human/project text preserved
                                     + optional MANAGED region
                                     scaffold-consumer
  .gitattributes                     human/project rules preserved
                                     + MANAGED scaffold-consumer-git
                                     region last (`-text` on install bytes)
  .cursor/skills/scaffold-understand/SKILL.md
  .cursor/skills/scaffold-develop/SKILL.md
  .cursor/skills/scaffold-test/SKILL.md
  .cursor/skills/scaffold-submit/SKILL.md
  (exactly four Cursor adapters; AGENTS.md is first-contact routing)
  .cursor/rules/scaffold-first-use.mdc
                                     Always Apply Cursor first-use rule
                                     (MANAGED; not a Skill)
  .cursor/hooks.json                 mixed-ownership; Scaffold owns only
                                     the scaffold-first-use fragment
  .agents/skills/<unrelated>/        NEVER owned or overwritten
  .scaffold/install/                 MANAGED consumer plane
    install.yaml                     pre-Adoption provenance
    .gitignore                       ignore pyc/cache only
    run.py                           local launcher
    cursor_first_use_hook.py         Cursor first-use adapter
    runtime/                         copy of Distribution src/*.py
      scaffold_p5/ … scaffold_p8/
      scaffold_entry.py
    packages/
      understand/ develop/ test/ submit/
    releases/
      installed.yaml                 selected release built from
                                     actual installed packages
  .scaffold/project.yaml             ABSENT until Adoption
  .scaffold/skills.lock              ABSENT until Adoption
```

`.scaffold/install/` is reserved product installation, distinct from
`.scaffold/runtime/` (ephemeral) and from Adoption records.

## Ownership

Fully managed consumer artifacts are **MANAGED** whole files, hashed by
raw SHA-256, traceable to a Scaffold release/commit:

- `.scaffold/install/**`
- `.cursor/skills/scaffold-understand|develop|test|submit/**`
- `.cursor/rules/scaffold-first-use.mdc`

Mixed-ownership host files are **MANAGED_REGION** or **MANAGED_JSON_FRAGMENT**:

`AGENTS.md`: insert or replace only the `scaffold-consumer` managed region.
Human text and an existing `agents-router` region are preserved. Whole-file
replace is forbidden. Human edits outside the region are not install drift.

`.gitattributes`: insert or replace only the `scaffold-consumer-git` region
and keep it last so `-text` wins over host `text=auto` / `eol=lf` rules.
Human Git attribute lines stay. Whole-file replace is forbidden. Git `-text`
may govern checkout of the whole host file; Scaffold integrity authority
covers only the managed region. The region also marks
`.cursor/rules/scaffold-first-use.mdc` and `.cursor/hooks.json` as `-text`.

`.cursor/hooks.json`: merge only the Scaffold `preToolUse` /
`postToolUse` / `postToolUseFailure` / `beforeShellExecution` /
`subagentStart` / `beforeMCPExecution` / `afterFileEdit` /
`afterTabFileEdit` entries identified as `fragment_id: scaffold-first-use`.
Do not claim unrelated JSON. Do not claim live mutation enforcement on
Cursor surfaces that omit those mutation hooks.

`.agents/skills/impeccable` and any other non-scaffold client skill: preserve.

## Provenance vs `skills.lock`

| Authority | When it exists | Meaning |
| --- | --- | --- |
| `.scaffold/install/install.yaml` | After install, before Adoption | What product bytes were installed |
| `.scaffold/skills.lock` | After Adoption lock publish | Expected Skill identities for this adopted host |

They MUST NOT substitute for each other. Install MUST NOT write `skills.lock`.
Adoption MUST NOT treat `install.yaml` as lock authority.

## Commands

From a Scaffold Distribution checkout (operator may know this path **only at
install/update time**):

```text
python src/scaffold_consumer.py import-project --host <project-root>
python src/scaffold_consumer.py install --host <project-root>
python src/scaffold_consumer.py update --host <project-root>
python src/scaffold_consumer.py verify --host <project-root>
python src/scaffold_consumer.py plan --host <project-root>
```

`import-project` is the ordinary teammate entry. It classifies the host and
reuses INSTALL / UPDATE / VERIFY / STATUS. It is not a fifth Skill and not
Adoption. `--host` is an operation-time locator only; it is not durable
project authority. A current VALID installation is `ALREADY_READY`.

`--distribution` defaults to the Distribution repository that contains the
invoked `src/scaffold_consumer.py`.

After installation, teammates run:

```text
python .scaffold/install/run.py verify
python .scaffold/install/run.py understand bootstrap
```

Approved Adoption apply uses the same launcher with `--approved --plan-digest <hex>`.
That flag is an APPLY REQUEST, not human provenance. The business-task text
is not that approval. On Cursor, Agent-originated apply is authorized only
by `beforeShellExecution` `permission=ask`. Other clients need an equivalent
adapter to claim hard enforcement.

First-use Cursor enforcement is documented in
[FIRST_USE_ENFORCEMENT_DESIGN.md](FIRST_USE_ENFORCEMENT_DESIGN.md).

## Update

Replace only whole-file MANAGED installation files and Scaffold managed
regions. Unrelated human-owned / client skills are untouched. Unexpected
digest drift of fully managed files or of a managed region fails closed
(no silent overwrite). Human edits outside `AGENTS.md` `scaffold-consumer`
and `.gitattributes` `scaffold-consumer-git` are preserved and are not
drift. Staging directory swap avoids a half-old/half-new tree being treated
as VALID. UPDATE of a pre-C01 five-adapter managed installation removes only
the obsolete managed generic `.cursor/skills/scaffold/` adapter. An
unmanaged file at that path is a collision, not a deletion target. UPDATE of
a pre-C02 installation adds the `.gitattributes` clone-stability region
without replacing human rules. UPDATE of C02 whole-file AGENTS.md /
`.gitattributes` provenance migrates to `regions:` when those managed
regions are intact, including when legitimate human edits exist outside the
regions. If a human Git rule was appended after the clone-stability region,
UPDATE repositions the intact region last and keeps the human rule.

## Verify

`VALID` | `DRIFTED` | `INCOMPLETE` | `INCOMPATIBLE` | `UNKNOWN`

Checks: runtime + four packages present, package identities, whole-file
digests for fully managed paths, managed-region digests for `AGENTS.md` and
`.gitattributes`, exactly four Cursor Scaffold adapters, no generic
`.cursor/skills/scaffold/` Skill, Git clone-stability policy present and
effective, manifest consistency, no operational absolute Distribution path.
An invalid managed adapter set is `INCOMPATIBLE` (fail closed).
A missing Git-attributes or AGENTS managed region is `INCOMPLETE` so UPDATE
can repair it. Missing first-use rule/hook/fragment is `INCOMPLETE` so an RC2
host can UPDATE. Human edits outside those regions, and unrelated hook
entries, are not `DRIFTED`. A later
human Git rule after the clone-stability region is `INCOMPATIBLE`; UPDATE
may move the intact region last without deleting the human rule.

## Fail-closed install

Unsafe / non-directory / out-of-root targets; host is the Distribution
itself; unmanaged collision on a managed path; invalid source packages;
source release pin digest mismatch.

## Uninstall

Not implemented in this closure. Future uninstall would remove only MANAGED
install files and the `scaffold-consumer` region, leaving human `AGENTS.md`
body and unrelated client skills.

## Internal-repository readiness

Installed bytes MUST be deterministic, reviewable, Git-friendly, free of
`__pycache__` / tests / freeze artifacts, and free of machine-specific
absolute runtime paths, so a later Consumer Pilot may commit them into
canonical Project-City’s internal repository. This task does not perform
that commit or any Project-City mutation.

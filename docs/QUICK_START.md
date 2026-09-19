# Internal Pilot Quick Start

Clone this Scaffold repository, import it into an existing project, then open
that **host** repository. After import, teammates do not need a second Scaffold
checkout, `PYTHONPATH` to SOURCE, or an absolute Distribution path. See
[CONSUMER_INSTALLATION.md](CONSUMER_INSTALLATION.md).

```text
git clone <Scaffold repository>
cd <Scaffold repository>
python src/scaffold_consumer.py import-project --host <project>
```

`--host .` is also supported. Import is the normal onboarding command. It
reuses INSTALL / UPDATE / VERIFY / STATUS. It does not adopt the project.

On a never-adopted host, ordinary business work is **not authorized** until
Understand bootstrap applies that exact Adoption Plan. `--approved
--plan-digest` is the apply-request spelling, not Git Commit or Git Push.
Only Git Commit and Git Push require a current explicit user instruction.
On Cursor-profile installs, Trusted-workspace project hooks are a client
adapter, not Core authority. See
[CONSUMER_INSTALLATION.md](CONSUMER_INSTALLATION.md) and
[implementation/FIRST_USE_ENFORCEMENT_DESIGN.md](implementation/FIRST_USE_ENFORCEMENT_DESIGN.md).

Open the project and speak naturally:

- “Where are we now, and what can I do next?”
- “Continue this project.”
- “Understand the current state and tell me what needs doing.”
- “Help me understand this project.”
- “Implement this feature and add the necessary tests.”
- “Only run the relevant tests.”
- “Review this change and prepare it for submission.”

The Agent maps those requests to existing Skills. Zero-context resume is
Understand `refresh` with `action=resume` and reads project-local records, not
chat history. Incremental understanding is Understand `refresh` with
`action=understand`. Physical observation decides the refresh scope;
Understand-produced completion receipts are required before a current-head
may become CURRENT. Receipts do not grant mutation authority; knowledge still
follows `project.yaml` ownership. Malformed canonical Task or Session
authority fail-closes resume to human recovery. There is not a fifth Skill or
a fifth routing engine.

The Agent may stop for explicit human action when:

- Task scope, acceptance, tests, or governance is materially uncertain;
- Repair target Stages cannot be mapped without guessing;
- Project Rules conflict with the request;
- repository currentness is stale, diverged, or unknown;
- Git Commit is requested (current explicit user instruction);
- Push is requested (always a separate current explicit user instruction).

When first attachment proposes persistent Adoption changes, the Agent previews
the Adoption Plan, then applies that exact `plan_id` / `plan_digest` when
machine preconditions still hold. “Adopt this project” or “Run Day-1
Bootstrap” authorizes entering Bootstrap and applying that generated Plan; it
is not Git Commit or Git Push. The Agent must still see `plan_id`,
`plan_digest`, mutation envelope, ownership changes, managed regions, and
preserved surfaces before apply.

Consumer UPDATE does not rewrite `skills.lock`. If Understand compatibility
is `UNKNOWN` because expected package identity differs from an installed
VALID package, continue with
`python .scaffold/install/run.py understand compatibility --action
lock_update --new-expected <json>` and apply that exact `--plan-digest`.
Do not edit `skills.lock` by hand.

When stopped, the Agent should explain what it observed, why it stopped, what
you need to decide, what approval would do, and what remains unchanged.

Current product path: import Scaffold into the host with one command, then a
fresh Agent discovers Skills from repository-local adapters. The
Distribution checkout is needed only at import/install/update time.

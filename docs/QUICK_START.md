# Internal Pilot Quick Start

Make this local Scaffold Distribution checkout available to the Agent together
with the project (for example, both workspace roots are visible and the
Distribution `src/` and `skills/` are loadable). There is not yet a one-click
installer or automatic client discovery.

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

- first attachment proposes persistent Adoption changes;
- a VALID host is `MIGRATION_REQUIRED` and a Migration Plan needs approval;
- Task scope, acceptance, tests, or governance is materially uncertain;
- Repair target Stages cannot be mapped without guessing;
- Project Rules conflict with the request;
- repository currentness is stale, diverged, or unknown;
- Submit needs current candidate-bound Commit authorization;
- Push is requested (Push authorization is always separate).

When first attachment proposes persistent Adoption changes, the Agent must
stop after preview. “Adopt this project” or “Run Day-1 Bootstrap” is
authorization to enter Bootstrap, not approval of the exact Adoption Plan
that preview generated. The human must see `plan_id`, `plan_digest`, mutation
envelope, ownership changes, managed regions, and preserved surfaces before
apply.

When stopped, the Agent should explain what it observed, why it stopped, what
you need to decide, what approval would do, and what remains unchanged.

Current internal-Pilot requirement: the operator must provide the known local
Distribution checkout/package path to the Agent. Cursor/Claude/Codex installers,
automatic Distribution discovery, and one-click teammate setup remain later
client/deployment work.

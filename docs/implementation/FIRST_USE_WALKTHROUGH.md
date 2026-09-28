# First-use walkthrough — project-local consumer installation

Trace of a real teammate scenario against the intended product, not against a
developer Distribution checkout. This is design authority for the installer.
It is not a fifth Skill.

## Scenario

A teammate:

1. clones an already Scaffold-enabled host repository;
2. opens that repository in Cursor;
3. knows nothing about Scaffold;
4. sends only:

   “按照 3C.md 帮我完善一下现在的 3C 功能，这次先把翻越做出来。”

No step may require `F:\NewResearch\ai-native-project-scaffold` or any other
operator Distribution path.

## Three planes (do not conflate)

| Plane | What lives there | When it appears |
| --- | --- | --- |
| Distribution | Canonical Scaffold release/source used at **install/update time** | Operator machine only |
| Project-local consumer | Committed MANAGED artifacts: runtime, four Skill packages, install provenance, thin client bridges | After install, before Adoption |
| Adoption / work | `project.yaml`, `skills.lock`, knowledge, Tasks, Sessions, Change Records | Only after Understand bootstrap + human Plan approval |

Installing Scaffold into a repository does **not** mean the project is
understood or adopted. `.scaffold/install/` existence is not Adoption.

## Fresh-Agent discovery chain

```text
clone host
  → open in Cursor
  → read repository-local AGENTS.md (human project rules + managed
    scaffold-consumer first-contact region)
  → discover exactly four Cursor adapters:
       scaffold-understand, scaffold-develop, scaffold-test, scaffold-submit
     (no generic .cursor/skills/scaffold/ Skill)
  → canonical four packages at .scaffold/install/packages/{understand,develop,test,submit}/
  → execute runtime via python .scaffold/install/run.py
       (run.py inserts .scaffold/install/runtime onto sys.path)
  → host is NOT_ADOPTED (no project.yaml / skills.lock)
  → ordinary feature request is NOT Adoption approval
  → Read / status / plain Understand bootstrap are allowed
  → Cursor first-use hook denies actual project mutation
    (operation identity, not path shape, determines Read authorization)
  → Agent must run Understand bootstrap
  → preview Adoption Plan; NEEDS_HUMAN means STOP
  → Agent issues the digest-bound apply command as an APPLY REQUEST
  → Cursor beforeShellExecution returns allow (official lifecycle command);
    first-time Adoption is Agent-autonomous, no interactive confirmation
  → the apply records its authorization basis (default standing_policy)
    in the Adoption Session; it is not Git Commit or Git Push
  → host becomes ACTIVE / ESTABLISHED_HOST
  → ordinary HUMAN_OWNED business mutation is still denied until Develop
    has a current Task Book, mutable Stage, OPEN Session, and current
    execution pointer
  → required route: `python .scaffold/install/run.py enter develop
       --intake-json-b64 <envelope>`
    Intake creates no Develop Session.
    Then `python .scaffold/install/run.py develop session --task-id
       <task-id>` opens the execution window and writes the current
       execution pointer. Close with `develop seal` or `develop abort`.
  → later Test / Submit use the same installed packages + runtime
```

Cursor project-skill convention used here is the documented location
`.cursor/skills/<name>/SKILL.md`. This installer does not invent undocumented
Cursor syntax and does not take ownership of unrelated skills such as
`.agents/skills/impeccable`.

## What the Agent must be able to determine locally

| Question | Repository-local answer |
| --- | --- |
| Does Scaffold exist? | `AGENTS.md` `scaffold-consumer` region plus `.scaffold/install/install.yaml` and the four Cursor adapters |
| Where are the four Skills? | `.scaffold/install/packages/{understand,develop,test,submit}/` |
| Which entrypoint governs normal work? | `python .scaffold/install/run.py` and `src/scaffold_entry.py` inside the vendored runtime |
| How does first-use Adoption begin? | Understand `bootstrap`; preview is not apply; `NEEDS_HUMAN` means STOP |
| Is ordinary mutation authorized while NOT_ADOPTED? | No. That is a mandatory authorization boundary, not advice |
| Does `--approved --plan-digest` prove a human approved? | No. That spelling is an APPLY REQUEST. First-time Adoption is Agent-autonomous lifecycle work: `beforeShellExecution` returns `permission=allow` for the exact digest-bound apply, and the authorization basis (default `standing_policy`) is persisted in the Adoption Session. Git Commit and Git Push each require a separate explicit user instruction |
| What enforces that on Cursor? | Always Apply `.cursor/rules/scaffold-first-use.mdc` plus project hooks; digest-bound apply is allowed as an official lifecycle command; other clients need their own adapter |
| How does runtime execute? | Vendored `.scaffold/install/runtime/` — no PYTHONPATH to SOURCE |
| How is package identity verified? | `install.yaml` digests + `load_package` on installed packages; later `skills.lock` after Adoption |
| How do Develop/Test/Submit proceed? | Same installed packages; Repair remains Develop |
| How does first Task authority get created after Adoption? | Installed `enter develop --intake-json-b64 <envelope>` (or `develop intake --intake-json-b64`) calls `DevelopEngine.intake`. Intake creates no Develop Session. Bare `enter develop` without a proposal fails closed. Do not write `.scaffold/tasks/` directly |
| How does Develop execution start? | `python .scaffold/install/run.py develop session --task-id <task-id>` opens a canonical OPEN Session, binds `.scaffold/runtime/develop-execution.yaml`, and a mutable Stage. Close with `develop seal` or `develop abort`. Deleting the pointer cannot resurrect editor authority from leftover OPEN history. |
| What may an OPEN Session mutate? | Only after the current execution pointer is bound. Then only the current Task's product scope and explicit supporting scope, and only paths recorded through the authorized client mutation events. Not governance, not unrelated paths, not arbitrary shell, not unexplained same-scope files |
| Project ownership vs Task scope | `project.yaml` ownership is not Task permission. Task `scope.paths`/`modules` are product scope. Task `scope.supporting_paths` are supporting delta and do not become product ownership |

## Non-goals of this walkthrough

- No Project-City 3C/Vault/Babylon product knowledge in Scaffold Core.
- No fifth Skill (Install/Bootstrap/Repair/Consumer/first-use-guard).
- Cursor rules/hooks are client adapters, not Skills.
- No absolute Distribution path in host authority.
- No false READY_FOR_REVIEW / Bootstrap complete / project understood state.

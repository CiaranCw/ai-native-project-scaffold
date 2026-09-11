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
  → Cursor first-use hook denies project mutation
  → Agent must run Understand bootstrap
  → preview Adoption Plan; NEEDS_HUMAN means STOP
  → Agent may issue the digest-bound apply command only as an APPLY REQUEST
  → Cursor beforeShellExecution returns ask (FORCE_PROMPT); the Agent cannot
    self-approve that prompt
  → only after the user confirms that Cursor permission may the apply run
  → later Develop / Test / Submit use the same installed packages + runtime
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
| How does first-use Adoption begin? | Understand `bootstrap`; preview is not approval; `NEEDS_HUMAN` means STOP |
| Is ordinary mutation authorized while NOT_ADOPTED? | No. That is a mandatory authorization boundary, not advice |
| Does `--approved --plan-digest` prove a human approved? | No. That spelling is an APPLY REQUEST. On Cursor, Agent-originated apply is authorized only by `beforeShellExecution` `permission=ask` |
| What enforces that on Cursor? | Always Apply `.cursor/rules/scaffold-first-use.mdc` plus project hooks; `beforeShellExecution` ASK / FORCE_PROMPT; other clients need their own adapter |
| How does runtime execute? | Vendored `.scaffold/install/runtime/` — no PYTHONPATH to SOURCE |
| How is package identity verified? | `install.yaml` digests + `load_package` on installed packages; later `skills.lock` after Adoption |
| How do Develop/Test/Submit proceed? | Same installed packages; Repair remains Develop |

## Non-goals of this walkthrough

- No Project-City 3C/Vault/Babylon product knowledge in Scaffold Core.
- No fifth Skill (Install/Bootstrap/Repair/Consumer/first-use-guard).
- Cursor rules/hooks are client adapters, not Skills.
- No absolute Distribution path in host authority.
- No false READY_FOR_REVIEW / Bootstrap complete / project understood state.

# How to install Scaffold into an existing project

Project-local consumer installation. This is product/distribution lifecycle
infrastructure, **not** a fifth Skill. Exactly four Skills remain:
Understand, Develop, Test, Submit. Repair remains a Develop mode.

Design: [implementation/CONSUMER_INSTALLATION_DESIGN.md](implementation/CONSUMER_INSTALLATION_DESIGN.md).
First-use chain: [implementation/FIRST_USE_WALKTHROUGH.md](implementation/FIRST_USE_WALKTHROUGH.md).

## How do I install Scaffold into an existing project?

From a Scaffold Distribution checkout (you need this path **only now**):

```text
python src/scaffold_consumer.py install --host <project-root>
```

The Distribution root is inferred from the invoked script. You may pass
`--distribution <distribution-root>` explicitly. Preview without writing:

```text
python src/scaffold_consumer.py plan --host <project-root>
```

Install fails closed if the target is unsafe, is the Distribution itself,
would overwrite unmanaged human-owned content, or if source Skill packages
are invalid.

## What files will be committed?

MANAGED consumer artifacts:

- `.scaffold/install/` — runtime, four Skill packages, `install.yaml`, `run.py`
- `.cursor/skills/scaffold-{understand,develop,test,submit}/` — exactly four Cursor adapters
- a bounded managed region in `AGENTS.md` if that file is safe to integrate
  (this region is first-contact routing; there is no generic `.cursor/skills/scaffold/` Skill)
- a bounded managed region in `.gitattributes` that sets `-text` on MANAGED
  install bytes so a normal `git add` / `git commit` / `git clone` cannot
  rewrite those hashes
- a bounded managed region in `.gitattributes` that sets `-text` on MANAGED
  install bytes so Git checkout cannot rewrite EOL

Do **not** commit `__pycache__`, `.pyc`, test/review zips, or freeze JSON from
the Distribution. A later teammate clone of **this host repository** is enough.

## How does a fresh Agent discover it?

Repository-local `AGENTS.md` carries a managed `scaffold-consumer` region.
That region is first-contact routing: Scaffold is installed, installation is
not Adoption, ordinary work on a never-adopted host starts with Understand
bootstrap, and the launcher is `python .scaffold/install/run.py`.

Cursor project skills live at `.cursor/skills/<name>/SKILL.md` (documented
Cursor convention). Scaffold installs **exactly four** adapters:

- `.cursor/skills/scaffold-understand/SKILL.md`
- `.cursor/skills/scaffold-develop/SKILL.md`
- `.cursor/skills/scaffold-test/SKILL.md`
- `.cursor/skills/scaffold-submit/SKILL.md`

There is no generic `.cursor/skills/scaffold/` Skill. Unrelated skills such as
`.agents/skills/impeccable` are left alone.

The Agent does not need a long Scaffold-specific prompt or a Distribution
path.

## Where is the runtime?

`.scaffold/install/runtime/` (vendored `scaffold_p5` … `scaffold_p8` plus
`scaffold_entry.py`). Launch with:

```text
python .scaffold/install/run.py
```

## Does it require the Scaffold source repo afterward?

No. After install, the host is self-contained. Do not set `PYTHONPATH` to a
developer checkout.

## How do I verify installation?

```text
python .scaffold/install/run.py verify
```

or, from Distribution:

```text
python src/scaffold_consumer.py verify --host <project-root>
```

Results: `VALID`, `DRIFTED`, `INCOMPLETE`, `INCOMPATIBLE`, `UNKNOWN`.
VERIFY fails closed if the managed Cursor adapter set is not exactly the four
Scaffold adapters above, including when a generic `.cursor/skills/scaffold/`
Skill is still present. Unrelated project skills are not counted as Scaffold
Skills. VERIFY also fails closed if the clone-stability Git-attributes policy
is missing, malformed, or (in a Git repository) not actually effective
(`git check-attr` must report `text: unset` for managed consumer paths).
Human edits outside the `AGENTS.md` and `.gitattributes` managed regions
do not fail VERIFY. Tampering inside those regions does.

## How do I update it?

From a newer Distribution checkout:

```text
python src/scaffold_consumer.py update --host <project-root>
```

Update rewrites only MANAGED install files and Scaffold managed regions.
Unexpected whole-file or managed-region drift fails closed. Human edits
outside `AGENTS.md` / `.gitattributes` managed regions are preserved.
Unrelated human-owned files and client skills are not modified. A pre-C01
managed generic `.cursor/skills/scaffold/` adapter is removed on UPDATE; an
unmanaged file at that path is not deleted.

## Which files are MANAGED?

Whole-file MANAGED paths are recorded in `.scaffold/install/install.yaml`
`files:` (runtime, packages, `run.py`, four Cursor adapters). Mixed-ownership
host files are recorded in `regions:` as `ownership: MANAGED_REGION`:

- `AGENTS.md` region `scaffold-consumer`
- `.gitattributes` region `scaffold-consumer-git`

Only those regions are Scaffold-owned. Human/project text outside them is
not install drift. They remain traceable to the installed Scaffold
release/commit.

## What happens before/after Adoption?

Install does **not** adopt the project. After install the host stays
`NOT_ADOPTED`: no `project.yaml`, no `skills.lock`, no Bootstrap complete,
no READY_FOR_REVIEW.

First-use: Understand bootstrap previews an Adoption Plan and stops for
explicit human approval of that exact plan digest. Only then does Scaffold
write Adoption/work-plane records. `skills.lock` is that later expected-identity
authority; `install.yaml` is product provenance and does not replace it.

## How do I commit it into an internal project repository?

Commit the MANAGED install tree and adapters like ordinary reviewable source.
Do not include caches or machine-specific absolute paths. After Consumer
Pilot stabilization, the accepted installation is expected to be committed
into canonical Project-City’s **internal** repository by a dedicated setup
step — not by this Distribution task.

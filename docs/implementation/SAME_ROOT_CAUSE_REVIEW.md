# Same-root-cause review — consumer installation

Reviewed against the partial-product failures listed for this closure.
No product patch after freeze.

| Failure mode | Status | Evidence |
| --- | --- | --- |
| Agent can discover Scaffold and still mutate a NOT_ADOPTED host | Closed | Client-neutral `BLOCK_PROJECT_MUTATION`; Cursor Always Apply rule + `failClosed` pre-tool hooks deny Write/Delete/arbitrary mutating Shell/Task/MCP before execution; FU01–FU30 |
| First-use gate overblocks Read / status / plain bootstrap (PC-CONSUMER-002) | Closed after B2 | Operation identity, not path shape, determines Read authorization. Explicit `beforeReadFile`/Read/ReadFile ALLOW. Nameless `file_path` DENY. Path-shaped Delete/unknown DENY. Status/preview bootstrap ALLOW. Exact apply ASK |
| Agent self-approves Adoption via `--approved --plan-digest` after reading the digest | Closed | That spelling is an APPLY REQUEST. `beforeShellExecution` returns `ask` / FORCE_PROMPT; no-user path leaves the host NOT_ADOPTED (PC-CONSUMER-001-B2; FU31–FU39) |
| Soft AGENTS wording treated as optional | Closed | Normative first-use region plus structural hook; anti-rationalization language; ordinary user task is not approval |
| Agent deletes/rewrites hook/rule/AGENTS to bypass first-use | Closed | Those mutation tools are themselves denied while NOT_ADOPTED (FU16–FU18) |
| Existing host `.cursor/hooks.json` overwritten | Closed | `MANAGED_JSON_FRAGMENT` ownership; unrelated hooks survive INSTALL/UPDATE (FU19–FU22) |
| Runtime is self-contained but fresh Agent cannot discover entrypoint | Closed | AGENTS `scaffold-consumer` first-contact region plus exactly four Cursor adapters (`scaffold-understand/develop/test/submit`) |
| Generic `.cursor/skills/scaffold/` fifth Skill | Closed | Adapter set is exactly four; VERIFY fails closed; UPDATE removes only that obsolete managed adapter |
| AGENTS.md / `.gitattributes` hashed as whole-file MANAGED | Closed | `install.yaml` `regions:` records `MANAGED_REGION` digests only; CIC03 human-edit / C02-migration tests |
| Install works but Git clone rewrites MANAGED hashes | Closed | Root `.gitattributes` managed region last; `-text` on `.scaffold/install/**`, four Cursor adapters, `AGENTS.md`, `.gitattributes`; CIC02 Git matrix; CIC03 reduced matrix |
| Install works but re-clone breaks | Closed | CI-03/CI-24/CI-25 copy-only-host then `run.py verify`; CIC02 commit/clone byte equality |
| Install works only because PYTHONPATH leaks SOURCE | Closed | Subprocess verify/bootstrap with PYTHONPATH unset |
| Install overwrites existing AGENTS.md | Closed | Bounded `scaffold-consumer` region; CI-07; Project-City dry-run preserves PZ body |
| Install overwrites unrelated `.agents/skills` | Closed | Installer never writes `.agents/`; CI-08; dry-run leaves impeccable |
| Install marks host adopted before Adoption | Closed | No `project.yaml` / `skills.lock`; host_class `NOT_ADOPTED`; CI-05/CI-26 |
| Update silently overwrites drift | Closed | CI-15 fails closed on managed drift |
| Multiple competing Skill identity authorities | Closed | `install.yaml` is pre-Adoption provenance; `skills.lock` remains Adoption lock (CI-27) |
| Machine-specific absolute runtime paths | Closed | Verify regex + CI-20; `run.py` uses `__file__` |
| Large caches/tests/audit data vendored | Closed | CI-19; copy skips `__pycache__` / tests / freeze artifacts |

Additional checks:

- Mixed-ownership host files are `AGENTS.md`, `.gitattributes`, and the
  Scaffold fragment of `.cursor/hooks.json`. Cursor adapters, the Always Apply
  first-use rule, `run.py`, packages, runtime, and the hook executable remain
  whole-file MANAGED.
- Exactly four Skills; no Install/Bootstrap/Repair/Consumer/first-use Skill (CI-28, FU23–FU24).
- Skill package bytes/identities unchanged (Correction 05 identities).
- Canonical Project-City and consumer-pilot were not installed into.
- Agent2 remains not started (out of scope; no Project-City mutation).

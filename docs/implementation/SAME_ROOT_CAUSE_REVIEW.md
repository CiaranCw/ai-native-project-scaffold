# Same-root-cause review — consumer installation

Reviewed against the partial-product failures listed for this closure.
No product patch after freeze.

| Failure mode | Status | Evidence |
| --- | --- | --- |
| Agent can discover Skills but runtime still requires Distribution | Closed | Canonical packages and `run.py` use `.scaffold/install/runtime/` only |
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

- Mixed-ownership host files are only `AGENTS.md` and `.gitattributes`. Cursor adapters, `run.py`, packages, and runtime remain whole-file MANAGED.
- Exactly four Skills; no Install/Bootstrap/Repair/Consumer Skill (CI-28).
- Skill package bytes/identities unchanged (Correction 05 identities).
- Canonical Project-City and consumer-pilot were not installed into.
- Agent2 remains not started (out of scope; no Project-City mutation).

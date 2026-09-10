# Gate-1B-C03 inventory enumeration

Closes the residual G1B-T1-001 operational-boundedness gap: digest
inventory (`observe_inventory` / `_walk` / `durable_inventory` /
`list_files`) now uses the same streaming directory primitive as
`bounded_metadata_walk`.

## Shared primitive

`_directory_scandir` → `_stream_directory_names`

- iterator-backed (`os.scandir`)
- count each yield before retaining the name as authority
- at most `ENUMERATION_OVERFLOW_PROBE` extra yield after `max_entries`
- overflowing directory prefix is discarded (not sorted, not product truth)
- scanner closed via `with`

## Classification of remaining P5 directory listing

| Location | Class | Why |
| --- | --- | --- |
| `inventory._walk` | A → fixed | Was `sorted(os.listdir)`; now `_stream_directory_names`. |
| `inventory` `cheap_count` | A → removed | Cosmetic `bounded_file_count` no longer lists EXCLUDED/BOUNDED children. Count is `null` unless already known from a fully streamed directory. |
| `discovery._modules_fact` | A → fixed | Immediate children of an already-authorized source area now stream under the same `max_entries` budget. Overflow → modules `UNKNOWN`. |
| `discovery.resolve_existing` | B | Case-insensitive match of **one** path component in the current directory while resolving a named candidate. Not recursive whole-project inventory. Bounded by path depth, not inventory fanout. |
| `currentness._files_under` `os.walk` | B | Active-host knowledge currentness over **declared** module prefixes after Adoption. Not Initial Adoption digest inventory. |
| `refresh._business_files` `rglob` | B | Ownership refresh helper over the four declared source-root names (`src`/`lib`/`app`/`pkg`). Not digest inventory. |
| `migration._durable_directory_digest` `rglob` | B | Digest of one already-selected package/distribution directory. Not host inventory walk. |
| `resume` `glob("*.yaml")` | B | Fixed `.scaffold` runtime folder listing. |

No remaining class-A recursive/inventory discovery path uses `os.listdir`,
`list(os.scandir(...))`, or `sorted(os.scandir(...))`.

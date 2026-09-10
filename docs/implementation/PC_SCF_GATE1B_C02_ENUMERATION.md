# Gate-1B-C02 — Operational enumeration bound

One-blocker correction. Closes G1B-T1-001. Does not reopen T1-002 / T2 / T3.
Does not repair G1B-T2-SHOULD-001.

## Finding → root cause → fix

| Finding | Root cause | Fix |
| --- | --- | --- |
| G1B-T1-001 | `bounded_metadata_walk` used `sorted(os.listdir(directory))`, so a wide directory was fully enumerated before `max_entries` was checked. | Stream `os.scandir` via `_directory_scandir`. Count each yield against the budget before the name is stored. At most one overflow probe for the whole walk. Overflowing-directory prefixes are discarded. Exhausted directories are sorted only after iterator end. |

## Operational rule

`remaining = max_entries - entries_enumerated`

A directory is opened only when `remaining > 0`. The scanner may yield at most `remaining + 1` names. The `+1` overflow probe sets `TRUNCATED` and stops the walk. Pending directories are not opened after global exhaustion.

Call sites remain the shared primitive: discovery test-tree, Adoption preserve-docs, host_state nested-workspace.

Truncation truth from C01 is unchanged: test discovery `UNKNOWN`, preservation Apply blocked, nested-workspace `truncated` not verified `absent`.

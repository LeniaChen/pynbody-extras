# History

[English](README.md) | [简体中文](README.zh-CN.md)

This directory is the permanent, compact ledger of completed work items. It
keeps `docs/work/` small without losing the decisions, acceptance criteria, or
handoff notes: those stay in the commit that last contained the full item.

## Layout

```text
docs/history/
  2026-10.md          # English ledger for one month
  2026-10.zh-CN.md    # Chinese ledger for the same month
```

One file per month, always as an English/Chinese pair. One row per archived
item. Do not create a yearly file.

## What a row means

```markdown
| 2026-10-21 | BUG-0001 | bug | Execution tree renders the full graph | [2088326](...) | [work item](...) | [#21](...) |
```

- `Commit` points at the last commit that still contains
  `docs/work/<ID>/`.
- `Details` points at the work-item directory in that same commit.
- `PR` points at the pull request that completed the item.

The deletion commit must not be used as the `Commit` link: the work item no
longer exists there.

## Archiving

The item must already be committed with `status: done` and a `completed` date:

```bash
make archive-item ID=BUG-0001
```

The command appends one row to both language files for the completion month,
deletes `docs/work/<ID>/`, and regenerates `docs/work/INDEX.md`. Review and
commit the result as a separate commit.

## Rules

- IDs are never reused. `new_work_item.py` scans both active and archived IDs.
- Reopening an item means a new ID with `related: ["OLD-ID"]`.
- Do not hand-edit rows except to correct a broken link; the archive script is
  the normal writer.
- Keep the English and Chinese tables in the same order with the same IDs and
  commit SHAs.

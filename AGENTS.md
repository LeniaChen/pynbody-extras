# Agent guide

This file is the entry point for any AI agent working in this repository.
Read it first, then follow the reading order below.

## Read before changing code

1. `CONTEXT.md` — glossary, architecture invariants, and where each layer lives.
   Use its vocabulary in issues, tests, and PRs.
2. `docs/work/INDEX.md` — find the work item for the task, then read its
   `meta.json`, `en.md`/`zh-CN.md`, and the last `handoff.md` entry.
3. The tests for the area — they encode the public contract.

## Environment

```bash
make setup     # uv-managed .venv, all extras, git hooks
make check     # lint + typecheck + fast tests (target: under a minute)
```

Do not install project dependencies globally. `tests/conftest.py` runs pytest
from the repository root, so `testdata/...` paths are stable.

## Commands

| Command | Purpose |
| --- | --- |
| `make test` | fast loop; excludes `data` and `slow` markers |
| `make test-all` | full suite; first run downloads about 1.1 GB of testdata |
| `make test-data` | only the data-backed tests |
| `make cpp-test` | native C++ tests; needs `g++` |
| `make format` | `ruff format ./pynbodyext` |
| `make check` | lint + typecheck + fast tests |
| `make docs-check` | validate work-item pairs, metadata, and index |
| `make work-item TYPE=bug TITLE_EN="..." TITLE_ZH="..."` | create a bilingual item |
| `make archive-item ID=BUG-0001` | archive a `done` item into `docs/history/` |

## Workflow

1. Start from a GitHub issue labelled `ready-for-agent`, or from the spec that
   defines the requirement.
2. Restate the acceptance criteria as a failing test. Run it and confirm it is
   red for the expected reason.
3. Implement the smallest change that makes it green.
4. Keep existing tests intact. If a requirement really changed, update the
   spec or ADR first and say so in the PR.
5. Run `make check`; run `make test-all` when touching data paths, native code,
   or public behavior.
6. Update both `en.md` and `zh-CN.md`, set `meta.json.status`, and append a
   `handoff.md` entry before opening the PR.
7. Open a PR with the template and paste the red -> green evidence.
8. After the retention window, archive a `done` item with
   `make archive-item ID=...`; the history row points at the last commit that
   still contains the full work item.

## Guardrails

- Architecture changes (`pynbodyext/core/`, `cpp/`, import layers) need human
  review and a recorded decision.
- Never edit a test only to make it pass. Never delete or skip a failing test
  without an explicit requirement change.
- Never commit `testdata/`, `.venv/`, `build/`, `dist/`, coverage output, or
  secrets.
- Keep `en.md` and `zh-CN.md` in sync; the docs check enforces pairing and IDs,
  not translation quality.
- Never reuse a work-item ID, including IDs that have been archived into
  `docs/history/`.
- Do not add a dependency without updating `pyproject.toml` and `uv.lock`
  together.
- If a task is ambiguous about architecture, stop and ask rather than guessing.

## Where things live

| Path | Contents |
| --- | --- |
| `pynbodyext/core/` | calculator DAG, bins, result store |
| `pynbodyext/plot/` | image processing and display |
| `pynbodyext/gravity/` | thin Python API over the native solver |
| `cpp/` | pybind11 native implementation |
| `tests/` | unit, contract, and data-backed tests |

## Repository conventions

- **Issue tracker:** GitHub Issues.
- **Triage labels:** `needs-triage`, `needs-info`, `ready-for-agent`,
  `ready-for-human`, `wontfix`.
- **Domain docs:** `CONTEXT.md` is the glossary and the architecture invariants.

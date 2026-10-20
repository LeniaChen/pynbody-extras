## 2026-10-20 — Codex @ workstation

- State: ready
- Done: reproduced the one-line execution tree; traced it to the second
  `children(root)` call in `tree_lines()` and the stateful callback in
  `ResultQuery.execution_tree()`.
- Next: add the regression test, then make `tree_lines()` evaluate
  `children(root)` once and/or make the execution-tree callback idempotent.
- Commands: `make test`; the reproduction is in `en.md` / `zh-CN.md`.
- Failing test: none yet; the regression test is the next step.
- Blockers: none.
- Files: `pynbodyext/core/calculate/display.py`,
  `pynbodyext/core/calculate/result/query.py`,
  `tests/test_calculate_render.py`.
- Env: Python 3.11.9 / uv 0.9.17 / pynbody 2.8.0.

## 2026-10-20 — Claude @ cloud session

- State: review
- Done: added regression tests in `tests/test_calculate_render.py`
  (`tree_lines` calls `children` at most once per line; full execution tree;
  `max_depth=1` truncation; a shared subtree expanded once; the rich card's
  Execution tree `<pre>`). Fixed `tree_lines()` to evaluate `children(root)`
  once, and moved the "repeat occurrence" decision in
  `ResultQuery.execution_tree()` from `children_of` into `label`.
- Next: run `make check` and `make test-all` with the project environment;
  paste the red -> green output into the PR; tick the acceptance criteria and
  fill `Outcome` when merged.
- Commands: `make check`; `make test-all`;
  `.venv/bin/python -m pytest tests/test_calculate_render.py -k "execution_tree or tree_lines"`.
- Failing test: red -> green verified only for
  `test_tree_lines_asks_for_each_lines_children_at_most_once`, by loading
  `display.py` alone (old: `children("root")` called twice; new: pass). The
  session could not install pynbody (no PyPI access), so the
  `make_pipeline()`-based tests and package-wide `mypy` have not run yet.
- Blockers: none in the code; the full suite still needs a run.
- Files: `pynbodyext/core/calculate/display.py`,
  `pynbodyext/core/calculate/result/query.py`,
  `tests/test_calculate_render.py`, `docs/work/BUG-0001/*`.
- Env: Python 3.13 (isolated `display.py` harness) / ruff 0.16.9 / mypy 2.3.1;
  pynbody not installed.

## 2026-10-20 — Claude @ cloud session

- State: review
- Done: first local run (macOS, Python 3.11.7): 4 of 5 new tests passed;
  `test_execution_tree_truncates_like_the_node_tree` failed because the test
  assumed `max_depth=1` shows the root's children. In this codebase
  `max_depth=1` folds everything under the root (2 lines, matching
  `node_tree`). The test now checks `max_depth=1` (2 lines) and
  `max_depth=2` (5 lines) against the node tree.
- Next: re-run the five tests, then `make lint && make test && make docs-check
  && make test-all`.
- Failing test: none expected.
- Blockers: `make typecheck` reports 22 mypy errors, all in files this item
  does not touch (gravity, store, plot/image, bins, transforms); likely
  pre-existing stub drift, to be tracked separately.
- Files: `tests/test_calculate_render.py`, `docs/work/BUG-0001/*`.
- Env: Python 3.11.7 / pytest 9.0.2 (user's Mac).

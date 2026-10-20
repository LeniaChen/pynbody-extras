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

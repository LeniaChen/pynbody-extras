## 2026-10-20 — Claude @ cloud session

- State: ready
- Done: opened from the user's `make test` run after BUG-0001 merged
  (797 passed / 6 failed / 3 skipped). Confirmed there is no `_native*.so` in
  the tree or `.venv`, so `GRAVITY_NATIVE_AVAILABLE` is `False`; `vcirc`'s
  `condition` ignores that, and `tests/test_bins_vcirc.py` has no skip guard.
- Next: write the "extension missing" test (monkeypatch), add the skip guard,
  then gate or wrap the `vcirc` import.
- Commands: `.venv/bin/python -m pytest tests/test_bins_vcirc.py`;
  `.venv/bin/python setup.py build_ext --inplace` (to see why the build fails).
- Failing test: the three tests in `tests/test_bins_vcirc.py`.
- Blockers: none for the gating fix; the macOS build question is separate.
- Files: `pynbodyext/core/calculate/bins/result.py`,
  `tests/test_bins_vcirc.py`, `pynbodyext/util/deps.py`.
- Env: macOS / Python 3.11.7 / pytest 9.0.2 / pynbody 2.3.3; no native
  extension.

## 2026-10-20 — Claude @ cloud session

- State: draft
- Done: opened from BUG-0003's open question. `setup.py` builds
  `pynbodyext._native` with `-fopenmp` and `optional=True`; no `_native*.so`
  exists on the user's Mac.
- Next: on the Mac, run `.venv/bin/python setup.py build_ext --inplace` and
  paste the compiler error into `Actual behavior`; then confirm the cause and
  move to `ready`.
- Commands: `.venv/bin/python setup.py build_ext --inplace 2>&1 | tail -40`;
  `clang++ --version`; `brew list libomp`.
- Failing test: none; gravity tests skip without the extension.
- Blockers: needs the compiler output from macOS.
- Files: `setup.py`, `cpp/`, `README.md`, `README.zh-CN.md`.
- Env: macOS (Apple Silicon) / Python 3.11.7.

## 2026-10-20 — Claude @ cloud session

- State: draft
- Done: first reproduction attempt failed before compiling:
  `.venv/bin/python setup.py build_ext --inplace` ->
  `ModuleNotFoundError: No module named 'setuptools'` (uv venvs do not ship
  setuptools; it is only a `[build-system]` requirement). Updated
  Reproduction to supply setuptools and pybind11 via `uv run --with`.
- Next: run the new command on the Mac and paste the compiler error.
- Commands: `uv run --with setuptools --with pybind11 python setup.py build_ext --inplace 2>&1 | tail -60`.
- Failing test: none.
- Blockers: still needs the compiler output.
- Files: `docs/work/BUG-0004/*`.
- Env: macOS / `.venv` with pybind11 3.1.0, no setuptools.

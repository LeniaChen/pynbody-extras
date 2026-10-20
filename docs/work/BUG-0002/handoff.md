## 2026-10-20 — Claude @ cloud session

- State: draft
- Done: opened from the user's `make test` run after BUG-0001 merged
  (797 passed / 6 failed / 3 skipped). Traced the three SPH failures to the
  locked pynbody 2.3.3: the kernel API (`get_value(d=r/h)` only) and the
  `to_3d_grid` z sizing that uses `ny`.
- Next: answer the open questions (pynbody floor; option A or B), then set
  `ready`.
- Commands: `.venv/bin/python -m pytest tests/test_bins_sph_render.py -k "volume_render or unequal_z"`.
- Failing test: the three tests named in `en.md`, on pynbody 2.3.3.
- Blockers: maintainer decision on the pynbody floor.
- Files: `tests/test_bins_sph_render.py`, `pyproject.toml`, `uv.lock`,
  `pynbodyext/core/calculate/bins/_pynbody_render.py`,
  `pynbodyext/util/deps.py`.
- Env: macOS / Python 3.11.7 / pytest 9.0.2 / pynbody 2.3.3.

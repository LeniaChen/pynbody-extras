# BUG-0002: SPH 3-D render tests fail against the locked pynbody 2.3.3

## Context

`make test` on a fresh `make setup` environment (macOS, Python 3.11.7) fails
three tests in `tests/test_bins_sph_render.py`. `uv.lock` resolves `pynbody`
to **2.3.3** for Python >= 3.11 (and 2.0.0 for 3.10), while `pyproject.toml`
only asks for `pynbody>=2.0`. The tests, and one production behaviour, assume a
newer pynbody: the BUG-0001 handoff recorded pynbody 2.8.0 on the machine where
the suite passed.

## Goal

The locked environment that `make setup` creates passes `make test`, and a
3-D `sph_render` with `nz != ny` is never silently wrong.

## Actual behavior

```text
FAILED tests/test_bins_sph_render.py::test_a_volume_render_places_the_kernel_on_the_cell_grid
  AttributeError: 'CubicSplineKernel' object has no attribute 'value'
FAILED tests/test_bins_sph_render.py::test_a_volume_render_matches_a_direct_kernel_sum
  AttributeError: 'CubicSplineKernel' object has no attribute 'value'
FAILED tests/test_bins_sph_render.py::test_an_unequal_z_resolution_renders_the_grid_it_was_asked_for
  assert (np.int64(0), ..., np.int64(0)) == (2, 3, 2)
```

Two separate causes:

1. **Kernel API (tests only).** pynbody 2.3.3 kernels have
   `get_value(d, h=1)`, where `d` is already `r / h` and the input is a
   scalar. Lines 341, 369 and 403 call `kernel.value(distance, h)` with a
   physical distance (line 369 passes an array). Line 260 of the same file still
   uses `get_value(r / h)`, so the file mixes the two APIs.
2. **`to_3d_grid` z sizing (production).** In pynbody 2.3.3 `to_3d_grid` sizes
   z pixels with `ny`. For a grid of `(4, 6, 3)` cells, the particle in cell
   `(2, 3, 2)` lands at `(0, 0, 0)`. The test says the warning for this
   upstream bug was removed because it "is fixed", which is true only for newer
   pynbody. On 2.3.3, `bins.sph_render[...]` with `nz != ny` returns a wrong
   grid **without a warning**.

## Expected behavior

- `make setup && make test` passes with the versions in `uv.lock`.
- With any pynbody that `pyproject.toml` allows, a 3-D render with `nz != ny`
  is either correct or warns (or raises) that it is not.

## Reproduction

```bash
make setup
.venv/bin/python -c "import pynbody; print(pynbody.__version__)"   # 2.3.3
.venv/bin/python -m pytest tests/test_bins_sph_render.py -k "volume_render or unequal_z"
```

## Non-goals

- Changing the SPH view's conventions or the `_pynbody_render` adapter's
  positional signatures (pinned by `tests/test_pynbody_render_contract.py`).
- Supporting pynbody 1.x.

## Acceptance criteria

- [ ] `pyproject.toml` and `uv.lock` agree on a pynbody floor that the suite
      actually passes on, or the suite passes on every pynbody the floor admits.
- [ ] The three tests above pass in the environment `make setup` creates.
- [ ] `tests/test_bins_sph_render.py` uses one kernel-evaluation helper, not a
      mix of `get_value` and `value`.
- [ ] With a pynbody whose `to_3d_grid` has the z-sizing bug, a 3-D render
      with `nz != ny` warns or raises; a test covers this (or the floor
      excludes such versions and a contract test pins it).
- [ ] `make check` and `make test-all` pass.

## Design notes

Two ways to fix it, and the choice needs a maintainer:

- **A. Raise the floor.** Set `pynbody>=X` where X is the first release with
  both `Kernel.value(distance, h)` and the fixed `to_3d_grid`, then re-lock.
  Consequence: Python 3.10 may lose pynbody support if X has no 3.10 wheels.
  The lock uses the TUNA mirror URLs, so re-locking needs that mirror or
  `--index-url` with the mirror kept.
- **B. Keep the floor.** Add a test helper that evaluates the kernel on both
  APIs (`value(r, h)` when present, else `get_value(r / h, h)` vectorised), and
  bring back a version-gated warning (or a workaround) in the 3-D render path
  for pynbody versions with the z bug. `PYNBODY_VERSION` already exists in
  `pynbodyext/util/deps.py`.

A is the smaller change if the floor is acceptable. Either way, a contract test
that fails loudly on an unsupported pynbody is better than wrong numbers.

## Test plan

- Reproduce on the locked 2.3.3 environment (red).
- For A: re-lock, run `make test` (green), and add a contract test that
  asserts `pynbody.__version__ >= X`.
- For B: run the three tests on 2.3.3 and on the newer pynbody; add a test that
  the `nz != ny` render warns on an affected version (use `monkeypatch` on
  `PYNBODY_VERSION` or the adapter if a real old version is unavailable).
- `make check`, `make test-all`.

## Outcome

## Open questions

- Which pynbody release first has `Kernel.value(distance, h)` and the fixed
  `to_3d_grid` z sizing? (The passing environment had 2.8.0; the exact first
  version has not been checked.)
- Option A or B? Is dropping Python 3.10 acceptable if A needs it?

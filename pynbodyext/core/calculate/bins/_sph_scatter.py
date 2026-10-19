"""The particle-to-cell pair engines: who reaches a cell, and with what weight.

A kernel *sum* can be accumulated on the fly — pynbody's renderer does that, and
``_pynbody_render`` drives it.  A kernel-weighted *quantile* cannot: it needs each
cell's set of ``(value, weight)`` pairs, so every particle has to lay its kernel
over the cells it reaches.  That is what this module produces:

- :func:`scatter_pairs` — the pair loop in NumPy.  A particle's cells follow from
  its support (``2h``) and the uniform grid, so one particle touches a rectangular
  block; the blocks of all particles are expanded into flat arrays at once
  (``np.repeat`` plus a mixed-radix decomposition) instead of in a Python loop, and
  nothing is ordered — the caller reduces with a per-entry cell index.
- :func:`kernel_weights` — pynbody's kernel lookup, i.e. the weight of one pair,
  indexed exactly as pynbody's own renderer indexes it.
- :func:`pairs_for_slab` — the entry point the render calls once per slab: it picks
  the compiled engine (``cpp/image/scatter.cpp`` through ``pynbodyext._native``)
  when the extension is built, and otherwise falls back to NumPy.  Both weigh with
  the same kernel table, so the fallback changes the speed and not the answer.
- :func:`native_pair_builder` and :func:`kernel_table` — the compiled path's inputs,
  and its optionality, in one place.

Numbers and shapes only: nothing here looks at the result, the axis model or the
snapshot — that is ``_sph_geometry``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._sph_geometry import SlabGrid

__all__ = ["kernel_table", "kernel_weights", "native_pair_builder", "pairs_for_slab", "scatter_pairs"]


def pairs_for_slab(
    position: np.ndarray,
    smoothing: np.ndarray,
    support: np.ndarray,
    value: np.ndarray,
    extra: np.ndarray,
    grid: SlabGrid,
    low: int,
    high: int,
    kernel: Any,
    measure: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(cell, value, weight)`` for every particle-cell pair in one slab.

    The compiled kernel does the work of :func:`scatter_pairs` *and* pynbody's
    kernel lookup — the ``result[...] += ...`` loop of its renderer, writing
    pair records instead of sums — and is roughly an order of magnitude faster;
    the NumPy fallback keeps the layer working without the optional extension and
    weighs the pairs with the same lookup in :func:`kernel_weights`.
    """
    builder = native_pair_builder()
    if builder is not None:
        cell, values, weights = builder(
            np.ascontiguousarray(position, dtype=float),
            np.ascontiguousarray(smoothing, dtype=float),
            np.ascontiguousarray(support, dtype=float),
            np.ascontiguousarray(value, dtype=float),
            np.ascontiguousarray(extra, dtype=float),
            kernel_table(kernel),
            int(getattr(kernel, "h_power", 3)),
            float(measure),
            list(grid.origins),
            list(grid.widths),
            [len(centre) for centre in grid.centres],
            list(grid.strides),
            int(low),
            int(high),
            0,
        )
        return (np.asarray(cell, dtype=np.intp), np.asarray(values, dtype=float), np.asarray(weights, dtype=float))
    cell, distance, found = scatter_pairs(position, smoothing, support, grid, low, high)
    weight = kernel_weights(np.sqrt(distance), smoothing[found], kernel) * measure * extra[found]
    return cell, value[found], weight


def scatter_pairs(
    position: np.ndarray,
    smoothing: np.ndarray,
    support: np.ndarray,
    grid: SlabGrid,
    low_row: int,
    high_row: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every ``(cell, distance², row)`` inside one slab of rows, in NumPy.

    Each particle's cell range comes from its own support (``2h``) and the uniform
    grid, so the block of cells one particle touches is a rectangular range;
    the ranges of all particles are then expanded into flat arrays at once
    (``np.repeat`` and a mixed-radix decomposition) rather than in a Python loop.
    Nothing is ordered: the caller reduces with a per-entry sample index, which is
    what :func:`~.statistics.bucketed_weighted_percentiles` takes.  The compiled
    kernel in ``cpp/image/scatter.cpp`` does the same arithmetic; this is the
    fallback for an install without it.
    """
    centres, origins, widths, strides = grid.centres, grid.origins, grid.widths, grid.strides
    dimensions = len(centres)
    ranges: list[tuple[np.ndarray, np.ndarray]] = []
    for axis in range(dimensions):
        low = np.floor((position[:, axis] - support - origins[axis]) / widths[axis])
        high = np.ceil((position[:, axis] + support - origins[axis]) / widths[axis])
        # Clip to the *grid*, so the cell centres are the real ones; the slab is
        # accounted for when the row index is turned into a cell index below.
        lower_bound = low_row if axis == 0 else 0
        upper_bound = high_row if axis == 0 else len(centres[axis])
        low = np.clip(low, lower_bound, upper_bound)
        high = np.clip(high, lower_bound, upper_bound)
        ranges.append((low.astype(np.intp), high.astype(np.intp)))

    sizes = [high - low for low, high in ranges]
    block = np.prod(np.stack(sizes), axis=0)
    picked = np.flatnonzero(block > 0)
    if not len(picked):
        return (np.empty(0, dtype=np.intp), np.empty(0), np.empty(0, dtype=np.intp))

    per_particle = block[picked]
    total = int(per_particle.sum())
    particle = np.repeat(picked, per_particle)
    within = np.arange(total, dtype=np.intp) - np.repeat(np.cumsum(per_particle) - per_particle, per_particle)

    offsets = []
    radix = np.ones(total, dtype=np.intp)
    for axis in reversed(range(dimensions)):
        size = sizes[axis][particle]
        offsets.append((axis, (within // radix) % size))
        radix = radix * size

    cell = np.zeros(total, dtype=np.intp)
    distance = np.zeros(total, dtype=float)
    for axis, offset in offsets:
        index = ranges[axis][0][particle] + offset
        if axis == 0:
            cell += (index - low_row) * strides[axis]
        else:
            cell += index * strides[axis]
        displacement = centres[axis][index] - position[particle, axis]
        distance += displacement**2

    return cell, distance, particle


@lru_cache(maxsize=1)
def native_pair_builder() -> Callable[..., tuple[np.ndarray, np.ndarray, np.ndarray]] | None:
    """The compiled pair builder, or ``None`` without the optional extension."""
    try:
        from pynbodyext import _native
    except ImportError:
        return None
    builder = getattr(_native, "scatter_pairs", None)
    return cast("Callable[..., tuple[np.ndarray, np.ndarray, np.ndarray]] | None", builder)


def kernel_table(kernel: Any) -> np.ndarray:
    """pynbody's kernel lookup table as float64, for the compiled pair builder.

    Passing the table — rather than a kernel id — keeps the kernel definition on the
    Python side: the C loop indexes the same numbers pynbody's renderer indexes.
    """
    return np.ascontiguousarray(kernel.get_samples(), dtype=float)


def kernel_weights(distance: np.ndarray, smoothing: np.ndarray, kernel: Any) -> np.ndarray:
    r"""``W(distance, h)`` for a grid of separations and a matching grid of ``h``.

    The kernel is indexed exactly as pynbody's renderer indexes it — its own
    lookup table, ``index = len(table) * d²/(2h)²``, zero beyond — so a quantile
    weighs its neighbours with the very weights the kernel sums use, whether the
    kernel is three-dimensional or the projected one.  (The C kernel in
    ``cpp/image/scatter.cpp`` does this same indexing.)
    """
    # pynbody caches the sample table per kernel and *not* per dtype, and its C
    # renderer asks for it as float32 — so ask for the same thing it will, or a
    # later kernel sum trips over a float64 table.
    samples = np.asarray(kernel.get_samples(), dtype=float)
    index = ((distance / smoothing) ** 2 / 4.0 * len(samples)).astype(np.intp)
    inside = index < len(samples)
    table = samples[np.clip(index, 0, len(samples) - 1)]
    return np.where(inside, table, 0.0) / smoothing ** int(getattr(kernel, "h_power", 3))

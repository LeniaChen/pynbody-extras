"""Where a smoothed render's cells and particles are.

Everything here is *geometry*: the plan a render is validated against (which axes,
how wide the cells, what the measure is, the particle positions and smoothing
lengths), the per-axis numbers a scatter needs, the periodic images that can reach
the grid, and the two conventions a render has to respect — the result's own axis
order, and the wrap offsets pynbody's renderer builds.

Pure functions over the result's model and its snapshot, with no engine in them:
the pair engines live in ``_sph_scatter``, and the query orchestration in
``sph_render``.  Nothing here imports either of the other two.

The one stateful-looking piece, :func:`layout`, is a pure function of the model and
the render settings; ``SphRender`` is what memoises it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .model import BinResultModel

__all__ = [
    "AXIS_COLUMN",
    "SPATIAL",
    "SlabGrid",
    "boxsize",
    "cell_centres",
    "images",
    "is_uniform",
    "layout",
    "offset_vectors",
    "position_array",
    "slab_grid",
    "smooth_array",
    "to_axis_order",
    "wrap_offsets",
]

#: The spatial axes a render can be built over.
SPATIAL = ("x", "y", "z")

#: Column of a ``pos`` array per axis name.
AXIS_COLUMN = {"x": 0, "y": 1, "z": 2}


def layout(
    model: BinResultModel,
    *,
    wrap: bool,
    smooth_source: str,
) -> dict[str, Any]:
    """Validate the result once, and cache what a render needs from it."""
    axes = model.axes
    props = [str(axis.prop) for axis in axes]
    if len(axes) not in (2, 3):
        raise ValueError(f"sph_render needs 2 or 3 axes (a plane or a volume); this result has {len(axes)} ({props}).")
    if any(prop not in SPATIAL for prop in props) or len(set(props)) != len(props):
        raise ValueError(
            f"sph_render renders onto the sky/volume, so its axes must be distinct spatial ones; "
            f"this result has {props} — rebuild the bins from x/y/z."
        )
    for axis in axes:
        if not is_uniform(axis):
            label = axis.alias or axis.prop
            raise ValueError(
                f"sph_render needs evenly spaced bins: axis {label!r} has bins of unequal width. Use mode='linear'."
            )

    sim = model.sim
    smooth = smooth_array(sim, source=smooth_source)
    if not np.all(np.isfinite(smooth)) or np.any(smooth <= 0.0):
        raise ValueError(
            "sph_render needs finite, positive smoothing lengths; this snapshot's 'smooth' array "
            "has zeros or non-finite values."
        )

    by_prop = {str(axis.prop): axis for axis in axes}
    widths = {prop: float(axis.edges[1] - axis.edges[0]) for prop, axis in by_prop.items()}
    present = [prop for prop in SPATIAL if prop in by_prop]
    measure = float(np.prod([widths[prop] for prop in present]))

    return {
        "axes": by_prop,
        "present": present,
        "widths": widths,
        "measure": measure,
        "position": position_array(sim, by_prop),
        "smooth": smooth,
        "boxsize": boxsize(sim) if wrap else None,
    }


def smooth_array(sim: Any, *, source: str) -> np.ndarray:
    """The smoothing length of every particle, in the position units.

    ``source="snapshot"`` (the default) reads ``sim["smooth"]`` — pynbody's on-disk
    values where they exist, and its k-d tree estimate for a single family that has
    none.  A *mixed* set can be refused this way; the error names
    ``smooth="kdtree"``, which derives the whole array with
    :func:`pynbody.sph.smooth` instead.  That is the same run pynbody's own ``rho``
    uses, and the only way to render a particle set whose families do not all carry
    the block.
    """
    if source == "kdtree":
        from pynbody.sph import smooth as derive_smoothing

        try:
            return np.asarray(derive_smoothing(sim), dtype=float)
        except Exception as exc:  # noqa: BLE001 - report whatever it was, with the cause attached
            raise ValueError(
                "sph_render could not derive smoothing lengths for this particle set with "
                f"pynbody.sph.smooth: {type(exc).__name__}: {exc}"
            ) from exc
    try:
        return np.asarray(sim["smooth"], dtype=float)
    except Exception as exc:  # noqa: BLE001 - the spelling of "no such array" is the subclass's business
        # pynbody spells it KeyError, but a snapshot wrapper may raise anything
        # (a custom ``__getitem__`` often falls through to TypeError).  Type is
        # what the caller cannot guess, so it goes in the message; the original
        # exception stays attached as the cause.
        raise ValueError(
            "sph_render needs a smoothing length for every particle, and this particle set does not "
            "provide one: pynbody derives 'smooth' on demand for a single family, but a mixed set must "
            "carry one for each of them (usually only the gas does).  Render a family or sub-result "
            "that has it — bins.gas.sph_render[...] — give 'smooth' to every family first, or call "
            'bins.sph_render(smooth="kdtree") to derive one for the whole set.  '
            f"(reading sim['smooth'] raised {type(exc).__name__}.)"
        ) from exc


def position_array(sim: Any, axes: dict[str, Any]) -> np.ndarray:
    """The particle positions, in the axes' own units."""
    position = sim["pos"]
    units = getattr(position, "units", None)
    axis_units = getattr(axes["x"], "units", None)
    if units is not None and axis_units is not None and units != axis_units:
        position = position.in_units(axis_units)
    return np.asarray(position, dtype=float)


def boxsize(sim: Any) -> float | None:
    """The periodic box, in position units, or ``None`` when there is none."""
    boxsize_value = sim.properties.get("boxsize") if hasattr(sim, "properties") else None
    if boxsize_value is None:
        return None
    position_units = getattr(sim["pos"], "units", None)
    if position_units is not None and getattr(boxsize_value, "units", None) is not None:
        boxsize_value = boxsize_value.in_units(position_units, **sim.conversion_context())
    return float(boxsize_value)


def is_uniform(axis: Any) -> bool:
    edges = np.asarray(axis.edges, dtype=float)
    return bool(np.allclose(np.diff(edges), np.diff(edges)[0]))


def cell_centres(axis: Any) -> np.ndarray:
    edges = np.asarray(axis.edges, dtype=float)
    return 0.5 * (edges[:-1] + edges[1:])


def wrap_offsets(axis: Any, boxsize_value: float | None) -> list[float]:
    """The offsets along one axis, as pynbody's renderer builds them."""
    if boxsize_value is None:
        return [0.0]
    span = float(axis.edges[-1] - axis.edges[0])
    repeats = int(round(span / (2.0 * boxsize_value))) + 1
    return list(np.linspace(-repeats * boxsize_value, repeats * boxsize_value, 2 * repeats + 1))


def offset_vectors(boxsize_value: float | None, axes: list[Any]) -> list[tuple[float, ...]]:
    """Every combination of per-axis periodic shifts that could matter.

    pynbody's renderer repeats particles by whole boxes when a snapshot is periodic
    (``_calculate_wrapping_repeat_array``); the same repeats are needed here, and
    ``boxsize is None`` means the single, unshifted case.
    """
    if boxsize_value is None:
        return [tuple(0.0 for _ in axes)]
    per_axis = []
    for axis in axes:
        span = float(axis.edges[-1] - axis.edges[0])
        repeats = int(round(span / (2.0 * boxsize_value))) + 1
        per_axis.append(np.linspace(-repeats * boxsize_value, repeats * boxsize_value, 2 * repeats + 1))
    return [tuple(float(component) for component in combination) for combination in itertools.product(*per_axis)]


def images(plan: dict[str, Any], smoothing: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Particle indices and per-axis shifts for every image that can reach the grid.

    A periodic box means a particle near one edge reaches cells at the other, so
    a handful of shifted copies are needed — the same repeats pynbody's renderer
    uses.  Only the particles an image brings within reach are kept, so the
    common case costs one pass and no copies.
    """
    present = plan["present"]
    columns = [AXIS_COLUMN[prop] for prop in present]
    position = plan["position"][:, columns]
    support = 2.0 * smoothing
    bounds = [(float(plan["axes"][prop].edges[0]), float(plan["axes"][prop].edges[-1])) for prop in present]
    parts: list[np.ndarray] = []
    shifts: list[np.ndarray] = []
    for shift in offset_vectors(plan["boxsize"], [plan["axes"][prop] for prop in present]):
        reaches = np.ones(len(position), dtype=bool)
        for axis, (low, high) in enumerate(bounds):
            moved = position[:, axis] + shift[axis]
            reaches &= (moved + support > low) & (moved - support < high)
        if reaches.any():
            picked = np.flatnonzero(reaches)
            parts.append(picked)
            shifts.append(np.tile(shift, (len(picked), 1)))
    return np.concatenate(parts), np.concatenate(shifts)


def to_axis_order(rendered: np.ndarray, plan: dict[str, Any], model_axes: Any) -> np.ndarray:
    """Reorder an ``(x, y[, z])`` grid into the result's own axis order."""
    order = [plan["present"].index(str(axis.prop)) for axis in model_axes]
    return np.transpose(rendered, np.argsort(order))


@dataclass(frozen=True, slots=True)
class SlabGrid:
    """The per-axis numbers a scatter needs, in the plan's ``present`` order.

    One value object instead of five separate arguments threaded down to the pair
    engines: the shape, which ``pos`` column each axis is, where the cell centres
    sit, where the grid starts, how wide a cell is, and the row-major stride of
    each axis.
    """

    shape: tuple[int, ...]
    columns: tuple[int, ...]
    centres: tuple[np.ndarray, ...]
    origins: tuple[float, ...]
    widths: tuple[float, ...]
    strides: tuple[int, ...]


def slab_grid(plan: dict[str, Any]) -> SlabGrid:
    """The geometry of one grid row-slab, derived from the plan."""
    present = plan["present"]
    axes = plan["axes"]
    shape = tuple(axes[prop].nbins for prop in present)
    return SlabGrid(
        shape=shape,
        columns=tuple(AXIS_COLUMN[prop] for prop in present),
        centres=tuple(cell_centres(axes[prop]) for prop in present),
        origins=tuple(float(axes[prop].edges[0]) for prop in present),
        widths=tuple(plan["widths"][prop] for prop in present),
        strides=tuple(int(np.prod(shape[index + 1 :], dtype=int)) for index in range(len(shape))),
    )

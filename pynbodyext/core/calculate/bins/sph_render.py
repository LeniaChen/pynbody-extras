"""SPH-smoothed views of a binned result: ``bins.sph_render["mass.sum"]``.

A normal query answers "what is in this cell" by counting the particles that fall
inside it.  The same query through :attr:`BinNDResult.sph_render` answers it by
*smearing* each particle with its SPH kernel instead, so a cell borrows from its
neighbours and the map is smooth where the strict binning was noisy::

    bins.sph_render["count"]  # kernel-integrated particle count
    bins.sph_render["mass.sum"]  # per-cell mass, smoothed
    bins.s.sph_render["vz.mean@mass"]  # stars only, mass-weighted mean vz

Semantics
---------
The query grammar does not change — ``"<field>.<transform>.<stat>@<weight>"``, as
parsed by :func:`~.statistics.parse_pipeline_key` — and neither does what the parts
mean.  Only cell membership changes: a particle at separation ``r`` from a cell
contributes with the weight

.. math::  w_{ij} = W(r_{ij}, h_i)\\, V_{\\rm cell}\\, [\\text{@weight}]

where ``W`` is pynbody's kernel (normalised so that ``∫ W dV = 1``), ``h_i`` is the
particle's smoothing length and ``V_cell`` the cell's volume (area, for a
two-dimensional projection).  The weights are dimensionless.  Two consequences of
that sum are worth knowing, because both differ from the strict query:

- **A render of a subregion is a genuine SPH estimate of that subregion**, so it
  includes the particles just outside the grid whose kernels reach in — the
  quantity in a cell is ``Σ`` over *neighbours*, not over the particles the grid
  happens to contain.  The totals agree with the particle number only when the
  grid contains every kernel.
- **The kernel is sampled at the cell centre, not integrated over the cell** (the
  same choice pynbody's own renderer makes), so the cells have to resolve it:
  with ``h`` of the order of a cell the totals come out right, and with a grid far
  coarser than the smoothing length they are inflated.  Raise ``smooth_floor`` or
  use a finer grid when that matters.

With those in mind:

- ``count`` is that sum — a *kernel-integrated* count, fractional by nature
  (``0.37`` particles may land in a cell), unlike ``bins["count"]``;
- ``sum`` is ``Σ_i w_ij f_i``, with the units of ``f`` (so
  ``sph_render["mass.sum"]`` is a mass per cell, like ``bins["mass.sum"]``);
- ``mean`` (and ``rms``, ``disp``) are the weighted versions, ``Σ w f / Σ w``,
  which also carries the units of ``f``; ``@mass`` weights them by mass exactly
  as it does for a strict query;
- ``transform``s act on the *particle* values before smoothing, so
  ``"vz.abs.mean@mass"`` is the mass-weighted mean of ``|vz|``.

The statistic picks the engine, so there is no mode to remember:

- **the kernel sums** — ``count``, ``sum`` and the mean-likes (``mean``, ``rms``,
  ``disp``) — accumulate over the whole kernel support, which is what pynbody's
  renderer does in C.  They are exact and cheap;
- **the quantiles** — ``median`` and the percentiles ``pXX`` — are weighted
  quantiles over **every particle the kernel reaches**, since a quantile is not
  linear in the weights and so cannot be a kernel sum.  They are built by
  *scattering*: each particle lays its kernel over the cells it touches — the same
  thing pynbody's renderer does internally, periodic images included — and the
  resulting ``(value, weight)`` pairs are reduced by
  :func:`~.statistics.bucketed_weighted_percentiles`, which is the strict query's
  own definition: it counts the weights into value bins, finds the bin the
  percentile falls in and orders only the entries there, so a cell's answer is what
  ``bins[...]`` would give for the same neighbours, smoothed.  A cell therefore
  sees exactly the neighbours its kernel sums see, and ``"vz.abs.p16@mass"`` is
  the mass-weighted 16th percentile of ``|vz|`` over all of them, while
  ``"vz.median"`` is the weighted median — which need not equal ``"vz.mean"``.
  (An earlier version looked at the *nearest* particles, capped at a fixed number;
  a real snapshot holds hundreds inside ``2h``, so that truncated the weight by up
  to 44% and moved medians by tens of km/s.  Scattering is why there is no such
  parameter now.)

  The pair loop itself is ``cpp/image/scatter.cpp`` — pynbody's ``result[...] +=
  ...`` walk writing ``(cell, value, weight)`` records rather than sums, the
  kernel lookup included — with a NumPy fallback that weighs the pairs the same
  way.  Building and weighing the million pairs of a 32² grid off 200k particles
  costs about what a kernel sum costs (23 ms against 12 ms); the reduction is what
  makes a quantile cost about a dozen kernel sums (142 ms).  That is the price of
  the definition rather than a mode: ``bins.sph_render["vz.median"]`` scatters
  because a median has to, and ``bins.sph_render["vz.mean"]`` does not.  A scatter
  that would touch an unreasonable number of pairs warns instead of being refused
  — see ``smooth_floor`` below, which is what bounds it.

Derived quantities
------------------
The view answers the result's *derived* properties too, wherever smoothing leaves
their meaning alone:

- ``<field>.density`` — the strict suffix with the smoothed numerator, so
  ``"mass.sum.density"`` is a kernel-smoothed mass per cell over that same cell
  measure, in the units ``bins["mass.sum.density"]`` carries (and ``"count.density"``,
  ``"mass.density"`` and ``"density"`` work as they do on the result);
- a property registered ``allow_sph=True`` — its own callback runs again, against
  the queries above, so there is no second definition of it to keep in step.
  ``gas_fraction`` and ``number_density`` ship that way.  The flag belongs on a
  per-cell function of what the callback reads: a ratio of two ``mass.sum`` maps
  becomes the ratio of two SPH maps, but a cumulative sum or a statistic of the
  strict particle census would mean something else once cells borrow from their
  neighbours;
- geometry (``measure``) — the grid's own, identical either way.

A derived property that is not declared sph-renderable is refused by name, rather
than answered with the strict map and left to look smoothed.

Relationship to pynbody's other renderers
-----------------------------------------
The kernel sums call pynbody's own ``_render.render_image`` and
``_render.to_3d_grid`` — the loops its ``ImageRenderer`` and ``Grid3dRenderer``
drive — with pynbody's kernels, and for a projection pynbody's
``KernelBase.projection`` (the ``∫W dz`` two-dimensional kernel).  The high-level
classes are deliberately *not* used: ``ImageRenderer.render`` reads ``mass``,
``rho``, ``x``, ``y``, ``z`` and ``smooth`` off the snapshot and accumulates
``Σ q_i W_i m_i/ρ_i``, whereas this view is defined to keep the strict query's
units — ``Σ q_i W_i V_cell``, which is what passing ``mass = rho = 1`` gives.  The
renderer API offers no way to override ``mass``/``rho``, and computing ``rho`` is
not free: a 32² image of the gas in ``testdata/gadget2`` costs 65 ms that way
against 2 ms here, most of it the density.  ``make_render_pipeline`` has the same
convention, and a mixed particle set fails in pynbody's renderer too — on ``rho``
rather than ``smooth`` (``KeyError: Block rho is not available for all
families``).

The two conventions differ by exactly one factor.  Writing ``v_i = m_i/ρ_i`` for
the volume one particle occupies, the renderer estimates a *field* — ``Σ_i v_i q_i
W_i``, the SPH interpolation that gives the constant back for a constant ``q`` —
while this view counts what lands in a cell, ``V_cell Σ_i q_i W_i``.  So
``I_ours(q) = V_cell × I_pynbody(q·ρ/m)``, and the same quantity comes out of both
to float32.  With the same smoothing lengths, on ``testdata/gadget2`` and a 32²
projected grid::

    bins.sph_render["mass.sum"]          == V_cell  ×  Grid3dRenderer render of "rho"
    bins.sph_render["count"]             == A_cell  ×  projected render of "rho/mass"
    bins.sph_render["mass.sum.density"]  ==            projected render of "rho"

(each to ~1e-8 relative).  ``count`` against a render of the constant ``1`` is the
plainest way to see the difference: their ratio is the number of particles per
cell, ~4 on that grid, because the renderer is answering "what is the value of the
field here", not "how many particles are here".

That identity is the way across.  For a *sum* the field convention is already
spelled ``<field>.density``.  For a *mean* the renderer weights by volume,
``Σ_i v_i q_i W_i / Σ_i v_i W_i``, which is just a different per-particle weight —
and ``@<field>`` takes any array the snapshot carries::

    sim["vol"] = sim["mass"] / sim["rho"]  # the volume each particle occupies
    bins.sph_render["vz.mean@vol"]  # the volume-weighted mean

It is deliberately not a built-in weight.  ``@mass`` is an array the snapshot
already has; ``v = mass/rho`` costs an SPH density from the k-d tree (65 ms
against this view's 2 ms on the gadget2 gas) and is refused on a mixed particle
set, and a weight that silently pays either price does not belong in the query
grammar.  Writing the array makes the cost visible — the same reason ``@vol`` is
checked against the renderer in the tests rather than assumed.  (That test also
pins ``sim["smooth"]`` first: ``rho`` is built with the smoothing lengths
pynbody's derived arrays choose, which are not necessarily the ones this view
reads, and a comparison across two sets of them measures the kernels rather than
the conventions — 30% on the gadget2 gas.)

Requirements
------------
- **Two or three spatial axes.**  The bin axes must be ``x``, ``y`` and — for a
  three-dimensional result — ``z``, all distinct.  A radial or temperature axis
  has no SPH geometry to render onto.
- **Evenly spaced bins** (``mode="linear"``), because the renderer works on the
  cell grid: ``V_cell`` is a single number.  Anything else raises.
- **An SPH snapshot.**  Every particle needs a smoothing length.  By default it is
  read as ``sim["smooth"]``, which pynbody fills in from the particle distribution
  when a *single family* has none on disk — so ``bins.gas.sph_render[...]`` works
  on any snapshot — but a *mixed* set must carry one for every family it contains
  and says so when it cannot.  ``bins.sph_render(smooth="kdtree")`` derives one
  for the whole set instead, which is the only way to render a mixed set.  Zeros
  or non-finite values are rejected rather than rendered.

``pynbody.sph`` is imported on first use, so importing the bins package stays
light.

Where the pieces live
---------------------
This module is the *view*: it decides which engine answers a statistic, walks the
cell slabs, and hands the result back in the bins' own axis order.  The parts a
maintainer is likely to reach for live beside it:

- :mod:`._sph_geometry` — the plan (validated axes, particle positions, smoothing
  lengths, periodic box), the per-axis grid a scatter needs, the periodic images
  that can reach the grid, and the wrap/axis-order conventions.
- :mod:`._sph_scatter` — the pair engines: the compiled one through
  ``pynbodyext._native``, the NumPy fallback, and the kernel lookup both weigh with.
- :mod:`._pynbody_render` — the two private pynbody renderer entry points the
  kernel sums go through.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from ._pynbody_render import projected_kernel_sum, volume_kernel_sum
from ._sph_geometry import SPATIAL, images, layout, slab_grid, to_axis_order, wrap_offsets
from ._sph_scatter import pairs_for_slab
from .model import BinResultModel
from .query import DensityResolver, QueryCache, _wrap, evaluate_derived
from .statistics import (
    RMS,
    Dispersion,
    Mean,
    Median,
    Percentile,
    Sum,
    apply_pipeline,
    bucketed_weighted_percentiles,
    parse_pipeline_key,
)

if TYPE_CHECKING:

    from pynbody.sph.kernels import KernelBase

    from .arrays import BinsArray
    from .registries import BinDerivedSpec
    from .result import BinNDResult

__all__ = ["BinSphRenderMixin", "SphRender"]

#: Statistics built from one or two kernel sums (no neighbour lists needed).
_SUM_STATISTICS = (Sum, Mean, RMS, Dispersion)

#: Statistics that need the per-cell neighbour lists: a weighted quantile.
_QUANTILE_STATISTICS = (Median, Percentile)

#: Rows of cells the quantile engine scatters at a time.  Peak memory is set by the
#: particle-cell pairs inside one slab, so this trades passes over the particles
#: for memory.
_SLAB_ROWS = 32

#: Particle-cell pairs in one quantile before we warn about the cost.
_ENTRY_WARNING = 50_000_000

#: Where a render gets its smoothing lengths: the snapshot's own array, or a
#: derivation over the whole particle set.  See
#: :func:`pynbodyext.core.calculate.bins._sph_geometry.smooth_array`.
_SMOOTH_SOURCES = ("snapshot", "kdtree")

#: Sentinel for :meth:`SphRender.__call__`, meaning "keep this view's setting".
_INHERIT = object()

#: Buckets (cells x value bins) the quantile reduction may allocate at once.  The
#: bin count follows from the slab; it affects only speed, never the answer.
_BUCKET_BUDGET = 4_000_000

#: Bounds on that bin count, for a slab of very many or very few cells.
_MIN_BUCKETS = 64
_MAX_BUCKETS = 4096


class SphRender:
    """Kernel-smoothed queries over a binned result.

    Reached as :attr:`BinNDResult.sph_render`; see the module docstring for what a
    query means here and which results support it.

    Parameters
    ----------
    result : BinNDResult
        The binned result whose particles are rendered.  Its ``model.sim`` is the
        particle set — a family sub-result (``bins.s``) renders only that family.
    kernel : str, pynbody.sph.kernels.KernelBase or None, optional
        SPH kernel, by pynbody name (``"CubicSpline"``, ``"WendlandC2"``) or as an
        instance; ``None`` takes pynbody's configured default.
    smooth_floor : float, default: 0.0
        Lower bound on the smoothing length, in the units of the axes.  Useful for
        a snapshot with a few very small ``h``; passed to the renderer unchanged.
    wrap : bool, default: True
        Whether to repeat particles across a periodic ``boxsize``, as pynbody's
        renderer does.  Turning it off restricts the render to the box.  The
        quantiles scatter the same periodic images, so both engines agree across
        a boundary.
    smooth : {"snapshot", "kdtree"}, default: "snapshot"
        Where the smoothing lengths come from.  ``"snapshot"`` reads
        ``sim["smooth"]``: on-disk values where the snapshot has them, and
        pynbody's k-d tree estimate for a single family that has none.  A *mixed*
        particle set (gas plus collisionless families) cannot be read that way,
        because pynbody refuses a block only some families carry; ``"kdtree"``
        derives a length for every particle with :func:`pynbody.sph.smooth`
        instead — the run pynbody's own ``rho`` uses, and the only way to render
        such a set.  It disregards on-disk values, so the numbers differ from
        ``"snapshot"`` wherever the snapshot has them.

    Notes
    -----
    A cell holds ``Σ_i q_i W_i V_cell``, so the units are the strict query's and
    the totals are the strict totals.  pynbody's own ``ImageRenderer`` estimates
    a *field* instead (``Σ_i q_i W_i m_i/ρ_i``) and differs by the cell measure —
    reach for it for a physical field, for this view for a cell census.  The
    module docstring derives the relation, and shows that pynbody's
    volume-weighted mean is one per-particle weight away::

        sim["vol"] = sim["mass"] / sim["rho"]
        bins.sph_render["vz.mean@vol"]

    Examples
    --------
    >>> bins.sph_render["mass.sum"]  # doctest: +SKIP
    >>> bins.s.sph_render["vz.mean@mass"]  # doctest: +SKIP
    >>> bins.sph_render["vz.mean@vol"]  # doctest: +SKIP
    """

    def __init__(
        self,
        result: BinNDResult,
        *,
        kernel: str | KernelBase | None = None,
        smooth_floor: float = 0.0,
        wrap: bool = True,
        smooth: str = "snapshot",
    ) -> None:
        if smooth not in _SMOOTH_SOURCES:
            raise ValueError(f"smooth must be one of {list(_SMOOTH_SOURCES)}; got {smooth!r}.")
        self._result = result
        self._kernel_spec = kernel
        self._smooth_floor = float(smooth_floor)
        self._wrap = bool(wrap)
        self._smooth_source = smooth
        self._renders: dict[str, BinsArray] = {}
        self._plan: dict[str, Any] | None = None
        # The strict query's density definition, reading its numerator from here.
        self._density_resolver = DensityResolver(result, QueryCache(), self.__getitem__)

    def __repr__(self) -> str:
        return f"<SphRender {self._kernel_spec!r} of {self._result!r}>"

    def __call__(
        self, *, kernel: Any = _INHERIT, smooth_floor: Any = _INHERIT, wrap: Any = _INHERIT, smooth: Any = _INHERIT
    ) -> SphRender:
        """This view with some settings changed: ``bins.sph_render(smooth="kdtree")``.

        The view is what a result hands out, so this is how the constructor's
        options are reached from the query spelling.  Anything left out keeps this
        view's value, and the result caches the answer — so
        ``bins.sph_render(smooth="kdtree")`` is one object, whose renders are cached
        with it, however many times it is asked for.

        Parameters
        ----------
        kernel, smooth_floor, wrap, smooth : optional
            As in :class:`SphRender`.  ``smooth="kdtree"`` is the one that changes
            what a render can be answered at all: it derives a smoothing length for
            every particle, which a *mixed* particle set needs.

        Returns
        -------
        SphRender
            A view over the same result, configured as asked.

        Examples
        --------
        >>> bins.sph_render(smooth="kdtree")["gas_fraction"]  # doctest: +SKIP
        >>> bins.sph_render(smooth_floor=1.0, kernel="WendlandC2")["count"]  # doctest: +SKIP
        """
        return self._result._sph_render_view(
            kernel=self._kernel_spec if kernel is _INHERIT else kernel,
            smooth_floor=self._smooth_floor if smooth_floor is _INHERIT else smooth_floor,
            wrap=self._wrap if wrap is _INHERIT else wrap,
            smooth=self._smooth_source if smooth is _INHERIT else smooth,
        )

    # ------------------------------------------------------------------ query
    def __getitem__(self, key: str) -> BinsArray:
        """Render one query, e.g. ``"mass.sum"``, ``"count"``, ``"vz.mean@mass"``.

        Parameters
        ----------
        key : str
            A per-bin query in the usual grammar, or ``"count"`` for the
            kernel-integrated particle count.

        Returns
        -------
        BinsArray
            The smoothed values on the result's own bin grid, so ``.image``,
            ``.plot`` and the image layer work unchanged.  Besides the per-particle
            queries this answers ``"<field>.density"`` and any derived property
            registered ``allow_sph=True`` — the callback runs again against the
            smoothed queries, so e.g. ``"gas_fraction"`` is the ratio of the two
            *kernel-integrated* masses.  See the module docstring.

        Notes
        -----
        ``@<field>`` takes any per-particle array the snapshot carries, so any
        definition of a weighted average is one assignment away — a
        volume-weighted mean, the weighting pynbody's own renderers use, is::

            sim["vol"] = sim["mass"] / sim["rho"]
            bins.sph_render["vz.mean@vol"]

        That one is slow — ``rho`` is an SPH density from the k-d tree — and it is
        unavailable on a mixed particle set, unlike ``@mass``, which the snapshot
        already has.
        """
        cached = self._renders.get(key)
        if cached is not None:
            return cached
        rendered = self._compute(key)
        self._renders[key] = rendered
        return rendered

    def _compute(self, key: str) -> BinsArray:
        sim = self._result.model.sim
        parsed = parse_pipeline_key(key)

        if parsed is None:
            if key != "count":
                return self._derived(key)
            statistic: Any = Sum("sum")
            units = None
            field = None
            values = np.ones(len(sim), dtype=float)
            weights = None
        else:
            field, transforms, statistic, weight = parsed
            if not isinstance(statistic, _SUM_STATISTICS + _QUANTILE_STATISTICS):
                raise NotImplementedError(
                    f"sph_render does not support the {statistic.key!r} statistic: it is neither a ratio "
                    "of kernel sums nor a weighted quantile. Use 'sum', 'mean', 'rms', 'disp', 'median' "
                    "or 'pXX'."
                )
            raw = sim[field]
            units = getattr(raw, "units", None)
            values = apply_pipeline(np.asarray(raw, dtype=float), transforms)
            weights = None if weight is None else np.asarray(sim[weight], dtype=float)

        out = np.asarray(self._statistic(statistic, values, weights), dtype=float)
        result = _wrap(self._result, out, name=key, field=field, mode=statistic.key)
        if units is not None:
            result.units = units
        return result

    # ---------------------------------------------------------------- derived
    def _derived(self, key: str) -> BinsArray:
        """Answer a key that is not a per-particle query.

        Three kinds reach here.  ``<field>.density`` divides a smoothed map by the
        cell measure, because a density is a per-cell ratio and the grid is the
        one the strict query uses.  A property registered ``allow_sph=True`` runs
        its own callback — the very one the strict result runs — against a model
        whose queries come back smoothed.  Geometry (``measure``) is the grid's
        own, identical either way, so it is passed through unchanged.
        """
        base = DensityResolver.strip(key)
        if base is not None or key == "density":
            return self._density(key, key if base is None else base)

        spec = type(self._result)._extensions.get_derived_spec(self._result, key)
        if spec is None:
            raise KeyError(
                f"Unknown sph_render query {key!r}; use 'count', a '<field>.<stat>' query, a "
                "'<field>.density' query, or a derived property the result declares allow_sph=True."
            )
        if spec.allow_sph:
            return self._render_derived(spec)
        if spec.scope == "geometry":
            return self._result[key]
        raise KeyError(
            f"{key!r} is a derived property that is not declared sph-renderable.  Register it with "
            "allow_sph=True if it is a per-cell function of the quantities it reads; a smoothed "
            "version of it would otherwise mean something else."
        )

    def _density(self, key: str, base: str) -> BinsArray:
        """``<field>.density``: the smoothed map divided by the cell measure.

        Reuses :class:`~.query.DensityResolver` — the strict query's own definition
        of the suffix — with this view as its numerator source, so ``"mass.density"``,
        ``"mass.sum.density"`` and ``"count.density"`` behave exactly as they do on
        the result, only smoothed.
        """
        return self._density_resolver.resolve(key, base)

    def _render_derived(self, spec: BinDerivedSpec) -> BinsArray:
        """Run a derived callback against this view's model."""
        return evaluate_derived(self._result, spec, _SphModel(self._result.model, self))

    def _sibling(self, model: BinResultModel) -> SphRender:
        """A view of a sub-result, with this view's own settings."""
        owner = model.owner
        if owner is None:
            raise RuntimeError(f"sph_render reached a sub-result of {model!r} with no owning result.")
        return SphRender(
            owner,
            kernel=self._kernel_spec,
            smooth_floor=self._smooth_floor,
            wrap=self._wrap,
            smooth=self._smooth_source,
        )

    def _statistic(self, statistic: Any, values: np.ndarray, weights: np.ndarray | None) -> np.ndarray:
        """One kernel sum for ``sum``/``count``, a ratio of two for the mean-likes."""
        if isinstance(statistic, _QUANTILE_STATISTICS):
            plan = self._layout()
            return to_axis_order(self._quantile(statistic, values, weights, plan), plan, self._result.model.axes)
        weight = np.ones_like(values) if weights is None else weights
        if isinstance(statistic, Sum):
            return self._render(values * weight)
        total = self._render(weight)
        # Cells no kernel reaches come out NaN, as an empty bin does in a strict
        # query; dividing into them is expected, not a warning.
        with np.errstate(invalid="ignore", divide="ignore"):
            if isinstance(statistic, Mean):
                return self._render(values * weight) / total
            if isinstance(statistic, RMS):
                return np.sqrt(self._render(values * values * weight) / total)
            if isinstance(statistic, Dispersion):
                mean = self._render(values * weight) / total
                square = self._render(values * values * weight) / total
                return np.sqrt(np.clip(square - mean * mean, 0.0, None))
        raise TypeError(f"{statistic!r} has no kernel-weighted form.")

    def _quantile(
        self, statistic: Percentile | Median, values: np.ndarray, weights: np.ndarray | None, plan: dict[str, Any]
    ) -> np.ndarray:
        r"""A kernel-weighted quantile per cell, from every particle the kernel reaches.

        A quantile is not linear in the weights, so — unlike the kernel sums, which
        pynbody's renderer accumulates cell by cell on the fly — it needs each
        cell's *set* of ``(value, weight)`` pairs.  Those come from scattering: every
        particle lays its kernel over the cells it touches, exactly as the renderer
        does internally, its periodic images included, so a cell sees the same
        neighbours the kernel sums see and nothing is truncated.

        The pairs are reduced one *slab* of cells at a time, which bounds peak
        memory by the slab rather than the grid; within a slab they are sorted
        cell-major and handed to :func:`~.statistics.weighted_percentiles` with a
        length per cell, so no padding to the busiest cell is needed.  The
        definition is therefore the strict query's own, only smoothed:
        ``"vz.abs.p16@mass"`` is the mass-weighted 16th percentile of ``|vz|`` over
        everything the kernel reaches.
        """
        present = plan["present"]
        shape = tuple(plan["axes"][prop].nbins for prop in present)
        grid = slab_grid(plan)
        widths = list(grid.widths)
        quantity = np.asarray(values, dtype=float)
        extra = np.ones_like(quantity) if weights is None else np.asarray(weights, dtype=float)

        particle, shift = images(plan, self._smoothing(plan["smooth"]))
        position = plan["position"][particle][:, list(grid.columns)] + shift
        smoothing = self._smoothing(plan["smooth"])[particle]
        support = 2.0 * smoothing
        value = quantity[particle]
        weight = extra[particle]
        kernel = self._kernel(projected=len(present) == 2)
        measure = plan["measure"]
        self._warn_if_expensive(position, support, widths, shape)

        out = np.empty(shape, dtype=float)
        row = grid.strides[0]
        for low in range(0, shape[0], _SLAB_ROWS):
            high = min(low + _SLAB_ROWS, shape[0])
            slab_cells = (high - low) * row
            cell, entry_value, entry_weight = pairs_for_slab(
                position, smoothing, support, value, weight, grid, low, high, kernel, measure
            )
            # Bucketing reduces the slab in O(pairs) instead of ordering it; the
            # answer is the same one :func:`weighted_percentiles` gives.
            bins = int(np.clip(_BUCKET_BUDGET // max(slab_cells, 1), _MIN_BUCKETS, _MAX_BUCKETS))
            reduced = bucketed_weighted_percentiles(
                entry_value, entry_weight, statistic.percentile, sample_of=cell, samples=slab_cells, bins=bins
            )
            out[low:high] = np.asarray(reduced, dtype=float).reshape((high - low, *shape[1:]))
        return out

    def _warn_if_expensive(
        self, position: np.ndarray, support: np.ndarray, widths: list[float], shape: tuple[int, ...]
    ) -> None:
        """Warn when a scatter would touch an unreasonable number of pairs."""
        reach = np.ones(len(position), dtype=float)
        for axis, width in enumerate(widths):
            reach *= np.clip(np.ceil(2.0 * support / width) + 1.0, 0.0, float(shape[axis]))
        entries = float(reach.sum())
        if entries > _ENTRY_WARNING:
            warnings.warn(
                f"this sph_render scatters about {entries / 1e6:.0f} million particle-cell pairs: the smoothing "
                "lengths are large next to the cells. Use smooth_floor, or a coarser grid, to bound it.",
                UserWarning,
                stacklevel=3,
            )

    # ------------------------------------------------------------------ plan
    def _layout(self) -> dict[str, Any]:
        """Validate the result once, and cache what a render needs from it."""
        if self._plan is not None:
            return self._plan
        self._plan = layout(self._result.model, wrap=self._wrap, smooth_source=self._smooth_source)
        return self._plan

    def _kernel(self, *, projected: bool) -> Any:
        from pynbody.sph import kernels

        kernel = kernels.create_kernel(self._kernel_spec)
        return kernel.projection() if projected else kernel

    def _smoothing(self, smooth: np.ndarray) -> np.ndarray:
        return np.maximum(smooth, self._smooth_floor)

    # ----------------------------------------------------------------- render
    def _render(self, quantity: np.ndarray) -> np.ndarray:
        """Kernel sum of *quantity* over the cells, in the result's axis order."""
        return to_axis_order(self._render_cells(quantity), self._layout(), self._result.model.axes)

    def _render_cells(self, quantity: np.ndarray) -> np.ndarray:
        """Kernel sum of *quantity*, in the order the cell grid is indexed here."""
        plan = self._layout()
        if len(plan["present"]) == 2:
            return self._render_projected(quantity, plan)
        return self._render_volume(quantity, plan)

    def _render_projected(self, quantity: np.ndarray, plan: dict[str, Any]) -> np.ndarray:
        r"""Project along the missing axis with pynbody's C renderer.

        The column render uses pynbody's projected kernel (``∫W dz``), so the
        quantity pynbody accumulates is ``Σ_i q_i W_2D(r_ij, h_i)`` — the same
        convention pynbody uses for its own images, with ``mass``/``rho`` set to
        one so that nothing is weighted twice.  Multiplying by the cell area makes
        the weight dimensionless, and by the cell measure we keep the units of the
        strict query rather than pynbody's per-area ones.

        The private call itself lives in
        :mod:`pynbodyext.core.calculate.bins._pynbody_render`.
        """
        first, second = plan["present"]
        coord = {"x": 0, "y": 1, "z": 2}
        position = plan["position"]
        first_axis, second_axis = plan["axes"][first], plan["axes"][second]

        rendered = projected_kernel_sum(
            nx=first_axis.nbins,
            ny=second_axis.nbins,
            x_range=(float(first_axis.edges[0]), float(first_axis.edges[-1])),
            y_range=(float(second_axis.edges[0]), float(second_axis.edges[-1])),
            x=position[:, coord[first]],
            y=position[:, coord[second]],
            z=position[:, 2],
            smoothing=self._smoothing(plan["smooth"]),
            quantity=quantity,
            kernel=self._kernel(projected=True),
            wrap_x=wrap_offsets(first_axis, plan["boxsize"]),
            wrap_y=wrap_offsets(second_axis, plan["boxsize"]),
        )
        return rendered * plan["measure"]

    def _render_volume(self, quantity: np.ndarray, plan: dict[str, Any]) -> np.ndarray:
        r"""Render onto the 3-D cell grid with pynbody's own renderer.

        Same convention as the projected path — pynbody's kernel, ``mass``/``rho``
        set to one so nothing is weighted twice, multiplied by the cell volume to
        keep the units of the strict query.

        The private call itself lives in
        :mod:`pynbodyext.core.calculate.bins._pynbody_render`.
        """
        axes = plan["axes"]
        position = plan["position"]
        bounds = {prop: (float(axes[prop].edges[0]), float(axes[prop].edges[-1])) for prop in SPATIAL}

        volume = volume_kernel_sum(
            nbins=(axes["x"].nbins, axes["y"].nbins, axes["z"].nbins),
            bounds=(bounds["x"], bounds["y"], bounds["z"]),
            coordinates=(position[:, 0], position[:, 1], position[:, 2]),
            smoothing=self._smoothing(plan["smooth"]),
            quantity=quantity,
            kernel=self._kernel(projected=False),
            wrap=(
                wrap_offsets(axes["x"], plan["boxsize"]),
                wrap_offsets(axes["y"], plan["boxsize"]),
                wrap_offsets(axes["z"], plan["boxsize"]),
            ),
        )
        return volume * plan["measure"]

class BinSphRenderMixin:
    """Provides the :attr:`sph_render` view for :class:`~.result.BinNDResult`."""

    @property
    def sph_render(self) -> SphRender:
        """Kernel-smoothed queries over this result: ``bins.sph_render["mass.sum"]``.

        The same queries as ``bins[...]``, with particles smeared by their SPH
        kernel instead of counted in their cell: cells borrow from their
        neighbours, so a noisy map comes out smooth and a sparse one keeps its
        neighbours' signal.  ``bins.s.sph_render[...]`` does it for one family or
        sub-result.

        The statistic picks the engine.  The kernel sums (``count``, ``sum``,
        ``mean``, ``rms``, ``disp``) are accumulated by pynbody's C renderer and
        are exact and cheap; the quantiles (``median``, ``pXX``) are not kernel
        sums, so they scatter every particle over the cells its kernel reaches —
        exact, and about a dozen kernel sums.  Both answer ``bins[...]``'s own
        query grammar, so one view answers whatever the strict result would.  The
        result's derived properties join in too: ``"mass.sum.density"``, and any
        property registered ``allow_sph=True`` such as ``"gas_fraction"``, which
        is then the ratio of the kernel-integrated masses.

        Notes
        -----
        A render answers "how much of this query lands in the cell", so the units
        are the strict query's own: ``count`` is a kernel-integrated *number of
        particles* — fractional by nature — and ``mass.sum`` is a mass.
        :class:`pynbody.sph.renderers.ImageRenderer` answers a different question,
        "what is the value of the field here" (it accumulates
        ``Σ_i q_i W_i m_i/ρ_i``), which is what to reach for when you want a
        temperature or density map rather than a cell census; the two differ by
        the cell's measure, and ``bins.sph_render["mass.sum.density"]`` is exactly
        pynbody's projected render of ``rho``.  The module docstring works the
        relation out and shows how to reproduce pynbody's volume-weighted mean::

            sim["vol"] = sim["mass"] / sim["rho"]  # the volume a particle takes
            bins.sph_render["vz.mean@vol"]

        Returns
        -------
        SphRender
            A view; index it with a query such as ``"mass.sum"``, ``"count"`` or
            ``"vz.median"``, ``"vz.mean@mass"``, or a derived key such as
            ``"mass.sum.density"``.  See :class:`SphRender` for what each part
            means and which results can be rendered.  The view is callable to
            change its settings — ``bins.sph_render(smooth="kdtree")`` — which is
            how a *mixed* particle set gets rendered.

        Raises
        ------
        ValueError
            If the result is not two or three spatial axes with evenly spaced
            bins, or the snapshot has no smoothing lengths.  Raised on the first
            query, not on this property.

        Examples
        --------
        >>> bins.sph_render["count"]  # doctest: +SKIP
        >>> bins.sph_render["vz.median"]  # doctest: +SKIP
        >>> bins.sph_render["mass.sum.density"]  # doctest: +SKIP
        >>> bins.sph_render(smooth="kdtree")["gas_fraction"]  # doctest: +SKIP
        >>> bins.sph_render["vz.mean@vol"]  # doctest: +SKIP
        >>> bins.s.sph_render["vz.mean"]  # doctest: +SKIP
        """
        return self._sph_render_view()

    def _sph_render_view(
        self,
        *,
        kernel: str | KernelBase | None = None,
        smooth_floor: float = 0.0,
        wrap: bool = True,
        smooth: str = "snapshot",
    ) -> SphRender:
        """A :class:`SphRender` over this result, cached by its settings.

        The default view lives in the same cache as the configured ones, so
        ``bins.sph_render is bins.sph_render`` and
        ``bins.sph_render(smooth="kdtree") is bins.sph_render(smooth="kdtree")`` —
        which matters because a render keeps the plan it built, and deriving
        smoothing lengths is not free.
        """
        views = self.__dict__.setdefault("_sph_render_views", {})
        key = (kernel, smooth_floor, wrap, smooth)
        render = views.get(key)
        if render is None:
            render = SphRender(
                cast("BinNDResult", self), kernel=kernel, smooth_floor=smooth_floor, wrap=wrap, smooth=smooth
            )
            views[key] = render
        return render


class _SphModel:
    """A :class:`~.model.BinResultModel` whose queries come back smoothed.

    A derived property is written once, against the query API — ``result["mass.sum"]``,
    ``result.gas["count"]`` — so handing the callback this wrapper instead of the
    model answers the smoothed version of the same property, with no second
    definition of it anywhere.  Sub-result access (``.gas``, ``.star``) recurses to
    that sub-result's own render, so a family ratio smooths each family with its own
    particles.  Anything that is not a query of this view (a model attribute, an
    axis) is passed through untouched.
    """

    def __init__(self, model: BinResultModel, render: SphRender) -> None:
        self._model = model
        self._render = render

    def __getitem__(self, key: str) -> BinsArray:
        return self._render[key]

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._model, name)
        if isinstance(value, BinResultModel):
            return _SphModel(value, self._render._sibling(value))
        return value

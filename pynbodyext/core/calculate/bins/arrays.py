"""The :class:`BinsArray` per-bin result array (a :class:`SimArray` subclass)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from pynbody.array import SimArray

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.lines import Line2D

    from pynbodyext.plot.image.data import ImageData

    from .result import BinNDResult


def _still_the_grid(array: Any, shape_bins: tuple[int, ...] | None) -> bool:
    """Whether *array* is still a map over a grid of *shape_bins*.

    Shape is the test, not the memory: a map whose values no longer line up with
    its bin edges has nothing to draw, and one drawn transposed is worse than one
    that refuses.  C-contiguity catches the transposes, which share the shape of a
    square grid while standing its axes on their heads.
    """
    if shape_bins is None or tuple(array.shape) != tuple(shape_bins):
        return False
    return bool(array.flags.c_contiguous)


def _as_bins_array(result: Any, source: BinsArray) -> Any:
    """Give a numpy result back the grid it was computed on, when it still is it.

    ``SimArray.__array_ufunc__`` finishes by re-viewing every result as a plain
    ``SimArray``, which is what dropped the type through ``+ - * /`` and
    ``in_units``.  The grid comes back only if the values are still the whole grid;
    the name and provenance do not, because the result is no longer that query.
    Results whose units pynbody gave up on (a plain ``ndarray`` out of an
    unregistered ``numpy`` function) are left alone: no units, no map.
    """
    if isinstance(result, BinsArray) or not isinstance(result, SimArray):
        return result
    if not _still_the_grid(result, source._shape_bins):
        return result

    wrapped = result.view(BinsArray)
    wrapped._bins = source._bins
    wrapped._shape_bins = source._shape_bins
    wrapped._axis_aliases = source._axis_aliases
    return wrapped


class BinsArray(SimArray):
    """Per-bin result array with ND grid shape.

    The stored values are shaped as ``(axis0_nbins, axis1_nbins, ...)`` (C-order,
    last axis varies fastest), matching the bin grid.  Flat indexing is still
    available via ``np.asarray(arr).ravel()``.

    Use :meth:`grid` or :meth:`reshape_bins` for an explicit ND view.

    The type is a promise — *these values are a map over this result's bin grid* —
    so it survives the operations that keep that true and is dropped by the ones
    that do not.  Arithmetic keeps it (``mass / count`` is a map too, though its
    :attr:`name` goes, since it is no longer that query), :meth:`in_units` keeps
    it along with the name, and a slice, reshape or transpose drops it: the grid
    operations then refuse with a sentence rather than draw values over bin edges
    they no longer line up with.  ``image``, ``plot`` and ``grid`` are the ones
    that need it::

        bins2d["mass.sum"].in_units("kg").image.display.imshow(colorbar=True)
        (bins2d["mass.sum"] / bins2d["count"]).image.process.smooth.gaussian(fwhm=1.0)

    A reduction (``.sum()``, ``.mean()``) is a number, not a map, and comes back
    as the plain :class:`~pynbody.array.SimArray` it is.

    Examples
    --------
    >>> import pynbody
    >>> sim = pynbody.new(dm=6)
    >>> sim["r"] = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
    >>> sim["mass"] = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    >>> bins = Bin1D("r", vmin=0, vmax=6, nbins=3)(sim)
    >>> mass_sum = bins["mass.sum"]
    >>> mass_sum.shape_bins
    (3,)
    >>> mass_sum.axis_aliases
    ('r',)
    >>> mass_sum.grid.tolist()
    [3.0, 7.0, 11.0]
    """

    __slots__ = ["_bins", "_name", "_field", "_mode", "_shape_bins", "_axis_aliases", "_provenance"]

    _bins: Any  # set by __new__; kept Any for numpy __array_finalize__ quirks
    _name: str | None
    _field: str | None
    _mode: str | None
    _shape_bins: tuple[int, ...] | None
    _axis_aliases: tuple[str, ...] | None
    _provenance: dict[str, Any]

    def __new__(
        cls,
        bins: BinNDResult,
        values: Any,
        *,
        name: str | None = None,
        field: str | None = None,
        mode: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> BinsArray:
        shape_bins = tuple(bins.shape_bins)
        # Reshape flat values to ND grid shape.
        # Arrays of shape (nbins, *extra) are reshaped to (*shape_bins, *extra)
        # so that per-bin 2-D results (e.g. multi_index, cell_widths) work correctly.
        arr = np.asarray(values)
        if arr.shape != shape_bins:
            nbins = int(np.prod(shape_bins))
            if arr.ndim > 1 and arr.shape[0] == nbins:
                arr = arr.reshape((*shape_bins, *arr.shape[1:]))
            else:
                arr = arr.reshape(shape_bins)
        # A map over the grid is stored the way the grid is: C-order.  Everything
        # downstream relies on it — see `_still_the_grid`, which uses contiguity to
        # tell a transposed or flipped *view* from the grid itself.
        arr = np.ascontiguousarray(arr)
        obj = super().__new__(cls, arr)
        # Preserve units and sim from the source array so that BinsArray
        # retains unit-tracking when wrapping a SimArray/IndexedSimArray.
        if hasattr(values, "units") and values.units is not None:
            obj.units = values.units
        if hasattr(values, "sim") and values.sim is not None:
            obj.sim = values.sim
        obj._bins = bins
        obj._name = name
        obj._field = field
        obj._mode = mode
        obj._shape_bins = shape_bins
        obj._axis_aliases = tuple(axis.alias for axis in bins.axes)
        obj._provenance = provenance or {}
        return obj

    def __array_finalize__(self, obj: Any) -> None:
        super().__array_finalize__(obj)
        if obj is None:
            return
        self._bins = getattr(obj, "_bins", None)
        self._name = getattr(obj, "_name", None)
        self._field = getattr(obj, "_field", None)
        self._mode = getattr(obj, "_mode", None)
        self._shape_bins = getattr(obj, "_shape_bins", None)
        self._axis_aliases = getattr(obj, "_axis_aliases", None)
        self._provenance = getattr(obj, "_provenance", {})
        # numpy routes every view here — a slice, a reshape, a transpose.  Only one
        # that is still the whole grid is still a map; the rest is plain values that
        # happen to have come from bins.
        if not _still_the_grid(self, self._shape_bins):
            self._forget_grid()

    def _forget_grid(self) -> None:
        """Drop the bin grid: this value is not a map over it any more."""
        self._bins = None
        self._shape_bins = None
        self._axis_aliases = None
        self._name = None
        self._field = None
        self._mode = None
        self._provenance = {}

    def __array_ufunc__(self, ufunc: Any, method: str, *inputs: Any, **kwargs: Any) -> Any:
        return _as_bins_array(super().__array_ufunc__(ufunc, method, *inputs, **kwargs), self)

    def __array_function__(self, func: Any, types: Any, args: Any, kwargs: Any) -> Any:
        result = super().__array_function__(func, types, args, kwargs)
        if isinstance(result, tuple):
            return tuple(_as_bins_array(item, self) for item in result)
        return _as_bins_array(result, self)

    def in_units(self, new_unit: Any, **context_overrides: Any) -> BinsArray:
        """Return this query in other units — the same query, so the same map.

        A computed-on array keeps only the grid (``(mass / count).name`` is not a
        query), but a unit conversion is the query itself, so its name, field and
        provenance survive::

            bins2d["mass.sum"].in_units("kg").image.draw(colorbar=True)
        """
        converted = super().in_units(new_unit, **context_overrides)
        if isinstance(converted, BinsArray):
            converted._name = self._name
            converted._field = self._field
            converted._mode = self._mode
            converted._provenance = dict(self._provenance)
        return converted

    @property
    def bins(self) -> BinNDResult:
        return self._bins

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def field(self) -> str | None:
        return self._field

    @property
    def mode(self) -> str | None:
        return self._mode

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(self._provenance)

    @property
    def shape_bins(self) -> tuple[int, ...]:
        """The bin grid's shape, or ``()`` once this array is no longer that grid.

        The check is lazy rather than only in :meth:`__array_finalize__` because
        numpy finishes a transpose *after* calling it, so ``a.T`` arrives there
        still wearing the untransposed shape; by the time anyone asks, it is final.
        """
        shape_bins = self._shape_bins
        if shape_bins is None or not _still_the_grid(self, shape_bins):
            return ()
        return tuple(shape_bins)

    @property
    def axis_aliases(self) -> tuple[str, ...]:
        """The bin axes' aliases, or ``()`` once this array is no longer that grid."""
        axis_aliases = self._axis_aliases
        if axis_aliases is None or not _still_the_grid(self, self._shape_bins):
            return ()
        return tuple(axis_aliases)

    @property
    def grid(self) -> np.ndarray:
        """Return the values reshaped to the N-D bin grid."""
        return np.asarray(self).reshape(self._require_grid("grid").shape_bins)

    def _require_grid(self, what: str) -> BinNDResult:
        """The owning result, or a clear refusal if this is not a map any more.

        Slicing, reshaping or transposing a :class:`BinsArray` drops the grid (see
        :meth:`_forget_grid`), because the values are no longer laid out over the
        bin edges.  Saying so beats the reshape error that ``grid`` and ``image``
        used to raise from underneath.
        """
        if self._bins is None or not _still_the_grid(self, self._shape_bins):
            raise ValueError(
                f"{what} needs a per-bin array, and this one is no longer the whole bin grid — it was "
                "sliced, reshaped, transposed, or reduced.  Ask the result for the query again, e.g. "
                "bins2d['mass.sum'], and compute on the answer from there."
            )
        return self._bins

    @property
    def image(self) -> ImageData:
        """This query as an image, ready for :mod:`pynbodyext.plot.image`.

        The values are laid out ``(x, y)`` here and transposed into the image
        convention of rows ``= y``, columns ``= x``, carrying the bin edges, units
        and axis names along::

            bins2d["mass.sum"].image.display.imshow(colorbar=True)
            bins2d["vz.mean"].image.display.contour(ax=ax, levels=[-100, 0, 100])

        The drawing itself lives in :mod:`pynbodyext.plot.image`, which is imported
        lazily so that the calculator layer needs no matplotlib to run.

        Returns
        -------
        ImageData
            The image, with the geometry of this bin grid.

        Raises
        ------
        ValueError
            If the result does not have exactly two bin axes, or if this array is
            no longer the whole bin grid.
        """
        from pynbodyext.plot.image import ImageData

        self._require_grid("image")
        return ImageData.from_bins_array(self)

    def reshape_bins(self, copy: bool = False) -> np.ndarray:
        """Return a view (or a copy when ``copy=True``) reshaped to the bin grid.

        Parameters
        ----------
        copy : bool, default: False
            Whether to return a copy.

        Returns
        -------
        np.ndarray
            The values reshaped to ``self.shape_bins``.

        Examples
        --------
        >>> mass_sum.reshape_bins()
        array([3.,  7., 11.])
        """
        arr = np.asarray(self)
        if copy:
            arr = arr.copy()
        return arr.reshape(self._require_grid("reshape_bins").shape_bins)

    def plot(self, ax: Axes | None = None, **kwargs: Any) -> list[Line2D]:
        """Plot this 1-D per-bin array against the first axis's bin centers.

        Parameters
        ----------
        ax:
            Matplotlib axes object.  A new figure/axes is created if ``None``.
        **kwargs:
            Extra keyword arguments forwarded to :meth:`matplotlib.axes.Axes.plot`.

        Returns
        -------
        list[Line2D]
            The line objects returned by ``ax.plot`` (one line for a 1-D array).

        Raises
        ------
        ValueError
            If the owning result is not one-dimensional.

        Examples
        --------
        >>> mass_sum.plot()  # new figure
        >>> import matplotlib.pyplot as plt
        >>> fig, ax = plt.subplots()
        >>> lines = mass_sum.plot(ax=ax)
        >>> len(lines)
        1
        """
        import matplotlib.pyplot as plt

        bins = self._require_grid("plot")
        if bins.ndim != 1:
            raise ValueError("BinsArray.plot requires a one-dimensional bin result.")

        if ax is None:
            _, ax = plt.subplots()
        x = np.asarray(bins.centers)
        y = np.asarray(self)
        return ax.plot(x, y, **kwargs)

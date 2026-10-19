"""The built-in binning algorithms: where a mode turns into bin edges.

A mode name ("linear", "log", "equaln") maps to a function of the sampled values
and the requested range; ``register_bin_algorithm`` adds one, and ``BIN_ALGORITHMS``
is the table both the bin nodes and the extension hooks read.  Kept apart from
``axes.py`` so that "add a binning mode" has one small file to open, and so the
axis object itself stays about geometry rather than construction.

The algorithms return *edges*, or any ``ArrayLike`` the caller accepts, and take
``(values, nbins, vmin, vmax)``; they never look at a ``BinAxis``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, overload

import numpy as np

ArrayLike = Any
BinAlgorithm = Callable[[np.ndarray, int, float, float], ArrayLike]
def _as_1d_array(value: Any, *, name: str) -> np.ndarray:
    arr = np.asarray(value)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional.")
    return arr


def _linear_edges(values: np.ndarray, nbins: int, vmin: float, vmax: float) -> np.ndarray:
    return np.linspace(vmin, vmax, nbins + 1)


def _log_edges(values: np.ndarray, nbins: int, vmin: float, vmax: float) -> np.ndarray:
    if vmin <= 0 or vmax <= 0:
        raise ValueError("log bin mode requires positive vmin and vmax.")
    return np.logspace(np.log10(vmin), np.log10(vmax), nbins + 1)


def _equaln_edges(values: np.ndarray, nbins: int, vmin: float, vmax: float) -> np.ndarray:
    finite = np.asarray(values)[np.isfinite(values)]
    finite = finite[(finite >= vmin) & (finite <= vmax)]
    if finite.size == 0:
        raise ValueError("equaln bin mode requires at least one finite value in range.")
    quantiles = np.linspace(0.0, 1.0, nbins + 1)
    edges = np.quantile(finite, quantiles)
    edges[0] = vmin
    edges[-1] = vmax
    return edges


BIN_ALGORITHMS: dict[str, BinAlgorithm] = {
    "linear": _linear_edges,
    "lin": _linear_edges,
    "log": _log_edges,
    "equaln": _equaln_edges,
    "quantile": _equaln_edges,
}


@overload
def register_bin_algorithm(
    name: str, func: None = None, *, overwrite: bool = False
) -> Callable[[BinAlgorithm], BinAlgorithm]: ...


@overload
def register_bin_algorithm(name: str, func: BinAlgorithm, *, overwrite: bool = False) -> BinAlgorithm: ...


def register_bin_algorithm(
    name: str, func: BinAlgorithm | None = None, *, overwrite: bool = False
) -> BinAlgorithm | Callable[[BinAlgorithm], BinAlgorithm]:
    """Register a custom bin-edge algorithm.

    The algorithm must be ``f(values, nbins, vmin, vmax) -> ndarray`` returning
    ``nbins + 1`` strictly increasing edges.  Works as a decorator or as a direct
    call.

    Parameters
    ----------
    name : str
        Key used by ``Bin1D(mode=...)``.
    func : callable, optional
        The algorithm.  Omit to use as a decorator.
    overwrite : bool, default: False
        Whether to replace an existing algorithm with the same name.

    Returns
    -------
    callable
        The algorithm (when called directly) or a decorator.

    Examples
    --------
    >>> import numpy as np
    >>> @register_bin_algorithm("centroid_edges", overwrite=True)
    ... def centroid_edges(values, nbins, vmin, vmax):
    ...     return np.linspace(vmin, vmax, nbins + 1)
    """

    def decorator(algorithm: BinAlgorithm) -> BinAlgorithm:
        if not overwrite and name in BIN_ALGORITHMS:
            raise KeyError(f"Bin algorithm {name!r} is already registered.")
        BIN_ALGORITHMS[name] = algorithm
        return algorithm

    if func is None:
        return decorator
    return decorator(func)


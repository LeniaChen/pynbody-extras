"""The one place that calls pynbody's private ``sph._render`` loops.

``pynbody.sph._render.render_image`` and ``to_3d_grid`` are private, positional-argument
C functions.  The public wrappers cannot be used in their place: ``ImageRenderer`` and
``Grid3dRenderer`` read ``mass``/``rho`` off the snapshot and accumulate
``Σ q_i W_i m_i / ρ_i``, whereas the SPH view in :mod:`.sph_render` is defined to keep
the strict query's units — ``Σ q_i W_i V_cell``, which is what ``mass = rho = 1`` gives.
The public API offers no way to override those, and deriving ``rho`` is not free: a 32²
image of the gas costs ~65 ms that way against ~2 ms here.

Confining the private calls to this module gives the dependency one edge instead of
several, and ``tests/test_pynbody_render_contract.py`` pins the exact upstream signature
these functions are written against, so an upstream change fails loudly at test time
rather than silently changing the numbers.

Relevant decisions: ADR-0013 (``bins.sph_render`` smooths the binned queries) and the
``sph_render`` section of ``CONTEXT.md``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: The upstream parameter names this module passes positionally, in order.  Pinned by
#: ``tests/test_pynbody_render_contract.py``.
RENDER_IMAGE_PARAMS = (
    "nx",
    "ny",
    "x",
    "y",
    "z",
    "sm",
    "x1",
    "x2",
    "y1",
    "y2",
    "z_camera",
    "z0",
    "qty",
    "mass",
    "rho",
    "smooth_lo",
    "smooth_hi",
    "z_lo",
    "z_hi",
    "min_smooth",
    "kernel",
    "wrap_offsets_x",
    "wrap_offsets_y",
)

#: The same for ``to_3d_grid``.
TO_3D_GRID_PARAMS = (
    "nx",
    "ny",
    "nz",
    "x",
    "y",
    "z",
    "sm",
    "x1",
    "x2",
    "y1",
    "y2",
    "z1",
    "z2",
    "qty",
    "mass",
    "rho",
    "smooth_lo",
    "smooth_hi",
    "kernel",
    "wrap_offsets_x",
    "wrap_offsets_y",
    "wrap_offsets_z",
)

# The constants pynbody's loops take beyond the geometry and the quantity.  ``mass``,
# ``rho`` are one so nothing is weighted twice; the smoothing range is left open because
# the caller already floored the smoothing lengths (``to_3d_grid`` has no ``min_smooth``
# of its own, so the floor lives in one place for every path).
_Z_CAMERA = 0.0
_Z0 = 0.0
_SMOOTH_LO = 0.0
_SMOOTH_HI = float("inf")
_Z_LO = float("-inf")
_Z_HI = float("inf")
_MIN_SMOOTH = 0.0


def projected_kernel_sum(
    *,
    nx: int,
    ny: int,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    smoothing: np.ndarray,
    quantity: np.ndarray,
    kernel: Any,
    wrap_x: list[float],
    wrap_y: list[float],
) -> np.ndarray:
    r"""Kernel-sum *quantity* onto an ``(nx, ny)`` grid, projected along the third axis.

    Returns the grid indexed ``(x, y)``: pynbody's loop returns ``(ny, nx)``, so the
    transpose is done here rather than at every call site.
    """
    from pynbody.sph import _render

    ones = np.ones_like(quantity)
    image = _render.render_image(
        nx,
        ny,
        x,
        y,
        z,
        smoothing,
        x_range[0],
        x_range[1],
        y_range[0],
        y_range[1],
        _Z_CAMERA,
        _Z0,
        quantity,
        ones,
        ones,
        _SMOOTH_LO,
        _SMOOTH_HI,
        _Z_LO,
        _Z_HI,
        _MIN_SMOOTH,
        kernel,
        list(wrap_x),
        list(wrap_y),
    )
    return np.asarray(image).T


def volume_kernel_sum(
    *,
    nbins: tuple[int, int, int],
    bounds: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    coordinates: tuple[np.ndarray, np.ndarray, np.ndarray],
    smoothing: np.ndarray,
    quantity: np.ndarray,
    kernel: Any,
    wrap: tuple[list[float], list[float], list[float]],
) -> np.ndarray:
    """Kernel-sum *quantity* onto an ``(nx, ny, nz)`` grid."""
    from pynbody.sph import _render

    ones = np.ones_like(quantity)
    (x, y, z) = coordinates
    ((x1, x2), (y1, y2), (z1, z2)) = bounds
    volume = _render.to_3d_grid(
        nbins[0],
        nbins[1],
        nbins[2],
        x,
        y,
        z,
        smoothing,
        x1,
        x2,
        y1,
        y2,
        z1,
        z2,
        quantity,
        ones,
        ones,
        _SMOOTH_LO,
        _SMOOTH_HI,
        kernel,
        list(wrap[0]),
        list(wrap[1]),
        list(wrap[2]),
    )
    return np.asarray(volume)

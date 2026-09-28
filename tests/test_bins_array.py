"""What a :class:`BinsArray` is, and what it stops being.

The type is a promise: *these values are a map over this result's bin grid*.  It
survives the operations that keep that true and is dropped by the ones that do
not, so ``bins2d["mass.sum"].in_units("kg").image`` works while a transposed or
sliced array refuses to be drawn as the map it no longer is.
"""

from __future__ import annotations

import numpy as np
import pynbody
import pytest
from pynbody.array import SimArray

from pynbodyext.core.calculate import Bin1D, BinsArray


def make_bins(nx: int = 6, ny: int = 9):
    """A 2-D binned result with mass, count and a velocity."""
    rng = np.random.default_rng(0)
    n = 400
    sim = pynbody.new(dm=n)
    sim["x"] = SimArray(rng.uniform(0.0, 10.0, n), "kpc")
    sim["y"] = SimArray(rng.uniform(0.0, 10.0, n), "kpc")
    sim["mass"] = SimArray(rng.uniform(1.0, 2.0, n), "Msol")
    sim["vz"] = SimArray(rng.normal(0.0, 100.0, n), "km s**-1")
    x = Bin1D("x", vmin=0, vmax=10, nbins=nx, alias="x")
    y = Bin1D("y", vmin=0, vmax=10, nbins=ny, alias="y")
    return (x @ y)(sim)


@pytest.mark.parametrize(
    "operation",
    [
        lambda a, b: a + 1.0,
        lambda a, b: a - 1.0,
        lambda a, b: a * 2.0,
        lambda a, b: a / b,
        lambda a, b: -a,
        lambda a, b: np.abs(a),
        lambda a, b: np.sqrt(a),
        lambda a, b: np.log10(a),
    ],
    ids=["add", "subtract", "multiply", "divide", "negate", "abs", "sqrt", "log10"],
)
def test_an_operation_that_keeps_the_grid_keeps_the_type(operation) -> None:
    """Arithmetic on a map is a map: same grid, so it is still drawable."""
    bins = make_bins()
    mass, count = bins["mass.sum"], bins["count"]

    result = operation(mass, count)

    assert isinstance(result, BinsArray)
    assert result.shape_bins == (6, 9)
    assert result.image.shape == (9, 6)


def test_a_computed_map_keeps_the_grid_but_not_the_query_name() -> None:
    """The values are a map; they are no longer the query the name would claim."""
    bins = make_bins()
    mass = bins["mass.sum"]

    per_particle = mass / bins["count"]

    assert isinstance(per_particle, BinsArray)
    assert per_particle.name is None
    assert per_particle.bins is mass.bins


def test_in_units_keeps_the_grid_and_the_name() -> None:
    """A unit conversion *is* the query, so nothing about it is lost."""
    bins = make_bins()
    mass = bins["mass.sum"]

    kilograms = mass.in_units("kg")

    assert isinstance(kilograms, BinsArray)
    assert kilograms.name == mass.name
    assert kilograms.bins is mass.bins
    np.testing.assert_allclose(np.asarray(kilograms), np.asarray(mass) * mass.units.ratio("kg"))
    assert kilograms.image.shape == (9, 6)


@pytest.mark.parametrize(
    "operation",
    [
        lambda a: a[0],  # a slice: one row of the grid
        lambda a: a.reshape(-1),  # flattened
        lambda a: a.T,  # transposed, which a square grid hides
        lambda a: a[:, None],  # broadcast into a shape that is not the grid
    ],
    ids=["slice", "reshape", "transpose", "broadcast"],
)
def test_an_operation_that_leaves_the_grid_drops_the_map(operation) -> None:
    """Refusing beats drawing values over the wrong bin edges."""
    mass = make_bins()["mass.sum"]

    moved = operation(mass)

    assert moved.shape_bins == ()
    with pytest.raises(ValueError, match="no longer the whole bin grid"):
        moved.image


def test_a_transpose_is_not_drawn_as_the_untransposed_grid() -> None:
    """A square grid is the trap: transpose it and the shape still looks right."""
    square = make_bins(nx=6, ny=6)["mass.sum"]
    transposed = square.T

    assert transposed.shape == square.shape, "the shape cannot tell us"
    np.testing.assert_allclose(np.asarray(transposed), np.asarray(square).T)
    with pytest.raises(ValueError, match="transposed"):
        transposed.image


def test_the_grid_operations_say_why_they_cannot_continue() -> None:
    mass = make_bins()["mass.sum"]

    grid_operations = {
        "grid": lambda array: array.grid,
        "reshape_bins": lambda array: array.reshape_bins(),
        "image": lambda array: array.image,
        "plot": lambda array: array.plot(),
    }
    for operation in (lambda a: a[0], lambda a: a.reshape(-1), lambda a: a.T):
        moved = operation(mass)
        for name, call in grid_operations.items():
            with pytest.raises(ValueError, match="no longer the whole bin grid"):
                call(moved)


def test_a_reduction_is_a_number_not_a_map() -> None:
    mass = make_bins()["mass.sum"]

    total = mass.sum()

    assert not isinstance(total, BinsArray)
    assert float(total) == pytest.approx(float(np.asarray(mass).sum()))


def test_numpy_functions_pynbody_leaves_unitless_do_not_become_maps() -> None:
    """The boundary: pynbody drops even the units, so there is no map to restore.

    ``np.nan_to_num`` and friends are not in pynbody's unit registry, and its
    ``__array_function__`` returns a plain ndarray for them.  Handing that back as
    a ``BinsArray`` would put the grid on values whose units nobody knows.
    """
    mass = make_bins()["mass.sum"]

    cleaned = np.nan_to_num(mass)

    assert type(cleaned) is np.ndarray

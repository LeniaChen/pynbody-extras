from typing import Any, TypeAlias

import numpy as np
from pynbody.array import SimArray
from pynbody.family import Family, get_family
from pynbody.filt import (
    Annulus as _Annulus,
    BandPass as _BandPass,
    Cuboid as _Cuboid,
    Disc as _Disc,
    FamilyFilter as _FamilyFilter,
    HighPass as _HighPass,
    LowPass as _LowPass,
    SolarNeighborhood as _SolarNeighborhood,
    Sphere as _Sphere,
)
from pynbody.snapshot import SimSnap
from pynbody.units import UnitBase

from pynbodyext.core.calculate import FilterBase, Param

__all__ = [
    "Sphere",
    "FamilyFilter",
    "Cuboid",
    "Disc",
    "Annulus",
    "BandPass",
    "HighPass",
    "LowPass",
    "SolarNeighborhood",
]

ValueLike: TypeAlias = float | str | UnitBase

ArrayLike: TypeAlias = tuple[float, float, float] | SimArray | np.ndarray

FamilyLike: TypeAlias = Family | str


class VolumeFilter(FilterBase):
    """A filter that defines a volume in the simulation space."""

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        """Return the volume of the filter."""
        raise NotImplementedError


@VolumeFilter.dataclass
class Sphere(VolumeFilter, _Sphere):
    """Spherical selection filter.

    Parameters
    ----------
    radius : float, unit-like, callable, or CalculatorBase
        Sphere radius.  Calculator-valued radii are evaluated in the current
        scope before the mask is built.
    cen : array-like, callable, or CalculatorBase, default: (0, 0, 0)
        Sphere center in position units.
    """

    signature_name = "pynbodyext.filters.Sphere"

    radius: Param[ValueLike] = Param(field_name="pos")
    cen: Param[ArrayLike] = Param(default=(0, 0, 0), field_name="pos")

    def calculate(self, sim, params=None):
        return _Sphere(params.radius, params.cen)(sim)

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        radius = self.resolve_param_for_sim(sim, "radius", options=options, coerce_unit_string=True)
        return 4.0 / 3.0 * np.pi * radius**3


@FilterBase.dataclass
class FamilyFilter(FilterBase, _FamilyFilter):
    """Family selection filter."""

    signature_name = "pynbodyext.filters.FamilyFilter"

    family: Param[FamilyLike]

    def __post_init__(self) -> None:
        if isinstance(self.family, str):
            self.family = get_family(self.family, False)
        if isinstance(self.family, Family):
            return
        if callable(self.family):
            return
        raise ValueError(
            f"Invalid family parameter: {self.family}. Expected a Family instance, string, or callable returning a Family."
        )

    def calculate(self, sim: SimSnap, params: Any = None) -> Any:
        family = get_family(params.family, False)
        return _FamilyFilter(family)(sim)


@VolumeFilter.dataclass
class Cuboid(VolumeFilter, _Cuboid):
    """Cuboid selection filter.

    Parameters
    ----------
    x1, y1, z1, x2, y2, z2 : float, unit-like, callable, or CalculatorBase
        Coordinates of the cuboid corners.  Calculator-valued coordinates are
        evaluated in the current scope before the mask is built.
    """

    signature_name = "pynbodyext.filters.Cuboid"

    x1: Param[ValueLike] = Param(field_name="pos")
    y1: Param[ValueLike] = Param(default=None, field_name="pos")
    z1: Param[ValueLike] = Param(default=None, field_name="pos")
    x2: Param[ValueLike] = Param(default=None, field_name="pos")
    y2: Param[ValueLike] = Param(default=None, field_name="pos")
    z2: Param[ValueLike] = Param(default=None, field_name="pos")

    def calculate(self, sim, params=None):
        return _Cuboid(params.x1, params.y1, params.z1, params.x2, params.y2, params.z2)(sim)

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        x1 = self.resolve_param_for_sim(sim, "x1", options=options, coerce_unit_string=True)
        y1 = self.resolve_param_for_sim(sim, "y1", options=options, coerce_unit_string=True)
        z1 = self.resolve_param_for_sim(sim, "z1", options=options, coerce_unit_string=True)

        x2 = self.resolve_param_for_sim(sim, "x2", options=options, coerce_unit_string=True)
        y2 = self.resolve_param_for_sim(sim, "y2", options=options, coerce_unit_string=True)
        z2 = self.resolve_param_for_sim(sim, "z2", options=options, coerce_unit_string=True)

        l1 = (x2 - x1) if x2 is not None else 2 * x1
        l2 = (y2 - y1) if y2 is not None else 2 * y1
        l3 = (z2 - z1) if z2 is not None else 2 * z1
        return l1 * l2 * l3


@VolumeFilter.dataclass
class Disc(VolumeFilter, _Disc):
    """Disc selection filter."""

    signature_name = "pynbodyext.filters.Disc"

    radius: Param[ValueLike] = Param(field_name="pos")
    height: Param[ValueLike] = Param(field_name="pos")
    cen: Param[ArrayLike] = Param(default=(0, 0, 0), field_name="pos")

    def calculate(self, sim, params=None):
        return _Disc(params.radius, params.height, params.cen)(sim)

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        radius = self.resolve_param_for_sim(sim, "radius", options=options, coerce_unit_string=True)
        height = self.resolve_param_for_sim(sim, "height", options=options, coerce_unit_string=True)
        return 2 * np.pi * radius**2 * height


@FilterBase.dataclass
class BandPass(FilterBase, _BandPass):
    """Selects particles in a bandpass of a named property

    Parameters
    ----------
    prop: str
        The name of the simulation array to filter on.
    min: ValueLike
        The minimum value of the property. If a string, it is interpreted as a unit string.
    max: ValueLike
        The maximum value of the property. If a string, it is interpreted as a unit string.
    """

    signature_name = "pynbodyext.filters.BandPass"

    prop: str
    min: Param[ValueLike]
    max: Param[ValueLike]

    def calculate(self, sim: SimSnap, params: Any = None) -> Any:
        return _BandPass(params.prop, params.min, params.max)(sim)


@FilterBase.dataclass
class HighPass(FilterBase, _HighPass):
    """Selects particles above a threshold in a named property

    Parameters
    ----------
    prop: str
        The name of the simulation array to filter on.
    min: ValueLike
        The minimum value of the property. If a string, it is interpreted as a unit string.
    """

    signature_name = "pynbodyext.filters.HighPass"

    prop: str
    min: Param[ValueLike]

    def calculate(self, sim: SimSnap, params: Any = None) -> Any:
        return _HighPass(params.prop, params.min)(sim)


@FilterBase.dataclass
class LowPass(FilterBase, _LowPass):
    """Selects particles below a threshold in a named property

    Parameters
    ----------
    prop: str
        The name of the simulation array to filter on.
    max: ValueLike
        The maximum value of the property. If a string, it is interpreted as a unit string.
    """

    signature_name = "pynbodyext.filters.LowPass"

    prop: str
    max: Param[ValueLike]

    def calculate(self, sim: SimSnap, params: Any = None) -> Any:
        return _LowPass(params.prop, params.max)(sim)


@VolumeFilter.dataclass
class Annulus(VolumeFilter, _Annulus):
    """Annulus selection filter.

    Parameters
    ----------
    r1: float, unit-like, callable, or CalculatorBase
        Inner radius of the annulus.  Calculator-valued radii are evaluated in the current scope before the mask is built.
    r2: float, unit-like, callable, or CalculatorBase
        Outer radius of the annulus.  Calculator-valued radii are evaluated in the current scope before the mask is built.
    cen: array-like, callable, or CalculatorBase, default: (0, 0, 0)
        Annulus center in position units.
    """

    signature_name = "pynbodyext.filters.Annulus"

    r1: Param[ValueLike] = Param(field_name="pos")
    r2: Param[ValueLike] = Param(field_name="pos")
    cen: Param[ArrayLike] = Param(default=(0, 0, 0), field_name="pos")

    def calculate(self, sim, params=None):
        return _Annulus(params.r1, params.r2, params.cen)(sim)

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        r1 = self.resolve_param_for_sim(sim, "r1", options=options, coerce_unit_string=True)
        r2 = self.resolve_param_for_sim(sim, "r2", options=options, coerce_unit_string=True)
        return 4.0 / 3.0 * np.pi * (r2**3 - r1**3)


@VolumeFilter.dataclass
class SolarNeighborhood(VolumeFilter, _SolarNeighborhood):
    """Solar neighborhood selection filter."""

    signature_name = "pynbodyext.filters.SolarNeighborhood"

    r1: Param[ValueLike] = Param(default="5 kpc", field_name="pos")
    r2: Param[ValueLike] = Param(default="10 kpc", field_name="pos")
    height: Param[ValueLike] = Param(default="2 kpc", field_name="pos")
    cen: Param[ArrayLike] = Param(default=(0, 0, 0), field_name="pos")

    def calculate(self, sim, params=None):
        return _SolarNeighborhood(params.r1, params.r2, params.height, params.cen)(sim)

    def volume(self, sim: SimSnap | None = None, *, options: Any | None = None) -> float | UnitBase:
        r1 = self.resolve_param_for_sim(sim, "r1", options=options, coerce_unit_string=True)
        r2 = self.resolve_param_for_sim(sim, "r2", options=options, coerce_unit_string=True)
        height = self.resolve_param_for_sim(sim, "height", options=options, coerce_unit_string=True)
        return 2 * np.pi * height * (r2**2 - r1**2)

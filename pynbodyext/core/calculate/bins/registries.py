"""Every extension registry the bins package has, in one place.

``BinsRegistry`` is the bundle callers see; the storage and the rules that guard a
registration live here rather than in the module that happens to *use* the registry.
The axis registries are the case that matters: ``axes.py`` reads them (an axis's
``measure``, its dynamic properties), ``result.py`` subscribes to them, and neither
owns them — so they live here, and the import direction is ``axes -> registries``.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

    from .result import BinNDResult

BinDerivedCondition = Callable[[Any], bool]
BinDerivedFunc = Callable[[Any], Any]


@dataclass(frozen=True)
class BinDerivedSpec:
    """One derived query: the callback, when it applies, and how far it reaches.

    ``scope`` says which family of queries it answers (``geometry`` for an axis
    property, ``derived`` for a computed one); ``allow_sph`` says whether a
    smoothed render may answer it, which is only true when the callback is a
    per-cell function of its inputs.
    """

    name: str
    func: BinDerivedFunc
    condition: BinDerivedCondition | None = None
    scope: str = "geometry"
    allow_sph: bool = False

    def is_available(self, bins: Any) -> bool:
        return True if self.condition is None else bool(self.condition(bins))


# ---------------------------------------------------------------------------
# Axis measures
# ---------------------------------------------------------------------------

#: axis alias / prop string -> per-bin measure function
AXIS_MEASURES: dict[str, Callable[[Any], np.ndarray]] = {}

#: named measure type -> per-bin measure function (``spherical_shell``, ...)
AXIS_MEASURE_TYPES: dict[str, Callable[[Any], np.ndarray]] = {
    "spherical_shell": lambda axis: axis.shell_volume,
    "annulus": lambda axis: axis.annulus_area,
    "linear": lambda axis: axis.widths,
}

#: live ``BinNDResult`` instances to tell when a measure type is redefined; each
#: exposes ``_on_axis_measure_change(name, name) -> (count, names)``
MEASURE_SUBSCRIBERS: weakref.WeakSet = weakref.WeakSet()

#: dynamic axis property -> evaluator (``center``, ``min``, ``width``, ...)
AXIS_PROPERTIES: dict[str, Callable[[Any], Any]] = {}


def register_axis_property(name: str, func: Callable[[Any], Any], *, overwrite: bool = False) -> None:
    """Add *func* as the evaluator of the ``axis.<name>`` property."""
    if not overwrite and name in AXIS_PROPERTIES:
        raise KeyError(f"Axis property {name!r} is already registered.")
    AXIS_PROPERTIES[name] = func


def register_axis_measure(alias: str, func: Callable[[Any], np.ndarray], *, overwrite: bool = False) -> None:
    """Register a physical measure for one axis alias (or prop string)."""
    if not overwrite and alias in AXIS_MEASURES:
        raise KeyError(f"Axis measure for alias {alias!r} is already registered.")
    AXIS_MEASURES[alias] = func


def register_measure_type(name: str, func: Callable[[Any], np.ndarray], *, overwrite: bool = False) -> None:
    """Register a named measure type; redefining one notifies the live results."""
    if not overwrite and name in AXIS_MEASURE_TYPES:
        raise KeyError(f"Measure type {name!r} is already registered.")
    old_func = AXIS_MEASURE_TYPES.get(name)
    AXIS_MEASURE_TYPES[name] = func
    if overwrite and old_func is not None and old_func is not func:
        _notify_measure_change(name)


def subscribe_measure_changes(owner: Any) -> None:
    """Tell *owner* (a ``BinNDResult``) about redefinitions of a measure type.

    A cached density was computed against *some* measure, so a redefinition makes
    the affected entries wrong; the result drops them through
    ``_on_axis_measure_change``.  A weak set, so a discarded result is not kept
    alive by the registry.
    """
    MEASURE_SUBSCRIBERS.add(owner)


def _notify_measure_change(name: str) -> None:
    total_cleared = 0
    all_cleared: list[str] = []
    for subscriber in list(MEASURE_SUBSCRIBERS):
        try:
            cleared, names = subscriber._on_axis_measure_change(name, name)
        except Exception:  # noqa: BLE001 - one broken subscriber must not stop the others
            continue
        total_cleared += cleared
        all_cleared.extend(names)
    if total_cleared > 0:
        unique = sorted(set(all_cleared))
        logging.getLogger("pynbody").warning(
            "Measure type %r redefined (overwrite=True). Cleared %d cached entr%s: %s.",
            name,
            total_cleared,
            "y" if total_cleared == 1 else "ies",
            ", ".join(unique),
        )


class DerivedRegistry:
    """Per-class derived-property registry used by ``BinNDResult.derived``."""

    def __init__(self) -> None:
        self._specs: dict[type, dict[str, BinDerivedSpec]] = {}

    def register(
        self,
        owner_cls: type,
        fn: Callable[[Any], Any] | str | None = None,
        *,
        name: str | None = None,
        scope: str = "derived",
        condition: Any = None,
        overwrite: bool = False,
    ) -> Any:
        if isinstance(fn, str):
            return self.register(owner_cls, name=fn, scope=scope, condition=condition, overwrite=overwrite)

        def decorator(func: Callable[[Any], Any]) -> Callable[[Any], Any]:
            query_name = name or func.__name__
            self._register(owner_cls, query_name, func, scope=scope, condition=condition, overwrite=overwrite)
            return func

        if fn is None:
            return decorator
        return decorator(fn)

    def _register(
        self, owner_cls: type, name: str, func: Callable[[Any], Any], *, scope: str, condition: Any, overwrite: bool
    ) -> None:
        bucket = self._specs.setdefault(owner_cls, {})
        if not overwrite and name in bucket:
            raise KeyError(f"BinNDResult derived property {name!r} is already registered.")
        bucket[name] = BinDerivedSpec(name=name, func=func, scope=scope, condition=condition)

    def get(self, owner: BinNDResult | type[BinNDResult], key: str) -> BinDerivedSpec | None:
        for cls in self._mro(owner):
            spec = self._specs.get(cls, {}).get(key)
            if spec is not None and spec.is_available(owner):
                return spec
        return None

    def keys(self, owner: BinNDResult | type[BinNDResult]) -> list[str]:
        out: set[str] = set()
        for cls in self._mro(owner):
            out.update(n for n, spec in self._specs.get(cls, {}).items() if spec.is_available(owner))
        return sorted(out)

    @staticmethod
    def _mro(owner: Any) -> list[type]:
        return owner.mro() if isinstance(owner, type) else type(owner).mro()


class BinsRegistry:
    """Bundle of the bins extension registries (single source of truth)."""

    def __init__(self) -> None:
        self.derived = DerivedRegistry()

    @property
    def stat(self) -> Any:
        from .statistics import STAT_REGISTRY

        return STAT_REGISTRY

    @property
    def pipeline(self) -> Any:
        from .statistics import PIPELINE_PARSER

        return PIPELINE_PARSER

    @property
    def algorithms(self) -> Any:
        """The bin-algorithm registry (``{name: (values, nbins, vmin, vmax) -> edges}``)."""
        from ._axis_edges import BIN_ALGORITHMS

        return BIN_ALGORITHMS

    @property
    def measures(self) -> Any:
        """The axis-measure registry (keyed by axis alias / prop string)."""
        return AXIS_MEASURES

    @property
    def measure_types(self) -> Any:
        """The named axis-measure-type registry (``spherical_shell``, ``annulus``, ...)."""
        return AXIS_MEASURE_TYPES

    @property
    def axis_properties(self) -> Any:
        """The dynamic axis-property registry (name -> evaluator callable)."""
        return AXIS_PROPERTIES

    def register_derived(
        self,
        fn: Callable[[Any], Any] | str | None = None,
        *,
        name: str | None = None,
        scope: str = "derived",
        condition: Any = None,
        overwrite: bool = False,
    ) -> Any:
        from .result import BinNDResult

        return self.derived.register(BinNDResult, fn, name=name, scope=scope, condition=condition, overwrite=overwrite)

    def derived_keys(self) -> list[str]:
        from .result import BinNDResult

        return self.derived.keys(BinNDResult)


# Default instance used by exported classmethods/decorators for back-compat.
DEFAULT_REGISTRY = BinsRegistry()

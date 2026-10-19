"""Query resolution, typed caching, statistics, density, and apply.

This module decomposes the former ``query_engine`` into focused collaborating
pieces: a typed :class:`QueryCache`, a :class:`StatPipeline` (vectorised
statistics with a per-bin fallback), a :class:`DensityResolver`, an
:class:`ApplyComposer`, and an orchestrating :class:`BinQueryService`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ._query_cache import ApplyKey, DerivedKey, PipelineStatKey, QueryCache
from ._query_engines import (
    ApplyComposer,
    DensityResolver,
    StatPipeline,
    _wrap,
    callable_cache_token,
    evaluate_derived,
    weight_cache_token,
)
from .extensions import BIN_RESULT_EXTENSIONS

if TYPE_CHECKING:
    from collections.abc import Callable

    from pynbodyext.core.calculate.nodes.base import CalculatorBase

    from .arrays import BinsArray
    from .axes import BinDerivedSpec
    from .model import BinResultModel
    from .result import BinNDResult

# Re-exported: ``sph_render`` and the bin nodes import these from ``.query``.
__all__ = [
    "ApplyKey",
    "BinQueryService",
    "DerivedKey",
    "DensityResolver",
    "PipelineStatKey",
    "QueryCache",
    "StatPipeline",
]


class BinQueryService:
    """Orchestrates query resolution over a model, using the owner for extensions."""

    def __init__(self, model: BinResultModel, owner: BinNDResult, diagnostics: Any, *, extensions: Any = None) -> None:
        self._model = model
        self._owner = owner
        self._diagnostics = diagnostics
        self._extensions = extensions if extensions is not None else BIN_RESULT_EXTENSIONS
        self._cache = QueryCache()
        self._stat = StatPipeline(model, owner, self._cache)
        self._density = DensityResolver(owner, self._cache, self._owner._resolve_query)
        self._apply = ApplyComposer(model, owner, self._cache, diagnostics)

    @property
    def num_cached_arr(self) -> int:
        return self._cache.num_cached

    def keys(self) -> list[str]:
        keys: set[str] = set()
        keys.update(self.property_keys())
        for cache_key in self._cache.keys():
            if isinstance(cache_key, PipelineStatKey):
                base = (
                    f"{cache_key.field}.{'.'.join(cache_key.transforms)}.{cache_key.stat_key}"
                    if cache_key.transforms
                    else f"{cache_key.field}.{cache_key.stat_key}"
                )
                keys.add(f"{base}@{cache_key.weight_token}" if isinstance(cache_key.weight_token, str) else base)
            elif isinstance(cache_key, DerivedKey):
                keys.add(cache_key.name)
        return sorted(keys)

    def property_keys(self) -> list[str]:
        return self._extensions.property_keys(self._owner)

    def resolve(self, key: str) -> BinsArray:
        scope = self._extensions.query_scope(self._owner, key)
        parsed = self._extensions.parse_pipeline_key(key)
        if parsed is not None:
            field, transforms, terminal_stat, weight_field = parsed
            result = self.stat_pipeline(field, transforms, terminal_stat, weight=weight_field, query_key=key)
            self._diagnostics.record("query", key=key, scope=scope)
            return result

        density_base = self._density.strip(key)
        if density_base is not None or key == "density":
            return self._density.resolve(key, density_base if density_base is not None else key)

        cache_key = DerivedKey(scope, key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        arr = self.compute_query(key, scope=scope)
        self._cache.put(cache_key, arr)
        self._diagnostics.record("query", key=key, scope=scope)
        return arr

    def wrap(self, values: Any, *, name: str, field: str | None = None, mode: str | None = None) -> BinsArray:
        return _wrap(self._owner, values, name=name, field=field, mode=mode)

    def compute_query(self, key: str, *, scope: str) -> BinsArray:
        spec = self._extensions.get_derived_spec(self._owner, key)
        if spec is not None:
            return self.compute_derived(spec)
        raise KeyError(
            f"Unknown BinND query {key!r}. "
            "Use 'field.stat' syntax (e.g. 'mass.sum') for particle statistics. "
            "For axis properties use bins.axes['r'].center."
        )

    def compute_derived(self, spec: BinDerivedSpec) -> BinsArray:
        return evaluate_derived(self._owner, spec, self._model)

    def stat_pipeline(
        self,
        field: str,
        transforms: list[str],
        terminal_stat: Any,
        *,
        weight: str | Callable[[Any], Any] | Any | None = None,
        query_key: str | None = None,
    ) -> BinsArray:
        return self._stat.compute(field, transforms, terminal_stat, weight=weight, query_key=query_key)

    def stat_explicit(
        self,
        field: str,
        statistic: str,
        weight: str | Callable[[Any], Any] | Any | None = None,
        transforms: list[str] | None = None,
    ) -> BinsArray:
        stat_obj = self._extensions.get_statistic(statistic)
        if stat_obj is None:
            raise KeyError(f"Unknown statistic {statistic!r}.")
        return self.stat_pipeline(field, transforms or [], stat_obj, weight=weight)

    def apply(
        self,
        query: Callable[[Any], Any] | CalculatorBase[Any, Any],
        *,
        name: str | None = None,
        empty: float = np.nan,
        vectorized: bool = False,
    ) -> BinsArray:
        return self._apply.apply(query, name=name, empty=empty, vectorized=vectorized)

    @staticmethod
    def weight_cache_token(weight: str | Callable[[Any], Any] | Any | None) -> Any:
        return weight_cache_token(weight)

    @staticmethod
    def callable_cache_token(query: Any) -> Any:
        return callable_cache_token(query)

    def cache_report(self) -> dict[str, Any]:
        owner = self._owner
        return {"queries": self._cache.num_cached, "subresults": owner.nsubs, "total_queries": owner.cache.total_cached}

    def query_report(self) -> list[dict[str, Any]]:
        return list(self._diagnostics.diagnostics)

    def invalidate_measure_dependent_cache(self) -> tuple[int, list[str]]:
        return self._cache.invalidate_measure_dependent()

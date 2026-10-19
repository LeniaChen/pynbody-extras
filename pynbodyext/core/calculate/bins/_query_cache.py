"""Typed query cache and the keys that address it.

Every answer a binned result computes is keyed by *what was asked*: a statistic
pipeline (field, transforms, statistic, weight), a derived or geometry query, or an
applied callable.  The keys are frozen dataclasses so they hash and compare by
value; ``QueryCache`` stores the arrays, and ``invalidate_measure_dependent`` drops
the entries whose meaning depends on an axis measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .arrays import BinsArray


CacheKey = Any  # PipelineStatKey | DerivedKey | ApplyKey

@dataclass(frozen=True)
class PipelineStatKey:
    field: str
    transforms: tuple[str, ...]
    stat_key: str
    weight_token: Any

@dataclass(frozen=True)
class DerivedKey:
    scope: str
    name: str

@dataclass(frozen=True)
class ApplyKey:
    query_token: Any
    name: str | None
    empty: float
    vectorized: bool

class QueryCache:
    """Typed-key cache for resolved queries."""

    def __init__(self) -> None:
        self._cache: dict[CacheKey, BinsArray] = {}

    def get(self, key: CacheKey) -> BinsArray | None:
        return self._cache.get(key)

    def put(self, key: CacheKey, arr: BinsArray) -> None:
        self._cache[key] = arr

    @property
    def num_cached(self) -> int:
        return len(self._cache)

    def keys(self) -> list[CacheKey]:
        return list(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    def invalidate_measure_dependent(self) -> tuple[int, list[str]]:
        """Clear cached entries that depend on the axis measure.

        These are density-derived entries (canonical names ending in
        ``.density``) and the ``geometry.measure`` entry.  Returns
        ``(count, cleared_names)``.
        """
        to_del: list[CacheKey] = []
        names: list[str] = []
        for k in self._cache:
            if isinstance(k, DerivedKey):
                if (k.scope == "derived" and k.name.endswith(".density")) or (
                    k.scope == "geometry" and k.name == "measure"
                ):
                    to_del.append(k)
                    names.append(k.name)
        for k in to_del:
            del self._cache[k]
        return len(to_del), names

def _cache_key_for_stat(field: str, transforms: tuple[str, ...], stat_key: str, weight_token: Any) -> PipelineStatKey:
    return PipelineStatKey(field, transforms, stat_key, weight_token)

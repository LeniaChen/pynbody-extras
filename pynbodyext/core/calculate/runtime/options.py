"""Run-time execution options for calculator evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from pynbodyext.core.calculate.display import InfoView, display_value
from pynbodyext.core.calculate.result.enums import ErrorPolicy, RecordPolicy, normalize_error_policy

if TYPE_CHECKING:
    from .progress import ProgressSink


class RunOptionKwargs(TypedDict, total=False):
    """Keyword overrides accepted by ``CalculatorBase.run`` and ``__call__``.

    One name per :class:`RunOptions` field, so a call can override any option
    without ``run``, ``__call__`` and ``_resolve_run_options`` each listing them
    again: ``calc.run(sim, perf_memory=True)``.  ``total=False`` because every
    option is optional; a name passed as ``None`` keeps the value the base options
    already had.

    ``tests/test_calculate_contract.py`` pins this against :class:`RunOptions`, so
    the two cannot drift.
    """

    cache: bool
    progress: bool | str | ProgressSink | list[ProgressSink] | tuple[ProgressSink, ...] | None
    perf_time: bool
    perf_memory: bool
    observe: bool
    backend: str
    default_record_policy: RecordPolicy
    errors: ErrorPolicy | str
    cache_small_value_bytes: int
    auto_record_cached_values: bool
    auto_record_small_value_bytes: int | None


@dataclass(slots=True)
class RunOptions(InfoView):
    """Execution options for a calculator run.

    Parameters
    ----------
    cache : bool, default: True
        Enable the per-run runtime cache.
    progress : bool, str, ProgressSink, or sequence, optional
        Progress reporting configuration. Strings may be "run", "node",
        "phase", "debug", "bar", or "bar:<verbosity>", or "bar-only".
    perf_time, perf_memory : bool
        Enable time and memory collection.
    observe : bool, default: True
        Enable diagnostic observation of pynbody snapshot field reads and
        invalidations. Disable this to avoid installing observer patches.
    backend : str, default: "serial"
        Backend label reserved for future execution backends.
    default_record_policy : RecordPolicy, default: RecordPolicy.SUMMARY
        Recording policy for nodes without an explicit policy.
    errors : ErrorPolicy or str, default: ErrorPolicy.RAISE
        Error handling policy.
    cache_small_value_bytes : int, default: 10_000_000
        Maximum public-value size for automatic cache storage.
    auto_record_cached_values : bool, default: True
        When true, cached SUMMARY nodes may retain their public value in the
        returned result.
    auto_record_small_value_bytes : int or None, default: 1_000_000
        Maximum public-value size for automatic SUMMARY recording of cached
        values. ``None`` disables auto-recording.
    """

    cache: bool = True
    progress: bool | str | ProgressSink | list[ProgressSink] | tuple[ProgressSink, ...] | None = None
    perf_time: bool = True
    perf_memory: bool = False
    observe: bool = True
    backend: str = "serial"
    default_record_policy: RecordPolicy = RecordPolicy.SUMMARY
    errors: ErrorPolicy | str = ErrorPolicy.RAISE
    cache_small_value_bytes: int = 10_000_000
    auto_record_cached_values: bool = True
    auto_record_small_value_bytes: int | None = 1_000_000

    def __post_init__(self) -> None:
        self.errors = normalize_error_policy(self.errors)

    def _fields(self) -> list[tuple[str, str, Any]]:
        """``(repr name, display label, value)`` for every option.

        The one field list behind both the text repr and the HTML table, so the
        two cannot list different options.
        """
        return [
            ("cache", "cache", self.cache),
            ("progress", "progress", self.progress),
            ("perf_time", "perf time", self.perf_time),
            ("perf_memory", "perf memory", self.perf_memory),
            ("observe", "observe", self.observe),
            ("backend", "backend", self.backend),
            ("default_record_policy", "record policy", display_value(self.default_record_policy)),
            ("errors", "errors", display_value(self.errors)),
            ("cache_small_value_bytes", "small cache bytes", self.cache_small_value_bytes),
            ("auto_record_cached_values", "auto record cached values", self.auto_record_cached_values),
            ("auto_record_small_value_bytes", "auto record small bytes", self.auto_record_small_value_bytes),
        ]

    def __repr__(self) -> str:
        parts = ", ".join(f"{name}={value!r}" for name, _, value in self._fields())
        return f"RunOptions({parts})"

    def _repr_pretty_(self, printer: Any, cycle: bool) -> None:
        printer.text("RunOptions(...)" if cycle else repr(self))

    def _display_rows(self) -> list[tuple[str, Any]]:
        return [(label, value) for _, label, value in self._fields()]

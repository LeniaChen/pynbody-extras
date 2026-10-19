"""Kernel-weighted quantiles: the two ways to take a percentile of weighted samples.

A weighted quantile is not linear in its weights, so it cannot be accumulated on the
fly the way a mean can — it needs each sample's ``(value, weight)`` pair:

- :func:`weighted_percentiles` is the definition: order the samples, walk the
  cumulative weight, interpolate.  ``segments`` answers many independent samples at
  once (one per cell, say), accepting either the segment lengths or a per-sample
  index.
- :func:`bucketed_weighted_percentiles` gives the same answer without ordering:
  it counts weight into value bins and orders only the entries a percentile falls
  between, which is O(pairs) instead of O(pairs log pairs).  The bin count comes
  from the caller, so the caller owns the speed/accuracy trade.

Both are used by ``bins`` (the strict queries and the SPH view), and
``tests/test_bins_query.py`` checks the bucketed form against the exact one.  The
coercion helper :func:`_as_float` lives here because both halves need it.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_float(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=float)




def _flat_samples(values: Any, weights: Any, segments: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Flatten a batch of samples into values, weights and a sample index each.

    Accepts one sample (1-D), one per row (2-D), or flat arrays with a length per
    segment; the caller gets the same three things either way.
    """
    values_array = np.asarray(values, dtype=float)
    weights_array = np.asarray(weights, dtype=float)
    if values_array.shape != weights_array.shape:
        raise ValueError(
            f"values and weights must have the same shape, got {values_array.shape} and {weights_array.shape}."
        )
    if segments is not None:
        lengths = np.asarray(segments, dtype=int)
        sample_of = np.repeat(np.arange(len(lengths)), lengths)
        if len(values_array) != len(sample_of):
            raise ValueError(f"segments describe {len(sample_of)} values, got {len(values_array)}.")
        return values_array.ravel(), weights_array.ravel(), sample_of, len(lengths)
    if values_array.ndim == 1:
        values_array = values_array[None, :]
        weights_array = weights_array[None, :]
    if values_array.ndim != 2:
        raise ValueError(f"values must be 1-D or 2-D, got shape {values_array.shape}.")
    sample_of = np.repeat(np.arange(len(values_array)), values_array.shape[1])
    return values_array.ravel(), weights_array.ravel(), sample_of, len(values_array)


def weighted_percentiles(values: Any, weights: Any, percentile: float, *, segments: Any = None) -> np.ndarray | float:
    """Weighted percentile of one sample, of every row of a 2-D batch — or of a
    flat batch split into ``segments``.

    The definition is the one the weighted :class:`Percentile` has always used: the
    pairs are sorted by value, the cumulative weight is shifted so the lightest
    value sits at zero, normalised by the total, and the percentile is
    interpolated along that curve.  Two details matter at the edges:

    - a sample whose weight sits on a single value *is* that value (there is no
      curve to interpolate, and this used to come back as ``NaN``);
    - values that are not finite carry no information and are dropped, as the
      kernel sums drop them — weights and values have to be finite together.

    Parameters
    ----------
    values, weights : array_like
        Per-value values and weights, the same shape.
    percentile : float
        Percentile in ``[0, 100]``.
    segments : array_like of int, optional
        For flat input: the length of each consecutive sample.  This is how a
        scattering of particles onto cells is reduced — one segment per cell,
        however many particles landed in it — without padding every cell to the
        largest one.  The values are sorted within their segment here, so the
        caller need not order them.

    Returns
    -------
    numpy.ndarray or float
        A float for a single 1-D sample, else one value per sample (row, or
        segment), ``NaN`` where nothing carries weight.

    Examples
    --------
    >>> weighted_percentiles([1.0, 2.0, 3.0], [1.0, 1.0, 1.0], 50.0)
    2.0
    >>> weighted_percentiles([[1.0, 2.0], [3.0, 4.0]], [[1.0, 1.0], [1.0, 3.0]], 50.0)
    array([1.5, 3.5])
    >>> # segments are independent: [6.0], then the median of [1.0, 2.0, 3.0]
    >>> weighted_percentiles([6.0, 1.0, 2.0, 3.0], [1.0, 1.0, 1.0, 1.0], 50.0, segments=[1, 3])
    array([6., 2.])
    >>> # a segment with no weight at all is NaN, not a wrong number
    >>> weighted_percentiles([6.0, 1.0], [1.0, 0.0], 50.0, segments=[1, 1])
    array([ 6., nan])
    """
    single = segments is None and np.asarray(values).ndim == 1
    values_array, weights_array, sample_of, n_samples = _flat_samples(values, weights, segments)

    carries = (weights_array > 0.0) & np.isfinite(values_array)
    samples = sample_of[carries]
    counts = np.bincount(samples, minlength=n_samples)
    out = np.full(n_samples, np.nan)

    # Cell-major, value-sorted: the segments come out contiguous, and the sorting
    # puts the weighted, finite values of each before the rest.
    order = np.lexsort((values_array[carries], samples))
    sorted_values = values_array[carries][order]
    sorted_weights = weights_array[carries][order]
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]]).astype(np.intp)

    one_point = counts == 1
    if one_point.any():
        out[one_point] = sorted_values[starts[one_point]]

    several = counts > 1
    if several.any():
        # The lightest value sits at zero and the total excludes it, exactly as the
        # scalar definition does; "base" is the weight accumulated before each
        # segment starts.
        cumulative = np.cumsum(sorted_weights)
        last = max(len(sorted_weights) - 1, 0)
        safe_starts = np.clip(starts, 0, last)
        base = np.concatenate([[0.0], cumulative[:-1]])[safe_starts]
        first_weight = sorted_weights[safe_starts]
        ends = np.clip(starts + np.maximum(counts, 1) - 1, 0, last)
        segment_total = (cumulative[ends] - base) - first_weight
        shifted = (cumulative - np.repeat(base, counts)) - np.repeat(first_weight, counts)
        # The lightest value *is* the zero of the curve; cancellation in the line
        # above can leave it a few ulps off, which is enough to move a percentile
        # of 0 onto the next value.
        shifted[starts[counts > 0]] = 0.0
        total = np.repeat(segment_total, counts)
        with np.errstate(invalid="ignore", divide="ignore"):
            cdf = shifted / total

        # np.interp's lookup, done for every segment at once: the bracket is the
        # first entry whose cumulative weight reaches the percentile, and a target
        # on a knot interpolates to it.
        target = float(percentile) / 100.0
        reached = np.flatnonzero(cdf >= target)
        first = np.unique(samples[order][reached], return_index=True)[1]
        hit = reached[first]
        previous = np.maximum(hit - 1, starts[samples[order][hit]])
        low, high = cdf[previous], cdf[hit]
        below, above = sorted_values[previous], sorted_values[hit]
        with np.errstate(invalid="ignore", divide="ignore"):
            fraction = np.where(high > low, (target - low) / (high - low), 0.0)
        interpolated = below + np.nan_to_num(fraction) * (above - below)
        out[samples[order][hit]] = interpolated

    return float(out[0]) if single else out


def _lightest_weight(
    sample: np.ndarray, value: np.ndarray, weight: np.ndarray, which: np.ndarray, first_bin: np.ndarray, samples: int
) -> np.ndarray:
    """Weight of each sample's smallest value, which the definition excludes.

    Only the first occupied bin can hold it, so only that bin is ordered.
    """
    in_first = np.flatnonzero(which == first_bin[sample])
    in_first = in_first[np.lexsort((value[in_first], sample[in_first]))]
    heads = np.unique(sample[in_first], return_index=True)[1]
    lightest = np.full(samples, np.nan)
    lightest[sample[in_first[heads]]] = weight[in_first[heads]]
    return lightest


def _bracket(
    sample: np.ndarray, which: np.ndarray, cumulative: np.ndarray, occupied: np.ndarray, crossing: np.ndarray, bins: int
) -> tuple[np.ndarray, np.ndarray]:
    """Weight below the bracketing bins, and the entries that bracket the crossing.

    The value just below the crossing is the largest one in the highest *occupied*
    bin under it — not simply "the bin below", since a lumpy distribution can leave
    several bins empty between the two values a percentile falls between.
    """
    positions = np.arange(bins)[None, :]
    occupied_below = np.where(occupied & (positions < crossing[:, None]), positions, -1)
    below_bin = occupied_below.max(axis=1)
    has_below = below_bin >= 0
    rows = np.arange(len(cumulative))
    base = np.where(has_below, np.where(below_bin > 0, cumulative[rows, np.maximum(below_bin - 1, 0)], 0.0), 0.0)
    picked = which == crossing[sample]
    picked |= has_below[sample] & (which == below_bin[sample])
    return base, picked


def bucketed_weighted_percentiles(
    values: Any, weights: Any, percentile: float, *, sample_of: Any, samples: int, bins: int = 1024
) -> np.ndarray:
    """``weighted_percentiles(..., segments=...)`` without ordering every sample.

    The sorted path pays ``O(n log n)`` per cell for the *values*, and in the SPH
    quantile engine that is the single largest cost after the particle-cell pairs
    themselves are built.  Ordering is not actually needed: counting the weights
    into value *bins* is one ``O(n)`` pass, and the percentile is the bin where the
    cumulative weight crosses the target.  Only the entries in that bin — and the
    one below it, for the case where the crossing straddles a bin edge — are
    ordered, which the bins keep small.

    The answer is the sorted path's own, exactly, including its two edge
    conventions: the lightest value's weight is excluded from the distribution (so
    a single-point sample is that point) and the percentile is interpolated
    linearly between the two values it falls between.  Entries with a non-positive
    weight or a non-finite value are dropped, as there.

    Parameters
    ----------
    values, weights : array_like
        Flat per-entry values and weights, the same shape.  Entries need **not** be
        ordered — that is the point of this function: the sorted path needs a value
        ordering per sample, this one counts into bins and orders only the handful
        of entries a percentile falls between.
    percentile : float
        Percentile in ``[0, 100]``.
    sample_of : array_like of int
        Which sample each entry belongs to, in ``[0, samples)``.
    samples : int
        How many samples there are.
    bins : int, default: 1024
        How many value bins to count into.  More bins make the refinement cheaper
        (fewer entries per bin) and the counting pass no slower; memory is
        ``len(segments) * bins`` weights, so the engine lowers this for a wide slab.

    Returns
    -------
    numpy.ndarray
        One value per sample, ``NaN`` where nothing carries weight.

    Examples
    --------
    >>> bucketed_weighted_percentiles([3.0, 1.0, 2.0], [1.0, 1.0, 1.0], 50.0, sample_of=[0, 0, 0], samples=1)
    array([2.])
    """
    values_array = np.asarray(values, dtype=float)
    weights_array = np.asarray(weights, dtype=float)
    sample_all = np.asarray(sample_of, dtype=np.intp)
    if values_array.shape != weights_array.shape or values_array.shape != sample_all.shape:
        raise ValueError(
            "values, weights and sample_of must have the same shape, got "
            f"{values_array.shape}, {weights_array.shape} and {sample_all.shape}."
        )
    out = np.full(samples, np.nan)

    carries = (weights_array > 0.0) & np.isfinite(values_array)
    sample = sample_all[carries]
    value = values_array[carries]
    weight = weights_array[carries]
    if not len(sample):
        return out

    low = float(value.min())
    high = float(value.max())
    if high <= low:  # every value is the same: no distribution to invert
        out[np.unique(sample)] = low
        return out

    which = np.clip(((value - low) / (high - low) * bins).astype(np.intp), 0, bins - 1)
    histogram = np.bincount(sample * bins + which, weights=weight, minlength=samples * bins).reshape(samples, bins)
    cumulative = np.cumsum(histogram, axis=1)
    total = cumulative[:, -1]
    occupied = histogram > 0
    lightest = _lightest_weight(sample, value, weight, which, np.argmax(occupied, axis=1), samples)

    target = float(percentile) / 100.0
    threshold = lightest + target * (total - lightest)
    crossing = np.clip((cumulative < threshold[:, None]).sum(axis=1), 0, bins - 1)
    # The lightest bin has already served its purpose and must stay out of the
    # walk, where its weight is part of ``base``.
    base, picked = _bracket(sample, which, cumulative, occupied, crossing, bins)
    selected = np.flatnonzero(picked)
    selected = selected[np.lexsort((value[selected], sample[selected]))]
    starts = np.searchsorted(sample[selected], np.arange(samples))
    stops = np.searchsorted(sample[selected], np.arange(samples), side="right")

    for index in range(samples):
        if not np.isfinite(threshold[index]):
            continue
        block = selected[starts[index] : stops[index]]
        if not len(block):
            continue
        running = base[index] + np.cumsum(weight[block])
        reached = np.flatnonzero(running >= threshold[index])
        at = int(reached[0]) if len(reached) else len(block) - 1
        if at == 0:
            out[index] = value[block[0]]
            continue
        previous_value, next_value = value[block[at - 1]], value[block[at]]
        below, above = running[at - 1], running[at]
        out[index] = (
            next_value
            if above <= below
            else previous_value + (threshold[index] - below) / (above - below) * (next_value - previous_value)
        )
    return out



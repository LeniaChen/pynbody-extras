"""Every node kind survives a signature round trip.

``calculator_to_signature`` and ``calculator_from_signature`` are what the result
store keys on and what ``store.load`` rebuilds a recipe from, so the encode/decode
pair is a persisted format: a kind that encodes but does not decode (or decodes
into something that encodes differently) is a silent data-loss bug.

The pair lives in two layers on purpose — ``result/signature.py`` holds the generic
payload/hash/JSON machinery, and the nodes layer owns which kinds exist
(``nodes/serde.py``).  These tests walk one sample per kind through JSON and back,
which is what makes that split safe to move around.
"""

from __future__ import annotations

import pytest
from calculate_helpers import kind_samples


def test_every_node_kind_round_trips_through_json() -> None:
    from pynbodyext.core.calculate.result.signature import calculator_from_signature, calculator_to_signature

    for sample in kind_samples():
        first = calculator_to_signature(sample)
        if not first.constructible:
            # callables cannot be rebuilt; the refusal must be explicit, not a crash
            with pytest.raises(ValueError):
                calculator_from_signature(first.to_json())
            continue

        rebuilt = calculator_from_signature(first.to_json())
        second = calculator_to_signature(rebuilt)
        assert second.payload == first.payload, type(sample).__name__
        assert second.hash == first.hash, type(sample).__name__


def test_the_rebuilt_calculator_runs_the_same_way() -> None:
    """Decoding rebuilds a node that produces the same value, not just a payload."""
    from calculate_helpers import MassSum, RBelow, make_sim

    from pynbodyext.core.calculate.result.signature import calculator_from_signature, calculator_to_signature

    sim = make_sim()
    original = MassSum().filter(RBelow(5.0))
    rebuilt = calculator_from_signature(calculator_to_signature(original).to_json())

    assert rebuilt(sim) == original(sim)
    assert rebuilt.scope.filter is not None

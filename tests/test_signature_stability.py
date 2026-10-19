"""A signature is a key that has to mean the same thing tomorrow.

The content hash of a calculator signature keys stored results and, later, rows of
large sample tables, so it must be equal for equal calculators in every Python
session.  A signature that can only tell objects apart within one run (by ``id()``
or a function ``repr``) must say so — ``stable`` is false — and a persistent store
must refuse it rather than write a key no later session can match.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest
from calculate_helpers import MassSum, OpaqueProperty, RBelow, TempMean, kind_samples, make_pipeline, make_sim

from pynbodyext.core.calculate import LambdaProperty, Param, Pipeline, PropertyBase
from pynbodyext.core.calculate.result.signature import (
    SIGNATURE_SCHEMA,
    CalculatorSignature,
    calculator_from_signature,
    calculator_to_signature,
)
from pynbodyext.core.calculate.store import (
    InMemoryResultStore,
    SignatureMismatchError,
    UnstableSignatureError,
)

# ---------------------------------------------------------------------------
# Stability across sessions
# ---------------------------------------------------------------------------


def test_stable_hashes_are_equal_in_a_fresh_interpreter() -> None:
    """The hash a stable calculator gets here is the hash it gets in a new process."""
    here = {i: calculator_to_signature(s) for i, s in enumerate(kind_samples())}
    stable = {i: sig.hash for i, sig in here.items() if sig.stable}
    assert len(stable) >= 8, "the kind samples went stale: too few stable kinds"

    script = textwrap.dedent(
        """
        import json
        from calculate_helpers import kind_samples
        from pynbodyext.core.calculate.result.signature import calculator_to_signature
        print(json.dumps({i: calculator_to_signature(s).hash for i, s in enumerate(kind_samples())}))
        """
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(__file__).parent, env=env, capture_output=True, text=True, check=True
    )
    there = {int(k): v for k, v in json.loads(out.stdout.strip().splitlines()[-1]).items()}

    for index, digest in stable.items():
        assert there[index] == digest, type(kind_samples()[index]).__name__


@pytest.mark.parametrize(
    ("make", "constructible", "stable"),
    [
        (lambda: MassSum(), True, True),
        (lambda: make_pipeline(), True, True),
        (lambda: MassSum().filter(RBelow(5.0)), True, True),
        (lambda: LambdaProperty(lambda sim: 1.0), False, False),
        (lambda: OpaqueProperty(), False, False),
    ],
    ids=["dataclass", "pipeline", "scoped", "lambda", "opaque"],
)
def test_constructible_and_stable_are_reported(make, constructible: bool, stable: bool) -> None:
    sig = make().to_signature()
    assert sig.constructible is constructible
    assert sig.stable is stable
    assert bool(sig.unstable_paths) is (not stable)


def test_instability_propagates_to_the_enclosing_graph() -> None:
    """One session-specific leaf makes the whole key session-specific, and says where."""
    sig = Pipeline({"ok": MassSum(), "bad": LambdaProperty(lambda sim: 1.0)}).to_signature()
    assert not sig.stable
    assert sig.unstable_paths == ("calculator.outputs['bad'].func",)


def test_two_opaque_nodes_stay_apart_within_a_run() -> None:
    """Unstable is not ambiguous: the in-run cache must still tell them apart."""
    assert OpaqueProperty().signature() != OpaqueProperty().signature()
    assert LambdaProperty(lambda s: 1).signature() != LambdaProperty(lambda s: 1).signature()


def test_a_hash_only_array_is_stable_but_not_constructible() -> None:
    """A large array is identified by its content hash: durable, but not rebuildable."""

    @PropertyBase.dataclass
    class Weighted(PropertyBase[float]):
        weights: Param[object]

        def calculate(self, sim, params=None) -> float:
            return 0.0

    sig = Weighted(weights=np.arange(1000.0)).to_signature()
    assert sig.stable
    assert not sig.constructible
    assert sig.hash != Weighted(weights=np.arange(1000.0) + 1).to_signature().hash


# ---------------------------------------------------------------------------
# What the hash covers
# ---------------------------------------------------------------------------


def test_the_hash_covers_schema_and_payload_only() -> None:
    sig = make_pipeline().to_signature()
    identity = {"schema": SIGNATURE_SCHEMA, "payload": sig.identity()}
    expected = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert sig.hash == expected
    assert len(sig.hash) == 64
    # descriptive flags do not move the key
    relabelled = CalculatorSignature(payload=sig.payload, constructible=False, stable=False)
    assert relabelled.hash == sig.hash


def test_full_json_carries_the_flags_and_round_trips() -> None:
    sig = LambdaProperty(lambda sim: 1.0).to_signature()
    data = json.loads(sig.to_json(full=True))
    assert data["schema"] == SIGNATURE_SCHEMA
    assert data["stable"] is False
    again = CalculatorSignature.from_json(sig.to_json(full=True))
    assert (again.stable, again.unstable_paths) == (sig.stable, sig.unstable_paths)
    assert again.hash == sig.hash


def test_a_v1_signature_text_is_still_readable() -> None:
    payload = MassSum().to_signature().payload
    old = json.dumps({"schema": "pynbodyext.calculator.signature/v1", "payload": payload})
    assert calculator_from_signature(old).to_signature().payload == payload


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_a_pipeline_round_trips_and_runs_the_same() -> None:
    pipeline = make_pipeline()
    rebuilt = calculator_from_signature(pipeline.to_signature().to_json())
    assert isinstance(rebuilt, Pipeline)
    assert list(rebuilt.outputs) == ["m", "t"]
    assert rebuilt.to_signature().hash == pipeline.to_signature().hash
    assert rebuilt(make_sim()) == pipeline(make_sim())


def test_pipeline_identity_is_its_outputs_not_its_label() -> None:
    def build(keys=("m", "t"), name="p"):
        return Pipeline({keys[0]: MassSum(), keys[1]: TempMean()}, name=name)

    base = build().to_signature().hash
    assert build(name="another label").to_signature().hash == base
    assert build(keys=("mass", "t")).to_signature().hash != base  # output names key the value dict
    reordered = Pipeline({"t": TempMean(), "m": MassSum()}).to_signature().hash
    assert reordered != base  # and their order is the order of that dict


def test_pipeline_expression_reads_like_its_constructor() -> None:
    text = Pipeline({"m": MassSum(), "t": TempMean()}).to_signature().pretty()
    assert text == 'Pipeline({"m": MassSum(), "t": TempMean()})'


def test_a_pipeline_subclass_with_its_own_constructor_stays_generic() -> None:
    class Summary(Pipeline):
        def __init__(self) -> None:
            super().__init__({"m": MassSum()})

    payload = Summary().to_signature().payload
    assert payload["node"] == "generic"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class _PersistentMemoryStore(InMemoryResultStore):
    """An in-memory store that behaves like a persistent one, for the refusal path."""

    persistent = True


def _result(calc):
    return calc.run(make_sim())


def test_a_persistent_store_refuses_a_session_specific_signature() -> None:
    calc = LambdaProperty(lambda sim: 1.0)
    store = _PersistentMemoryStore()
    with pytest.raises(UnstableSignatureError, match="session-specific"):
        store.store(_result(calc), sim_signature=("sim", "a"), calculator_signature=calc.to_signature())
    assert store.list_refs() == []


def test_an_in_memory_store_accepts_a_session_specific_signature() -> None:
    calc = LambdaProperty(lambda sim: 1.0)
    store = InMemoryResultStore()
    store.store(_result(calc), sim_signature=("sim", "a"), calculator_signature=calc.to_signature())
    assert store.has(sim_signature=("sim", "a"), calculator_signature=calc.to_signature())


def test_a_run_with_an_unstable_calculator_warns_and_skips_a_persistent_store() -> None:
    store = _PersistentMemoryStore()
    with pytest.warns(UserWarning, match="not stored"):
        result = LambdaProperty(lambda sim: 2.0).run(make_sim(), store=store)
    assert result.value == 2.0  # the run itself is fine
    assert store.list_refs() == []


def test_records_are_keyed_on_the_full_hash() -> None:
    calc = make_pipeline()
    store = InMemoryResultStore()
    ref = store.store(_result(calc), sim_signature=("sim", "a"), calculator_signature=calc.to_signature())
    assert ref.calculator_signature_hash == calc.to_signature().hash
    assert len(ref.calculator_signature_hash) == 64
    assert _result(calc).provenance.calculator_signature_hash == calc.to_signature().hash


def test_a_record_for_another_calculator_under_the_same_key_is_refused() -> None:
    """A hit is checked against the signature that asked for it."""
    store = InMemoryResultStore()
    mass, temp = MassSum(), TempMean()
    store.store(_result(mass), sim_signature=("sim", "a"), calculator_signature=mass.to_signature())

    # Simulate a collision / corrupted row: the temperature key now holds the mass record.
    (key, record) = next(iter(store._records.items()))
    record.calculator_signature_hash = temp.to_signature().hash
    store._records[key.replace(mass.to_signature().hash, temp.to_signature().hash)] = record

    with pytest.raises(SignatureMismatchError):
        store.get(sim_signature=("sim", "a"), calculator_signature=temp.to_signature())
    with pytest.raises(SignatureMismatchError):
        store.has(sim_signature=("sim", "a"), calculator_signature=temp.to_signature())
    assert store.get(sim_signature=("sim", "a"), calculator_signature=mass.to_signature()) is not None


def test_the_sql_store_is_persistent_and_refuses_unstable_keys(tmp_path) -> None:
    pytest.importorskip("sqlalchemy")
    from pynbodyext.core.calculate.store import SQLAlchemyResultStore

    store = SQLAlchemyResultStore(f"sqlite:///{tmp_path / 'r.sqlite'}")
    assert store.persistent
    calc = LambdaProperty(lambda sim: 1.0)
    with pytest.raises(UnstableSignatureError):
        store.store(_result(calc), sim_signature=("sim", "a"), calculator_signature=calc.to_signature())

    stable = make_pipeline()
    store.store(_result(stable), sim_signature=("sim", "a"), calculator_signature=stable.to_signature())
    store.engine.dispose()
    reopened = SQLAlchemyResultStore(f"sqlite:///{tmp_path / 'r.sqlite'}")
    try:
        loaded = reopened.load(sim_signature=("sim", "a"), calculator_signature_text=stable.to_signature().to_json())
    finally:
        reopened.engine.dispose()
    assert loaded is not None
    assert loaded.calculator is not None
    assert loaded.calculator.to_signature().hash == stable.to_signature().hash

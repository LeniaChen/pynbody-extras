"""Compute once, read back afterwards: the store as a cache across sessions.

``calc.run(sim, store=store)`` looks the result up before computing.  For that to
be right in a later session, both halves of the key must address the same data
again: the calculator signature (stable since the signature work) and the
simulation identity, which :func:`snapshot_identity` derives from the snapshot's
file and the particles a sub-snapshot selects.
"""

from __future__ import annotations

import numpy as np
import pynbody
import pytest

from pynbodyext.core.calculate import LambdaProperty, Param, PropertyBase, snapshot_identity
from pynbodyext.core.calculate.runtime.sim_identity import id_based_sim_identity, is_stable_sim_identity
from pynbodyext.core.calculate.store import (
    InMemoryResultStore,
    SignatureMismatchError,
    UnstableSimIdentityError,
)
from pynbodyext.filters import Sphere

CALLS: list[str] = []


@PropertyBase.dataclass
class CountedMass(PropertyBase[float]):
    """Mass sum that records every time it is actually computed."""

    signature_name = "tests.CountedMass"

    scale: Param[float] = 1.0

    def calculate(self, sim, params=None) -> float:
        CALLS.append("computed")
        return float(sim["mass"].sum()) * self.scale


class _PersistentMemoryStore(InMemoryResultStore):
    persistent = True


@pytest.fixture(autouse=True)
def _reset_calls():
    CALLS.clear()
    yield
    CALLS.clear()


def file_sim(path, n: int = 6):
    """A snapshot that claims to come from *path* (pynbody.new, then named)."""
    sim = pynbody.new(n)
    sim["mass"] = np.arange(float(n))
    sim["pos"] = np.zeros((n, 3))
    sim._filename = str(path)
    return sim


# ---------------------------------------------------------------------------
# Simulation identity
# ---------------------------------------------------------------------------


def test_the_default_identity_is_session_only() -> None:
    sim = pynbody.new(3)
    assert id_based_sim_identity(sim) == ("session", id(sim))
    assert not is_stable_sim_identity(id_based_sim_identity(sim))


def test_a_snapshot_without_a_file_has_a_session_only_identity() -> None:
    sim = pynbody.new(3)  # named "<created>"
    assert snapshot_identity(sim)[0] == "session"


def test_a_file_snapshot_is_addressed_by_its_absolute_path(tmp_path) -> None:
    identity = snapshot_identity(file_sim(tmp_path / "snap_103"))
    assert identity == ("sim", str(tmp_path / "snap_103"))
    assert is_stable_sim_identity(identity)


def test_a_subset_is_addressed_by_the_particles_it_selects(tmp_path) -> None:
    a, b = file_sim(tmp_path / "snap"), file_sim(tmp_path / "snap")  # two loads of one file
    first = snapshot_identity(a[np.array([1, 3])])
    assert first[:3] == ("sim", str(tmp_path / "snap"), "subset")
    assert snapshot_identity(b[np.array([1, 3])]) == first  # same particles, another session
    assert snapshot_identity(a[np.array([1, 4])]) != first


def test_a_halo_is_addressed_by_number_and_particles(tmp_path) -> None:
    sim = file_sim(tmp_path / "snap")
    halo = sim[np.array([0, 2, 5])]
    halo._halo_number = np.int64(7)  # what a pynbody Halo carries
    identity = snapshot_identity(halo)
    assert identity[:4] == ("sim", str(tmp_path / "snap"), "halo", 7)
    assert isinstance(identity[3], int)
    assert len(identity[4]) == 16


def test_a_transformed_snapshot_is_session_only_until_reverted(tmp_path) -> None:
    """Positions moved outside the calculator are not the file's positions."""
    sim = file_sim(tmp_path / "snap")
    transformation = sim.translate([1.0, 0.0, 0.0])
    assert snapshot_identity(sim)[0] == "session"
    transformation.revert()
    assert snapshot_identity(sim) == ("sim", str(tmp_path / "snap"))


# ---------------------------------------------------------------------------
# Read-through
# ---------------------------------------------------------------------------


def test_a_second_run_reads_the_stored_result_instead_of_computing() -> None:
    store = InMemoryResultStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    calc = CountedMass()

    first = calc.run(sim, store=store)
    second = calc.run(sim, store=store)

    assert CALLS == ["computed"]
    assert not first.from_store
    assert second.from_store
    assert second.value == first.value == 6.0
    assert second.calculator is calc  # the live node, not one rebuilt from text


def test_reuse_false_recomputes_and_replaces() -> None:
    store = InMemoryResultStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    calc = CountedMass()

    calc.run(sim, store=store)
    sim["mass"] *= 2  # an in-place edit the identity cannot see ...
    assert calc.run(sim, store=store).value == 6.0  # ... so the stale value is reused
    refreshed = calc.run(sim, store=store, reuse=False)  # until asked to refresh
    assert refreshed.value == 12.0 and not refreshed.from_store
    assert calc.run(sim, store=store).value == 12.0
    assert CALLS == ["computed", "computed"]


def test_the_call_form_reuses_too() -> None:
    store = InMemoryResultStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    assert CountedMass()(sim, store=store) == CountedMass()(sim, store=store) == 6.0
    assert CALLS == ["computed"]


# ---------------------------------------------------------------------------
# Persistent stores
# ---------------------------------------------------------------------------


def test_a_persistent_store_finds_a_result_again_after_a_reload(tmp_path) -> None:
    """The file identity is the default for a persistent store, so a reload hits."""
    store = _PersistentMemoryStore()
    path = tmp_path / "snap_103"

    CountedMass().run(file_sim(path), store=store)
    again = CountedMass().run(file_sim(path), store=store)  # a new object, as after a restart

    assert again.from_store
    assert CALLS == ["computed"]
    assert [ref.sim_signature for ref in store.list_refs()] == [("sim", str(path))]


def test_a_persistent_store_skips_a_snapshot_without_a_file() -> None:
    store = _PersistentMemoryStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    with pytest.warns(UserWarning, match="session-only"):
        result = CountedMass().run(sim, store=store)
    assert result.value == 6.0
    assert store.list_refs() == []


def test_a_persistent_store_skips_an_unstable_calculator(tmp_path) -> None:
    store = _PersistentMemoryStore()
    with pytest.warns(UserWarning, match="session-specific"):
        LambdaProperty(lambda sim: 1.0).run(file_sim(tmp_path / "snap"), store=store)
    assert store.list_refs() == []


def test_storing_directly_under_a_session_identity_is_refused() -> None:
    store = _PersistentMemoryStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    result = CountedMass().run(sim)
    with pytest.raises(UnstableSimIdentityError):
        store.store(result, sim_signature=("session", id(sim)), calculator_signature=CountedMass().to_signature())


def test_the_sql_store_replaces_a_record_stored_twice(tmp_path) -> None:
    pytest.importorskip("sqlalchemy")
    from pynbodyext.core.calculate.store import SQLAlchemyResultStore

    store = SQLAlchemyResultStore(f"sqlite:///{tmp_path / 'r.sqlite'}")
    try:
        sim = file_sim(tmp_path / "snap")
        CountedMass().run(sim, store=store)
        sim["mass"] *= 2
        CountedMass().run(sim, store=store, reuse=False)  # same key again: no IntegrityError
        assert len(store.list_refs()) == 1
        assert CountedMass().run(file_sim(tmp_path / "snap"), store=store).value == 30.0
    finally:
        store.engine.dispose()


# ---------------------------------------------------------------------------
# Equal numbers, equal keys
# ---------------------------------------------------------------------------


def test_an_integral_float_and_its_int_share_a_key() -> None:
    assert Sphere(30).to_signature().hash == Sphere(30.0).to_signature().hash
    assert Sphere(-0.0).to_signature().hash == Sphere(0).to_signature().hash
    assert Sphere(30.5).to_signature().hash != Sphere(30).to_signature().hash
    assert CountedMass(scale=True).to_signature().hash != CountedMass(scale=1.0).to_signature().hash  # bool is not 1
    # the payload keeps the value as given, for rebuilding and display
    assert Sphere(30.0).to_signature().payload["init"]["radius"] == 30.0


def test_a_value_equal_to_the_default_is_the_default() -> None:
    assert Sphere(30, cen=(0.0, 0.0, 0.0)).to_signature().hash == Sphere(30).to_signature().hash
    assert CountedMass(scale=1).to_signature().hash == CountedMass().to_signature().hash


def test_a_stored_result_answers_an_equal_number(tmp_path) -> None:
    store = InMemoryResultStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    CountedMass(scale=2).run(sim, store=store)
    assert CountedMass(scale=2.0).run(sim, store=store).from_store
    assert CALLS == ["computed"]


def test_the_identity_check_still_catches_a_different_calculator() -> None:
    store = InMemoryResultStore()
    sim = pynbody.new(4)
    sim["mass"] = np.arange(4.0)
    two, three = CountedMass(scale=2), CountedMass(scale=3)
    store.store(two.run(sim), sim_signature=("session", id(sim)), calculator_signature=two.to_signature())
    key, record = next(iter(store._records.items()))
    store._records[key.replace(two.to_signature().hash, three.to_signature().hash)] = record
    with pytest.raises(SignatureMismatchError):
        store.get(sim_signature=("session", id(sim)), calculator_signature=three.to_signature())

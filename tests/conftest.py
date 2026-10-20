from __future__ import annotations

import gc
import os
from pathlib import Path

import pynbody
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTDATA = REPO_ROOT / "testdata"


@pytest.fixture(scope="session", autouse=True)
def _run_from_repo_root():
    """Make the ``testdata/...`` paths independent of where pytest was started."""
    previous = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


@pytest.fixture(scope="session")
def _test_data():
    """
    Download pynbody's test packages only when a test actually asks for them.

    The old autouse version made every ``pytest`` run download about 1.1 GB,
    including pure unit tests.  Tests that need data are marked ``data`` (see
    ``pytest_collection_modifyitems`` below) and excluded from ``make test``.
    """
    import pynbody.test_utils

    try:
        pynbody.test_utils.ensure_test_data_available("gadget", "arepo")
    except Exception as exc:  # surface a download failure as a clear exit
        pytest.exit(f"Failed to prepare pynbody test data: {exc}", returncode=1)
    if not TESTDATA.exists():
        pytest.exit("Test data directory 'testdata' is missing after the download", returncode=1)
    return TESTDATA


def pytest_collection_modifyitems(config, items):
    """Mark any test that requests a data-backed fixture as ``data``."""
    data_fixtures = {"snap", "subfind"}
    for item in items:
        if data_fixtures.intersection(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.data)


@pytest.fixture(autouse=True)
def _data_marked_tests_have_data(request):
    """Fetch testdata only for tests marked ``data``, and only once per session."""
    if request.node.get_closest_marker("data"):
        request.getfixturevalue("_test_data")


@pytest.fixture(scope="function")
def snap(_test_data):
    """
    Load a snapshot for tests that need the full gadget3 data set.
    """
    # total 4194304 particles, 2097152 dm + 2076907 gas + 20245 star
    f = pynbody.load(str(_test_data / "gadget3/data/snapshot_103/snap_103.hdf5"))
    yield f
    # explicit cleanup to release memory between modules
    try:
        del f
    finally:
        gc.collect()


@pytest.fixture(scope="function")
def subfind(_test_data):
    """
    Load subhalo/subfind data for tests that need it.
    """
    f = pynbody.load(str(_test_data / "gadget3/data/subhalos_103/subhalo_103"))
    # total 382909 particles, 189613 dm + 172955 gas + 20341 star
    # halos count: 4226
    # halos[0] count: 15682 particles, 7869 dm + 4410 gas + 3403 star
    yield f
    try:
        del f
    finally:
        gc.collect()

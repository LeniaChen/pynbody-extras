"""The image layer's side of the ADR-0004 boundary.

ADR-0004: ``plot/image/`` takes plain 2-D arrays, and ``ImageData`` is the only
place that knows the calculator layer.  The layer's annotations still *name* the
binning types (``BinNDResult``, ``BinsArray``, ``BinAxis``), which is fine — a
type-checking-only import costs nothing at run time, and the binning layer registers
those names with :func:`pynbodyext.util._type.register_annotation_names` so that
``resolve_type_hints`` can resolve them.

What must not come back is a runtime import: that is what made the two layers
import each other.  If a genuinely new call site needs one, add it to the allow-list
here and say why in the same commit.

As of this writing the image layer has *no* run-time import of the calculator layer
at all — even ``data.py`` (the sanctioned exception) only names the types under
``TYPE_CHECKING``.
"""

from __future__ import annotations

import pathlib

from import_graph import package_name, runtime_imports

import pynbodyext

#: The one module allowed to import the calculator layer at run time.
_ALLOWED = {"plot/image/data.py"}

#: Modules whose import of ``pynbodyext.core.calculate`` is the violation.
_CALCULATOR = "pynbodyext.core.calculate"


def test_the_image_layer_only_imports_the_calculator_in_data_py() -> None:
    package = pathlib.Path(pynbodyext.__file__).parent
    image_root = package / "plot"
    offenders: list[str] = []
    for path in sorted(image_root.rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        if relative in _ALLOWED:
            continue
        for module in runtime_imports(path, package_name(path, package.parent)):
            if module == _CALCULATOR or module.startswith(f"{_CALCULATOR}."):
                offenders.append(f"{relative}: {module}")
    assert offenders == []


def test_the_binning_types_are_registered_for_hint_resolution() -> None:
    """``resolve_type_hints`` gets the binning names without importing them."""
    from pynbodyext.core.calculate.bins.arrays import BinsArray
    from pynbodyext.core.calculate.bins.axes import BinAxis
    from pynbodyext.core.calculate.bins.result import BinNDResult
    from pynbodyext.plot.image._types import annotation_namespace

    namespace = annotation_namespace()
    assert namespace["BinsArray"] is BinsArray
    assert namespace["BinAxis"] is BinAxis
    assert namespace["BinNDResult"] is BinNDResult


# The scanner's own self-test lives in ``test_package_layers_contract.py``, which
# uses the same helpers; one copy is enough to keep them honest.

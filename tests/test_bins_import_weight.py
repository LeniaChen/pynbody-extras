"""The calculator package's import weight, and the rule that keeps it.

``pynbodyext.plot.image`` imports matplotlib at module level.  The binning layer
draws (``bins.imshow(...)`` and friends), so it must reach that layer *inside* the
method that draws — a module-level import would put the drawing stack behind
``import pynbodyext.calculate``, the entry point most callers use.

(scipy is deliberately *not* in the invariant: pynbody itself imports it, so it is
already loaded by the time this package runs whatever we do.)

This is why ``bins/plot.py`` stays in the binning package as a thin adapter rather
than moving next to the image layer: a mixin has to be importable at class-creation
time, so relocating it would move the cost from "when you draw" to "when you
import".
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pynbodyext
from import_graph import module_level_imports

_HEAVY = ("matplotlib",)


def test_the_calculator_import_stays_free_of_the_drawing_stack() -> None:
    probe = (
        "import sys, pynbodyext.calculate; "
        f"print(','.join(name for name in {_HEAVY!r} if name in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=pathlib.Path(pynbodyext.__file__).parent.parent,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


def test_the_binning_layer_reaches_the_plot_layer_only_inside_functions() -> None:
    package = pathlib.Path(pynbodyext.__file__).parent
    bins = package / "core" / "calculate" / "bins"

    offenders: list[str] = []
    for path in sorted(bins.glob("*.py")):
        relative = path.relative_to(package).as_posix()
        for module in module_level_imports(path, "pynbodyext.core.calculate.bins"):
            if module == "pynbodyext.plot" or module.startswith("pynbodyext.plot."):
                offenders.append(f"{relative}: {module}")
    assert offenders == []

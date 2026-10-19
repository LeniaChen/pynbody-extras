"""Public API for the binning framework.

Exports the calculator nodes (:class:`Bin1D`, :class:`BinND`), the binned
result (:class:`BinNDResult`, :class:`SubBinNDResult`), the per-bin array
(:class:`BinsArray`), axis utilities (:class:`BinAxis`, :class:`BinAxisAccessor`),
registries (``register_bin_algorithm``, ``register_pipeline_transform``), and
helpers (``has_axis``, ``has_axes``).
"""

from pynbodyext.util._type import register_annotation_names

from .accessors import BinParticlesAccessor
from .arrays import BinsArray
from .axes import BIN_ALGORITHMS, BinAxis, BinAxisAccessor, has_axes, has_axis, register_bin_algorithm
from .nodes import Bin1D, BinND
from .plot import BinPlotMixin
from .result import BinNDResult, BinsResultEngine, SubBinNDResult
from .sph_render import SphRender
from .statistics import register_pipeline_transform

# The image layer's annotations mention these three types without importing this
# package (ADR-0004); registering the names here is what lets
# ``plot.image.resolve_type_hints`` resolve them.  Keep this in step with the
# boundary contract test in ``tests/test_image_boundary_contract.py``.
register_annotation_names(BinAxis=BinAxis, BinNDResult=BinNDResult, BinsArray=BinsArray)

__all__ = [
    "BIN_ALGORITHMS",
    "register_bin_algorithm",
    "register_pipeline_transform",
    "has_axis",
    "has_axes",
    "Bin1D",
    "BinND",
    "BinAxis",
    "BinAxisAccessor",
    "BinNDResult",
    "SubBinNDResult",
    "BinsArray",
    "BinsResultEngine",
    "BinParticlesAccessor",
    "BinPlotMixin",
    "SphRender",
]

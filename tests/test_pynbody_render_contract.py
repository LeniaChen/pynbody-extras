"""Pin the private pynbody renderer surface the SPH view is built on.

``pynbodyext.core.calculate.bins.sph_render`` renders through
``pynbody.sph._render``, which is private and positional-argument only.  These tests
exist so that an upstream change to that surface fails here, with the parameter list
in the failure message, instead of silently changing the numbers a user sees.
``_pynbody_render`` is the only module allowed to call it.

If upstream renames or reorders a parameter, update
``pynbodyext/core/calculate/bins/_pynbody_render.py`` and this file together.
"""

from __future__ import annotations

import inspect


def test_render_image_signature_is_pinned() -> None:
    from pynbody.sph import _render

    from pynbodyext.core.calculate.bins._pynbody_render import RENDER_IMAGE_PARAMS

    assert tuple(inspect.signature(_render.render_image).parameters) == RENDER_IMAGE_PARAMS


def test_to_3d_grid_signature_is_pinned() -> None:
    from pynbody.sph import _render

    from pynbodyext.core.calculate.bins._pynbody_render import TO_3D_GRID_PARAMS

    assert tuple(inspect.signature(_render.to_3d_grid).parameters) == TO_3D_GRID_PARAMS


def test_only_the_adapter_calls_pynbody_private_renderers() -> None:
    """No module but the adapter may import ``pynbody.sph._render``."""
    import pathlib

    import pynbodyext

    package = pathlib.Path(pynbodyext.__file__).parent
    offenders = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "_pynbody_render.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "from pynbody.sph import _render" in text or "import pynbody.sph._render" in text:
            offenders.append(path.relative_to(package).as_posix())
    assert offenders == []

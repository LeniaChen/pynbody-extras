"""The seams between the calculator layers.

Import direction in ``core.calculate`` is a rule, not a habit: a module may only
import from the layers *below* it, so each layer can be imported, tested or replaced
without the ones above it.  The order, lowest first — the same tuple
``tests/test_layering_contract.py`` checks every run-time import against:

``interfaces`` · ``display`` · ``params`` · ``diagnostics`` · ``result`` · ``store`` ·
``runtime`` · ``nodes`` · ``bins``

Two things break that order on their own, and both are handled here rather than by
an import:

- A lower layer needs to *recognise* an object the upper layer defines (is this a
  calculator node?) — that is a :class:`Protocol`, checked structurally.
- A lower layer needs the upper layer to *build* or *serialize* something (rebuild a
  calculator from a payload; wrap transforms in a chain) — that is a registration
  hook, filled in by the layer that owns the classes.

Nothing here imports a sibling module, which is the property that makes it usable
from every layer.  ``tests/test_layering_contract.py`` holds the rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "CalculatorNode",
    "ScopeLike",
    "is_calculator_node",
    "register_calculator_layer",
    "encode_calculator_payload",
    "decode_calculator_payload",
    "register_node_factory",
    "make_node",
]


@runtime_checkable
class CalculatorNode(Protocol):
    """What a lower layer needs from a calculator node, structurally.

    The parameter machinery asks "is this value a calculator I should resolve, or a
    dependency I should walk?" without importing the node classes; the node layer
    satisfies this by being a ``CalculatorBase``, and nothing else does.

    Three members, because a runtime protocol check is a ``hasattr`` walk: an object
    that happens to answer ``signature()`` alone (a stored record, a snapshot) must
    not be mistaken for a calculator.
    """

    kind: Any

    def signature(self) -> tuple[Any, ...]: ...

    def children(self) -> list[Any]: ...


@runtime_checkable
class ScopeLike(Protocol):
    """What a lower layer needs from a calculator's scope."""

    @property
    def is_empty(self) -> bool: ...


# ---------------------------------------------------------------------------
# Hooks the node layer installs
# ---------------------------------------------------------------------------

_CALCULATOR_LAYER: dict[str, Callable[..., Any]] = {}
_NODE_FACTORIES: dict[str, Callable[..., Any]] = {}


def register_calculator_layer(
    *,
    is_node: Callable[[Any], bool],
    encode: Callable[..., tuple[Any, bool, tuple[str, ...], tuple[str, ...]]],
    decode: Callable[[dict[str, Any]], Any],
) -> None:
    """Install the node layer's three answers about calculators.

    ``is_node`` recognises a calculator object, ``encode`` turns one into a
    ``(payload, constructible, non_constructible_paths, unstable_paths)`` tuple,
    and ``decode`` rebuilds one from a payload.  ``nodes/serde.py`` calls this at import.
    """
    _CALCULATOR_LAYER.update(is_node=is_node, encode=encode, decode=decode)


def is_calculator_node(value: Any) -> bool:
    """Whether *value* is a calculator node, per the installed hook."""
    is_node = _CALCULATOR_LAYER.get("is_node")
    return bool(is_node(value)) if is_node is not None else False


def encode_calculator_payload(
    calculator: Any, *, path: str = "calculator", inline_array_bytes: int = 128
) -> tuple[Any, bool, tuple[str, ...], tuple[str, ...]]:
    """Encode *calculator* into its signature payload, via the node layer.

    Returns ``(payload, constructible, non_constructible_paths, unstable_paths)``;
    see :class:`~pynbodyext.core.calculate.result.signature.CalculatorSignature`.
    """
    encode = _CALCULATOR_LAYER.get("encode")
    if encode is None:
        raise RuntimeError(
            "no calculator encoder is registered; import pynbodyext.core.calculate.nodes first"
        )
    return encode(calculator, path=path, inline_array_bytes=inline_array_bytes)


def decode_calculator_payload(payload: Mapping[str, Any]) -> Any:
    """Rebuild a calculator from *payload*, via the node layer."""
    decode = _CALCULATOR_LAYER.get("decode")
    if decode is None:
        raise RuntimeError(
            "no calculator decoder is registered; import pynbodyext.core.calculate.nodes first"
        )
    return decode(dict(payload))


def register_node_factory(kind: str, factory: Callable[..., Any]) -> None:
    """Register a node-building factory under *kind*, for a lower layer to call.

    ``runtime.scopes`` builds a transform chain and a pipeline — both node classes —
    so it asks for them by name instead of importing the node layer.
    """
    _NODE_FACTORIES[kind] = factory


def make_node(kind: str, *args: Any, **kwargs: Any) -> Any:
    """Build the node registered under *kind*.

    The first parameter is positional-only in spirit (it names the registry slot), so
    it is spelled ``kind`` to leave ``name`` free for the node being built.
    """
    factory = _NODE_FACTORIES.get(kind)
    if factory is None:
        raise RuntimeError(f"no node factory registered as {kind!r}")
    return factory(*args, **kwargs)

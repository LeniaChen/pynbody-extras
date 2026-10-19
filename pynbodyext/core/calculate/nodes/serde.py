"""Which node kinds a signature can carry, and how each one rebuilds.

``result/signature.py`` owns the generic machinery: the payload container
(``CalculatorSignature``), hashing, JSON, and the value codecs.  *This* module owns
the half that knows the node classes — the kind table, how an object is recognised
as a kind, and how a payload becomes a calculator again — and installs it through
:mod:`pynbodyext.core.calculate.interfaces`.

The split is what keeps ``result`` (a layer *below* ``nodes``) from importing the
node layer: the lower module asks the registry instead of reaching up.  See
``tests/test_layering_contract.py``.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from pynbodyext.core.calculate.interfaces import register_calculator_layer
from pynbodyext.core.calculate.result.enums import RevertPolicy
from pynbodyext.core.calculate.result.signature import (
    _COMMUTATIVE_PROPERTY_OPS,
    _Decoder,
    _encode_init_entries,
    _Encoded,
    _Encoder,
    _merge_encoded,
    _sort_encoded_commutative,
)
from pynbodyext.util._type import class_path, import_object


def _is_calculator(value: Any) -> bool:
    """Whether *value* is a calculator node."""
    from .base import CalculatorBase

    return isinstance(value, CalculatorBase)


def _is_transform_base(value: Any) -> bool:
    from .transforms import TransformBase

    return isinstance(value, TransformBase)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _transform_state(calculator: Any, inline_bytes: int, path: str) -> tuple[dict[str, Any] | None, list[_Encoded]]:
    if not _is_transform_base(calculator):
        return None, []

    state: dict[str, Any] = {}
    children: list[_Encoded] = []
    if calculator.revert_policy != RevertPolicy.ALWAYS:
        rp = _Encoder.encode_value(calculator.revert_policy, f"{path}.revert_policy", inline_bytes)
        state["revert_policy"] = rp.value
        children.append(rp)
    if calculator.measure_filter is not None:
        mf = _Encoder.encode_value(calculator.measure_filter, f"{path}.measure_filter", inline_bytes)
        state["measure_filter"] = mf.value
        children.append(mf)
    if not state:
        return None, []
    return state, children


def _encode_scope(scope: Any, path: str, inline_bytes: int) -> _Encoded:
    transforms = [
        _Encoder.encode_calculator_value(t, f"{path}.transforms[{idx}]", inline_bytes)
        for idx, t in enumerate(scope.transforms)
    ]
    children: list[_Encoded] = [*transforms]
    payload: dict[str, Any] = {}
    if transforms:
        payload["transforms"] = [item.value for item in transforms]
    if scope.filter is not None:
        fe = _Encoder.encode_calculator_value(scope.filter, f"{path}.filter", inline_bytes)
        payload["filter"] = fe.value
        children.append(fe)
    if scope.revert_policy != RevertPolicy.ALWAYS:
        payload["revert_policy"] = scope.revert_policy.value
    return _merge_encoded(payload, children)


def _encode_dataclass(calculator: Any, path: str, inline_bytes: int) -> _Encoded:
    """Encode a dataclass-based calculator."""
    ts, children = _transform_state(calculator, inline_bytes, path)
    init_entries = _encode_init_entries(calculator, path, inline_bytes)
    init_payload: dict[str, Any] = {name: enc.value for name, enc in init_entries}
    children.extend(enc for _, enc in init_entries)
    payload: dict[str, Any] = {"node": "dataclass", "class": class_path(calculator)}
    if init_payload:
        payload["init"] = init_payload
    if ts is not None:
        payload["transform"] = ts
    return _merge_encoded(payload, children)


def _encode_special(calculator: Any, path: str, inline_bytes: int) -> _Encoded | None:
    """Encode known special calculator types; returns None for unknown types."""
    from .base import CombinedCalculator
    from .expr import CalculatorValueProperty, ConstantProperty, LambdaProperty, OpProperty
    from .filters import AndFilter, NotFilter, OrFilter
    from .transforms import TransformChain

    ts, ts_children = _transform_state(calculator, inline_bytes, path)
    encoded: _Encoded | None = None

    if isinstance(calculator, CombinedCalculator):
        items = [
            _Encoder.encode_calculator_value(item, f"{path}.items[{i}]", inline_bytes)
            for i, item in enumerate(calculator.items)
        ]
        encoded = _merge_encoded({"node": "combined", "items": [e.value for e in items]}, items)

    elif isinstance(calculator, TransformChain):
        transforms = [
            _Encoder.encode_calculator_value(t, f"{path}.transforms[{i}]", inline_bytes)
            for i, t in enumerate(calculator.transforms)
        ]
        payload: dict[str, Any] = {
            "node": "transform_chain",
            "class": class_path(calculator),
            "transforms": [e.value for e in transforms],
        }
        if ts is not None:
            payload["transform"] = ts
        encoded = _merge_encoded(payload, [*ts_children, *transforms])

    elif isinstance(calculator, (AndFilter, OrFilter)):
        op = "and" if isinstance(calculator, AndFilter) else "or"
        left = _Encoder.encode_calculator_value(calculator.left, f"{path}.left", inline_bytes)
        right = _Encoder.encode_calculator_value(calculator.right, f"{path}.right", inline_bytes)
        left, right = _sort_encoded_commutative([left, right])
        encoded = _merge_encoded(
            {"node": "filter_op", "op": op, "left": left.value, "right": right.value}, [left, right]
        )

    elif isinstance(calculator, NotFilter):
        child = _Encoder.encode_calculator_value(calculator.child, f"{path}.child", inline_bytes)
        encoded = _merge_encoded({"node": "filter_op", "op": "not", "child": child.value}, [child])

    elif isinstance(calculator, ConstantProperty):
        v = _Encoder.encode_value(calculator._value, f"{path}.value", inline_bytes)
        encoded = _merge_encoded({"node": "constant_property", "value": v.value}, [v])

    elif isinstance(calculator, CalculatorValueProperty):
        nested = _Encoder.encode_calculator_value(calculator.calculator, f"{path}.calculator", inline_bytes)
        encoded = _merge_encoded({"node": "calculator_value_property", "calculator": nested.value}, [nested])

    elif isinstance(calculator, OpProperty):
        operands = [
            _Encoder.encode_calculator_value(op, f"{path}.operands[{i}]", inline_bytes)
            for i, op in enumerate(calculator.operands)
        ]
        if calculator.op_name in _COMMUTATIVE_PROPERTY_OPS:
            operands = _sort_encoded_commutative(operands)
        encoded = _merge_encoded(
            {"node": "op_property", "op_name": calculator.op_name, "operands": [e.value for e in operands]},
            operands,
        )

    elif isinstance(calculator, LambdaProperty):
        payload = {"node": "lambda_property", "class": class_path(calculator), "func_repr": repr(calculator._func)}
        encoded = _Encoded(payload, constructible=False, paths=(f"{path}.func",))

    return encoded


def _encode_generic(calculator: Any, path: str, inline_bytes: int) -> _Encoded:
    """Encode a generic (non-dataclass, non-special) calculator."""
    payload_items = calculator.signature_payload()
    children: list[_Encoded] = []
    identity: dict[str, Any] = {}
    if payload_items is None:
        identity["opaque_id"] = id(calculator)
    else:
        for key, value in payload_items.items():
            enc = _Encoder.encode_value(value, f"{path}.identity.{key}", inline_bytes)
            identity[key] = enc.value
            children.append(enc)
    deps = [
        _Encoder.encode_calculator_value(dep, f"{path}.deps[{i}]", inline_bytes)
        for i, dep in enumerate(calculator.dependencies())
    ]
    children.extend(deps)
    ts, ts_children = _transform_state(calculator, inline_bytes, path)
    children.extend(ts_children)
    payload: dict[str, Any] = {"node": "generic", "class": class_path(calculator), "identity": identity}
    if deps:
        payload["deps"] = [e.value for e in deps]
    if ts is not None:
        payload["transform"] = ts
    merged = _merge_encoded(payload, children)
    return _Encoded(merged.value, constructible=False, paths=(*merged.paths, path))


def encode_calculator(
    calculator: Any, *, path: str = "calculator", inline_array_bytes: int = 128
) -> tuple[Any, bool, tuple[str, ...]]:
    """Encode *calculator* as ``(payload, constructible, non_constructible_paths)``."""
    if not _is_calculator(calculator):
        raise TypeError(f"expected CalculatorBase, got {type(calculator)!r}")

    encoded = _encode_special(calculator, path, inline_array_bytes)
    if encoded is None:
        if is_dataclass(calculator):
            encoded = _encode_dataclass(calculator, path, inline_array_bytes)
        else:
            encoded = _encode_generic(calculator, path, inline_array_bytes)

    # A non-empty scope on a calculator must be part of its identity so a scoped
    # clone gets a different cache key than the unscoped one.
    scope_spec = getattr(calculator, "scope", None)
    if scope_spec is not None and not scope_spec.is_empty:
        scope_e = _encode_scope(scope_spec, f"{path}.scope", inline_array_bytes)
        encoded = _merge_encoded({"node": "scoped", "base": encoded.value, "scope": scope_e.value}, [encoded, scope_e])

    return encoded.value, encoded.constructible, encoded.paths


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def _decode_scoped(payload: dict[str, Any]) -> Any:
    """Decode a plain calculator wrapped with a scope (see ``encode_calculator``)."""
    base = _Decoder.decode_value(payload["base"])
    base.scope = _decode_scope(payload["scope"])
    return base


def _decode_combined(payload: dict[str, Any]) -> Any:
    from .base import CombinedCalculator

    return CombinedCalculator(*(_Decoder.decode_value(item) for item in payload["items"]))


def _decode_transform_chain(payload: dict[str, Any]) -> Any:
    cls = import_object(payload["class"])
    return _apply_transform_state(
        cls(*(_Decoder.decode_value(item) for item in payload["transforms"])), payload.get("transform")
    )


def _decode_filter_op(payload: dict[str, Any]) -> Any:
    from .filters import AndFilter, NotFilter, OrFilter

    op = payload["op"]
    if op == "and":
        return AndFilter(_Decoder.decode_value(payload["left"]), _Decoder.decode_value(payload["right"]))
    if op == "or":
        return OrFilter(_Decoder.decode_value(payload["left"]), _Decoder.decode_value(payload["right"]))
    if op == "not":
        return NotFilter(_Decoder.decode_value(payload["child"]))
    raise ValueError(f"unsupported filter op: {op!r}")


def _decode_constant_property(payload: dict[str, Any]) -> Any:
    from .expr import ConstantProperty

    return ConstantProperty(_Decoder.decode_value(payload["value"]))


def _decode_calculator_value_property(payload: dict[str, Any]) -> Any:
    from .expr import CalculatorValueProperty

    return CalculatorValueProperty(_Decoder.decode_value(payload["calculator"]))


def _decode_op_property(payload: dict[str, Any]) -> Any:
    from .expr import OpProperty

    return OpProperty(payload["op_name"], [_Decoder.decode_value(item) for item in payload["operands"]])


def _decode_scope(payload: dict[str, Any]) -> Any:
    from pynbodyext.core.calculate.result.enums import RevertPolicy
    from pynbodyext.core.calculate.runtime.scopes import ScopeSpec

    transforms = tuple(_Decoder.decode_value(item) for item in payload.get("transforms", ()))
    filter_node = _Decoder.decode_value(payload["filter"]) if "filter" in payload else None
    revert_policy = RevertPolicy(payload.get("revert_policy", RevertPolicy.ALWAYS.value))
    return ScopeSpec(transforms=transforms, filter=filter_node, revert_policy=revert_policy)


def _apply_transform_state(calculator: Any, payload: dict[str, Any] | None) -> Any:
    if payload is not None:
        if "revert_policy" in payload:
            calculator.revert_policy = _Decoder.decode_value(payload["revert_policy"])
        if "measure_filter" in payload:
            calculator.measure_filter = _Decoder.decode_value(payload["measure_filter"])
    return calculator


def _decode_special(payload: dict[str, Any]) -> Any:
    """Decode a special (non-dataclass) calculator payload."""
    node_type = payload["node"]
    if node_type == "lambda_property":
        raise ValueError("cannot reconstruct LambdaProperty from signature")
    handler = _SPECIAL_DECODERS.get(node_type)
    if handler is None:
        raise ValueError(f"unsupported special calculator node: {node_type!r}")
    return handler(payload)


def _decode_dataclass(payload: dict[str, Any]) -> Any:
    """Decode a dataclass calculator payload."""
    cls = import_object(payload["class"])
    values = {name: _Decoder.decode_value(enc) for name, enc in payload.get("init", {}).items()}
    return _apply_transform_state(cls(**values), payload.get("transform"))


_SPECIAL_DECODERS: dict[str, Any] = {
    "scoped": _decode_scoped,
    "combined": _decode_combined,
    "transform_chain": _decode_transform_chain,
    "filter_op": _decode_filter_op,
    "constant_property": _decode_constant_property,
    "calculator_value_property": _decode_calculator_value_property,
    "op_property": _decode_op_property,
}


def decode_calculator(payload: dict[str, Any]) -> Any:
    """Rebuild a calculator from its signature payload."""
    if payload.get("node") == "dataclass":
        return _decode_dataclass(payload)
    return _decode_special(payload)


register_calculator_layer(is_node=_is_calculator, encode=encode_calculator, decode=decode_calculator)

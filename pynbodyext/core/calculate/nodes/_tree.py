"""Tree-labeling and rendering helpers for calculator dependency graphs.

These are pure functions that translate a calculator node (or a group of nodes)
into the multi-line tree strings shown by ``CalculatorBase.dependency_tree`` and
the node-tree report.  They operate on the duck-typed node surface — ``kind``,
``tree_label``, and ``children()`` — so they stay independent of the concrete
class hierarchy in :mod:`pynbodyext.core.calculate.nodes.base`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pynbodyext.core.calculate.display import hidden_summary, tree_lines

if TYPE_CHECKING:
    from pynbodyext.core.calculate.nodes.base import CalculatorBase


def kind_label(kind: str, *, compact: bool) -> str:
    """Return a human label for *kind*, optionally shortened in compact mode."""
    if not compact:
        return kind
    return {"property": "prop", "filter": "filt", "transform": "trans", "calculator": "calc", "combined": "comb"}.get(
        kind, kind
    )


def input_node(node: CalculatorBase[Any, Any]) -> CalculatorBase[Any, Any]:
    """Return the node whose init args should label the tree entry."""
    return node


def label_for(node: CalculatorBase[Any, Any], *, show_inputs: bool, compact_kinds: bool) -> str:
    """Build the ``name<kind>`` label for a tree entry, optionally with init args."""
    from pynbodyext.core.calculate.result.signature import calculator_pretty_init_args

    label = node.tree_label
    target = input_node(node)

    if show_inputs:
        init_text = calculator_pretty_init_args(target)
        if init_text:
            label = f"{label}({init_text})"

    kind = kind_label(node.kind, compact=compact_kinds)
    return f"{label}<{kind}>"


def children_of(node: CalculatorBase[Any, Any]) -> list[CalculatorBase[Any, Any]]:
    """The child nodes of *node*, as the tree walkers want them."""
    return node.children()


def hidden_label(children: list[CalculatorBase[Any, Any]]) -> str:
    """Describe *children* that are elided from a truncated tree."""
    return hidden_summary(children, key=id, children=children_of)


def render_tree(
    node: CalculatorBase[Any, Any],
    *,
    max_depth: int | None = None,
    max_children: int | None = None,
    show_inputs: bool = True,
    compact_kinds: bool = True,
) -> str:
    """Render *node* and its dependencies as a multi-line dependency tree.

    The tree ``CalculatorBase.dependency_tree`` shows.  ``max_depth`` /
    ``max_children`` truncate a large graph (elided subtrees are summarised),
    which is why the parameterised builder lives here rather than on the
    attribute itself.

    The walk itself comes from :func:`pynbodyext.core.calculate.display.tree_lines`,
    which the result trees share, so this function only decides what a node's
    label looks like.
    """
    lines = tree_lines(
        node,
        children=children_of,
        label=lambda current: label_for(current, show_inputs=show_inputs, compact_kinds=compact_kinds),
        hidden=hidden_label,
        max_depth=max_depth,
        max_children=max_children,
    )
    return "\n" + "\n".join(lines)

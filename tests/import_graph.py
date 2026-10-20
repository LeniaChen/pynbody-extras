"""Read a package's run-time import edges, for the boundary tests.

Shared by ``test_layering_contract.py`` (import direction inside the calculator
core), ``test_image_boundary_contract.py`` (the image layer's boundary) and
``test_package_layers_contract.py`` (the package-wide order).  All three need
the same things: the absolute module an ``ImportFrom`` names — relative imports
included, because that is how a lower layer would reach upward — whether a block
is ``TYPE_CHECKING``-only, and a walk over a file that collects the run-time ones.

Resolving a relative import needs the *absolute* dotted package of the file, so
every helper here takes the directory that holds the package rather than trusting
a relative path: ``from .nodes.base import X`` in ``core/calculate/nodes/base.py``
must come out as ``pynbodyext.core.calculate.nodes.base``, not ``nodes.base``.

Import-light on purpose: only the standard library, so the tests that use it stay
quick.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

#: The package the helpers below resolve names against.
PACKAGE = "pynbodyext"


def is_type_checking_block(node: ast.If) -> bool:
    """Whether *node* is an ``if TYPE_CHECKING:`` block."""
    return "TYPE_CHECKING" in ast.dump(node.test)


def module_name(path: pathlib.Path, root: pathlib.Path) -> str:
    """The dotted module name of *path*, where *root* holds the package.

    ``module_name(…/pynbodyext/core/calculate/display.py, repo)`` is
    ``"pynbodyext.core.calculate.display"``; an ``__init__.py`` names its package.
    """
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def package_name(path: pathlib.Path, root: pathlib.Path) -> str:
    """The dotted package *path* lives in — what its relative imports resolve against.

    For a module it is the containing package; for an ``__init__.py`` it is the
    package itself, because ``from . import x`` inside ``a/__init__.py`` means
    ``a.x``.
    """
    name = module_name(path, root)
    if path.name == "__init__.py":
        return name
    return name.rsplit(".", 1)[0] if "." in name else name


def resolved_module(node: ast.ImportFrom, package: str) -> str:
    """The dotted module an ``ImportFrom`` names, relative imports included.

    *package* is the absolute dotted package that contains the importing file: one
    leading dot means "inside it", two mean "inside its parent", and so on.
    """
    if node.level == 0:
        return node.module or ""
    parts = package.split(".")
    base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
    return ".".join([*base, node.module] if node.module else base)


def runtime_imports(path: pathlib.Path, package: str) -> list[str]:
    """Modules *path* imports at run time, skipping ``TYPE_CHECKING`` blocks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and is_type_checking_block(child):
                continue  # annotations only: not a run-time dependency
            if isinstance(child, ast.ImportFrom):
                found.append(resolved_module(child, package))
            elif isinstance(child, ast.Import):
                found.extend(alias.name for alias in child.names)
            visit(child)

    visit(tree)
    return found


def module_level_imports(path: pathlib.Path, package: str) -> list[str]:
    """Modules *path* imports at the top level of the module.

    Function-local imports are not reported: they are the seam a lower layer uses
    to reach an optional, heavy neighbour without paying for it at import time.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.If) and is_type_checking_block(node):
            continue
        if isinstance(node, ast.ImportFrom):
            found.append(resolved_module(node, package))
        elif isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Try):
            # ``try: import optional`` counts as a top-level import
            for statement in node.body:
                if isinstance(statement, ast.ImportFrom):
                    found.append(resolved_module(statement, package))
                elif isinstance(statement, ast.Import):
                    found.extend(alias.name for alias in statement.names)
    return found


def runtime_importers(root: pathlib.Path, *, package_root: pathlib.Path) -> dict[str, list[str]]:
    """Every ``*.py`` under *root*, mapped to the modules it imports at run time.

    *package_root* is the directory that holds the package.  Keys are dotted module
    names, so a caller can name the layer of an importer and of an import the same
    way.
    """
    out: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        out[module_name(path, package_root)] = runtime_imports(path, package_name(path, package_root))
    return out

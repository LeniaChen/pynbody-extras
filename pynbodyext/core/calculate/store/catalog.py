"""A directory of calculator signatures: from a key back to the calculator.

A signature hash is a key, not a description: it cannot be turned back into the
calculator it identifies.  A :class:`SignatureCatalog` keeps, for each key, the
full signature (so the calculator can be rebuilt and its expression printed) and
an optional human label (``"r_e"``, ``"m_star"``).  It is what a sample table
uses to describe its columns, and what makes a key found in a file or a database
row readable again::

    catalog = SignatureCatalog()
    key = catalog.add(ParamContain().filter(Sphere("30 kpc")), label="r_e")
    catalog[key[:12]].pretty()  # 'ParamContain(0.5, "r", "mass").filter(...)'
    catalog.calculator("r_e")  # the rebuilt, runnable calculator
    catalog.save("columns.json")

A result store already holds the signature of every result it stored;
:meth:`ResultStore.catalog <pynbodyext.core.calculate.store.base.ResultStore.catalog>`
collects them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pynbodyext.core.calculate.display import InfoView
from pynbodyext.core.calculate.interfaces import is_calculator_node
from pynbodyext.core.calculate.result.signature import CalculatorSignature, calculator_from_signature

if TYPE_CHECKING:
    import os
    from collections.abc import Iterator

__all__ = ["CATALOG_SCHEMA", "CatalogEntry", "SignatureCatalog"]

#: Discriminator of the catalog's JSON file format.
CATALOG_SCHEMA = "pynbodyext.signature.catalog/v1"

#: Shortest key prefix accepted for a lookup: 8 hex digits leave a collision
#: chance of about one in four billion per pair of keys.
MIN_PREFIX = 8


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """One catalogued calculator: its key, signature and optional label."""

    key: str
    signature: CalculatorSignature
    label: str | None = None

    @property
    def expression(self) -> str:
        """The calculator as a Python-like expression (:meth:`CalculatorSignature.pretty`)."""
        return self.signature.pretty()


class SignatureCatalog(InfoView):
    """Keys (full signature hashes) mapped to their signatures and labels.

    A key is looked up by its full 64-character hash, by a unique prefix of at
    least eight characters (the short hashes shown in cards and reports), or by
    its label.  Adding the same calculator twice is harmless; giving one label to
    two different calculators is refused, because a label must name one thing.
    """

    def __init__(self) -> None:
        self._entries: dict[str, CatalogEntry] = {}
        self._labels: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Building
    # ------------------------------------------------------------------

    def add(self, calculator: Any, *, label: str | None = None) -> str:
        """Catalogue *calculator* (a calculator or a :class:`CalculatorSignature`); return its key.

        A later *label* for an already catalogued key replaces the earlier one.

        Raises
        ------
        ValueError
            If *label* already names another key.
        """
        signature = calculator.to_signature() if is_calculator_node(calculator) else calculator
        if not isinstance(signature, CalculatorSignature):
            raise TypeError(f"expected a calculator or CalculatorSignature, got {type(calculator)!r}")
        key = signature.hash
        if label is not None:
            owner = self._labels.get(label)
            if owner is not None and owner != key:
                raise ValueError(f"label {label!r} already names {self._entries[owner].expression!r}")
        existing = self._entries.get(key)
        if existing is not None and label is None:
            return key
        if existing is not None and existing.label is not None and existing.label != label:
            self._labels.pop(existing.label, None)
        self._entries[key] = CatalogEntry(key, signature, label if label is not None else None)
        if label is not None:
            self._labels[label] = key
        return key

    def update(self, other: SignatureCatalog) -> None:
        """Add every entry of *other* (its labels too)."""
        for entry in other.entries():
            self.add(entry.signature, label=entry.label)

    def remove(self, key_or_label: str) -> None:
        """Drop one entry."""
        key = self.key(key_or_label)
        entry = self._entries.pop(key)
        if entry.label is not None:
            self._labels.pop(entry.label, None)

    # ------------------------------------------------------------------
    # Looking up
    # ------------------------------------------------------------------

    def key(self, key_or_label: str) -> str:
        """Resolve a full key, a unique prefix of one, or a label to the full key.

        Raises
        ------
        KeyError
            If nothing matches, or a prefix matches more than one key.
        """
        if key_or_label in self._entries:
            return key_or_label
        if key_or_label in self._labels:
            return self._labels[key_or_label]
        if len(key_or_label) >= MIN_PREFIX:
            matches = [key for key in self._entries if key.startswith(key_or_label)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise KeyError(f"key prefix {key_or_label!r} is ambiguous: {len(matches)} keys start with it")
        raise KeyError(f"no catalogued calculator for {key_or_label!r}")

    def entry(self, key_or_label: str) -> CatalogEntry:
        """The :class:`CatalogEntry` for a key, prefix or label."""
        return self._entries[self.key(key_or_label)]

    def __getitem__(self, key_or_label: str) -> CalculatorSignature:
        return self.entry(key_or_label).signature

    def calculator(self, key_or_label: str) -> Any:
        """Rebuild the catalogued calculator.

        Raises
        ------
        ValueError
            If its signature is not constructible (a lambda, an opaque node, a
            large array kept by hash).
        """
        return calculator_from_signature(self[key_or_label])

    def label(self, key_or_label: str) -> str | None:
        """The label of a catalogued key, if it has one."""
        return self.entry(key_or_label).label

    def find(self, text: str) -> list[CatalogEntry]:
        """Entries whose label or expression contains *text* (case-insensitive)."""
        needle = text.casefold()
        return [
            entry
            for entry in self._entries.values()
            if needle in entry.expression.casefold() or (entry.label is not None and needle in entry.label.casefold())
        ]

    def __contains__(self, key_or_label: object) -> bool:
        if is_calculator_node(key_or_label):
            to_signature = getattr(key_or_label, "to_signature")  # noqa: B009 - a calculator, checked above
            return to_signature().hash in self._entries
        if isinstance(key_or_label, CalculatorSignature):
            return key_or_label.hash in self._entries
        if not isinstance(key_or_label, str):
            return False
        try:
            self.key(key_or_label)
        except KeyError:
            return False
        return True

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def entries(self) -> list[CatalogEntry]:
        """Every entry, in the order they were added."""
        return list(self._entries.values())

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """A JSON-compatible description of the catalog."""
        return {
            "schema": CATALOG_SCHEMA,
            "entries": [
                {"key": entry.key, "label": entry.label, "signature": entry.signature.as_dict(full=True)}
                for entry in self._entries.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SignatureCatalog:
        """Rebuild a catalog from :meth:`to_dict`; every stored key is checked against its signature."""
        if data.get("schema") != CATALOG_SCHEMA:
            raise ValueError(f"unsupported catalog schema: {data.get('schema')!r}")
        catalog = cls()
        for item in data.get("entries", ()):
            signature = CalculatorSignature.from_dict(item["signature"])
            key = catalog.add(signature, label=item.get("label"))
            if key != item["key"]:
                raise ValueError(
                    f"catalog entry {item.get('label') or item['key'][:12]!r} was written under key "
                    f"{item['key'][:12]}..., but its signature hashes to {key[:12]}... (another schema version?)"
                )
        return catalog

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> SignatureCatalog:
        return cls.from_dict(json.loads(text))

    def save(self, path: str | os.PathLike[str]) -> None:
        """Write the catalog as JSON to *path*."""
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.to_json())

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> SignatureCatalog:
        """Read a catalog written by :meth:`save`."""
        with open(path, encoding="utf-8") as handle:
            return cls.from_json(handle.read())

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    #: Entries listed in the repr card; the rest are counted.
    display_limit = 20

    def _display_title(self) -> str:
        return "SignatureCatalog"

    def _display_rows(self) -> list[tuple[str, Any]]:
        rows: list[tuple[str, Any]] = [("entries", len(self._entries))]
        for entry in list(self._entries.values())[: self.display_limit]:
            name = entry.label or "-"
            expression = entry.expression
            if len(expression) > 160:
                expression = expression[:157] + "..."
            rows.append((entry.key[:12], f"{name} = {expression}"))
        hidden = len(self._entries) - self.display_limit
        if hidden > 0:
            rows.append(("...", f"{hidden} more"))
        return rows

    def __repr__(self) -> str:
        labels = [entry.label for entry in self._entries.values() if entry.label][:6]
        suffix = f", labels={labels!r}" if labels else ""
        return f"SignatureCatalog(entries={len(self._entries)}{suffix})"

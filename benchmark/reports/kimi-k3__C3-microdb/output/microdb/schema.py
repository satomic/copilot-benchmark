"""Schema layer: Column and Table."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError
from .value import BOOL, FLOAT, INT, TEXT

_VALID_TYPES = (INT, FLOAT, TEXT, BOOL)


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str  # "INT" | "FLOAT" | "TEXT" | "BOOL"


def _check_cell(col: Column, value: object) -> object:
    """Validate one cell against its column type; returns the stored value."""
    if value is None:
        return None
    if col.type == BOOL:
        if isinstance(value, bool):
            return value
        raise SchemaError(f"column {col.name!r}: expected BOOL, got {value!r}")
    if col.type == INT:
        # bool is a subclass of int; an INT column rejects True/False.
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise SchemaError(f"column {col.name!r}: expected INT, got {value!r}")
    if col.type == FLOAT:
        # FLOAT widening: an int is accepted and stored converted to float.
        if isinstance(value, float):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        raise SchemaError(f"column {col.name!r}: expected FLOAT, got {value!r}")
    if col.type == TEXT:
        if isinstance(value, str):
            return value
        raise SchemaError(f"column {col.name!r}: expected TEXT, got {value!r}")
    raise SchemaError(f"column {col.name!r}: unknown type {col.type!r}")


class Table:
    """A named table with typed columns and validated rows."""

    def __init__(
        self,
        name: str,
        columns: list[Column],
        rows: list[list[object]],
    ) -> None:
        if not columns:
            raise SchemaError("table must have at least one column")
        seen: set[str] = set()
        for col in columns:
            if col.type not in _VALID_TYPES:
                raise SchemaError(f"invalid column type {col.type!r}")
            if col.name in seen:
                raise SchemaError(f"duplicate column name {col.name!r}")
            seen.add(col.name)
        stored: list[list[object]] = []
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError(
                    f"row has {len(row)} cells, expected {len(columns)}"
                )
            stored.append(
                [_check_cell(col, v) for col, v in zip(columns, row)]
            )
        self._name = name
        self._columns = list(columns)
        self._rows = stored
        self._index = {col.name: i for i, col in enumerate(columns)}

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self) -> list[list[object]]:
        return list(self._rows)

    def column_index(self, name: str) -> int:
        """Return the zero-based index of a column; SchemaError if unknown."""
        try:
            return self._index[name]
        except KeyError:
            raise SchemaError(f"unknown column {name!r} in table {self._name!r}")

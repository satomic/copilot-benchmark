"""Schema layer: Column and Table."""

from __future__ import annotations

import dataclasses

from microdb.errors import SchemaError

VALID_TYPES = {"INT", "FLOAT", "TEXT", "BOOL"}


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


def _check_cell(value: object, col: Column, row_index: int) -> object:
    """Validate/coerce a single cell against its column type; returns the stored value."""
    if value is None:
        return None
    if col.type == "BOOL":
        if not isinstance(value, bool):
            raise SchemaError(f"row {row_index}: column {col.name!r} expects BOOL")
        return value
    if col.type == "INT":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"row {row_index}: column {col.name!r} expects INT")
        return value
    if col.type == "FLOAT":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"row {row_index}: column {col.name!r} expects FLOAT")
        return float(value)
    if col.type == "TEXT":
        if not isinstance(value, str):
            raise SchemaError(f"row {row_index}: column {col.name!r} expects TEXT")
        return value
    raise SchemaError(f"unreachable: unknown type {col.type!r}")


class Table:
    """An in-memory table: a fixed list of typed columns plus rows of values."""

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("a table must have at least one column")
        seen: set[str] = set()
        for col in columns:
            if col.type not in VALID_TYPES:
                raise SchemaError(f"unknown column type: {col.type!r}")
            if col.name in seen:
                raise SchemaError(f"duplicate column name: {col.name!r}")
            seen.add(col.name)
        checked_rows: list[list[object]] = []
        for row_index, row in enumerate(rows):
            if len(row) != len(columns):
                raise SchemaError(f"row {row_index} has {len(row)} cells, expected {len(columns)}")
            checked_rows.append([_check_cell(v, c, row_index) for v, c in zip(row, columns)])
        self._name = name
        self._columns = list(columns)
        self._rows = checked_rows

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return self._columns

    @property
    def rows(self) -> list[list[object]]:
        return self._rows

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self._columns):
            if col.name == name:
                return i
        raise SchemaError(f"unknown column: {name!r}")

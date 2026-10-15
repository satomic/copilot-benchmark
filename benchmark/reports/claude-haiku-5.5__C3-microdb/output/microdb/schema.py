"""Schema layer: columns and validated in-memory tables."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError

TYPE_NAMES = ("INT", "FLOAT", "TEXT", "BOOL")


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str  # one of TYPE_NAMES


def _coerce(col: Column, v: object) -> object:
    """Validate one cell against its column type, widening int to float."""
    if v is None:
        return None
    if col.type == "BOOL" and isinstance(v, bool):
        return v
    if col.type == "TEXT" and isinstance(v, str):
        return v
    if col.type == "INT" and type(v) is int:
        return v
    if col.type == "FLOAT":
        if type(v) is float:
            return v
        if type(v) is int:
            return float(v)
    raise SchemaError(f"value {v!r} does not match column {col.name!r} of type {col.type}")


class Table:
    """A named table whose rows are validated against its columns."""

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("a table must have at least one column")
        seen: set[str] = set()
        for col in columns:
            if col.name in seen:
                raise SchemaError(f"duplicate column name {col.name!r}")
            if col.type not in TYPE_NAMES:
                raise SchemaError(f"unknown column type {col.type!r}")
            seen.add(col.name)
        self._name = name
        self._columns = list(columns)
        self._rows = [self._check_row(row) for row in rows]

    def _check_row(self, row: list[object]) -> list[object]:
        values = list(row)
        if len(values) != len(self._columns):
            raise SchemaError(
                f"row has {len(values)} cells but table {self._name!r} has {len(self._columns)} columns"
            )
        return [_coerce(col, v) for col, v in zip(self._columns, values)]

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self) -> list[list[object]]:
        return self._rows

    def column_index(self, name: str) -> int:
        for i, col in enumerate(self._columns):
            if col.name == name:
                return i
        raise SchemaError(f"table {self._name!r} has no column {name!r}")

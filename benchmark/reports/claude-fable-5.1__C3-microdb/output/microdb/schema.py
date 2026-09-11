"""Schema layer: Column and Table."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError
from .value import TYPE_NAMES, type_of


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


def coerce_cell(value: object, col: Column, row_index: int) -> object:
    """Validate one cell against its column type; FLOAT columns widen int."""
    if value is None:
        return None
    kind = type_of(value)
    if kind == col.type:
        return value
    if col.type == "FLOAT" and kind == "INT":
        return float(value)
    raise SchemaError(
        f"row {row_index}: column {col.name!r} expects {col.type}, got {kind} {value!r}"
    )


class Table:
    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError(f"table {name!r} has no columns")
        seen: set[str] = set()
        for col in columns:
            if col.name in seen:
                raise SchemaError(f"duplicate column {col.name!r} in table {name!r}")
            seen.add(col.name)
            if col.type not in TYPE_NAMES:
                raise SchemaError(f"column {col.name!r} has unknown type {col.type!r}")
        checked: list[list[object]] = []
        for i, row in enumerate(rows):
            if len(row) != len(columns):
                raise SchemaError(
                    f"row {i} has {len(row)} values, expected {len(columns)}"
                )
            checked.append([coerce_cell(v, c, i) for v, c in zip(row, columns)])
        self._name = name
        self._columns = list(columns)
        self._rows = checked
        self._index = {c.name: i for i, c in enumerate(columns)}

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
        try:
            return self._index[name]
        except KeyError:
            raise SchemaError(f"unknown column {name!r} in table {self._name!r}") from None

    def __repr__(self) -> str:
        return f"Table({self._name!r}, {len(self._columns)} columns, {len(self._rows)} rows)"

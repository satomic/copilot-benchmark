"""Schema layer: Column and Table."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError
from .value import TYPE_NAMES, type_of


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str  # "INT" | "FLOAT" | "TEXT" | "BOOL"


def _coerce_cell(column: Column, cell: object) -> object:
    if cell is None:
        return None
    kind = type_of(cell) if isinstance(cell, (bool, int, float, str)) else "?"
    if kind == column.type:
        return cell
    if column.type == "FLOAT" and kind == "INT":
        return float(cell)  # type: ignore[arg-type]
    raise SchemaError(
        f"column {column.name!r} of type {column.type} cannot hold {cell!r}"
    )


class Table:
    """An immutable-schema, in-memory table."""

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        columns = list(columns)
        if not columns:
            raise SchemaError(f"table {name!r} has no columns")
        seen: set[str] = set()
        for col in columns:
            if col.type not in TYPE_NAMES:
                raise SchemaError(f"column {col.name!r} has unknown type {col.type!r}")
            if col.name in seen:
                raise SchemaError(f"duplicate column name {col.name!r}")
            seen.add(col.name)
        checked: list[list[object]] = []
        for number, row in enumerate(rows):
            row = list(row)
            if len(row) != len(columns):
                raise SchemaError(
                    f"row {number} has {len(row)} values, expected {len(columns)}"
                )
            checked.append([_coerce_cell(c, v) for c, v in zip(columns, row)])
        self._name = name
        self._columns = columns
        self._rows = checked
        self._index = {c.name: i for i, c in enumerate(columns)}

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self) -> list[list[object]]:
        return [list(r) for r in self._rows]

    def column_index(self, name: str) -> int:
        """Return the position of a column; SchemaError if it does not exist."""
        try:
            return self._index[name]
        except KeyError:
            raise SchemaError(f"table {self._name!r} has no column {name!r}") from None

    def __repr__(self) -> str:
        return f"Table({self._name!r}, {self._columns!r}, <{len(self._rows)} rows>)"

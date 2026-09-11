"""Columns and tables, with validation at construction time."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError
from .value import FLOAT, INT, TYPE_NAMES, type_of

__all__ = ["Column", "Table"]


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    """An immutable-by-convention table of rows.

    Validation happens once, here, so every later stage may assume the cells match
    their declared types.
    """

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError(f"table {name} has no columns")
        seen: set[str] = set()
        for col in columns:
            if col.name in seen:
                raise SchemaError(f"duplicate column {col.name} in table {name}")
            seen.add(col.name)
            if col.type not in TYPE_NAMES:
                raise SchemaError(f"column {col.name} has unknown type {col.type}")
        self._name = name
        self._columns = list(columns)
        self._rows = [self._check_row(index, row) for index, row in enumerate(rows)]

    def _check_row(self, index: int, row: list[object]) -> list[object]:
        if len(row) != len(self._columns):
            raise SchemaError(
                f"table {self._name} row {index} has {len(row)} cells, "
                f"expected {len(self._columns)}"
            )
        return [self._coerce(col, cell, index) for col, cell in zip(self._columns, row)]

    def _coerce(self, col: Column, cell: object, index: int) -> object:
        if cell is None:
            return None
        actual = type_of(cell)
        if col.type == FLOAT and actual == INT:
            return float(cell)  # the only implicit widening in the engine
        if actual != col.type:
            raise SchemaError(
                f"table {self._name} row {index} column {col.name} expects "
                f"{col.type}, got {actual}"
            )
        return cell

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self) -> list[list[object]]:
        return [list(row) for row in self._rows]

    def column_index(self, name: str) -> int:
        for index, col in enumerate(self._columns):
            if col.name == name:
                return index
        raise SchemaError(f"table {self._name} has no column {name}")

    def __len__(self) -> int:
        return len(self._rows)

    def __repr__(self) -> str:
        names = ",".join(f"{c.name}:{c.type}" for c in self._columns)
        return f"Table({self._name!r}, [{names}], {len(self._rows)} rows)"

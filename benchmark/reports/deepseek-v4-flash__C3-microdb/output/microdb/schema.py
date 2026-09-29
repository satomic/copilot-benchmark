"""Column and Table classes."""

import dataclasses
from typing import Any

from microdb.errors import SchemaError
from microdb.value import type_of


@dataclasses.dataclass(frozen=True)
class Column:
    """A column definition."""

    name: str
    type: str  # "INT" | "FLOAT" | "TEXT" | "BOOL"

    def __post_init__(self) -> None:
        if self.type not in ("INT", "FLOAT", "TEXT", "BOOL"):
            raise SchemaError(f"invalid column type: {self.type}")


_VALID_TYPES = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


class Table:
    """An in-memory table with validated rows."""

    __slots__ = ("_name", "_columns", "_rows")

    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        if not columns:
            raise SchemaError("table must have at least one column")
        if len(columns) != len({c.name for c in columns}):
            raise SchemaError("duplicate column name")
        for c in columns:
            if c.type not in _VALID_TYPES:
                raise SchemaError(f"invalid column type: {c.type}")
        col_count = len(columns)
        for i, row in enumerate(rows):
            if len(row) != col_count:
                raise SchemaError(
                    f"row {i} has {len(row)} values, expected {col_count}"
                )
            for j, cell in enumerate(row):
                if cell is None:
                    continue
                expected = columns[j].type
                actual = type_of(cell)
                # FLOAT columns accept int and convert
                if expected == "FLOAT" and actual == "INT":
                    row[j] = float(cell)
                elif actual != expected:
                    raise SchemaError(
                        f"row {i}, column '{columns[j].name}': "
                        f"expected {expected}, got {actual}"
                    )
        self._name = name
        self._columns = list(columns)
        self._rows = [list(row) for row in rows]

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
        """Return the index of a column by name. Raises SchemaError if unknown."""
        for i, c in enumerate(self._columns):
            if c.name == name:
                return i
        raise SchemaError(f"unknown column: {name}")
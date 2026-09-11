"""Schema layer: column definitions and in-memory tables."""

from __future__ import annotations

import dataclasses

from .errors import SchemaError
from .value import TYPE_NAMES, type_of


@dataclasses.dataclass(frozen=True)
class Column:
    """A named, typed column."""

    name: str
    type: str


def _coerce_cell(value: object, column: Column, row_index: int) -> object:
    """Validate one cell against its column type, widening INT to FLOAT if needed."""
    if value is None:
        return None
    actual = type_of(value)
    if actual == column.type:
        return value
    if column.type == "FLOAT" and actual == "INT":
        # The single implicit conversion in microdb: an INT stored in a FLOAT column.
        return float(value)
    raise SchemaError(
        f"row {row_index}: column {column.name!r} expects {column.type}, got {actual}"
    )


class Table:
    """An immutable-by-convention in-memory relation."""

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError(f"table {name!r} must have at least one column")
        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise SchemaError(f"duplicate column name {column.name!r} in table {name!r}")
            seen.add(column.name)
            if column.type not in TYPE_NAMES:
                raise SchemaError(
                    f"column {column.name!r} has unknown type {column.type!r}"
                )
        self._name: str = name
        self._columns: list[Column] = list(columns)
        self._rows: list[list[object]] = [
            self._validate_row(row, index) for index, row in enumerate(rows)
        ]

    def _validate_row(self, row: list[object], index: int) -> list[object]:
        if len(row) != len(self._columns):
            raise SchemaError(
                f"row {index} has {len(row)} values but table {self._name!r} "
                f"has {len(self._columns)} columns"
            )
        return [
            _coerce_cell(value, column, index)
            for value, column in zip(row, self._columns)
        ]

    @property
    def name(self) -> str:
        """The table name."""
        return self._name

    @property
    def columns(self) -> list[Column]:
        """The column definitions."""
        return self._columns

    @property
    def rows(self) -> list[list[object]]:
        """The stored rows."""
        return self._rows

    def column_index(self, name: str) -> int:
        """Return the zero-based index of ``name``, raising SchemaError if unknown."""
        for index, column in enumerate(self._columns):
            if column.name == name:
                return index
        raise SchemaError(f"table {self._name!r} has no column {name!r}")

    def __repr__(self) -> str:
        return f"Table({self._name!r}, {len(self._columns)} columns, {len(self._rows)} rows)"

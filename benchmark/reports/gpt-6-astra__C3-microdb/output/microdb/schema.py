"""Validated in-memory tables."""

from dataclasses import dataclass

from .errors import SchemaError, TypeMismatchError
from .value import type_of


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(self, name: str, columns: list[Column],
                 rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("A table must have at least one column")
        names = [column.name for column in columns]
        if len(set(names)) != len(names):
            raise SchemaError("Duplicate column name")
        for column in columns:
            if column.type not in ("INT", "FLOAT", "TEXT", "BOOL"):
                raise SchemaError(f"Invalid type for {column.name}: {column.type}")
        self._name = name
        self._columns = list(columns)
        self._indices = {column.name: i for i, column in enumerate(columns)}
        self._rows = [self._validate_row(row) for row in rows]

    def _validate_row(self, row: list[object]) -> list[object]:
        if len(row) != len(self._columns):
            raise SchemaError("Row length does not match column count")
        result = []
        for cell, column in zip(row, self._columns):
            try:
                kind = type_of(cell)
            except TypeMismatchError as error:
                raise SchemaError(str(error)) from error
            if column.type == "FLOAT" and kind == "INT":
                cell = float(cell)
            elif kind not in ("NULL", column.type):
                raise SchemaError(f"Column {column.name} expects {column.type}, got {kind}")
            result.append(cell)
        return result

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
        if name not in self._indices:
            raise SchemaError(f"Unknown column: {name}")
        return self._indices[name]

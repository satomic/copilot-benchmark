"""Validated in-memory tables."""

from dataclasses import dataclass

from .errors import SchemaError, TypeMismatchError
from .value import type_of


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("A table must have at least one column")
        names = [column.name for column in columns]
        if len(set(names)) != len(names):
            raise SchemaError("Duplicate column name")
        for column in columns:
            if column.type not in ("INT", "FLOAT", "TEXT", "BOOL"):
                raise SchemaError(f"Invalid column type: {column.type}")
        self._name = name
        self._columns = list(columns)
        self._rows = []
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError("Row length does not match column count")
            self._rows.append([self._cell(cell, col) for cell, col in zip(row, columns)])

    @staticmethod
    def _cell(cell: object, column: Column) -> object:
        if cell is None:
            return None
        try:
            kind = type_of(cell)
        except TypeMismatchError as error:
            raise SchemaError(str(error)) from error
        if column.type == "FLOAT" and kind == "INT":
            return float(cell)
        if kind != column.type:
            raise SchemaError(f"Column {column.name} expects {column.type}, got {kind}")
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
        for index, column in enumerate(self._columns):
            if column.name == name:
                return index
        raise SchemaError(f"Unknown column: {name}")

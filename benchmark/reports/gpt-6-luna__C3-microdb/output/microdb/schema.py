from __future__ import annotations

from dataclasses import dataclass

from .errors import SchemaError


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(self: Table, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("a table must have at least one column")
        names = [column.name for column in columns]
        if len(set(names)) != len(names):
            raise SchemaError("column names must be unique")
        allowed = {"INT", "FLOAT", "TEXT", "BOOL"}
        for column in columns:
            if column.type not in allowed:
                raise SchemaError(f"invalid column type: {column.type}")
        converted: list[list[object]] = []
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError("row length does not match column count")
            cells: list[object] = []
            for cell, column in zip(row, columns):
                cells.append(self._validate_cell(cell, column))
            converted.append(cells)
        self._name = name
        self._columns = list(columns)
        self._rows = converted

    @staticmethod
    def _validate_cell(value: object, column: Column) -> object:
        if value is None:
            return None
        valid = {
            "INT": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "FLOAT": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "TEXT": lambda v: isinstance(v, str),
            "BOOL": lambda v: isinstance(v, bool),
        }[column.type]
        if not valid(value):
            raise SchemaError(f"value does not match {column.type} column {column.name}")
        return float(value) if column.type == "FLOAT" else value

    @property
    def name(self: Table) -> str:
        return self._name

    @property
    def columns(self: Table) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self: Table) -> list[list[object]]:
        return [list(row) for row in self._rows]

    def column_index(self: Table, name: str) -> int:
        for index, column in enumerate(self._columns):
            if column.name == name:
                return index
        raise SchemaError(f"unknown column: {name}")

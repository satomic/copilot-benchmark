"""Table schema and row validation."""

from __future__ import annotations

import dataclasses

from microdb.errors import SchemaError

_TYPES = ("INT", "FLOAT", "TEXT", "BOOL")


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    """An in-memory relation. FLOAT columns accept int and store float."""

    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        self._name = name
        self._columns = _validate_columns(columns)
        self._rows = _validate_rows(self._columns, rows)

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
        for index, column in enumerate(self._columns):
            if column.name == name:
                return index
        raise SchemaError(f"unknown column {name}")


def _validate_columns(columns: list[Column]) -> list[Column]:
    if not columns:
        raise SchemaError("table has no columns")
    seen: set[str] = set()
    for column in columns:
        if column.type not in _TYPES:
            raise SchemaError(f"invalid column type {column.type}")
        if column.name in seen:
            raise SchemaError(f"duplicate column {column.name}")
        seen.add(column.name)
    return list(columns)


def _validate_rows(columns: list[Column], rows: list[list[object]]) -> list[list[object]]:
    stored: list[list[object]] = []
    width = len(columns)
    for row in rows:
        if len(row) != width:
            raise SchemaError(f"row length {len(row)} does not match {width} columns")
        stored.append([_coerce(column, cell) for column, cell in zip(columns, row)])
    return stored


def _coerce(column: Column, cell: object) -> object:
    if cell is None:
        return None
    if column.type == "INT":
        return _coerce_int(column.name, cell)
    if column.type == "FLOAT":
        return _coerce_float(column.name, cell)
    if column.type == "TEXT":
        return _coerce_text(column.name, cell)
    return _coerce_bool(column.name, cell)


def _coerce_int(name: str, cell: object) -> int:
    if type(cell) is int:
        return cell
    raise SchemaError(f"column {name} expects INT, got {cell!r}")


def _coerce_float(name: str, cell: object) -> float:
    # The only implicit conversion in the engine: INT widens to FLOAT.
    if type(cell) is float:
        return cell
    if type(cell) is int:
        return float(cell)
    raise SchemaError(f"column {name} expects FLOAT, got {cell!r}")


def _coerce_text(name: str, cell: object) -> str:
    if type(cell) is str:
        return cell
    raise SchemaError(f"column {name} expects TEXT, got {cell!r}")


def _coerce_bool(name: str, cell: object) -> bool:
    if type(cell) is bool:
        return cell
    raise SchemaError(f"column {name} expects BOOL, got {cell!r}")

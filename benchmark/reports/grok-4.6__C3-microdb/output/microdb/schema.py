"""Column and Table schema objects."""

from __future__ import annotations

import dataclasses

from microdb.errors import SchemaError

_TYPES = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        if not columns:
            raise SchemaError("table must have at least one column")
        seen: set[str] = set()
        for col in columns:
            if col.name in seen:
                raise SchemaError(f"duplicate column {col.name!r}")
            seen.add(col.name)
            if col.type not in _TYPES:
                raise SchemaError(f"invalid column type {col.type!r}")
        width = len(columns)
        stored: list[list[object]] = []
        for row in rows:
            if len(row) != width:
                raise SchemaError("row width does not match column count")
            stored.append([_coerce(columns[i], row[i]) for i in range(width)])
        self._name = name
        self._columns = list(columns)
        self._rows = stored

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
        for i, col in enumerate(self._columns):
            if col.name == name:
                return i
        raise SchemaError(f"unknown column {name!r}")


def _coerce(col: Column, value: object) -> object:
    if value is None:
        return None
    if col.type == "INT":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise SchemaError(f"expected INT for {col.name!r}")
    if col.type == "FLOAT":
        if isinstance(value, bool):
            raise SchemaError(f"expected FLOAT for {col.name!r}")
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        raise SchemaError(f"expected FLOAT for {col.name!r}")
    if col.type == "TEXT":
        if isinstance(value, str):
            return value
        raise SchemaError(f"expected TEXT for {col.name!r}")
    if value is True or value is False:
        return value
    raise SchemaError(f"expected BOOL for {col.name!r}")

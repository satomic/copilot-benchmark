from __future__ import annotations

from dataclasses import dataclass

from .errors import SchemaError


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("table has no columns")
        names: set[str] = set()
        valid = {"INT", "FLOAT", "TEXT", "BOOL"}
        for col in columns:
            if col.name in names:
                raise SchemaError(f"duplicate column {col.name}")
            names.add(col.name)
            if col.type not in valid:
                raise SchemaError(f"invalid type {col.type}")
        self._name = name
        self._columns = list(columns)
        self._rows: list[list[object]] = []
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError("row length mismatch")
            clean: list[object] = []
            for idx, val in enumerate(row):
                clean.append(self._coerce(columns[idx].type, val))
            self._rows.append(clean)

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
        for i, col in enumerate(self._columns):
            if col.name == name:
                return i
        raise SchemaError(f"unknown column {name}")

    def _coerce(self, col_type: str, value: object) -> object:
        if value is None:
            return None
        if col_type == "BOOL":
            if value in (True, False):
                return bool(value)
            raise SchemaError("BOOL column requires bool")
        if col_type == "INT":
            if isinstance(value, bool):
                raise SchemaError("INT column rejects bool")
            if isinstance(value, int):
                return value
            raise SchemaError("INT column requires int")
        if col_type == "FLOAT":
            if isinstance(value, bool):
                raise SchemaError("FLOAT column rejects bool")
            if isinstance(value, int):
                return float(value)
            if isinstance(value, float):
                return value
            raise SchemaError("FLOAT column requires float-compatible input")
        if col_type == "TEXT":
            if isinstance(value, str):
                return value
            raise SchemaError("TEXT column requires str")
        raise SchemaError(f"unknown type {col_type}")

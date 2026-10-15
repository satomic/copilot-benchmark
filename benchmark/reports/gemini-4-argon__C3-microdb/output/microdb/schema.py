from __future__ import annotations

import dataclasses

from microdb.errors import SchemaError
from microdb.value import VALID_TYPES, type_of


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


def _validate_cell(value: object, col_type: str, col_name: str) -> object:
    if value is None:
        return None
    try:
        val_type = type_of(value)
    except Exception as exc:
        raise SchemaError(f"Invalid cell value {value!r} for {col_name!r}") from exc
    if col_type == "FLOAT" and val_type == "INT":
        assert isinstance(value, int)
        return float(value)
    if val_type != col_type:
        raise SchemaError(
            f"Column {col_name!r} expects {col_type}, got {val_type} ({value!r})"
        )
    return value


class Table:
    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        if not columns:
            raise SchemaError("Table must have at least one column")
        seen_names: set[str] = set()
        col_index_map: dict[str, int] = {}
        for idx, col in enumerate(columns):
            if col.type not in VALID_TYPES:
                raise SchemaError(f"Invalid column type {col.type!r} for {col.name!r}")
            if col.name in seen_names:
                raise SchemaError(f"Duplicate column name: {col.name!r}")
            seen_names.add(col.name)
            col_index_map[col.name] = idx

        validated_rows: list[list[object]] = []
        num_cols = len(columns)
        for row in rows:
            if len(row) != num_cols:
                raise SchemaError(
                    f"Row length {len(row)} does not match column count {num_cols}"
                )
            new_row = [
                _validate_cell(cell, columns[i].type, columns[i].name)
                for i, cell in enumerate(row)
            ]
            validated_rows.append(new_row)

        self._name: str = name
        self._columns: list[Column] = list(columns)
        self._rows: list[list[object]] = validated_rows
        self._col_index: dict[str, int] = col_index_map

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
        if name not in self._col_index:
            raise SchemaError(f"Unknown column {name!r} in table {self._name!r}")
        return self._col_index[name]

"""Schema definitions for columns and tables."""

from __future__ import annotations

import dataclasses
from microdb.errors import SchemaError

VALID_TYPES = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


@dataclasses.dataclass(frozen=True)
class Column:
    """Column metadata."""

    name: str
    type: str


def _validate_columns(columns: list[Column]) -> dict[str, int]:
    if not columns:
        raise SchemaError("Table must have at least one column")
    col_map: dict[str, int] = {}
    for idx, col in enumerate(columns):
        if col.name in col_map:
            raise SchemaError(f"Duplicate column name: '{col.name}'")
        if col.type not in VALID_TYPES:
            raise SchemaError(f"Invalid column type: '{col.type}'")
        col_map[col.name] = idx
    return col_map


def _validate_cell(cell: object, expected_type: str, col_name: str) -> object:
    if cell is None:
        return None
    if expected_type == "BOOL":
        if isinstance(cell, bool):
            return cell
        raise SchemaError(f"Column '{col_name}' of type BOOL got {type(cell).__name__}")
    if expected_type == "INT":
        if isinstance(cell, int) and not isinstance(cell, bool):
            return cell
        raise SchemaError(f"Column '{col_name}' of type INT got {type(cell).__name__}")
    if expected_type == "FLOAT":
        if isinstance(cell, (int, float)) and not isinstance(cell, bool):
            return float(cell)
        raise SchemaError(f"Column '{col_name}' of type FLOAT got {type(cell).__name__}")
    if expected_type == "TEXT":
        if isinstance(cell, str):
            return cell
        raise SchemaError(f"Column '{col_name}' of type TEXT got {type(cell).__name__}")
    raise SchemaError(f"Unexpected column type: {expected_type}")


def _validate_rows(columns: list[Column], rows: list[list[object]]) -> list[list[object]]:
    col_count = len(columns)
    validated_rows: list[list[object]] = []
    for row_idx, row in enumerate(rows):
        if len(row) != col_count:
            raise SchemaError(
                f"Row {row_idx} length {len(row)} does not match column count {col_count}"
            )
        new_row = [
            _validate_cell(cell, col.type, col.name)
            for cell, col in zip(row, columns)
        ]
        validated_rows.append(new_row)
    return validated_rows


class Table:
    """Relational table with schema and validated rows."""

    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        self._name: str = name
        self._columns: list[Column] = list(columns)
        self._col_map: dict[str, int] = _validate_columns(self._columns)
        self._rows: list[list[object]] = _validate_rows(self._columns, rows)

    @property
    def name(self) -> str:
        return self._name

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    @property
    def rows(self) -> list[list[object]]:
        return list(self._rows)

    def column_index(self, name: str) -> int:
        """Return 0-based column index or raise SchemaError."""
        if name not in self._col_map:
            raise SchemaError(f"Unknown column: '{name}' in table '{self._name}'")
        return self._col_map[name]

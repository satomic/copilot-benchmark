import dataclasses
from .errors import SchemaError
from .value import type_of


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        if not columns:
            raise SchemaError("Table must have at least one column")
        if len(set(c.name for c in columns)) != len(columns):
            raise SchemaError("Column names must be unique")
        for col in columns:
            if col.type not in ("INT", "FLOAT", "TEXT", "BOOL"):
                raise SchemaError(f"Invalid type: {col.type}")
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError(
                    f"Row length {len(row)} does not match column count {len(columns)}"
                )
            for i, cell in enumerate(row):
                if cell is None:
                    continue
                col_type = columns[i].type
                val_type = type_of(cell)
                if col_type == "INT":
                    if not isinstance(cell, int) or isinstance(cell, bool):
                        raise SchemaError(
                            f"Column {columns[i].name} expects INT, got {val_type}"
                        )
                elif col_type == "FLOAT":
                    if isinstance(cell, bool) or not isinstance(cell, (int, float)):
                        raise SchemaError(
                            f"Column {columns[i].name} expects FLOAT, got {val_type}"
                        )
                    if isinstance(cell, int) and not isinstance(cell, bool):
                        row[i] = float(cell)
                elif col_type == "TEXT":
                    if not isinstance(cell, str):
                        raise SchemaError(
                            f"Column {columns[i].name} expects TEXT, got {val_type}"
                        )
                elif col_type == "BOOL":
                    if not isinstance(cell, bool):
                        raise SchemaError(
                            f"Column {columns[i].name} expects BOOL, got {val_type}"
                        )
        self._name = name
        self._columns = columns
        self._rows = rows

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
        raise SchemaError(f"Column '{name}' not found in table '{self._name}'")

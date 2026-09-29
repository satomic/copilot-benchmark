from dataclasses import dataclass

from .errors import SchemaError
from .value import type_of


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(
        self, name: str, columns: list[Column], rows: list[list[object]]
    ) -> None:
        self._name = name
        self._columns = list(columns)
        self._rows = [list(row) for row in rows]
        self._validate()

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
        raise SchemaError(f"unknown column: {name}")

    def _validate(self) -> None:
        if not self._columns:
            raise SchemaError("table must have at least one column")
        names = [column.name for column in self._columns]
        if len(names) != len(set(names)):
            raise SchemaError("duplicate column name")
        for column in self._columns:
            if column.type not in {"INT", "FLOAT", "TEXT", "BOOL"}:
                raise SchemaError(f"invalid column type: {column.type}")
        for row_index, row in enumerate(self._rows):
            if len(row) != len(self._columns):
                raise SchemaError(f"row {row_index} has the wrong length")
            self._validate_row(row_index, row)

    def _validate_row(self, row_index: int, row: list[object]) -> None:
        for index, (column, value) in enumerate(zip(self._columns, row)):
            if value is None:
                continue
            actual = type_of(value)
            if column.type == "FLOAT" and actual == "INT":
                row[index] = float(value)  # type: ignore[arg-type]
            elif actual != column.type:
                raise SchemaError(
                    f"row {row_index} column {column.name} expects "
                    f"{column.type}, got {actual}"
                )

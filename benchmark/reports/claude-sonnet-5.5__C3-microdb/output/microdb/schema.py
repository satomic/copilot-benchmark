"""Schema layer: Column and Table."""

import dataclasses

from .errors import SchemaError

COLUMN_TYPES = ("INT", "FLOAT", "TEXT", "BOOL")


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    type: str


def _coerce(value: object, ctype: str, where: str) -> object:
    if value is None:
        return None
    if ctype == "BOOL":
        ok = isinstance(value, bool)
    elif ctype == "INT":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif ctype == "FLOAT":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        if ok:
            return float(value)  # type: ignore[arg-type]
    else:
        ok = isinstance(value, str)
    if not ok:
        raise SchemaError(f"{where}: {value!r} is not a valid {ctype}")
    return value


class Table:
    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("a table needs at least one column")
        seen: set[str] = set()
        for col in columns:
            if col.name in seen:
                raise SchemaError(f"duplicate column name {col.name!r}")
            seen.add(col.name)
            if col.type not in COLUMN_TYPES:
                raise SchemaError(f"unknown column type {col.type!r}")
        self._name = name
        self._columns = list(columns)
        self._rows = [self._check_row(i, r) for i, r in enumerate(rows)]

    def _check_row(self, index: int, row: list[object]) -> list[object]:
        if len(row) != len(self._columns):
            raise SchemaError(
                f"row {index} has {len(row)} cells, expected {len(self._columns)}"
            )
        return [
            _coerce(v, c.type, f"row {index}, column {c.name!r}")
            for v, c in zip(row, self._columns)
        ]

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
        raise SchemaError(f"unknown column {name!r} in table {self._name!r}")

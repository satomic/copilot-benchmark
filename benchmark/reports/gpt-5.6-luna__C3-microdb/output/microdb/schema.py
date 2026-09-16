from dataclasses import dataclass
from .errors import SchemaError, UnknownColumnError


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class Table:
    def __init__(self, name: str, columns: list[Column], rows: list[list[object]]) -> None:
        if not columns:
            raise SchemaError("table needs columns")
        names = [c.name for c in columns]
        if len(names) != len(set(names)) or any(c.type not in {"INT", "FLOAT", "TEXT", "BOOL"} for c in columns):
            raise SchemaError("invalid schema")
        checked: list[list[object]] = []
        for row in rows:
            if len(row) != len(columns):
                raise SchemaError("row length mismatch")
            checked.append([self._cell(v, c.type) for v, c in zip(row, columns)])
        self._name, self._columns, self._rows = name, list(columns), checked

    @staticmethod
    def _cell(v: object, typ: str) -> object:
        if v is None:
            return None
        if typ == "INT" and (not isinstance(v, int) or isinstance(v, bool)):
            raise SchemaError("invalid INT cell")
        if typ == "FLOAT":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise SchemaError("invalid FLOAT cell")
            return float(v)
        if typ == "TEXT" and not isinstance(v, str):
            raise SchemaError("invalid TEXT cell")
        if typ == "BOOL" and not isinstance(v, bool):
            raise SchemaError("invalid BOOL cell")
        return v

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
        try:
            return [c.name for c in self._columns].index(name)
        except ValueError as exc:
            raise UnknownColumnError(name) from exc

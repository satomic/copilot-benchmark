from __future__ import annotations

import csv
import os
import sys

from .errors import MicroDBError
from .executor import execute
from .schema import Column, Table


def _load_table(name: str, path: str) -> Table:
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise MicroDBError(f"missing header in {path}")
        cols: list[Column] = []
        for raw in header:
            if ":" not in raw:
                raise MicroDBError(f"malformed header in {path}")
            cell_name, cell_type = raw.split(":", 1)
            if not cell_name or not cell_type:
                raise MicroDBError(f"malformed header in {path}")
            cols.append(Column(cell_name.strip(), cell_type.strip().upper()))
        rows: list[list[object]] = []
        for row in reader:
            values: list[object] = []
            for idx, field in enumerate(row):
                values.append(_coerce_csv_field(cols[idx].type, field))
            rows.append(values)
        return Table(name, cols, rows)


def _coerce_csv_field(col_type: str, field: str) -> object:
    if field == "":
        return None
    if field == "''":
        return ""
    if col_type == "INT":
        return int(field)
    if col_type == "FLOAT":
        return float(field)
    if col_type == "BOOL":
        lowered = field.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        raise MicroDBError(f"invalid BOOL {field}")
    if col_type == "TEXT":
        return field
    raise MicroDBError(f"unsupported type {col_type}")


def _as_csv(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(value)
    return str(value)


def _write_csv_row(row: list[object]) -> str:
    cells: list[str] = []
    for value in row:
        text = _as_csv(value)
        if text == "":
            cells.append("")
            continue
        if any(ch in text for ch in [",", '"', "\n"]):
            text = text.replace('"', '""')
            text = f'"{text}"'
        cells.append(text)
    return ",".join(cells) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    tables: dict[str, Table] = {}
    query: str | None = None
    idx = 0
    while idx < len(args):
        token = args[idx]
        if token == "--table":
            idx += 1
            if idx >= len(args):
                return 2
            spec = args[idx]
            if "=" not in spec:
                return 2
            name, path = spec.split("=", 1)
            try:
                tables[name] = _load_table(name, path)
            except OSError:
                return 2
            except MicroDBError:
                return 2
            idx += 1
            continue
        if token.startswith("--"):
            return 2
        if query is not None:
            return 2
        query = token
        idx += 1
    if not tables or query is None:
        return 2
    try:
        result = execute(query, tables)
    except MicroDBError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    sys.stdout.write(_write_csv_row(result.columns))
    for row in result.rows:
        sys.stdout.write(_write_csv_row(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

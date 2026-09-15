"""CLI: python -m microdb --table NAME=PATH QUERY."""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from microdb.errors import MicroDBError
from microdb.executor import Result, execute
from microdb.schema import Column, Table

_TYPES = frozenset({"INT", "FLOAT", "TEXT", "BOOL"})


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    specs, query, err = _parse_argv(argv)
    if err is not None:
        print(err, file=sys.stderr)
        return 2
    try:
        tables = _load_specs(specs)
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        result = execute(query, tables)
    except MicroDBError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    sys.stdout.write(_format_csv(result))
    return 0


def _parse_argv(argv: list[str]) -> tuple[list[tuple[str, str]], str, str | None]:
    specs: list[tuple[str, str]] = []
    query: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            if i + 1 >= len(argv):
                return [], "", "missing --table value"
            spec = argv[i + 1]
            if "=" not in spec:
                return [], "", "expected NAME=PATH"
            name, path = spec.split("=", 1)
            if not name or not path:
                return [], "", "expected NAME=PATH"
            specs.append((name, path))
            i += 2
            continue
        if query is not None:
            return [], "", "unexpected argument"
        query = arg
        i += 1
    if not specs or query is None:
        return [], "", "usage: --table NAME=PATH QUERY"
    return specs, query, None


def _load_specs(specs: list[tuple[str, str]]) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for name, path in specs:
        tables[name] = _load_csv(name, path)
    return tables


def _load_csv(name: str, path: str) -> Table:
    text = Path(path).read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError(f"empty CSV: {path}")
    columns = _parse_header(rows[0])
    body: list[list[object]] = []
    for raw in rows[1:]:
        if not raw:
            raw = [""] * len(columns)
        if len(raw) != len(columns):
            raise ValueError(f"malformed row in {path}")
        body.append([_parse_cell(columns[i], raw[i]) for i in range(len(columns))])
    return Table(name, columns, body)


def _parse_header(fields: list[str]) -> list[Column]:
    cols: list[Column] = []
    for field in fields:
        if ":" not in field:
            raise ValueError("malformed header")
        name, typ = field.split(":", 1)
        name, typ = name.strip(), typ.strip().upper()
        if not name or typ not in _TYPES:
            raise ValueError("malformed header")
        cols.append(Column(name, typ))
    if not cols:
        raise ValueError("malformed header")
    return cols


def _parse_cell(col: Column, field: str) -> object:
    if field == "":
        return None
    if field == "''":
        field = ""
    if col.type == "INT":
        return int(field)
    if col.type == "FLOAT":
        return float(field)
    if col.type == "BOOL":
        low = field.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        raise ValueError(f"invalid BOOL {field!r}")
    return field


def _format_csv(result: Result) -> str:
    lines = [_format_row(result.columns)]
    for row in result.rows:
        lines.append(_format_row([_cell_text(v) for v in row]))
    return "".join(line + "\n" for line in lines)


def _format_row(fields: list[str]) -> str:
    return ",".join(_quote(f) for f in fields)


def _cell_text(v: object) -> str:
    if v is None:
        return ""
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)


def _quote(field: str) -> str:
    if any(ch in field for ch in ',"\n'):
        return '"' + field.replace('"', '""') + '"'
    return field


if __name__ == "__main__":
    sys.exit(main())

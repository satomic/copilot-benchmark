"""CLI: python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY

Exit codes: 0 success; 2 usage error (bad arguments, missing --table,
unreadable file, malformed header); 3 any MicroDBError (message on stderr).
Nothing is written to stdout on a failure path.
"""

from __future__ import annotations

import csv
import sys

from . import execute
from .errors import MicroDBError, SchemaError
from .executor import Result
from .schema import Column, Table

USAGE = "usage: python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY"
_TYPES = ("INT", "FLOAT", "TEXT", "BOOL")


class _UsageError(Exception):
    """Internal marker for exit-code-2 usage errors."""


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        specs, query = _parse_args(args)
        tables = {name: _load_csv(name, path) for name, path in specs}
        result = execute(query, tables)
    except _UsageError as exc:
        print(f"{exc}\n{USAGE}", file=sys.stderr)
        return 2
    except MicroDBError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    sys.stdout.write(_render(result))
    return 0


def _parse_args(args: list[str]) -> tuple[list[tuple[str, str]], str]:
    specs: list[tuple[str, str]] = []
    i = 0
    while i < len(args) and args[i] == "--table":
        if i + 1 >= len(args):
            raise _UsageError("missing value for --table")
        spec = args[i + 1]
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            raise _UsageError(f"bad --table spec {spec!r}")
        specs.append((name, path))
        i += 2
    rest = args[i:]
    if not specs:
        raise _UsageError("missing --table")
    if len(rest) != 1:
        raise _UsageError("expected exactly one QUERY argument")
    return specs, rest[0]


def _load_csv(name: str, path: str) -> Table:
    """Load a CSV file whose first line is a header of name:TYPE pairs."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            lines = [row for row in csv.reader(fh) if row]
    except OSError as exc:
        raise _UsageError(f"cannot read {path}: {exc}")
    if not lines:
        raise _UsageError(f"{path}: missing header line")
    columns = [_header_cell(cell) for cell in lines[0]]
    rows: list[list[object]] = []
    for raw in lines[1:]:
        if len(raw) != len(columns):
            raise SchemaError(
                f"{name}: row has {len(raw)} fields, expected {len(columns)}")
        rows.append([_convert(col, field) for col, field in zip(columns, raw)])
    return Table(name, columns, rows)


def _header_cell(cell: str) -> Column:
    name, sep, typ = cell.partition(":")
    typ = typ.upper()
    if not sep or not name or typ not in _TYPES:
        raise _UsageError(f"malformed header cell {cell!r}")
    return Column(name=name, type=typ)


def _convert(col: Column, field: str) -> object:
    """Convert one CSV field; an empty field is NULL, '' is empty string."""
    if field == "":
        return None
    if col.type == "TEXT":
        return "" if field == "''" else field
    try:
        if col.type == "INT":
            return int(field)
        if col.type == "FLOAT":
            return float(field)
        lowered = field.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        raise ValueError(field)
    except ValueError:
        raise SchemaError(f"bad {col.type} value {field!r}")


def _render(result: Result) -> str:
    """Render a Result as CSV text with microdb's quoting rules."""
    lines = [_format_line(result.columns)]
    for row in result.rows:
        lines.append(_format_line([_cell(v) for v in row]))
    return "\n".join(lines) + "\n"


def _cell(v: object) -> str:
    if v is None:
        return ""  # NULL renders as an empty field
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)  # floats use str()


def _format_line(fields: list[str]) -> str:
    return ",".join(_quote(f) for f in fields)


def _quote(field: str) -> str:
    """Quote only fields containing a comma, double quote or newline."""
    if any(c in field for c in (",", '"', "\n", "\r")):
        return '"' + field.replace('"', '""') + '"'
    return field


if __name__ == "__main__":
    sys.exit(main())

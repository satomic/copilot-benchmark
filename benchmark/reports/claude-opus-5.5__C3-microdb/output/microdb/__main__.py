"""Command line interface: python -m microdb --table NAME=PATH QUERY."""

from __future__ import annotations

import re
import sys

from .errors import MicroDBError, SchemaError
from .executor import execute
from .schema import Column, Table
from .value import TYPE_NAMES

USAGE = "usage: python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INT = re.compile(r"[+-]?[0-9]+\Z")


class UsageError(Exception):
    """A problem with arguments or input files (exit code 2)."""


# ---------------------------------------------------------------- arguments


def _parse_table_spec(spec: str) -> tuple[str, str]:
    name, sep, path = spec.partition("=")
    if not sep or not _IDENT.match(name) or not path:
        raise UsageError(f"invalid --table value {spec!r}, expected NAME=PATH")
    return name, path


def parse_args(argv: list[str]) -> tuple[dict[str, str], str]:
    """Return ({table name: path}, query) or raise UsageError."""
    specs: dict[str, str] = {}
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            if i + 1 >= len(argv):
                raise UsageError("--table requires a NAME=PATH value")
            spec, i = argv[i + 1], i + 2
        elif arg.startswith("--table="):
            spec, i = arg[len("--table="):], i + 1
        elif arg.startswith("--"):
            raise UsageError(f"unknown option {arg!r}")
        else:
            positional.append(arg)
            i += 1
            continue
        name, path = _parse_table_spec(spec)
        if name in specs:
            raise UsageError(f"table {name!r} given more than once")
        specs[name] = path
    if not specs:
        raise UsageError("at least one --table is required")
    if len(positional) != 1:
        raise UsageError("exactly one QUERY argument is required")
    return specs, positional[0]


# ---------------------------------------------------------------- CSV input


def _end_field(record: list, buf: list[str], quoted: bool) -> None:
    record.append(("".join(buf), quoted))
    buf.clear()


def _read_quoted(text: str, i: int, buf: list[str]) -> int:
    """Read a quoted field starting after its opening quote; return next index."""
    while True:
        j = text.find('"', i)
        if j < 0:
            raise UsageError("unterminated quoted field in CSV input")
        buf.append(text[i:j])
        if text.startswith('""', j):
            buf.append('"')
            i = j + 2
            continue
        j += 1
        if j < len(text) and text[j] not in ",\r\n":
            raise UsageError("unexpected character after quoted CSV field")
        return j


def split_csv(text: str) -> list[list[tuple[str, bool]]]:
    """Split CSV text into records of (field text, was quoted) pairs."""
    records: list[list[tuple[str, bool]]] = []
    record: list[tuple[str, bool]] = []
    buf: list[str] = []
    quoted, started, i = False, False, 0
    while i < len(text):
        c = text[i]
        started = True
        if c == '"' and not buf and not quoted:
            quoted = True
            i = _read_quoted(text, i + 1, buf)
            continue
        if c == ",":
            _end_field(record, buf, quoted)
            quoted = False
        elif c in "\r\n":
            _end_field(record, buf, quoted)
            records.append(record)
            record, quoted, started = [], False, False
            if c == "\r" and text.startswith("\n", i + 1):
                i += 1
        else:
            buf.append(c)
        i += 1
    if started:
        _end_field(record, buf, quoted)
        records.append(record)
    return records


def _parse_header(fields: list[tuple[str, bool]]) -> list[Column]:
    columns: list[Column] = []
    for text, _ in fields:
        name, sep, type_name = text.strip().partition(":")
        type_name = type_name.strip().upper()
        if not sep or not _IDENT.match(name.strip()) or type_name not in TYPE_NAMES:
            raise UsageError(f"malformed header field {text!r}, expected name:TYPE")
        columns.append(Column(name.strip(), type_name))
    if len({c.name for c in columns}) != len(columns):
        raise UsageError("malformed header: duplicate column name")
    return columns


def _convert(column: Column, text: str, quoted: bool) -> object:
    """Convert one CSV cell. Unparseable cells raise SchemaError (exit code 3)."""
    if text == "" and not quoted:
        return None
    if column.type == "TEXT":
        # The spec's "''" is taken literally (two apostrophes); a CSV-quoted
        # empty field ("") is also the empty string.
        return "" if text == "''" and not quoted else text
    raw = text.strip()
    try:
        if column.type == "INT" and _INT.match(raw):
            return int(raw)
        if column.type == "FLOAT":
            return int(raw) if _INT.match(raw) else float(raw)
        if column.type == "BOOL" and raw.lower() in ("true", "false"):
            return raw.lower() == "true"
    except ValueError:
        pass
    raise SchemaError(f"invalid {column.type} value {text!r} in column {column.name!r}")


def load_table(name: str, path: str) -> Table:
    """Load a typed CSV file as a Table."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"cannot read {path!r}: {exc}") from None
    records = split_csv(text)
    if not records:
        raise UsageError(f"{path!r} has no header line")
    columns = _parse_header(records[0])
    rows = []
    for number, record in enumerate(records[1:], start=2):
        if len(record) != len(columns):
            raise SchemaError(
                f"{path}: record {number} has {len(record)} fields, expected {len(columns)}"
            )
        rows.append([_convert(c, t, q) for c, (t, q) in zip(columns, record)])
    return Table(name, columns, rows)


# ---------------------------------------------------------------- CSV output


def format_value(value: object) -> str:
    """Render one output cell: NULL is empty, booleans are lowercase."""
    if value is None:
        text = ""
    elif isinstance(value, bool):
        text = "true" if value else "false"
    else:
        text = str(value)
    if any(ch in text for ch in ',"\n\r'):
        text = '"' + text.replace('"', '""') + '"'
    return text


def format_result(columns: list[str], rows: list[list[object]]) -> str:
    """Render a whole result as CSV text with a header line."""
    lines = [",".join(format_value(c) for c in columns)]
    lines.extend(",".join(format_value(v) for v in row) for row in rows)
    return "".join(line + "\n" for line in lines)


def _write_stdout(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(text.encode("utf-8"))  # bytes avoid "\r\n" translation on Windows
    buffer.flush()


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        specs, query = parse_args(args)
        tables = {name: load_table(name, path) for name, path in specs.items()}
        result = execute(query, tables)
        output = format_result(result.columns, result.rows)
    except UsageError as exc:
        print(f"error: {exc}\n{USAGE}", file=sys.stderr)
        return 2
    except MicroDBError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    _write_stdout(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

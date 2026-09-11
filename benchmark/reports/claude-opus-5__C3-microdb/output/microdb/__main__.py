"""Command line interface: ``python -m microdb --table NAME=PATH QUERY``."""

from __future__ import annotations

import sys

from .errors import MicroDBError
from .executor import Result, execute
from .schema import Column, Table


class UsageError(Exception):
    """Raised for bad arguments or unusable input files (exit code 2)."""


def parse_args(argv: list[str]) -> tuple[dict[str, str], str]:
    """Split ``argv`` into table bindings and the query text."""
    sources: dict[str, str] = {}
    positional: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--table":
            index += 1
            if index >= len(argv):
                raise UsageError("--table requires NAME=PATH")
            _add_source(sources, argv[index])
        elif arg.startswith("--table="):
            _add_source(sources, arg[len("--table=") :])
        elif arg.startswith("-") and arg != "-":
            raise UsageError(f"unknown option {arg!r}")
        else:
            positional.append(arg)
        index += 1
    if not sources:
        raise UsageError("at least one --table NAME=PATH is required")
    if len(positional) != 1:
        raise UsageError("exactly one QUERY argument is required")
    return sources, positional[0]


def _add_source(sources: dict[str, str], spec: str) -> None:
    name, sep, path = spec.partition("=")
    if not sep or not name or not path:
        raise UsageError(f"invalid --table value {spec!r}, expected NAME=PATH")
    sources[name] = path


def split_csv(text: str) -> list[list[tuple[str, bool]]]:
    """Parse CSV text into rows of (raw text, was quoted) pairs."""
    rows: list[list[tuple[str, bool]]] = []
    field: list[str] = []
    quoted = False
    row: list[tuple[str, bool]] = []
    i, n, in_quotes = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"' and i + 1 < n and text[i + 1] == '"':
                field.append('"')
                i += 1
            elif ch == '"':
                in_quotes = False
            else:
                field.append(ch)
        elif ch == '"':
            in_quotes, quoted = True, True
        elif ch == ",":
            row.append(("".join(field), quoted))
            field, quoted = [], False
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append(("".join(field), quoted))
            rows.append(row)
            row, field, quoted = [], [], False
        else:
            field.append(ch)
        i += 1
    if field or quoted or row:
        row.append(("".join(field), quoted))
        rows.append(row)
    return rows


def parse_header(cells: list[tuple[str, bool]]) -> list[Column]:
    """Turn a header row of ``name:TYPE`` pairs into columns."""
    columns: list[Column] = []
    for raw, _ in cells:
        name, sep, type_name = raw.strip().partition(":")
        if not sep or not name:
            raise UsageError(f"malformed header field {raw!r}, expected name:TYPE")
        columns.append(Column(name, type_name.strip().upper()))
    return columns


def convert(raw: str, quoted: bool, column: Column) -> object:
    """Convert one CSV field to a microdb value according to its column type.

    A cell that does not parse as its declared type is treated as a usage error
    (exit code 2), like a malformed header, rather than as a query error.
    """
    if raw == "" and not quoted:
        # An empty, unquoted field is NULL; a quoted empty field is the empty string.
        return None
    if column.type == "TEXT":
        # A field written as two quote characters denotes the empty string.
        return "" if (raw == "''" and not quoted) else raw
    text = raw.strip()
    try:
        if column.type == "INT":
            return int(text)
        if column.type == "FLOAT":
            return float(text)
    except ValueError as exc:
        raise UsageError(f"bad {column.type} value {raw!r} for column {column.name!r}") from exc
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    raise UsageError(f"bad BOOL value {raw!r} for column {column.name!r}")


def load_table(name: str, path: str) -> Table:
    """Read a CSV file into a :class:`Table`."""
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    except OSError as exc:
        raise UsageError(f"cannot read {path!r}: {exc}") from exc
    rows = split_csv(text)
    if not rows:
        raise UsageError(f"{path!r} has no header line")
    columns = parse_header(rows[0])
    data: list[list[object]] = []
    for cells in rows[1:]:
        if len(cells) != len(columns):
            raise UsageError(f"{path!r}: row has {len(cells)} fields, expected {len(columns)}")
        data.append([convert(raw, q, col) for (raw, q), col in zip(cells, columns)])
    try:
        return Table(name, columns, data)
    except MicroDBError as exc:
        raise UsageError(f"{path!r}: {exc}") from exc


def render_value(v: object) -> str:
    """Render one value as an unquoted CSV field."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def quote_field(field: str) -> str:
    """Quote a field only when it contains a comma, a double quote or a newline."""
    if any(ch in field for ch in (",", '"', "\n", "\r")):
        return '"' + field.replace('"', '""') + '"'
    return field


def render_result(result: Result) -> str:
    """Render a whole result as CSV text."""
    lines = [",".join(quote_field(name) for name in result.columns)]
    for row in result.rows:
        lines.append(",".join(quote_field(render_value(v)) for v in row))
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        sources, query = parse_args(args)
        tables = {name: load_table(name, path) for name, path in sources.items()}
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        text = render_result(execute(query, tables))
    except MicroDBError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    _write(text)
    return 0


def _write(text: str) -> None:
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(newline="\n")
        except (ValueError, OSError):
            pass
    stream.write(text)


if __name__ == "__main__":
    sys.exit(main())

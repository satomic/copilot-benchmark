"""Command line interface: python -m microdb --table NAME=PATH QUERY"""

import csv
import sys

from .errors import MicroDBError
from .executor import Result, execute
from .schema import COLUMN_TYPES, Column, Table


class _UsageError(Exception):
    pass


def _parse_args(argv: list[str]) -> tuple[list[tuple[str, str]], str]:
    specs: list[tuple[str, str]] = []
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            i += 1
            if i >= len(argv):
                raise _UsageError("--table needs NAME=PATH")
            name, sep, path = argv[i].partition("=")
            if not sep or not name or not path:
                raise _UsageError(f"bad --table value {argv[i]!r}, expected NAME=PATH")
            specs.append((name, path))
        elif arg.startswith("--"):
            raise _UsageError(f"unknown option {arg!r}")
        else:
            positional.append(arg)
        i += 1
    if not specs:
        raise _UsageError("at least one --table is required")
    if len(positional) != 1:
        raise _UsageError("exactly one QUERY argument is required")
    return specs, positional[0]


def _parse_header(fields: list[str]) -> list[Column]:
    columns = []
    for field in fields:
        name, sep, ctype = field.rpartition(":")
        ctype = ctype.strip().upper()
        if not sep or not name or ctype not in COLUMN_TYPES:
            raise _UsageError(f"malformed header field {field!r}, expected name:TYPE")
        columns.append(Column(name, ctype))
    return columns


def _convert_cell(field: str, ctype: str) -> object:
    # An empty field is NULL; two single quotes ('') mean the empty string.
    if field == "":
        return None
    try:
        if ctype == "TEXT":
            return "" if field == "''" else field
        if ctype == "INT":
            return int(field)
        if ctype == "FLOAT":
            return float(field)
        if field.lower() in ("true", "false"):
            return field.lower() == "true"
    except ValueError:
        pass
    raise _UsageError(f"invalid {ctype} value {field!r}")


def _read_csv(path: str) -> list[list[str]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            return list(csv.reader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise _UsageError(f"cannot read {path!r}: {exc}") from exc


def _load_table(name: str, path: str) -> Table:
    lines = _read_csv(path)
    if not lines:
        raise _UsageError(f"{path!r} is empty, a header line is required")
    columns = _parse_header(lines[0])
    rows: list[list[object]] = []
    for raw in lines[1:]:
        if not raw:
            if len(columns) != 1:
                continue
            raw = [""]  # a blank line is one NULL cell in a one-column table
        if len(raw) != len(columns):
            rows.append(list(raw))  # Table reports the length mismatch
        else:
            rows.append([_convert_cell(f, c.type) for f, c in zip(raw, columns)])
    return Table(name, columns, rows)


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(ch in text for ch in ',"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def render(result: Result) -> str:
    lines = [",".join(_format_value(c) for c in result.columns)]
    lines += [",".join(_format_value(v) for v in row) for row in result.rows]
    return "".join(line + "\n" for line in lines)


def _write_stdout(text: str) -> None:
    out = sys.stdout
    try:
        out.reconfigure(newline="\n", encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass
    out.write(text)
    out.flush()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        specs, query = _parse_args(args)
        tables = {name: _load_table(name, path) for name, path in specs}
        output = render(execute(query, tables))
    except _UsageError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    except MicroDBError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    _write_stdout(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Command-line entry point: python -m microdb --table NAME=PATH QUERY."""

from __future__ import annotations

import re
import sys

from .errors import MicroDBError, SchemaError
from .executor import Result, execute
from .schema import TYPE_NAMES, Column, Table

USAGE = "usage: python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY"
_INT_RE = re.compile(r"[+-]?[0-9]+")
_FLOAT_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class _Usage(Exception):
    """Bad arguments or unreadable/malformed input; exit code 2."""


def _split_fields(line: str) -> list[tuple[str, bool]]:
    """Split one CSV line into (text, was_quoted) pairs.

    Inside quotes, a doubled quote stands for one quote character.
    """
    fields: list[tuple[str, bool]] = []
    i, n = 0, len(line)
    while True:
        if i < n and line[i] == '"':
            text, i = _quoted_field(line, i)
            fields.append((text, True))
            if i < n and line[i] != ",":
                raise _Usage(f"unexpected text after quoted field: {line!r}")
        else:
            j = line.find(",", i)
            j = n if j < 0 else j
            fields.append((line[i:j], False))
            i = j
        if i >= n:
            return fields
        i += 1


def _quoted_field(line: str, start: int) -> tuple[str, int]:
    chars: list[str] = []
    j = start + 1
    while j < len(line):
        if line[j] == '"':
            if j + 1 < len(line) and line[j + 1] == '"':
                chars.append('"')
                j += 2
                continue
            return "".join(chars), j + 1
        chars.append(line[j])
        j += 1
    raise _Usage(f"unterminated quoted field: {line!r}")


def _parse_header(line: str) -> list[Column]:
    columns = []
    for text, _ in _split_fields(line):
        name, sep, type_name = text.rpartition(":")
        if not sep or not name or type_name not in TYPE_NAMES:
            raise _Usage(f"malformed header field {text!r}; expected name:TYPE")
        columns.append(Column(name, type_name))
    return columns


def _cell(text: str, quoted: bool, column: Column) -> object:
    """Convert one CSV field. An unquoted empty field is NULL."""
    if not quoted and text == "":
        return None
    if column.type == "TEXT":
        return text
    if quoted and text == "":
        raise SchemaError(f"empty string is not a valid {column.type} for column {column.name!r}")
    if column.type == "BOOL":
        if text.lower() not in ("true", "false"):
            raise SchemaError(f"invalid BOOL {text!r} for column {column.name!r}")
        return text.lower() == "true"
    if column.type == "INT":
        if not _INT_RE.fullmatch(text):
            raise SchemaError(f"invalid INT {text!r} for column {column.name!r}")
        return int(text)
    if not _FLOAT_RE.fullmatch(text):
        raise SchemaError(f"invalid FLOAT {text!r} for column {column.name!r}")
    return float(text)


def _load_table(name: str, path: str) -> Table:
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            text = handle.read()
    except OSError as exc:
        raise _Usage(f"cannot read {path!r}: {exc.strerror}") from exc
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise _Usage(f"{path!r} has no header line")
    columns = _parse_header(lines[0])
    rows: list[list[object]] = []
    for raw in lines[1:]:
        if raw == "" and len(columns) > 1:
            continue
        fields = _split_fields(raw)
        if len(fields) != len(columns):
            raise SchemaError(f"row {raw!r} has {len(fields)} fields, expected {len(columns)}")
        rows.append([_cell(t, q, c) for (t, q), c in zip(fields, columns)])
    return Table(name, columns, rows)


def _parse_args(argv: list[str]) -> tuple[list[tuple[str, str]], str]:
    specs: list[tuple[str, str]] = []
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table" or arg.startswith("--table="):
            if arg == "--table":
                i += 1
                if i >= len(argv):
                    raise _Usage("--table needs a NAME=PATH value")
                value = argv[i]
            else:
                value = arg[len("--table="):]
            name, sep, path = value.partition("=")
            if not sep or not name or not path:
                raise _Usage(f"--table expects NAME=PATH, got {value!r}")
            specs.append((name, path))
        elif arg.startswith("--"):
            raise _Usage(f"unknown option {arg!r}")
        else:
            positional.append(arg)
        i += 1
    if not specs:
        raise _Usage("missing --table")
    if len(positional) != 1:
        raise _Usage("exactly one QUERY argument is required")
    names = [name for name, _ in specs]
    if len(set(names)) != len(names):
        raise _Usage("duplicate table name")
    return specs, positional[0]


def _quote(text: str) -> str:
    if any(c in text for c in ',"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def _render_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return _quote(str(value))


def _render(result: Result) -> str:
    lines = [",".join(_quote(name) for name in result.columns)]
    lines += [",".join(_render_value(v) for v in row) for row in result.rows]
    return "".join(line + "\n" for line in lines)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its exit code."""
    args = sys.argv[1:] if argv is None else list(argv)
    try:
        specs, query = _parse_args(args)
        tables = {name: _load_table(name, path) for name, path in specs}
        result = execute(query, tables)
    except _Usage as exc:
        sys.stderr.write(f"error: {exc}\n{USAGE}\n")
        return 2
    except MicroDBError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 3
    sys.stdout.buffer.write(_render(result).encode("utf-8"))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

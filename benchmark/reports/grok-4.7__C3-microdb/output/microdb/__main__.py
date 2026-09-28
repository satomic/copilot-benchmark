"""CLI: python -m microdb --table NAME=PATH QUERY."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from microdb.errors import MicroDBError
from microdb.executor import Result, execute
from microdb.schema import Column, Table

# Choice: an unquoted field of '' is the empty string. A quoted "" is also empty.
# Choice: whitespace-only unquoted fields are NULL. Header types are case-insensitive.


class _UsageError(Exception):
    """Bad arguments or an unreadable / malformed CSV. Exit code 2."""


@dataclass
class _Field:
    text: str
    quoted: bool


def main(argv: list[str] | None = None) -> int:
    """Run a query. Return 0, 2 (usage) or 3 (MicroDBError)."""
    if argv is None:
        argv = sys.argv[1:]
    try:
        specs, query = _parse_args(argv)
        tables = _load_tables(specs)
        result = execute(query, tables)
    except _UsageError as exc:
        _fail(str(exc))
        return 2
    except MicroDBError as exc:
        _fail(str(exc))
        return 3
    _write_result(result)
    return 0


def _fail(message: str) -> None:
    sys.stderr.write(message + "\n")


def _parse_args(argv: list[str]) -> tuple[list[tuple[str, str]], str]:
    tables: list[tuple[str, str]] = []
    query: list[str] = []
    index = 0
    while index < len(argv):
        index = _one_arg(argv, index, tables, query)
    if not tables:
        raise _UsageError("missing --table")
    if not query:
        raise _UsageError("missing query")
    return tables, " ".join(query)


def _one_arg(argv: list[str], index: int, tables: list[tuple[str, str]], query: list[str]) -> int:
    arg = argv[index]
    if arg == "--table":
        if index + 1 >= len(argv):
            raise _UsageError("missing --table value")
        tables.append(_split_table(argv[index + 1]))
        return index + 2
    if arg.startswith("--table="):
        tables.append(_split_table(arg[len("--table="):]))
        return index + 1
    if arg.startswith("--"):
        raise _UsageError(f"unknown argument {arg}")
    query.append(arg)
    return index + 1


def _split_table(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise _UsageError("expected NAME=PATH")
    name, path = spec.split("=", 1)
    if not name or not path:
        raise _UsageError("expected NAME=PATH")
    return name, path


def _load_tables(specs: list[tuple[str, str]]) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    for name, path in specs:
        if name in tables:
            raise _UsageError(f"duplicate table {name}")
        tables[name] = _load_csv(name, path)
    return tables


def _load_csv(name: str, path: str) -> Table:
    text = _read_text(path)
    if text.startswith("\ufeff"):
        text = text[1:]
    rows = _Csv(text).parse()
    if not rows:
        raise _UsageError("malformed header")
    header = _header(rows[0])
    columns = [Column(col_name, col_type) for col_name, col_type in header]
    data = [_data_row(header, row) for row in rows[1:]]
    return Table(name, columns, data)


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise _UsageError(f"unreadable file: {path}") from exc


def _header(fields: list[_Field]) -> list[tuple[str, str]]:
    columns: list[tuple[str, str]] = []
    seen: set[str] = set()
    for field in fields:
        columns.append(_header_field(field.text.strip(), seen))
    if not columns:
        raise _UsageError("malformed header")
    return columns


def _header_field(text: str, seen: set[str]) -> tuple[str, str]:
    if ":" not in text:
        raise _UsageError("malformed header")
    name, typ = text.split(":", 1)
    name, typ = name.strip(), typ.strip().upper()
    if not name or typ not in {"INT", "FLOAT", "TEXT", "BOOL"} or name in seen:
        raise _UsageError("malformed header")
    seen.add(name)
    return name, typ


def _data_row(header: list[tuple[str, str]], fields: list[_Field]) -> list[object]:
    if len(fields) != len(header):
        raise _UsageError("malformed row")
    return [_cell(field, typ) for field, (_, typ) in zip(fields, header)]


def _cell(field: _Field, typ: str) -> object:
    if not field.quoted and field.text.strip() == "":
        return None
    text = field.text if field.quoted else field.text.strip()
    if typ == "TEXT":
        return "" if not field.quoted and text == "''" else text
    if typ == "BOOL":
        return _bool_cell(text)
    if typ == "INT":
        return _int_cell(text)
    return _float_cell(text)


def _bool_cell(text: str) -> bool:
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    raise _UsageError("malformed BOOL value")


def _int_cell(text: str) -> int:
    body = text[1:] if text[:1] in "+-" else text
    if not _is_int_text(body):
        raise _UsageError("malformed INT value")
    return int(text, 10)


def _is_int_text(text: str) -> bool:
    return bool(text) and all("0" <= ch <= "9" for ch in text)


def _float_cell(text: str) -> float:
    try:
        if text.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
            raise ValueError
        return float(text)
    except ValueError as exc:
        raise _UsageError("malformed FLOAT value") from exc


def _write_result(result: Result) -> None:
    lines = [_join([_quote(name) for name in result.columns])]
    for row in result.rows:
        lines.append(_join([_quote(_format_value(value)) for value in row]))
    _emit("\n".join(lines) + "\n")


def _join(fields: list[str]) -> str:
    return ",".join(fields)


def _format_value(value: object) -> str:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    return str(value)


def _quote(text: str) -> str:
    if "," in text or '"' in text or "\n" in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def _emit(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        return
    sys.stdout.write(text)


class _Csv:
    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.i = 0
        self.rows: list[list[_Field]] = []
        self.row: list[_Field] = []
        self.buf: list[str] = []
        self.quoted = False
        self.in_quotes = False
        self.started = False

    def parse(self) -> list[list[_Field]]:
        while self.i < self.n:
            self._one()
        self._finish()
        return self.rows

    def _one(self) -> None:
        ch = self.text[self.i]
        if self.in_quotes:
            self._quoted(ch)
            return
        if ch == '"' and not self.started:
            self._start_quote()
            return
        if ch == ",":
            self._flush()
            self.i += 1
            return
        if ch == "\n":
            self._end_row()
            return
        if ch == "\r":
            self.i += 1
            return
        self.buf.append(ch)
        self.started = True
        self.i += 1

    def _quoted(self, ch: str) -> None:
        if ch != '"':
            self.buf.append(ch)
            self.i += 1
            return
        if self.i + 1 < self.n and self.text[self.i + 1] == '"':
            self.buf.append('"')
            self.i += 2
            return
        self.in_quotes = False
        self.i += 1

    def _start_quote(self) -> None:
        self.in_quotes = True
        self.quoted = True
        self.started = True
        self.i += 1

    def _end_row(self) -> None:
        self._flush()
        self.rows.append(self.row)
        self.row = []
        self.i += 1

    def _flush(self) -> None:
        self.row.append(_Field("".join(self.buf), self.quoted))
        self.buf = []
        self.quoted = False
        self.started = False

    def _finish(self) -> None:
        if self.in_quotes:
            raise _UsageError("unterminated quote in CSV")
        if self.started or self.buf or self.row:
            self._flush()
            self.rows.append(self.row)


if __name__ == "__main__":
    sys.exit(main())

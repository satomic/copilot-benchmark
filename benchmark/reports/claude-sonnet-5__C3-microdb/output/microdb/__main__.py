"""CLI: python -m microdb --table NAME=PATH [--table NAME=PATH] QUERY."""

from __future__ import annotations

import sys

from microdb import Column, MicroDBError, Table, execute


def _parse_csv_records(text: str) -> list:
    """Parse CSV text into rows of (field_text, was_quoted) tuples."""
    rows: list = []
    row: list = []
    field_chars: list = []
    was_quoted = False
    in_quotes = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field_chars.append('"')
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            field_chars.append(ch)
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            was_quoted = True
            i += 1
            continue
        if ch == ',':
            row.append(("".join(field_chars), was_quoted))
            field_chars, was_quoted = [], False
            i += 1
            continue
        if ch == '\r':
            i += 1
            continue
        if ch == '\n':
            row.append(("".join(field_chars), was_quoted))
            rows.append(row)
            row, field_chars, was_quoted = [], [], False
            i += 1
            continue
        field_chars.append(ch)
        i += 1
    if field_chars or row:
        row.append(("".join(field_chars), was_quoted))
        rows.append(row)
    return rows


def _convert_field(text: str, quoted: bool, col_type: str) -> object:
    if text == "" and not quoted:
        return None
    if col_type == "INT":
        return int(text)
    if col_type == "FLOAT":
        return float(text)
    if col_type == "BOOL":
        low = text.strip().lower()
        if low not in ("true", "false"):
            raise ValueError(f"invalid BOOL value: {text!r}")
        return low == "true"
    return text


def _parse_header(header_fields: list) -> list:
    columns = []
    for text, _quoted in header_fields:
        if ":" not in text:
            raise ValueError(f"malformed header field: {text!r}")
        name, ctype = text.split(":", 1)
        columns.append(Column(name, ctype.strip().upper()))
    return columns


def _load_table(name: str, path: str) -> Table:
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    records = _parse_csv_records(text)
    if not records:
        raise ValueError("empty CSV file")
    columns = _parse_header(records[0])
    data_rows = []
    for rec in records[1:]:
        if len(rec) != len(columns):
            raise ValueError(f"row has {len(rec)} fields, expected {len(columns)}")
        data_rows.append([_convert_field(t, q, columns[i].type) for i, (t, q) in enumerate(rec)])
    return Table(name, columns, data_rows)


def _cell_to_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _quote_field(s: str) -> str:
    if "," in s or '"' in s or "\n" in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def _format_csv(columns: list, rows: list) -> str:
    lines = [",".join(_quote_field(c) for c in columns)]
    for row in rows:
        lines.append(",".join(_quote_field(_cell_to_str(v)) for v in row))
    return "\n".join(lines) + "\n"


def _parse_args(argv: list) -> tuple:
    table_specs: list = []
    query_parts: list = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--table":
            i += 1
            if i >= len(argv):
                raise ValueError("--table requires a NAME=PATH argument")
            table_specs.append(argv[i])
            i += 1
            continue
        query_parts.append(arg)
        i += 1
    return table_specs, query_parts


def main(argv: list | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        table_specs, query_parts = _parse_args(argv)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not table_specs:
        print("at least one --table NAME=PATH is required", file=sys.stderr)
        return 2
    if len(query_parts) != 1:
        print("exactly one query argument is required", file=sys.stderr)
        return 2
    tables = {}
    for spec in table_specs:
        if "=" not in spec:
            print(f"invalid --table spec: {spec!r}", file=sys.stderr)
            return 2
        name, path = spec.split("=", 1)
        try:
            tables[name] = _load_table(name, path)
        except (OSError, ValueError) as e:
            print(f"cannot load table {name!r}: {e}", file=sys.stderr)
            return 2
        except MicroDBError as e:
            print(f"cannot load table {name!r}: {e}", file=sys.stderr)
            return 2
    try:
        result = execute(query_parts[0], tables)
    except MicroDBError as e:
        print(str(e), file=sys.stderr)
        return 3
    sys.stdout.write(_format_csv(result.columns, result.rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

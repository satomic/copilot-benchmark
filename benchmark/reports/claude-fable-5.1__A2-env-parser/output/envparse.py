"""Parser for a small, precisely specified ``.env``-style configuration format."""

import re as _re

__all__ = ["parse_env"]

_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPORT_RE = _re.compile(r"^export\s+")
_DQ_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _error(lineno: int, line: str) -> ValueError:
    return ValueError(f"invalid line {lineno}: {line}")


def _parse_key(raw_key: str) -> str | None:
    key = raw_key.strip()
    key = _EXPORT_RE.sub("", key, count=1)
    if not key or not _KEY_RE.match(key):
        return None
    return key


def _expand_double_quoted(content: str) -> str:
    out: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == "\\" and i + 1 < n:
            nxt = content[i + 1]
            if nxt in _DQ_ESCAPES:
                out.append(_DQ_ESCAPES[nxt])
            else:
                out.append(ch)
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_trailing_comment(value: str) -> str:
    for i in range(1, len(value)):
        if value[i] == "#" and value[i - 1].isspace():
            return value[:i].strip()
    return value


def _parse_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _expand_double_quoted(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return _strip_trailing_comment(value)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), start=1):
        # A trailing "\r" is treated as part of the line terminator, so it is
        # also omitted from the error message.
        if line.endswith("\r"):
            line = line[:-1]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise _error(lineno, line)
        raw_key, raw_value = line.split("=", 1)
        key = _parse_key(raw_key)
        if key is None:
            raise _error(lineno, line)
        result[key] = _parse_value(raw_value)
    return result

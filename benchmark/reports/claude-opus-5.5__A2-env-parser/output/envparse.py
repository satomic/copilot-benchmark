"""Parser for a small, precisely specified .env-style configuration format."""

import re

__all__ = ["parse_env"]

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPORT_RE = re.compile(r"^export[ \t]+")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                out.append(ch + nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_comment(value: str) -> str:
    for i in range(1, len(value)):
        if value[i] == "#" and value[i - 1].isspace():
            return value[:i].strip()
    return value


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return _strip_comment(value)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), start=1):
        # The trailing "\r" is stripped before processing, so error messages
        # report the line without it as well.
        if line.endswith("\r"):
            line = line[:-1]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")
        raw_key, raw_value = line.split("=", 1)
        key = _EXPORT_RE.sub("", raw_key.strip(), count=1)
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {lineno}: {line}")
        # Assigning to an existing key keeps its original insertion position.
        result[key] = _parse_value(raw_value)
    return result

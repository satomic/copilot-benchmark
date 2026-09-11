"""Parse a small .env-style configuration format."""

import re

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPORT_RE = re.compile(r"^export\s+")

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def parse_env(text: str) -> dict[str, str]:
    """Parse `text` into a mapping, honouring quoting, escapes and comments."""
    result: dict[str, str] = {}
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw[:-1] if raw.endswith("\r") else raw
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {number}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = _EXPORT_RE.sub("", raw_key.strip())
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {number}: {line}")

        result[key] = _parse_value(raw_value.strip())
    return result


def _parse_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _expand(value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return _strip_comment(value)


def _expand(body: str) -> str:
    """Expand backslash escapes in a single left-to-right pass."""
    out: list[str] = []
    i = 0
    while i < len(body):
        char = body[i]
        if char == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                out.append(char)
                out.append(nxt)
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _strip_comment(value: str) -> str:
    """Drop a trailing comment introduced by whitespace followed by '#'."""
    for i, char in enumerate(value):
        if char == "#" and i > 0 and value[i - 1].isspace():
            return value[:i].strip()
    return value

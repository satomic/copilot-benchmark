"""Parser for a small `.env`-style configuration format."""

import re as _re

__all__ = ["parse_env"]

_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def _expand_escapes(content: str) -> str:
    out = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == "\\" and i + 1 < n:
            nxt = content[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                # Unknown escape: keep both characters as-is.
                out.append(ch)
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_inline_comment(value: str) -> str:
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1].isspace():
            return value[:i].strip()
    return value


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return _expand_escapes(value[1:-1])
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return _strip_inline_comment(value)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {lineno}: {line}")
        result[key] = _parse_value(raw_value)
    return result

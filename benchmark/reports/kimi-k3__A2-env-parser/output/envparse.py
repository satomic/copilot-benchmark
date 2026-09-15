"""Parser for a small, precisely specified .env-style configuration format."""

import re

__all__ = ["parse_env"]

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _expand_escapes(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                # Unknown escape: keep both characters as-is.
                out.append(c)
                out.append(nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), start=1):
        # A trailing carriage return is stripped before processing; error
        # messages report the line content after that strip.
        if line.endswith("\r"):
            line = line[:-1]

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        # Optional `export` prefix (followed by whitespace) is removed once.
        if key.startswith("export") and len(key) > 6 and key[6].isspace():
            key = key[6:].strip()

        if not key or not _KEY_RE.match(key):
            raise ValueError(f"invalid line {lineno}: {line}")

        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = _expand_escapes(value[1:-1])
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            # Unquoted: a `#` preceded by whitespace starts a trailing comment.
            for i, c in enumerate(value):
                if c == "#" and i > 0 and value[i - 1].isspace():
                    value = value[:i].strip()
                    break

        result[key] = value
    return result

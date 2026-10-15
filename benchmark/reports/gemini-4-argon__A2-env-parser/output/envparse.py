import re as _re

_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}

__all__ = ["parse_env"]


def _unescape_double_quoted(val: str) -> str:
    out: list[str] = []
    i = 0
    n = len(val)
    while i < n:
        ch = val[i]
        if ch == "\\" and i + 1 < n:
            nxt = val[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
            else:
                out.append("\\")
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_unquoted_comment(val: str) -> str:
    for i, ch in enumerate(val):
        if ch == "#" and i > 0 and val[i - 1].isspace():
            return val[:i].strip()
    return val


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not text:
        return result

    lines = text.split("\n")
    for line_no, raw_line in enumerate(lines, start=1):
        if raw_line.endswith("\r"):
            line = raw_line[:-1]
        else:
            line = raw_line

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {line_no}: {line}")

        raw_key, raw_val = line.split("=", 1)
        key = raw_key.strip()

        # Rule 4: The key is the raw key with leading and trailing whitespace stripped.
        # An optional `export` prefix followed by at least one space is removed.
        if key.startswith("export "):
            key = key[6:].lstrip(" ")

        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {line_no}: {line}")

        val = raw_val.strip()
        if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
            val = _unescape_double_quoted(val[1:-1])
        elif len(val) >= 2 and val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        else:
            val = _strip_unquoted_comment(val)

        result[key] = val

    return result

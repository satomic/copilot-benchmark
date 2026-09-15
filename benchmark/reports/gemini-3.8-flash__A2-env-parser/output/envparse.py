"""A line-by-line parser for .env configuration files."""

import re as _re

__all__ = ["parse_env"]

_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _expand_escapes(s: str) -> str:
    res = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            c = s[i + 1]
            if c == "n":
                res.append("\n")
                i += 2
            elif c == "t":
                res.append("\t")
                i += 2
            elif c == "r":
                res.append("\r")
                i += 2
            elif c == '"':
                res.append('"')
                i += 2
            elif c == "\\":
                res.append("\\")
                i += 2
            else:
                res.append("\\")
                res.append(c)
                i += 2
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


def _strip_unquoted_comment(val: str, had_leading_space: bool) -> str:
    # Scan for an unquoted '#' preceded by whitespace
    in_single = False
    in_double = False
    escape = False

    for i, ch in enumerate(val):
        if in_single:
            if ch == "'":
                in_single = False
        elif in_double:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            elif ch == "#":
                preceded_by_ws = had_leading_space if i == 0 else val[i - 1].isspace()
                if preceded_by_ws:
                    return val[:i].strip()
    return val


def _extract_key(raw_key: str) -> str:
    # Rule 4: Strip leading/trailing whitespace, remove optional 'export' prefix
    # followed by at least one space/whitespace character.
    s = raw_key.lstrip()
    if s.startswith("export") and len(s) > 6 and s[6].isspace():
        return s[6:].strip()
    return s.strip()


def _parse_value(raw_value: str) -> str:
    # Rule 6: Process value after stripping leading/trailing whitespace via if-elif-else.
    val = raw_value.strip()
    if len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        return _expand_escapes(val[1:-1])
    elif len(val) >= 2 and val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    else:
        had_leading_space = len(raw_value) > 0 and raw_value[0].isspace()
        return _strip_unquoted_comment(val, had_leading_space)


def parse_env(text: str) -> dict[str, str]:
    """Parse a .env format string into a dictionary."""
    result: dict[str, str] = {}
    lines = text.split("\n")

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line

        # 1. Empty or whitespace-only lines are skipped
        if not line.strip():
            continue

        # 2. Comment lines starting with # are skipped
        if line.lstrip().startswith("#"):
            continue

        # 3. Must contain at least one '='
        if "=" not in line:
            raise ValueError(f"invalid line {line_no}: {line}")

        raw_key, raw_value = line.split("=", 1)

        # 4 & 5. Key extraction and validation
        key = _extract_key(raw_key)
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {line_no}: {line}")

        # 6. Value parsing
        value = _parse_value(raw_value)

        # 7 & 8. Last occurrence wins, dict preserves first-appearance key order
        result[key] = value

    return result

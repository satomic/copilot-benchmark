import re

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _expand_double_escapes(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                i += 2
                continue
            out.append(c)
            out.append(nxt)
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_unquoted_comment(value: str) -> str:
    i = 0
    n = len(value)
    while i < n:
        if value[i] == "#" and i > 0 and value[i - 1] in (" ", "\t"):
            value = value[:i]
            break
        i += 1
    return value.strip()


def _parse_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        inner = value[1:-1]
        return _expand_double_escapes(inner)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return _strip_unquoted_comment(value)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = text.split("\n")
    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line

        stripped = line.strip()
        if stripped == "":
            continue
        if stripped[0] == "#":
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {idx}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export ") or key.startswith("export\t"):
            key = key[len("export"):].lstrip()

        if not key or not _KEY_RE.match(key):
            raise ValueError(f"invalid line {idx}: {line}")

        value = _parse_value(raw_value)
        result[key] = value

    return result

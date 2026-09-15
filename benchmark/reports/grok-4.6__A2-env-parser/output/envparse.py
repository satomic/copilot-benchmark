import re as _re

_KEY_RE = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _expand_double_quoted(value: str) -> str:
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "\\" and i + 1 < n:
            nxt = value[i + 1]
            mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
            else:
                out.append("\\")
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _unquoted_value(value: str) -> str:
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1].isspace():
            return value[:i].strip()
    return value


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.removesuffix("\r")
        if not line.strip():
            continue
        if line.lstrip()[:1] == "#":
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export "):  # optional `export` prefix + space
            key = key[7:].strip()
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"invalid line {lineno}: {line}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = _expand_double_quoted(value[1:-1])
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        else:
            value = _unquoted_value(value)
        result[key] = value
    return result

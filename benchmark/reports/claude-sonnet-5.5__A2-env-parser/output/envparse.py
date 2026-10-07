import re

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXPORT_RE = re.compile(r"^export[ \t]+(.*)$", re.DOTALL)
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def _unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in _ESCAPES:
            out.append(_ESCAPES[s[i + 1]])
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    # A '#' at the very start of the stripped value has no preceding
    # whitespace, so it is treated as part of the value (literal reading).
    m = re.search(r"\s#", value)
    if m:
        value = value[: m.start()].strip()
    return value


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), 1):
        if line.endswith("\r"):
            line = line[:-1]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")
        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        m = _EXPORT_RE.match(key)
        if m:
            key = m.group(1).strip()
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid line {lineno}: {line}")
        result[key] = _parse_value(raw_value)
    return result

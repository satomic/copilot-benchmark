import re

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXPORT_RE = re.compile(r"^export[ \t]+")
_ESCAPE_RE = re.compile(r'\\([ntr"\\])')
_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
# A '#' preceded by whitespace in the raw value starts a trailing comment.
_COMMENT_RE = re.compile(r"(?<=\s)#")


def _expand(content):
    # Single pass so that "\\n" becomes backslash + 'n', not a newline.
    return _ESCAPE_RE.sub(lambda m: _ESCAPE_MAP[m.group(1)], content)


def _parse_value(raw):
    value = raw.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _expand(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    # Unquoted: strip trailing comment based on the raw value.
    m = _COMMENT_RE.search(raw)
    if m:
        raw = raw[: m.start()]
    return raw.strip()


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {line}")
        raw_key, raw_value = line.split("=", 1)
        key = _EXPORT_RE.sub("", raw_key.strip(), count=1)
        if not _KEY_RE.fullmatch(key):
            raise ValueError(f"invalid line {lineno}: {line}")
        result[key] = _parse_value(raw_value)
    return result

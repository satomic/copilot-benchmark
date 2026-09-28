import re as _re


_KEY_PATTERN = _re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_EXPORT_PREFIX = _re.compile(r"^export\s+")
_DOUBLE_QUOTED_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def _expand_double_quoted(value: str) -> str:
    result = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            if escaped in _DOUBLE_QUOTED_ESCAPES:
                result.append(_DOUBLE_QUOTED_ESCAPES[escaped])
            else:
                result.extend(("\\", escaped))
            index += 2
        else:
            result.append(value[index])
            index += 1
    return "".join(result)


def _strip_unquoted_comment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].strip()
    return value


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}

    for line_number, original_line in enumerate(text.split("\n"), start=1):
        line = original_line.removesuffix("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {line_number}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        key = _EXPORT_PREFIX.sub("", key, count=1)
        if not _KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid line {line_number}: {line}")

        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = _expand_double_quoted(value[1:-1])
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            value = _strip_unquoted_comment(value)

        result[key] = value

    return result

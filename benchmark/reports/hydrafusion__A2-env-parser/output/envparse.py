"""Parser for the project's small .env-style format."""

import re as _re


_KEY_PATTERN = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def _expand_double_quoted(value: str) -> str:
    result: list[str] = []
    index = 0

    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            replacement = _ESCAPES.get(escaped)
            if replacement is not None:
                result.append(replacement)
                index += 2
                continue

        result.append(character)
        index += 1

    return "".join(result)


def _parse_value(raw_value: str) -> str:
    value = raw_value.strip()

    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return _expand_double_quoted(value[1:-1])

    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    for index, character in enumerate(value):
        if character == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].strip()

    return value


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}

    for line_number, original_line in enumerate(text.split("\n"), start=1):
        line = original_line[:-1] if original_line.endswith("\r") else original_line

        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {line_number}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].lstrip(" ")

        if _KEY_PATTERN.fullmatch(key) is None:
            raise ValueError(f"invalid line {line_number}: {line}")

        values[key] = _parse_value(raw_value)

    return values

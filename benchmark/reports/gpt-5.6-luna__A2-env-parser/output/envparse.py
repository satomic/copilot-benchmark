import re as _re


_KEY_PATTERN = _re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}

    for line_number, line in enumerate(text.split("\n"), 1):
        if line.endswith("\r"):
            line = line[:-1]

        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {line_number}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export") and len(key) > len("export") and key[6] == " ":
            key = key[6:].strip()
        if not key or _KEY_PATTERN.fullmatch(key) is None:
            raise ValueError(f"invalid line {line_number}: {line}")

        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = _expand_double_quoted(value[1:-1])
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            value = _remove_trailing_comment(value)

        result[key] = value

    return result


def _expand_double_quoted(value: str) -> str:
    expanded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            next_character = value[index + 1]
            expanded.append(_ESCAPES.get(next_character, "\\" + next_character))
            index += 2
        else:
            expanded.append(character)
            index += 1
    return "".join(expanded)


def _remove_trailing_comment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "#" and index > 0 and value[index - 1].isspace():
            return value[:index].strip()
    return value

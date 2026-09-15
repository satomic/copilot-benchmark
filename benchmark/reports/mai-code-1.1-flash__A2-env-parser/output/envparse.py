import re


_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _decode_double_quoted(value: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == "n":
                chars.append("\n")
                i += 2
                continue
            if nxt == "t":
                chars.append("\t")
                i += 2
                continue
            if nxt == "r":
                chars.append("\r")
                i += 2
                continue
            if nxt == '"':
                chars.append('"')
                i += 2
                continue
            if nxt == "\\":
                chars.append("\\")
                i += 2
                continue
            chars.append("\\")
            chars.append(nxt)
            i += 2
            continue
        chars.append(ch)
        i += 1
    if i < len(value) and value[i] == "\\":
        chars.append("\\")
    return "".join(chars)


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}

    for line_number, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.rstrip("\r")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid line {line_number}: {line}")

        raw_key, raw_value = line.split("=", 1)
        key = raw_key.strip()
        if key.startswith("export"):
            suffix = key[len("export") :]
            if suffix and suffix[0].isspace():
                key = suffix.lstrip()
        key = key.strip()
        if not key or not _KEY_RE.fullmatch(key):
            raise ValueError(f"invalid line {line_number}: {line}")

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = _decode_double_quoted(value[1:-1])
        elif len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            value = value[1:-1]
        else:
            for index, ch in enumerate(value):
                if ch == "#" and index > 0 and value[index - 1].isspace():
                    value = value[:index].rstrip()
                    break

        result[key] = value

    return result

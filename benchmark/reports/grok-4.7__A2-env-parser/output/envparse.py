"""Parser for a small .env-style configuration format."""


def parse_env(text: str) -> dict[str, str]:
    """Parse ``text`` into an ordered mapping of keys to string values.

    Later assignments overwrite earlier ones; insertion order follows the
    first appearance of each key.
    """
    result: dict[str, str] = {}
    # Lines are separated by ``\n``. A trailing ``\r`` is treated as part of
    # the line terminator (CRLF) and is omitted from error messages.
    for lineno, line in enumerate(text.split("\n"), start=1):
        if line.endswith("\r"):
            line = line[:-1]
        _parse_line(line, lineno, result)
    return result


def _parse_line(line: str, lineno: int, result: dict[str, str]) -> None:
    stripped = line.strip()
    if not stripped or stripped[0] == "#":
        return
    eq = line.find("=")
    if eq < 0:
        _fail(lineno, line)
    key = _normalize_key(line[:eq])
    if not _is_valid_key(key):
        _fail(lineno, line)
    result[key] = _parse_value(line[eq + 1 :])


def _fail(lineno: int, line: str) -> None:
    raise ValueError(f"invalid line {lineno}: {line}")


def _normalize_key(raw_key: str) -> str:
    key = raw_key.strip()
    # "export" is removed only when followed by an ASCII space, not other
    # whitespace. Additional spaces after that prefix are discarded once.
    if key.startswith("export "):
        key = key[7:].lstrip(" ")
    return key


def _is_valid_key(key: str) -> bool:
    if not key:
        return False
    first = key[0]
    if not (("A" <= first <= "Z") or ("a" <= first <= "z") or first == "_"):
        return False
    for ch in key[1:]:
        if not (
            ("A" <= ch <= "Z")
            or ("a" <= ch <= "z")
            or ("0" <= ch <= "9")
            or ch == "_"
        ):
            return False
    return True


def _parse_value(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _expand_double_quoted(value[1:-1])
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1]
    return _strip_unquoted_comment(value)


def _expand_double_quoted(content: str) -> str:
    out: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch == "\\" and i + 1 < n:
            nxt = content[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append("\\")
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _strip_unquoted_comment(value: str) -> str:
    for i, ch in enumerate(value):
        if ch == "#" and i > 0 and value[i - 1].isspace():
            return value[:i].strip()
    return value

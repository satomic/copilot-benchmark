def _expand_escapes(s: str) -> str:
    """Expand \\n, \\t, \\r, \\\", \\\\ escape sequences in a double-quoted string."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                result.append("\n")
                i += 2
            elif nxt == "t":
                result.append("\t")
                i += 2
            elif nxt == "r":
                result.append("\r")
                i += 2
            elif nxt == '"':
                result.append('"')
                i += 2
            elif nxt == "\\":
                result.append("\\")
                i += 2
            else:
                # Any other \\x sequence left as-is (both characters)
                result.append(s[i])
                result.append(s[i + 1])
                i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _strip_comment(value: str) -> str:
    """Remove an unquoted trailing comment: a '#' preceded by whitespace."""
    # Find '#' that is preceded by at least one whitespace character.
    i = 0
    while i < len(value):
        if value[i] == "#" and i > 0 and value[i - 1] in " \t":
            return value[:i].rstrip()
        i += 1
    return value


def parse_env(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    order: list[str] = []
    lines = text.split("\n")
    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\r")

        # Skip empty/whitespace-only lines
        if not line or line.strip() == "":
            continue

        # Skip comment lines
        stripped = line.lstrip()
        if stripped and stripped[0] == "#":
            continue

        # Line must contain '='
        if "=" not in line:
            raise ValueError(f"invalid line {lineno}: {raw_line}")

        raw_key, raw_val = line.split("=", 1)

        # Strip key
        key = raw_key.strip()

        # Strip optional 'export ' prefix (with at least one space)
        if key.startswith("export ") and len(key) > 7:
            key = key[7:].lstrip()

        # Validate key
        if not key or not all(c.isalnum() or c == "_" for c in key):
            if not key:
                raise ValueError(f"invalid line {lineno}: {raw_line}")
            if not (key[0].isalpha() or key[0] == "_"):
                raise ValueError(f"invalid line {lineno}: {raw_line}")
            raise ValueError(f"invalid line {lineno}: {raw_line}")

        if not (key[0].isalpha() or key[0] == "_"):
            raise ValueError(f"invalid line {lineno}: {raw_line}")

        # Process value
        value = raw_val.strip()

        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            # Double-quoted
            inner = value[1:-1]
            value = _expand_escapes(inner)
        elif len(value) >= 2 and value[0] == "'" and value[-1] == "'":
            # Single-quoted - literal, no escape expansion
            value = value[1:-1]
        else:
            # Unquoted: strip trailing comment, then strip again
            value = _strip_comment(value)

        if key not in result:
            order.append(key)
        result[key] = value

    return {k: result[k] for k in order}
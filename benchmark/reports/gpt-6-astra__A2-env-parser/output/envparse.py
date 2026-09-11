import re as _re


def parse_env(text: str) -> dict[str, str]:
    """Parse line-based environment assignments, preserving first key order."""
    result: dict[str, str] = {}
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}

    for number, line in enumerate(text.split("\n"), 1):
        line = line.removesuffix("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if "=" not in line:
            raise ValueError(f"invalid line {number}: {line}")
        key, value = line.split("=", 1)
        key = key.strip()
        # The export separator requires a literal space, not just whitespace.
        if key.startswith("export "):
            key = key[len("export "):].lstrip()
        if _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise ValueError(f"invalid line {number}: {line}")

        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = _re.sub(
                r"\\(.)",
                lambda match: escapes.get(match[1], match[0]),
                value[1:-1],
                flags=_re.DOTALL,
            )
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            comment = _re.search(r"\s#", value)
            if comment is not None:
                value = value[:comment.start()].strip()
        result[key] = value

    return result

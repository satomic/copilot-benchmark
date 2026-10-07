import re as _re


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


def parse_env(text: str) -> dict[str, str]:
    """Parse the specified line-based environment format."""
    result: dict[str, str] = {}
    for number, original in enumerate(text.split("\n"), 1):
        line = original.removesuffix("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        raw_key, separator, raw_value = line.partition("=")
        key = raw_key.strip()
        # The export separator must contain a literal space, not just a tab.
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not separator or _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            # Keep the original content (including any CR) in diagnostics.
            raise ValueError(f"invalid line {number}: {original}")

        value = raw_value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = _re.sub(
                r"\\(.)",
                lambda match: _ESCAPES.get(match[1], match[0]),
                value[1:-1],
            )
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        else:
            comment = _re.search(r"\s+#", value)
            if comment is not None:
                value = value[:comment.start()].strip()
        result[key] = value
    return result

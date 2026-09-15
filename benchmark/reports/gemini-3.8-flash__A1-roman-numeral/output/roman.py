"""Roman numeral encoder."""

_ROMAN_MAP: tuple[tuple[int, str], ...] = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)


def to_roman(n: int) -> str:
    """Convert an integer in 1..3999 to its standard Roman numeral representation."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an integer, got {type(n).__name__}")
    if not (1 <= n <= 3999):
        raise ValueError(f"n must be between 1 and 3999, got {n}")

    parts: list[str] = []
    for value, numeral in _ROMAN_MAP:
        count, n = divmod(n, value)
        if count:
            parts.append(numeral * count)
    return "".join(parts)

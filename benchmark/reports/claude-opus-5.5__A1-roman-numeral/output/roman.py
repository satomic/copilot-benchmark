_PAIRS = (
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
    """Convert an integer in 1..3999 to its standard Roman numeral."""
    # Strict type check: rejects bool (an int subclass) and int subclasses in general.
    if type(n) is not int:
        raise TypeError(f"expected int, got {type(n).__name__}")
    if not 1 <= n <= 3999:
        raise ValueError(f"n must be in 1..3999, got {n}")
    parts = []
    for value, symbol in _PAIRS:
        count, n = divmod(n, value)
        parts.append(symbol * count)
    return "".join(parts)

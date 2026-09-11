_NUMERALS = (
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
    """Convert an integer in 1..3999 to a standard uppercase Roman numeral."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int, not bool")
    if not 1 <= n <= 3999:
        raise ValueError("n must be in the range 1..3999")

    parts = []
    for value, numeral in _NUMERALS:
        count, n = divmod(n, value)
        parts.append(numeral * count)
    return "".join(parts)

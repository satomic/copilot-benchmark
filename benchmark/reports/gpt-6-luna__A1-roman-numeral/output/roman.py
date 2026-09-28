_ROMAN_VALUES = (
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
    """Convert an integer from 1 to 3999 to a standard Roman numeral."""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int")
    if not 1 <= n <= 3999:
        raise ValueError("n must be in the range 1..3999")

    numeral = []
    for value, symbol in _ROMAN_VALUES:
        count, n = divmod(n, value)
        numeral.append(symbol * count)
    return "".join(numeral)

"""Convert integers in 1..3999 to standard subtractive Roman numerals."""

# bool is a subclass of int; reject it explicitly so True/False are not numerals.
_VALUES = (
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
    """Return the standard Roman numeral for n in the inclusive range 1..3999.

    Raises TypeError if n is not an int (bool is rejected). Raises ValueError
    if n is outside 1..3999.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int")
    if n < 1 or n > 3999:
        raise ValueError("n must be in 1..3999")

    parts: list[str] = []
    remaining = n
    for value, symbol in _VALUES:
        count, remaining = divmod(remaining, value)
        if count:
            parts.append(symbol * count)
    return "".join(parts)

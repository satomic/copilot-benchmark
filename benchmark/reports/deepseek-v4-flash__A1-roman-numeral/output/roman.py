def to_roman(n: int) -> str:
    """Convert an integer in the range 1..3999 to its Roman numeral representation."""
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("n must be an int")
    if n < 1 or n > 3999:
        raise ValueError("n must be in the range 1..3999")

    _values = [
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
    ]

    result = []
    for value, numeral in _values:
        while n >= value:
            result.append(numeral)
            n -= value
    return "".join(result)
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
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("n must be an int")
    if not 1 <= n <= 3999:
        raise ValueError("n must be between 1 and 3999")

    result = []
    for value, numeral in _ROMAN_VALUES:
        count, n = divmod(n, value)
        result.append(numeral * count)
    return "".join(result)

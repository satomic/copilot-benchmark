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
    if type(n) is not int:
        raise TypeError("n must be an int")
    if n < 1 or n > 3999:
        raise ValueError("n must be in the range 1..3999")
    parts = []
    remaining = n
    for value, numeral in _VALUES:
        count, remaining = divmod(remaining, value)
        if count:
            parts.append(numeral * count)
    return "".join(parts)

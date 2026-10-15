_NUMERAL_MAP: tuple[tuple[int, str], ...] = (
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
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n must be an int")
    if n < 1 or n > 3999:
        raise ValueError("n must be in the range 1..3999")

    parts: list[str] = []
    remaining = n
    for value, symbol in _NUMERAL_MAP:
        if remaining >= value:
            count, remaining = divmod(remaining, value)
            parts.append(symbol * count)
            if remaining == 0:
                break
    return "".join(parts)

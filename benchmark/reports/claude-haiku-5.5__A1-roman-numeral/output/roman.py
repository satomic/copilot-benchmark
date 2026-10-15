_NUMERAL_PAIRS = (
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
    # bool is a subclass of int; reject it explicitly.
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"expected int, got {type(n).__name__}")
    if not 1 <= n <= 3999:
        raise ValueError(f"value must be in 1..3999, got {n}")

    parts = []
    remaining = n
    for value, numeral in _NUMERAL_PAIRS:
        count, remaining = divmod(remaining, value)
        parts.append(numeral * count)
    return "".join(parts)

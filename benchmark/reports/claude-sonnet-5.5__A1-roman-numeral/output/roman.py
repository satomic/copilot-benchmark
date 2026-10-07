_TABLE = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def to_roman(n: int) -> str:
    # bool is a subclass of int but is explicitly rejected.
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("n must be an int")
    if not 1 <= n <= 3999:
        raise ValueError("n must be in range 1..3999")
    parts = []
    for value, symbol in _TABLE:
        count, n = divmod(n, value)
        parts.append(symbol * count)
    return "".join(parts)

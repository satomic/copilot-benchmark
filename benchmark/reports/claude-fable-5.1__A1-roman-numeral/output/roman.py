"""Convert integers in the range 1..3999 to standard Roman numerals."""

__all__ = ["to_roman"]

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
    # bool is a subclass of int but is explicitly rejected.
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, not {type(n).__name__}")
    if not 1 <= n <= 3999:
        raise ValueError(f"n must be in the range 1..3999, got {n}")

    parts = []
    remaining = n
    for value, symbol in _NUMERALS:
        count, remaining = divmod(remaining, value)
        parts.append(symbol * count)
    return "".join(parts)

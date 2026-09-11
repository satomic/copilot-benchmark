"""Convert integers to Roman numerals."""

# Value/symbol pairs ordered high to low, including the subtractive forms.
_NUMERALS: tuple[tuple[int, str], ...] = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)

_MIN, _MAX = 1, 3999


def to_roman(n: int) -> str:
    """Return the Roman numeral for `n` (1..3999)."""
    # bool is a subclass of int, so it has to be rejected explicitly.
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if not _MIN <= n <= _MAX:
        raise ValueError(f"n must be between {_MIN} and {_MAX}, got {n}")

    parts: list[str] = []
    remaining = n
    for value, symbol in _NUMERALS:
        count, remaining = divmod(remaining, value)
        parts.append(symbol * count)
    return "".join(parts)

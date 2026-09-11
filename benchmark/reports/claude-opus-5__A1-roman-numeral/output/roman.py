"""Integer to Roman numeral conversion."""

__all__ = ["to_roman"]

# Value/symbol pairs ordered descending, including the subtractive forms.
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
    """Return the standard subtractive Roman numeral for ``n`` (1..3999)."""
    # bool is a subclass of int but is not an acceptable input.
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if not 1 <= n <= 3999:
        raise ValueError(f"n must be in range 1..3999, got {n}")

    parts = []
    for value, symbol in _VALUES:
        count, n = divmod(n, value)
        parts.append(symbol * count)
    return "".join(parts)

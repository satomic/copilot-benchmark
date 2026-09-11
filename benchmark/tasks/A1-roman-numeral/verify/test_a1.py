"""Hidden verification suite for task A1. Not visible to the model under test."""
import io
import contextlib
import importlib
import sys

import pytest

def _public_names(module) -> set[str]:
    """Public names *defined* by `module`, excluding imported modules and objects."""
    import types

    names = set()
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if isinstance(value, types.ModuleType):
            continue
        if getattr(value, "__module__", module.__name__) != module.__name__:
            continue
        names.add(name)
    return names


_VALUES = {
    "I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000,
}


def _decode(s: str) -> int:
    total = 0
    prev = 0
    for ch in reversed(s):
        v = _VALUES[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


@pytest.fixture(scope="module")
def roman():
    sys.path.insert(0, ".")
    return importlib.import_module("roman")


@pytest.mark.parametrize(
    "n,expected",
    [
        (1, "I"), (2, "II"), (3, "III"), (4, "IV"), (5, "V"), (6, "VI"),
        (9, "IX"), (10, "X"), (14, "XIV"), (19, "XIX"), (40, "XL"),
        (44, "XLIV"), (49, "XLIX"), (50, "L"), (90, "XC"), (99, "XCIX"),
        (100, "C"), (400, "CD"), (500, "D"), (900, "CM"), (1000, "M"),
        (1066, "MLXVI"), (1444, "MCDXLIV"), (1994, "MCMXCIV"),
        (2026, "MMXXVI"), (3888, "MMMDCCCLXXXVIII"), (3999, "MMMCMXCIX"),
    ],
)
def test_known_values(roman, n, expected):
    assert roman.to_roman(n) == expected


def test_full_round_trip(roman):
    for n in range(1, 4000):
        s = roman.to_roman(n)
        assert isinstance(s, str)
        assert s == s.upper()
        assert _decode(s) == n, f"round-trip failed for {n}: {s!r}"


@pytest.mark.parametrize("n", [0, -1, -3999, 4000, 10_000])
def test_out_of_range_raises_value_error(roman, n):
    with pytest.raises(ValueError):
        roman.to_roman(n)


@pytest.mark.parametrize("n", ["5", 5.0, None, True, False, [1], 3 + 0j])
def test_bad_type_raises_type_error(roman, n):
    with pytest.raises(TypeError):
        roman.to_roman(n)


def test_import_is_silent():
    sys.path.insert(0, ".")
    sys.modules.pop("roman", None)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        importlib.import_module("roman")
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_no_extra_public_names(roman):
    public = _public_names(roman)
    assert public == {"to_roman"}, f"unexpected public names: {sorted(public - {'to_roman'})}"

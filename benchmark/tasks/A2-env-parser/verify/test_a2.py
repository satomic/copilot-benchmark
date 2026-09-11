"""Hidden verification suite for task A2. Not visible to the model under test."""
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



@pytest.fixture(scope="module")
def mod():
    sys.path.insert(0, ".")
    return importlib.import_module("envparse")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A=1\nB = 2 \n", {"A": "1", "B": "2"}),
        ("# c\n\n   \nA=1", {"A": "1"}),
        ("   # indented comment\nA=1", {"A": "1"}),
        ("A=1\r\nB=2\r\n", {"A": "1", "B": "2"}),
        ("A=", {"A": ""}),
        ("A=1\nA=2", {"A": "2"}),
        ("export FOO=bar", {"FOO": "bar"}),
        ("export   FOO=bar", {"FOO": "bar"}),
        ("_x=1\nX9_y=2", {"_x": "1", "X9_y": "2"}),
        ("URL=https://x/y?a=b", {"URL": "https://x/y?a=b"}),
        ("A=a=b=c", {"A": "a=b=c"}),
    ],
)
def test_basic(mod, text, expected):
    assert mod.parse_env(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ('A="x\\ny"', {"A": "x\ny"}),
        ('A="x\\ty"', {"A": "x\ty"}),
        ('A="x\\ry"', {"A": "x\ry"}),
        ('A="a\\"b"', {"A": 'a"b'}),
        ('A="a\\\\b"', {"A": "a\\b"}),
        ('A="a\\qb"', {"A": "a\\qb"}),
        ('A="  padded  "', {"A": "  padded  "}),
        ('A="#notcomment"', {"A": "#notcomment"}),
        ('A=""', {"A": ""}),
    ],
)
def test_double_quoted(mod, text, expected):
    assert mod.parse_env(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A='x\\ny'", {"A": "x\\ny"}),
        ("A='  padded  '", {"A": "  padded  "}),
        ("A='#notcomment'", {"A": "#notcomment"}),
        ("A=''", {"A": ""}),
        ("A='a\"b'", {"A": 'a"b'}),
    ],
)
def test_single_quoted(mod, text, expected):
    assert mod.parse_env(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A=hello  # trailing", {"A": "hello"}),
        ("A=hello\t# trailing", {"A": "hello"}),
        ("A=a#b", {"A": "a#b"}),
        ("A=a #b c", {"A": "a"}),
        ("A=#justhash", {"A": "#justhash"}),
    ],
)
def test_unquoted_trailing_comment(mod, text, expected):
    assert mod.parse_env(text) == expected


def test_insertion_order_follows_first_appearance(mod):
    got = mod.parse_env("B=1\nA=2\nB=3")
    assert list(got.keys()) == ["B", "A"]
    assert got == {"B": "3", "A": "2"}


@pytest.mark.parametrize(
    "text,message",
    [
        ("A=1\nnope\n", "invalid line 2: nope"),
        ("1BAD=x", "invalid line 1: 1BAD=x"),
        ("=x", "invalid line 1: =x"),
        ("  =x", "invalid line 1:   =x"),
        ("A-B=x", "invalid line 1: A-B=x"),
        ("A=1\n\n\nbroken", "invalid line 4: broken"),
    ],
)
def test_errors(mod, text, message):
    with pytest.raises(ValueError) as ei:
        mod.parse_env(text)
    assert str(ei.value) == message


def test_no_extra_public_names(mod):
    public = _public_names(mod)
    assert public == {"parse_env"}, f"unexpected public names: {sorted(public - {'parse_env'})}"

"""Hidden verification suite for task A3. Not visible to the model under test."""
import copy
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
    return importlib.import_module("sales")


def test_empty(mod):
    assert mod.summarize([]) == []


def test_reference_example(mod):
    rows = [
        {"region": "North", "amount": "100"},
        {"region": "south", "amount": 50.5},
        {"region": " NORTH ", "amount": " 25 "},
        {"region": "South", "amount": None},
    ]
    assert mod.summarize(rows) == [
        {"region": "North", "count": 2, "total": 125.0, "avg": 62.5},
        {"region": "south", "count": 2, "total": 50.5, "avg": 25.25},
    ]


def test_output_key_set_and_types(mod):
    (row,) = mod.summarize([{"region": "x", "amount": 3}])
    assert list(row.keys()) == ["region", "count", "total", "avg"]
    assert isinstance(row["region"], str)
    assert isinstance(row["count"], int) and not isinstance(row["count"], bool)
    assert isinstance(row["total"], float)
    assert isinstance(row["avg"], float)


def test_first_seen_casing_wins(mod):
    rows = [
        {"region": "  North  ", "amount": 1},
        {"region": "NORTH", "amount": 1},
        {"region": "north", "amount": 1},
    ]
    assert mod.summarize(rows) == [
        {"region": "North", "count": 3, "total": 3.0, "avg": 1.0}
    ]


def test_missing_and_blank_amounts_count_as_zero(mod):
    rows = [
        {"region": "a", "amount": 10},
        {"region": "a"},
        {"region": "a", "amount": None},
        {"region": "a", "amount": ""},
        {"region": "a", "amount": "   "},
    ]
    assert mod.summarize(rows) == [
        {"region": "a", "count": 5, "total": 10.0, "avg": 2.0}
    ]


def test_bool_amount_is_one(mod):
    assert mod.summarize([{"region": "a", "amount": True}]) == [
        {"region": "a", "count": 1, "total": 1.0, "avg": 1.0}
    ]


def test_sort_by_total_desc_then_region_ci_asc(mod):
    rows = [
        {"region": "Beta", "amount": 10},
        {"region": "alpha", "amount": 10},
        {"region": "Gamma", "amount": 99},
        {"region": "delta", "amount": 1},
    ]
    assert [r["region"] for r in mod.summarize(rows)] == ["Gamma", "alpha", "Beta", "delta"]


def test_rounding(mod):
    rows = [
        {"region": "a", "amount": 0.1},
        {"region": "a", "amount": 0.2},
        {"region": "a", "amount": 10.005},
    ]
    out = mod.summarize(rows)[0]
    assert out["total"] == round(0.1 + 0.2 + 10.005, 2)
    assert out["avg"] == round((0.1 + 0.2 + 10.005) / 3, 2)


def test_avg_uses_unrounded_total(mod):
    # total before rounding is 1.004, after rounding 1.0; avg must derive from 1.004
    rows = [{"region": "a", "amount": 1.004}]
    out = mod.summarize(rows)[0]
    assert out["total"] == 1.0
    assert out["avg"] == round(1.004, 2)


def test_input_not_mutated(mod):
    rows = [{"region": " A ", "amount": "5"}, {"region": "b"}]
    snapshot = copy.deepcopy(rows)
    mod.summarize(rows)
    assert rows == snapshot


@pytest.mark.parametrize(
    "rows,message",
    [
        ([{"amount": 1}], "row 0: missing region"),
        ([{"region": "x"}, {"region": None}], "row 1: missing region"),
        ([{"region": "x"}, {"region": "   "}], "row 1: missing region"),
        ([{"region": "x", "amount": "abc"}], "row 0: invalid amount: 'abc'"),
        ([{"region": "x", "amount": 1}, {"region": "y", "amount": []}], "row 1: invalid amount: []"),
        ([{"region": "", "amount": "abc"}], "row 0: missing region"),
    ],
)
def test_errors(mod, rows, message):
    with pytest.raises(ValueError) as ei:
        mod.summarize(rows)
    assert str(ei.value) == message


def test_no_extra_public_names(mod):
    public = _public_names(mod)
    assert public == {"summarize"}, f"unexpected public names: {sorted(public - {'summarize'})}"

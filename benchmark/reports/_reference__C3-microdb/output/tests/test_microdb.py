"""Reference test suite for microdb."""

from __future__ import annotations

import subprocess
import sys

import pytest

import microdb as db
from microdb import Column, Table


@pytest.fixture
def people() -> Table:
    return Table(
        "p",
        [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT")],
        [[1, "ann", 30], [2, "bob", None], [3, "cid", 40], [4, None, 30]],
    )


def rows(query: str, tables: dict[str, Table]) -> list[list[object]]:
    return db.execute(query, tables).rows


def test_and_truth_table():
    assert db.and_(True, None) is None
    assert db.and_(False, None) is False
    assert db.and_(None, False) is False


def test_or_truth_table():
    assert db.or_(True, None) is True
    assert db.or_(False, None) is None
    assert db.or_(None, True) is True


def test_not_unknown():
    assert db.not_(None) is None


def test_null_equals_null_is_unknown():
    assert db.compare_eq(None, None) is None


def test_compare_numeric_mix():
    assert db.compare_lt(1, 2.5) is True


def test_compare_bool_with_number_raises():
    with pytest.raises(db.TypeMismatchError):
        db.compare_lt(True, 1)


def test_compare_text_with_number_raises():
    with pytest.raises(db.TypeMismatchError):
        db.compare_eq("a", 1)


def test_bool_is_not_numeric():
    assert db.is_numeric(True) is False
    assert db.type_of(True) == "BOOL"


def test_division_always_float():
    assert db.arith("/", 7, 2) == 3.5


def test_division_by_zero_is_null():
    assert db.arith("/", 1, 0) is None


def test_modulo_by_zero_is_null():
    assert db.arith("%", 1, 0) is None


def test_modulo_python_sign():
    assert db.arith("%", -7, 3) == 2


def test_arith_null_propagates():
    assert db.arith("+", None, 1) is None


def test_arith_rejects_text():
    with pytest.raises(db.TypeMismatchError):
        db.arith("+", "a", "b")


def test_negate_preserves_type():
    assert db.negate(3) == -3
    assert db.negate(None) is None


def test_table_rejects_duplicate_columns():
    with pytest.raises(db.SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])


def test_table_rejects_bad_type():
    with pytest.raises(db.SchemaError):
        Table("t", [Column("a", "NUMBER")], [])


def test_table_rejects_bool_in_int_column():
    with pytest.raises(db.SchemaError):
        Table("t", [Column("a", "INT")], [[True]])


def test_table_widens_int_to_float():
    t = Table("t", [Column("a", "FLOAT")], [[3]])
    assert t.rows == [[3.0]]


def test_table_rejects_float_in_int_column():
    with pytest.raises(db.SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])


def test_table_rejects_wrong_row_width():
    with pytest.raises(db.SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_select_star(people):
    assert len(rows("SELECT * FROM p", {"p": people})) == 4


def test_where_keeps_only_true(people):
    assert rows("SELECT id FROM p WHERE age > 30", {"p": people}) == [[3]]


def test_where_null_comparison_drops_row(people):
    assert rows("SELECT id FROM p WHERE age = NULL", {"p": people}) == []


def test_where_rejects_non_bool(people):
    with pytest.raises(db.TypeMismatchError):
        rows("SELECT id FROM p WHERE 1", {"p": people})


def test_where_rejects_aggregate(people):
    with pytest.raises(db.AggregateError):
        rows("SELECT id FROM p WHERE count(id) > 0", {"p": people})


def test_is_null(people):
    assert rows("SELECT id FROM p WHERE age IS NULL", {"p": people}) == [[2]]


def test_is_not_null(people):
    assert rows("SELECT id FROM p WHERE name IS NOT NULL", {"p": people}) == [[1], [2], [3]]


def test_count_star_counts_rows(people):
    assert rows("SELECT count(*) FROM p", {"p": people}) == [[4]]


def test_count_column_skips_null(people):
    assert rows("SELECT count(age) FROM p", {"p": people}) == [[3]]


def test_sum_of_empty_is_null():
    empty = Table("e", [Column("x", "INT")], [])
    assert rows("SELECT sum(x) FROM e", {"e": empty}) == [[None]]


def test_count_over_empty_yields_one_row():
    empty = Table("e", [Column("x", "INT")], [])
    assert rows("SELECT count(*) FROM e", {"e": empty}) == [[0]]


def test_group_by_over_empty_yields_no_rows():
    empty = Table("e", [Column("x", "INT")], [])
    assert rows("SELECT count(*) FROM e GROUP BY x", {"e": empty}) == []


def test_avg_is_float(people):
    assert rows("SELECT avg(age) FROM p", {"p": people}) == [[100 / 3]]


def test_sum_int_stays_int(people):
    assert rows("SELECT sum(age) FROM p", {"p": people}) == [[100]]


def test_nulls_group_together(people):
    out = rows("SELECT name, count(*) FROM p GROUP BY name", {"p": people})
    assert [r[0] for r in out] == ["ann", "bob", "cid", None]


def test_group_order_is_first_appearance(people):
    out = rows("SELECT age, count(*) FROM p GROUP BY age", {"p": people})
    assert [r[0] for r in out] == [30, None, 40]


def test_grouping_error_on_bare_column(people):
    with pytest.raises(db.GroupingError):
        rows("SELECT name, id FROM p GROUP BY name", {"p": people})


def test_having_filters_groups(people):
    out = rows(
        "SELECT age, count(*) AS c FROM p GROUP BY age HAVING count(*) > 1", {"p": people}
    )
    assert out == [[30, 2]]


def test_order_by_nulls_last_asc(people):
    assert rows("SELECT age FROM p ORDER BY age", {"p": people}) == [[30], [30], [40], [None]]


def test_order_by_nulls_last_desc(people):
    assert rows("SELECT age FROM p ORDER BY age DESC", {"p": people}) == [
        [40],
        [30],
        [30],
        [None],
    ]


def test_order_by_is_stable(people):
    out = rows("SELECT id, age FROM p ORDER BY age", {"p": people})
    assert [r[0] for r in out] == [1, 4, 3, 2]


def test_order_by_alias(people):
    out = rows("SELECT age AS a FROM p ORDER BY a DESC", {"p": people})
    assert out == [[40], [30], [30], [None]]


def test_order_by_alias_shadows_column(people):
    out = rows("SELECT age AS id FROM p ORDER BY id", {"p": people})
    assert out == [[30], [30], [40], [None]]


def test_limit_offset(people):
    assert rows("SELECT id FROM p ORDER BY id LIMIT 2 OFFSET 1", {"p": people}) == [[2], [3]]


def test_distinct(people):
    assert rows("SELECT DISTINCT age FROM p ORDER BY age", {"p": people}) == [
        [30],
        [40],
        [None],
    ]


def test_left_join_fills_null():
    left = Table("l", [Column("id", "INT")], [[1], [2]])
    right = Table("r", [Column("lid", "INT"), Column("v", "INT")], [[1, 9]])
    out = rows("SELECT l.id, r.v FROM l LEFT JOIN r ON l.id = r.lid", {"l": left, "r": right})
    assert out == [[1, 9], [2, None]]


def test_inner_join_drops_unmatched():
    left = Table("l", [Column("id", "INT")], [[1], [2]])
    right = Table("r", [Column("lid", "INT")], [[1]])
    out = rows("SELECT l.id FROM l JOIN r ON l.id = r.lid", {"l": left, "r": right})
    assert out == [[1]]


def test_ambiguous_column_raises():
    a = Table("a", [Column("x", "INT")], [[1]])
    b = Table("b", [Column("x", "INT")], [[1]])
    with pytest.raises(db.AmbiguousColumnError):
        rows("SELECT x FROM a JOIN b ON a.x = b.x", {"a": a, "b": b})


def test_unknown_table_raises(people):
    with pytest.raises(db.UnknownTableError):
        rows("SELECT q.id FROM p", {"p": people})


def test_coalesce_does_not_propagate_null(people):
    assert rows("SELECT coalesce(age, 0) FROM p WHERE id = 2", {"p": people}) == [[0]]


def test_concat_propagates_null(people):
    assert rows("SELECT concat(name, 'x') FROM p WHERE id = 4", {"p": people}) == [[None]]


def test_length_and_upper(people):
    assert rows("SELECT upper(name), length(name) FROM p WHERE id = 1", {"p": people}) == [
        ["ANN", 3]
    ]


def test_arity_error(people):
    with pytest.raises(db.ArityError):
        rows("SELECT upper(name, 1) FROM p", {"p": people})


def test_unknown_function(people):
    with pytest.raises(db.UnknownFunctionError):
        rows("SELECT sqrt(age) FROM p", {"p": people})


def test_comparison_not_associative(people):
    with pytest.raises(db.ParseError):
        rows("SELECT id FROM p WHERE 1 < 2 < 3", {"p": people})


def test_not_binds_looser_than_comparison(people):
    assert rows("SELECT NOT id = 1 FROM p WHERE id = 1", {"p": people}) == [[False]]


def test_lex_error_offset():
    with pytest.raises(db.LexError) as info:
        db.tokenize("SELECT #")
    assert info.value.offset == 7


def test_plan_stage_order(people):
    query = db.parse("SELECT age, count(*) FROM p GROUP BY age HAVING count(*) > 0 ORDER BY age")
    assert db.plan(query).names == [
        "scan",
        "group",
        "aggregate",
        "having",
        "project",
        "sort",
    ]


def test_output_name_from_expression(people):
    assert db.execute("SELECT age + 1 FROM p", {"p": people}).columns == ["age + 1"]


def _cli(tmp_path, csv_text, query, *extra):
    path = tmp_path / "t.csv"
    path.write_text(csv_text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={path}", *extra, query],
        capture_output=True,
        text=True,
    )


def test_cli_success(tmp_path):
    done = _cli(tmp_path, "id:INT,age:INT\n1,30\n2,40\n", "SELECT count(*) FROM t WHERE age > 30")
    assert done.returncode == 0
    assert done.stdout.splitlines()[-1] == "1"


def test_cli_null_is_empty_field(tmp_path):
    done = _cli(tmp_path, "id:INT,age:INT\n1,\n", "SELECT age FROM t")
    assert done.stdout.splitlines() == ["age", ""]


def test_cli_bool_lowercase(tmp_path):
    done = _cli(tmp_path, "f:BOOL\ntrue\n", "SELECT f FROM t")
    assert done.stdout.splitlines() == ["f", "true"]


def test_cli_usage_error_without_table(tmp_path):
    done = subprocess.run(
        [sys.executable, "-m", "microdb", "SELECT 1 FROM t"], capture_output=True, text=True
    )
    assert done.returncode == 2


def test_cli_query_error_exit_three(tmp_path):
    done = _cli(tmp_path, "id:INT\n1\n", "SELECT nope FROM t")
    assert done.returncode == 3
    assert done.stdout == ""

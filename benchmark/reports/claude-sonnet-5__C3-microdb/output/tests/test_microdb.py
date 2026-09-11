"""Test suite for microdb."""

from __future__ import annotations

import subprocess
import sys

import pytest

import microdb as m
from microdb import Column, Table
from microdb import value as V
from microdb.errors import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    GroupingError,
    LexError,
    ParseError,
    SchemaError,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
)

ROOT = __file__.replace("\\tests\\test_microdb.py", "").replace("/tests/test_microdb.py", "")


def run(query: str, tables: dict) -> m.Result:
    return m.execute(query, tables)


def people_table() -> Table:
    return Table(
        "people",
        [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT")],
        [[1, "Alice", 25], [2, "Bob", 35], [3, "Carol", 45], [4, "Dave", None]],
    )


def dept_table() -> Table:
    return Table(
        "dept",
        [Column("id", "INT"), Column("dept", "TEXT")],
        [[1, "eng"], [2, "sales"]],
    )


# ---- three-valued logic ----


def test_and_truth_table():
    assert V.and_(True, True) is True
    assert V.and_(True, False) is False
    assert V.and_(True, None) is None
    assert V.and_(False, True) is False
    assert V.and_(False, False) is False
    assert V.and_(False, None) is False
    assert V.and_(None, True) is None
    assert V.and_(None, False) is False
    assert V.and_(None, None) is None


def test_or_truth_table():
    assert V.or_(True, True) is True
    assert V.or_(True, False) is True
    assert V.or_(True, None) is True
    assert V.or_(False, True) is True
    assert V.or_(False, False) is False
    assert V.or_(False, None) is None
    assert V.or_(None, True) is True
    assert V.or_(None, False) is None
    assert V.or_(None, None) is None


def test_not_truth_table():
    assert V.not_(True) is False
    assert V.not_(False) is True
    assert V.not_(None) is None


def test_null_eq_null_is_unknown():
    assert V.compare_eq(None, None) is None
    assert V.compare_eq(None, 5) is None
    assert V.compare_eq(5, None) is None


def test_bool_is_distinct_type():
    assert V.type_of(True) == "BOOL"
    assert V.is_numeric(True) is False
    assert V.is_numeric(1) is True


def test_bool_vs_number_comparison_raises():
    with pytest.raises(TypeMismatchError):
        V.compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        V.compare_lt(True, 1)


def test_text_vs_number_comparison_raises():
    with pytest.raises(TypeMismatchError):
        V.compare_lt("a", 1)


def test_bool_ordering():
    assert V.compare_lt(False, True) is True
    assert V.compare_lt(True, False) is False


# ---- arithmetic ----


def test_division_always_float():
    assert V.arith("/", 7, 2) == 3.5
    assert isinstance(V.arith("/", 4, 2), float)


def test_division_by_zero_is_null():
    assert V.arith("/", 1, 0) is None
    assert V.arith("/", 1, 0.0) is None


def test_modulo_by_zero_is_null():
    assert V.arith("%", 5, 0) is None


def test_modulo_sign_rule():
    assert V.arith("%", -7, 3) == 2


def test_modulo_requires_ints():
    with pytest.raises(TypeMismatchError):
        V.arith("%", 5.0, 2)


def test_arith_null_propagates():
    assert V.arith("+", None, 1) is None
    assert V.negate(None) is None


def test_arith_bool_raises():
    with pytest.raises(TypeMismatchError):
        V.arith("+", True, 1)


def test_arith_int_plus_float_is_float():
    assert V.arith("+", 1, 2.0) == 3.0
    assert isinstance(V.arith("+", 1, 2.0), float)


def test_negate_preserves_type():
    assert V.negate(5) == -5 and isinstance(V.negate(5), int)
    assert V.negate(5.5) == -5.5 and isinstance(V.negate(5.5), float)


# ---- schema ----


def test_schema_rejects_empty_columns():
    with pytest.raises(SchemaError):
        Table("t", [], [])


def test_schema_rejects_duplicate_names():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])


def test_schema_case_sensitive_names_allowed():
    Table("t", [Column("a", "INT"), Column("A", "INT")], [[1, 2]])


def test_schema_rejects_bad_type():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "WEIRD")], [])


def test_schema_rejects_wrong_row_length():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_schema_bool_column_rejects_int():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BOOL")], [[1]])


def test_schema_int_column_rejects_bool():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])


def test_schema_float_widens_int():
    t = Table("t", [Column("a", "FLOAT")], [[3]])
    assert t.rows[0][0] == 3.0
    assert isinstance(t.rows[0][0], float)


def test_schema_int_rejects_float():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])


def test_schema_column_index():
    t = Table("t", [Column("a", "INT")], [])
    assert t.column_index("a") == 0
    with pytest.raises(SchemaError):
        t.column_index("nope")


# ---- lexer / parser basics ----


def test_lex_error_offset():
    with pytest.raises(LexError) as exc:
        m.parse("SELECT # FROM t")
    assert exc.value.offset == 7


def test_float_forms():
    q = m.parse("SELECT 1. FROM t")
    assert q.select_items[0].expr.value == 1.0
    q2 = m.parse("SELECT .5 FROM t")
    assert q2.select_items[0].expr.value == 0.5
    q3 = m.parse("SELECT 1e3 FROM t")
    assert q3.select_items[0].expr.value == 1000.0


def test_text_literal_with_escaped_quote():
    q = m.parse("SELECT 'it''s' FROM t")
    assert q.select_items[0].expr.value == "it's"


def test_predicate_not_associative():
    with pytest.raises(ParseError):
        m.parse("SELECT * FROM t WHERE 1 < 2 < 3")


def test_not_binds_looser_than_comparison():
    q = m.parse("SELECT * FROM t WHERE NOT a = b")
    where = q.where
    assert where.op == "NOT"
    assert where.operand.op == "="


def test_reserved_word_column_name_fails():
    with pytest.raises((ParseError, LexError)):
        m.parse("SELECT order FROM t")


# ---- WHERE / execution semantics ----


def test_where_null_eq_returns_nothing():
    t = people_table()
    r = run("SELECT id FROM people WHERE age = NULL", {"people": t})
    assert r.rows == []


def test_where_type_mismatch_raises():
    t = people_table()
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM people WHERE age", {"people": t})


def test_where_cannot_see_select_alias():
    t = people_table()
    with pytest.raises(UnknownColumnError):
        run("SELECT age AS a FROM people WHERE a > 30", {"people": t})


def test_where_cannot_contain_aggregate():
    t = people_table()
    with pytest.raises(AggregateError):
        run("SELECT id FROM people WHERE count(*) > 1", {"people": t})


def test_simple_where_filters_rows():
    t = people_table()
    r = run("SELECT name FROM people WHERE age > 30", {"people": t})
    assert r.rows == [["Bob"], ["Carol"]]


# ---- joins ----


def test_inner_join():
    p, d = people_table(), dept_table()
    r = run(
        "SELECT people.name, dept.dept FROM people JOIN dept ON people.id = dept.id",
        {"people": p, "dept": d},
    )
    assert r.rows == [["Alice", "eng"], ["Bob", "sales"]]


def test_left_join_fills_null():
    p, d = people_table(), dept_table()
    r = run(
        "SELECT people.name, dept.dept FROM people LEFT JOIN dept ON people.id = dept.id",
        {"people": p, "dept": d},
    )
    assert r.rows == [["Alice", "eng"], ["Bob", "sales"], ["Carol", None], ["Dave", None]]


def test_join_ambiguous_column():
    p = Table("a", [Column("id", "INT")], [[1]])
    q = Table("b", [Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        run("SELECT id FROM a JOIN b ON a.id = b.id", {"a": p, "b": q})


def test_join_unknown_table_qualifier():
    p = Table("a", [Column("id", "INT")], [[1]])
    q = Table("b", [Column("id", "INT")], [[1]])
    with pytest.raises(UnknownTableError):
        run("SELECT z.id FROM a JOIN b ON a.id = b.id", {"a": p, "b": q})


# ---- aggregation / grouping ----


def test_count_star_over_empty_table():
    t = Table("t", [Column("a", "INT")], [])
    r = run("SELECT count(*) FROM t", {"t": t})
    assert r.rows == [[0]]


def test_sum_of_empty_group_is_null():
    t = Table("t", [Column("a", "INT")], [])
    r = run("SELECT sum(a) FROM t", {"t": t})
    assert r.rows == [[None]]


def test_count_ignores_null_but_counts_star():
    t = Table("t", [Column("a", "INT")], [[1], [None], [2]])
    r = run("SELECT count(*), count(a) FROM t", {"t": t})
    assert r.rows == [[3, 2]]


def test_avg_always_float():
    t = Table("t", [Column("a", "INT")], [[1], [2], [3]])
    r = run("SELECT avg(a) FROM t", {"t": t})
    assert r.rows == [[2.0]]
    assert isinstance(r.rows[0][0], float)


def test_sum_type_int_vs_float():
    t = Table("t", [Column("a", "INT")], [[1], [2]])
    r = run("SELECT sum(a) FROM t", {"t": t})
    assert isinstance(r.rows[0][0], int)


def test_nulls_group_together():
    t = Table("t", [Column("a", "INT")], [[1], [None], [None]])
    r = run("SELECT a, count(*) FROM t GROUP BY a", {"t": t})
    assert sorted(r.rows, key=lambda row: (row[0] is None, row[0])) == [[1, 1], [None, 2]]


def test_group_order_follows_first_appearance():
    t = Table("t", [Column("a", "INT")], [[2], [1], [2], [1]])
    r = run("SELECT a FROM t GROUP BY a", {"t": t})
    assert r.rows == [[2], [1]]


def test_min_max_mixed_text_number_raises():
    t = Table("t", [Column("a", "TEXT")], [["x"], ["y"]])
    with pytest.raises(TypeMismatchError):
        run("SELECT min(a + 1) FROM t", {"t": t})


def test_grouping_error_on_ungrouped_column():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    with pytest.raises(GroupingError):
        run("SELECT b, count(*) FROM t GROUP BY a", {"t": t})


def test_grouping_allows_grouping_expression():
    t = Table("t", [Column("name", "TEXT")], [["ab"], ["cd"], ["xyz"]])
    r = run("SELECT length(name), count(*) FROM t GROUP BY length(name)", {"t": t})
    assert sorted(r.rows) == [[2, 2], [3, 1]]


def test_having_filters_groups():
    t = Table("t", [Column("a", "INT")], [[1], [1], [2]])
    r = run("SELECT a, count(*) AS c FROM t GROUP BY a HAVING count(*) > 1", {"t": t})
    assert r.rows == [[1, 2]]


def test_aggregate_nesting_is_parse_error():
    with pytest.raises(ParseError):
        m.parse("SELECT sum(count(x)) FROM t")


# ---- scalar functions ----


def test_concat_null_propagates():
    t = Table("t", [Column("a", "TEXT")], [["x"]])
    r = run("SELECT concat(a, NULL) FROM t", {"t": t})
    assert r.rows == [[None]]


def test_coalesce_first_non_null():
    t = Table("t", [Column("a", "TEXT")], [[None]])
    r = run("SELECT coalesce(a, 'default') FROM t", {"t": t})
    assert r.rows == [["default"]]


def test_arity_error_named():
    t = Table("t", [Column("a", "TEXT")], [["x"]])
    with pytest.raises(ArityError):
        run("SELECT upper(a, a) FROM t", {"t": t})


def test_unknown_function_error():
    t = Table("t", [Column("a", "TEXT")], [["x"]])
    with pytest.raises(UnknownFunctionError):
        run("SELECT frobnicate(a) FROM t", {"t": t})


def test_length_counts_code_points():
    t = Table("t", [Column("a", "TEXT")], [["hello"]])
    r = run("SELECT length(a) FROM t", {"t": t})
    assert r.rows == [[5]]


# ---- distinct / order / limit / offset ----


def test_distinct_removes_duplicates():
    t = Table("t", [Column("a", "INT")], [[1], [1], [2]])
    r = run("SELECT DISTINCT a FROM t", {"t": t})
    assert r.rows == [[1], [2]]


def test_order_by_nulls_last_desc():
    t = Table("t", [Column("a", "INT")], [[1], [None], [2]])
    r = run("SELECT a FROM t ORDER BY a DESC", {"t": t})
    assert r.rows == [[2], [1], [None]]


def test_order_by_nulls_last_asc():
    t = Table("t", [Column("a", "INT")], [[1], [None], [2]])
    r = run("SELECT a FROM t ORDER BY a ASC", {"t": t})
    assert r.rows == [[1], [2], [None]]


def test_order_by_stability():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 1], [1, 2], [1, 3]])
    r = run("SELECT b FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1], [2], [3]]


def test_order_by_alias_visible():
    t = Table("t", [Column("a", "INT")], [[3], [1], [2]])
    r = run("SELECT a AS x FROM t ORDER BY x", {"t": t})
    assert r.rows == [[1], [2], [3]]


def test_order_by_input_column_without_distinct():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 3], [2, 1]])
    r = run("SELECT a FROM t ORDER BY b", {"t": t})
    assert r.rows == [[2], [1]]


def test_order_by_input_column_with_distinct_fails():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 3], [2, 1]])
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT a FROM t ORDER BY b", {"t": t})


def test_alias_wins_over_input_column_name():
    t = Table("t", [Column("a", "INT")], [[3], [1]])
    r = run("SELECT (0 - a) AS a FROM t ORDER BY a", {"t": t})
    assert r.rows == [[-3], [-1]]


def test_limit_and_offset():
    t = Table("t", [Column("a", "INT")], [[1], [2], [3], [4]])
    r = run("SELECT a FROM t ORDER BY a LIMIT 2 OFFSET 1", {"t": t})
    assert r.rows == [[2], [3]]


# ---- star expansion / naming ----


def test_star_expansion():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    r = run("SELECT * FROM t", {"t": t})
    assert r.columns == ["a", "b"]
    assert r.rows == [[1, 2]]


def test_default_expr_name_collapses_whitespace():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    r = run("SELECT a  +   b FROM t", {"t": t})
    assert r.columns == ["a + b"]


def test_count_star_default_name():
    t = Table("t", [Column("a", "INT")], [[1]])
    r = run("SELECT count(*) FROM t", {"t": t})
    assert r.columns == ["count(*)"]


# ---- CLI ----


def test_cli_success_exit_code(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("id:INT,age:INT\n1,25\n2,35\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={csv_path}", "SELECT count(*) FROM t WHERE age > 30"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "count(*)\n1"


def test_cli_usage_error_missing_table():
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "SELECT 1 FROM t"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_cli_usage_error_bad_file(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", "t=nope.csv", "SELECT 1 FROM t"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""


def test_cli_microdb_error_exit_code(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("id:INT\n1\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={csv_path}", "SELECT nope FROM t"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 3
    assert proc.stdout == ""
    assert proc.stderr.strip() != ""


def test_cli_null_renders_empty(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("id:INT,name:TEXT\n1,\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={csv_path}", "SELECT name FROM t"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    lines = proc.stdout.split("\n")
    assert lines[1] == ""


def test_cli_bool_lowercase(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("id:INT,flag:BOOL\n1,TRUE\n2,false\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={csv_path}", "SELECT flag FROM t ORDER BY id"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip().splitlines()[1:] == ["true", "false"]


def test_cli_quoting_rule(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text("id:INT,name:TEXT\n1,\"a,b\"\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={csv_path}", "SELECT name FROM t"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0
    assert '"a,b"' in proc.stdout


def test_public_api_execute_function():
    t = people_table()
    r = m.execute("SELECT name FROM people WHERE age > 30", {"people": t})
    assert isinstance(r, m.Result)
    assert r.columns == ["name"]


def test_plan_is_a_sequence():
    q = m.parse("SELECT a FROM t WHERE a > 1")
    p = m.plan(q)
    assert len(p) > 0
    names = [s.name for s in p]
    assert "from" in names and "where" in names and "select" in names

"""Tests for microdb."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

from microdb import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    Column,
    GroupingError,
    LexError,
    ParseError,
    Plan,
    SchemaError,
    Table,
    TypeMismatchError,
    UnknownColumnError,
    UnknownFunctionError,
    UnknownTableError,
    and_,
    arith,
    compare_eq,
    compare_lt,
    execute,
    is_numeric,
    negate,
    not_,
    or_,
    parse,
    plan,
    type_of,
)
from microdb.__main__ import main
from microdb.planner import FromStage, SelectStage
from microdb.value import compare_ne


def T(name: str, cols: list[tuple[str, str]], rows: list[list[object]]) -> Table:
    return Table(name, [Column(n, t) for n, t in cols], rows)


def q(sql: str, *tables: Table):
    return execute(sql, {t.name: t for t in tables})


def test_type_of_kinds() -> None:
    assert type_of(1) == "INT"
    assert type_of(1.5) == "FLOAT"
    assert type_of("x") == "TEXT"
    assert type_of(True) == "BOOL"
    assert type_of(False) == "BOOL"
    assert type_of(None) == "NULL"


def test_bool_is_not_numeric() -> None:
    assert is_numeric(3)
    assert is_numeric(1.0)
    assert not is_numeric(True)
    assert not is_numeric(False)
    assert not is_numeric(None)
    assert not is_numeric("1")


def test_and_truth_table() -> None:
    vals = [True, False, None]
    expected = [
        [True, False, None],
        [False, False, False],
        [None, False, None],
    ]
    for i, a in enumerate(vals):
        for j, b in enumerate(vals):
            assert and_(a, b) is expected[i][j]


def test_or_truth_table() -> None:
    vals = [True, False, None]
    expected = [
        [True, True, True],
        [True, False, None],
        [True, None, None],
    ]
    for i, a in enumerate(vals):
        for j, b in enumerate(vals):
            assert or_(a, b) is expected[i][j]


def test_not_truth_table() -> None:
    assert not_(True) is False
    assert not_(False) is True
    assert not_(None) is None


def test_null_eq_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(None, 1) is None
    assert compare_lt(None, 1) is None
    assert compare_ne(None, None) is None


def test_compare_numeric_and_text_and_bool() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 2.5) is True
    assert compare_lt("a", "b") is True
    assert compare_lt(False, True) is True
    assert compare_eq(False, False) is True
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("a", 1)


def test_division_by_zero_is_null() -> None:
    assert arith("/", 7, 2) == 3.5
    assert arith("/", 1, 0) is None
    assert arith("/", 1.0, 0.0) is None
    assert arith("%", 1, 0) is None


def test_arith_rules() -> None:
    assert arith("+", 1, 2) == 3
    assert type_of(arith("+", 1, 2)) == "INT"
    assert type_of(arith("+", 1, 2.0)) == "FLOAT"
    assert type_of(arith("/", 8, 2)) == "FLOAT"
    assert arith("%", -7, 3) == 2
    assert negate(3) == -3
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        arith("+", "a", "b")
    with pytest.raises(TypeMismatchError):
        arith("%", 1.5, 2)
    with pytest.raises(TypeMismatchError):
        negate(True)


def test_schema_validation() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "NOPE")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1.0]])
    t = Table("t", [Column("a", "FLOAT")], [[2]])
    assert t.rows[0][0] == 2.0
    assert t.column_index("a") == 0


def test_select_basic() -> None:
    t = T("t", [("id", "INT"), ("name", "TEXT")], [[1, "a"], [2, "b"]])
    r = q("SELECT id, name FROM t", t)
    assert r.columns == ["id", "name"]
    assert r.rows == [[1, "a"], [2, "b"]]


def test_where_unknown_drops_row() -> None:
    t = T("t", [("a", "INT")], [[1], [None], [3]])
    r = q("SELECT a FROM t WHERE a = NULL", t)
    assert r.rows == []
    r2 = q("SELECT a FROM t WHERE a IS NULL", t)
    assert r2.rows == [[None]]


def test_where_requires_bool() -> None:
    t = T("t", [("a", "INT")], [[1]])
    with pytest.raises(TypeMismatchError):
        q("SELECT a FROM t WHERE 1", t)


def test_where_cannot_use_alias() -> None:
    t = T("t", [("a", "INT")], [[1]])
    with pytest.raises(UnknownColumnError):
        q("SELECT a AS b FROM t WHERE b = 1", t)


def test_order_by_can_use_alias() -> None:
    t = T("t", [("a", "INT")], [[2], [1]])
    r = q("SELECT a + 1 AS b FROM t ORDER BY b", t)
    assert r.rows == [[2], [3]]


def test_alias_wins_over_input() -> None:
    t = T("t", [("a", "INT")], [[2], [1]])
    r = q("SELECT a + 10 AS a FROM t ORDER BY a", t)
    assert r.rows == [[11], [12]]


def test_count_star_empty_table() -> None:
    t = T("t", [("a", "INT")], [])
    r = q("SELECT count(*) FROM t", t)
    assert r.columns == ["count(*)"]
    assert r.rows == [[0]]


def test_sum_empty_group_is_null() -> None:
    t = T("t", [("a", "INT"), ("g", "INT")], [])
    r = q("SELECT sum(a) FROM t", t)
    assert r.rows == [[None]]
    t2 = T("t", [("a", "INT"), ("g", "INT")], [[None, 1]])
    r2 = q("SELECT g, sum(a) FROM t GROUP BY g", t2)
    assert r2.rows == [[1, None]]


def test_nulls_group_together() -> None:
    t = T("t", [("g", "INT"), ("v", "INT")], [[None, 1], [None, 2], [3, 4]])
    r = q("SELECT g, count(*) FROM t GROUP BY g", t)
    assert r.rows == [[None, 2], [3, 1]]


def test_nulls_sort_last_desc() -> None:
    t = T("t", [("a", "INT")], [[1], [None], [3], [None], [2]])
    r = q("SELECT a FROM t ORDER BY a DESC", t)
    assert r.rows == [[3], [2], [1], [None], [None]]
    r2 = q("SELECT a FROM t ORDER BY a ASC", t)
    assert r2.rows == [[1], [2], [3], [None], [None]]


def test_sort_stability() -> None:
    t = T(
        "t",
        [("k", "INT"), ("s", "TEXT")],
        [[1, "a"], [1, "b"], [2, "c"], [1, "d"]],
    )
    r = q("SELECT s FROM t ORDER BY k", t)
    assert r.rows == [["a"], ["b"], ["d"], ["c"]]


def test_left_join_null_fill() -> None:
    l = T("l", [("id", "INT"), ("n", "TEXT")], [[1, "a"], [2, "b"]])
    rgt = T("r", [("id", "INT"), ("x", "TEXT")], [[1, "x"]])
    r = execute(
        "SELECT l.n, r.x FROM l LEFT JOIN r ON l.id = r.id",
        {"l": l, "r": rgt},
    )
    assert r.rows == [["a", "x"], ["b", None]]


def test_inner_join() -> None:
    l = T("l", [("id", "INT")], [[1], [2]])
    rgt = T("r", [("id", "INT")], [[2], [3]])
    r = execute("SELECT l.id FROM l INNER JOIN r ON l.id = r.id", {"l": l, "r": rgt})
    assert r.rows == [[2]]


def test_ambiguous_column() -> None:
    l = T("l", [("id", "INT")], [[1]])
    rgt = T("r", [("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM l INNER JOIN r ON l.id = r.id", {"l": l, "r": rgt})


def test_unknown_table_qualifier() -> None:
    t = T("t", [("a", "INT")], [[1]])
    with pytest.raises(UnknownTableError):
        q("SELECT u.a FROM t", t)


def test_where_aggregate_error() -> None:
    t = T("t", [("a", "INT")], [[1]])
    with pytest.raises(AggregateError):
        q("SELECT a FROM t WHERE count(*) > 0", t)


def test_grouping_error() -> None:
    t = T("t", [("a", "INT"), ("b", "INT")], [[1, 2]])
    with pytest.raises(GroupingError):
        q("SELECT a, count(*) FROM t", t)
    with pytest.raises(GroupingError):
        q("SELECT b FROM t GROUP BY a", t)


def test_distinct_and_limit_offset() -> None:
    t = T("t", [("a", "INT")], [[1], [1], [2], [3]])
    r = q("SELECT DISTINCT a FROM t ORDER BY a LIMIT 1 OFFSET 1", t)
    assert r.rows == [[2]]


def test_scalar_functions() -> None:
    t = T("t", [("s", "TEXT"), ("n", "INT")], [["Ab", -2], [None, None]])
    r = q(
        "SELECT upper(s), lower(s), length(s), abs(n), coalesce(s, 'z') FROM t",
        t,
    )
    assert r.rows[0] == ["AB", "ab", 2, 2, "Ab"]
    assert r.rows[1][0] is None
    assert r.rows[1][4] == "z"
    r2 = q("SELECT concat('a', s) FROM t", t)
    assert r2.rows[0] == ["aAb"]
    assert r2.rows[1][0] is None


def test_unknown_function_and_arity() -> None:
    t = T("t", [("a", "TEXT")], [["x"]])
    with pytest.raises(UnknownFunctionError):
        q("SELECT foo(a) FROM t", t)
    with pytest.raises(ArityError):
        q("SELECT upper(a, a) FROM t", t)
    with pytest.raises(ArityError):
        q("SELECT concat(a) FROM t", t)


def test_nested_aggregate_parse_error() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(a)) FROM t")


def test_predicate_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("SELECT 1 FROM t WHERE 1 < 2 < 3")


def test_not_binds_looser_than_compare() -> None:
    t = T("t", [("a", "INT")], [[1], [2]])
    r = q("SELECT a FROM t WHERE NOT a = 1", t)
    assert r.rows == [[2]]


def test_lex_error_offset() -> None:
    with pytest.raises(LexError) as ei:
        parse("SELECT 1 FROM t WHERE a @ 1")
    assert ei.value.offset >= 0


def test_comment_and_string_escape() -> None:
    t = T("t", [("a", "TEXT")], [["x"]])
    r = q("SELECT 'it''s' FROM t -- comment\n", t)
    assert r.rows == [["it's"]]


def test_float_lexemes() -> None:
    t = T("t", [("a", "INT")], [[1]])
    r = q("SELECT 1., .5, 1.5E-2 FROM t", t)
    assert r.rows[0][0] == 1.0
    assert r.rows[0][1] == 0.5
    assert r.rows[0][2] == 0.015


def test_avg_and_sum_types() -> None:
    t = T("t", [("a", "INT"), ("b", "FLOAT")], [[1, 1.0], [3, 3.0]])
    r = q("SELECT avg(a), sum(a), sum(b) FROM t", t)
    assert r.rows[0][0] == 2.0
    assert r.rows[0][1] == 4
    assert type_of(r.rows[0][1]) == "INT"
    assert type_of(r.rows[0][2]) == "FLOAT"


def test_min_max_text() -> None:
    t = T("t", [("s", "TEXT")], [["b"], [None], ["a"]])
    r = q("SELECT min(s), max(s) FROM t", t)
    assert r.rows == [["a", "b"]]


def test_having() -> None:
    t = T("t", [("g", "INT"), ("v", "INT")], [[1, 1], [1, 2], [2, 9]])
    r = q("SELECT g, count(*) FROM t GROUP BY g HAVING count(*) > 1", t)
    assert r.rows == [[1, 2]]


def test_select_star_and_qualified_star() -> None:
    t = T("t", [("a", "INT"), ("b", "INT")], [[1, 2]])
    r = q("SELECT * FROM t", t)
    assert r.columns == ["a", "b"]
    r2 = q("SELECT t.* FROM t", t)
    assert r2.rows == [[1, 2]]


def test_plan_is_sequence() -> None:
    p = plan(parse("SELECT a FROM t WHERE a > 1 LIMIT 2"))
    assert isinstance(p, Plan)
    assert len(p) >= 3
    assert isinstance(p[0], FromStage)
    names = [s.name for s in p]
    assert "from" in names and "select" in names
    assert any(isinstance(s, SelectStage) for s in p)


def test_keywords_case_insensitive_idents_sensitive() -> None:
    t = T("t", [("Name", "TEXT"), ("name", "TEXT")], [["A", "b"]])
    r = q("sElEcT Name FROM t", t)
    assert r.rows == [["A"]]


def test_output_name_collapsed_whitespace() -> None:
    t = T("t", [("a", "INT"), ("b", "INT")], [[1, 2]])
    r = q("SELECT a   +   b FROM t", t)
    assert r.columns == ["a + b"]


def test_group_by_expression() -> None:
    t = T("t", [("name", "TEXT")], [["aa"], ["bb"], ["c"]])
    r = q("SELECT length(name), count(*) FROM t GROUP BY length(name)", t)
    assert r.rows == [[2, 2], [1, 1]]


def test_true_false_null_literals() -> None:
    t = T("t", [("a", "INT")], [[1]])
    r = q("SELECT TRUE, FALSE, NULL FROM t", t)
    assert r.rows == [[True, False, None]]


def test_cli_success(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "people.csv"
    p.write_text("age:INT,name:TEXT\n40,Ann\n20,Bob\n35,Cy\n", encoding="utf-8")
    buf = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        code = main(["--table", f"t={p}", "SELECT count(*) FROM t WHERE age > 30"])
    assert code == 0
    assert err.getvalue() == ""
    assert buf.getvalue() == "count(*)\n2\n"


def test_cli_usage_exit_2() -> None:
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main([])
    assert code == 2
    assert out.getvalue() == ""
    assert err.getvalue() != ""


def test_cli_unreadable_exit_2(tmp_path) -> None:  # type: ignore[no-untyped-def]
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--table", f"t={tmp_path / 'missing.csv'}", "SELECT 1 FROM t"])
    assert code == 2
    assert out.getvalue() == ""


def test_cli_query_error_exit_3(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("a:INT\n1\n", encoding="utf-8")
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--table", f"t={p}", "SELECT nope FROM t"])
    assert code == 3
    assert out.getvalue() == ""


def test_cli_malformed_header_exit_2(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("aINT\n1\n", encoding="utf-8")
    err = io.StringIO()
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--table", f"t={p}", "SELECT a FROM t"])
    assert code == 2
    assert out.getvalue() == ""


def test_cli_quoting_and_null(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("s:TEXT\n\n''\nhello\n", encoding="utf-8")
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["--table", f"t={p}", "SELECT s FROM t"])
    assert code == 0
    assert err.getvalue() == ""
    assert out.getvalue() == "s\n\n\nhello\n"


def test_empty_string_vs_null_csv(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("s:TEXT\n\n''\n", encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(["--table", f"t={p}", "SELECT s IS NULL, length(s) FROM t"])
    assert code == 0
    lines = out.getvalue().split("\n")
    assert "true" in lines[1]
    assert "false,0" in lines[2]


def test_bool_csv_and_output(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("b:BOOL\ntrue\nFALSE\n", encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(["--table", f"t={p}", "SELECT b FROM t"])
    assert code == 0
    assert out.getvalue() == "b\ntrue\nfalse\n"


def test_join_row_order() -> None:
    l = T("l", [("id", "INT")], [[1], [2]])
    rgt = T("r", [("id", "INT"), ("v", "INT")], [[1, 10], [1, 11], [2, 20]])
    r = execute(
        "SELECT r.v FROM l INNER JOIN r ON l.id = r.id",
        {"l": l, "r": rgt},
    )
    assert r.rows == [[10], [11], [20]]


def test_count_expr_ignores_null() -> None:
    t = T("t", [("a", "INT")], [[1], [None], [2]])
    r = q("SELECT count(a), count(*) FROM t", t)
    assert r.rows == [[2, 3]]


def test_select_true_vs_int_distinct() -> None:
    t = T("t", [("a", "INT"), ("b", "BOOL")], [[1, True]])
    r = q("SELECT DISTINCT a, b FROM t", t)
    assert r.rows == [[1, True]]


def test_order_by_aggregate() -> None:
    t = T("t", [("g", "INT"), ("v", "INT")], [[1, 10], [2, 1], [1, 20]])
    r = q("SELECT g FROM t GROUP BY g ORDER BY count(*) DESC, g", t)
    assert r.rows == [[1], [2]]


def test_bare_join_is_inner() -> None:
    l = T("l", [("id", "INT")], [[1], [2]])
    rgt = T("r", [("id", "INT")], [[2]])
    r = execute("SELECT l.id FROM l JOIN r ON l.id = r.id", {"l": l, "r": rgt})
    assert r.rows == [[2]]


def test_qualified_select_name() -> None:
    t = T("t", [("a", "INT")], [[7]])
    r = q("SELECT t.a FROM t", t)
    assert r.columns == ["t.a"]
    assert r.rows == [[7]]


def test_count_arity_and_is_not_null() -> None:
    t = T("t", [("a", "INT")], [[1], [None]])
    r = q("SELECT a FROM t WHERE a IS NOT NULL", t)
    assert r.rows == [[1]]
    with pytest.raises(ArityError):
        q("SELECT count() FROM t", t)
    with pytest.raises(ArityError):
        q("SELECT count(a, a) FROM t", t)


def test_cli_quotes_comma(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "t.csv"
    p.write_text("s:TEXT\nhi\n", encoding="utf-8")
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(["--table", f"t={p}", "SELECT concat(s, ',x') FROM t"])
    assert code == 0
    assert out.getvalue() == '"concat(s, \',x\')"\n"hi,x"\n'

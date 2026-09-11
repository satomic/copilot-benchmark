"""Test suite for microdb."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import microdb
from microdb import (
    AggregateError,
    AmbiguousColumnError,
    ArityError,
    Column,
    GroupingError,
    LexError,
    ParseError,
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
    execute_plan,
    is_numeric,
    negate,
    not_,
    or_,
    parse,
    plan,
    type_of,
)
from microdb.__main__ import main
from microdb.lexer import tokenize

T, F, U = True, False, None


# --- fixtures -----------------------------------------------------------------


def people() -> Table:
    cols = [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT"), Column("dept", "TEXT")]
    rows = [
        [1, "ann", 30, "a"],
        [2, "bob", None, "b"],
        [3, "cy", 40, None],
        [4, "dee", 25, "a"],
        [5, "eve", 50, None],
    ]
    return Table("t", cols, rows)


def depts() -> Table:
    return Table("d", [Column("code", "TEXT"), Column("label", "TEXT")], [["a", "Alpha"], ["b", "Beta"]])


def empty() -> Table:
    return Table("e", [Column("x", "INT")], [])


TABLES = {"t": people(), "d": depts(), "e": empty()}


def run(sql: str) -> list[list[object]]:
    return execute(sql, TABLES).rows


# --- value model --------------------------------------------------------------


def test_type_of_and_bool_is_not_int() -> None:
    assert type_of(1) == "INT"
    assert type_of(1.0) == "FLOAT"
    assert type_of("x") == "TEXT"
    assert type_of(True) == "BOOL"
    assert type_of(None) == "NULL"
    assert is_numeric(1) and is_numeric(1.5)
    assert not is_numeric(True) and not is_numeric(None) and not is_numeric("1")


@pytest.mark.parametrize(
    "a,b,expected_and,expected_or",
    [
        (T, T, T, T),
        (T, F, F, T),
        (T, U, U, T),
        (F, T, F, T),
        (F, F, F, F),
        (F, U, F, U),
        (U, T, U, T),
        (U, F, F, U),
        (U, U, U, U),
    ],
)
def test_three_valued_truth_tables(a, b, expected_and, expected_or) -> None:
    assert and_(a, b) is expected_and
    assert or_(a, b) is expected_or


def test_not_truth_table() -> None:
    assert not_(T) is F
    assert not_(F) is T
    assert not_(U) is U


def test_null_equals_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(1, None) is None
    assert compare_lt(None, "a") is None


def test_comparison_rules() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True
    assert compare_lt("a", "b") is True
    assert compare_lt(False, True) is True
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("1", 1)


def test_arithmetic_types() -> None:
    assert arith("+", 1, 2) == 3 and type_of(arith("+", 1, 2)) == "INT"
    assert type_of(arith("*", 1, 2.0)) == "FLOAT"
    assert arith("/", 7, 2) == 3.5
    assert type_of(arith("/", 4, 2)) == "FLOAT"
    assert arith("%", -7, 3) == 2
    assert arith("+", None, 1) is None
    with pytest.raises(TypeMismatchError):
        arith("+", "a", "b")
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        arith("%", 7.0, 2)


def test_division_by_zero_yields_null() -> None:
    assert arith("/", 1, 0) is None
    assert arith("/", 1, 0.0) is None
    assert arith("%", 1, 0) is None


def test_negate() -> None:
    assert negate(3) == -3 and type_of(negate(3)) == "INT"
    assert negate(2.5) == -2.5
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        negate(True)


# --- schema -------------------------------------------------------------------


def test_table_validation_errors() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "DATE")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BOOL")], [[1]])


def test_table_case_sensitive_names_and_float_widening() -> None:
    t = Table("t", [Column("a", "INT"), Column("A", "FLOAT")], [[1, 2], [None, None]])
    assert t.rows[0][1] == 2.0 and isinstance(t.rows[0][1], float)
    assert t.column_index("A") == 1
    with pytest.raises(SchemaError):
        t.column_index("zzz")


# --- lexer and parser ---------------------------------------------------------


def test_lexer_numbers_and_text() -> None:
    kinds = [(t.kind, t.value) for t in tokenize("1 1. .5 1e3 1.5E-2 'it''s' x")]
    assert kinds[:6] == [
        ("INT", 1),
        ("FLOAT", 1.0),
        ("FLOAT", 0.5),
        ("FLOAT", 1000.0),
        ("FLOAT", 0.015),
        ("TEXT", "it's"),
    ]
    assert kinds[6] == ("IDENT", "x")


def test_lexer_comments_keywords_and_errors() -> None:
    toks = tokenize("select -- comment\n  x")
    assert [t.kind for t in toks] == ["KW", "IDENT", "EOF"]
    assert toks[0].value == "SELECT"
    with pytest.raises(LexError) as info:
        tokenize("SELECT a @ b")
    assert info.value.offset == 9
    with pytest.raises(LexError):
        tokenize("SELECT 'open")


def test_parse_chained_comparison_is_error() -> None:
    with pytest.raises(ParseError):
        parse("SELECT 1 < 2 < 3 FROM t")


def test_parse_nested_aggregate_is_error() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")


def test_parse_not_binds_looser_than_comparison() -> None:
    assert run("SELECT NOT age = 30 FROM t WHERE id = 1") == [[False]]
    assert run("SELECT id FROM t WHERE NOT age IS NULL AND age > 26") == [[1], [3], [5]]


def test_parse_errors_carry_offset() -> None:
    with pytest.raises(ParseError) as info:
        parse("SELECT FROM t")
    assert info.value.offset == 7
    with pytest.raises(ParseError):
        parse("SELECT a FROM t WHERE")
    with pytest.raises(ParseError):
        parse("SELECT a FROM t extra")


def test_keywords_are_not_identifiers() -> None:
    with pytest.raises(ParseError):
        parse("SELECT order FROM t")


# --- scalar functions ---------------------------------------------------------


def test_scalar_functions() -> None:
    row = run(
        "SELECT concat('a', 'b', 'c'), upper('x'), lower('Y'), length('héllo'), abs(-2), "
        "abs(-2.5), coalesce(NULL, NULL, 3), concat('a', NULL), coalesce(NULL) FROM t LIMIT 1"
    )
    assert row == [["abc", "X", "y", 5, 2, 2.5, 3, None, None]]


def test_scalar_function_errors() -> None:
    with pytest.raises(UnknownFunctionError):
        run("SELECT nosuch(1) FROM t")
    with pytest.raises(ArityError, match="upper"):
        run("SELECT upper('a', 'b') FROM t")
    with pytest.raises(ArityError):
        run("SELECT concat('a') FROM t")
    with pytest.raises(TypeMismatchError):
        run("SELECT upper(1) FROM t")
    with pytest.raises(TypeMismatchError):
        run("SELECT abs('x') FROM t")


# --- WHERE and NULL semantics -------------------------------------------------


def test_where_null_comparison_drops_rows() -> None:
    assert run("SELECT id FROM t WHERE age = NULL") == []
    assert run("SELECT id FROM t WHERE age > 26") == [[1], [3], [5]]
    assert run("SELECT id FROM t WHERE age IS NULL") == [[2]]


def test_where_requires_bool() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t WHERE 1")
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t WHERE age > 'x'")


def test_where_cannot_contain_aggregate() -> None:
    with pytest.raises(AggregateError):
        run("SELECT id FROM t WHERE count(*) > 1")


def test_alias_visible_in_order_by_but_not_where() -> None:
    assert run("SELECT id, age * 2 AS doubled FROM t ORDER BY doubled LIMIT 2") == [[4, 50], [1, 60]]
    with pytest.raises(UnknownColumnError):
        run("SELECT id, age * 2 AS doubled FROM t WHERE doubled > 50")


def test_alias_shadows_input_column_in_order_by() -> None:
    rows = run("SELECT id, 100 - age AS age FROM t WHERE age IS NOT NULL ORDER BY age")
    assert rows == [[5, 50], [3, 60], [1, 70], [4, 75]]


# --- aggregates ---------------------------------------------------------------


def test_count_star_over_empty_table_yields_one_row() -> None:
    res = execute("SELECT count(*) FROM e", TABLES)
    assert res.columns == ["count(*)"]
    assert res.rows == [[0]]


def test_sum_of_empty_group_is_null() -> None:
    assert run("SELECT sum(x), avg(x), min(x), max(x), count(x) FROM e") == [[None, None, None, None, 0]]
    assert run("SELECT sum(age) FROM t WHERE age > 1000") == [[None]]


def test_aggregates_ignore_nulls() -> None:
    assert run("SELECT count(*), count(age), sum(age), avg(age), min(age), max(age) FROM t") == [
        [5, 4, 145, 36.25, 25, 50]
    ]


def test_sum_and_avg_types() -> None:
    f = Table("f", [Column("v", "FLOAT")], [[1], [2]])
    res = execute("SELECT sum(v), avg(v) FROM f", {"f": f})
    assert res.rows == [[3.0, 1.5]]
    assert type_of(res.rows[0][0]) == "FLOAT"
    res = execute("SELECT sum(age), avg(age) FROM t WHERE id = 1", TABLES)
    assert type_of(res.rows[0][0]) == "INT" and type_of(res.rows[0][1]) == "FLOAT"


def test_aggregate_type_errors() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT sum(name) FROM t")
    m = Table("m", [Column("a", "TEXT"), Column("b", "INT")], [["x", None], [None, 1]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT min(coalesce(a, b)) FROM m", {"m": m})
    with pytest.raises(ArityError):
        run("SELECT count(id, name) FROM t")
    with pytest.raises(ParseError):
        run("SELECT sum(*) FROM t")


def test_min_max_text_and_names_case_insensitive() -> None:
    assert run("SELECT MIN(name), Max(name) FROM t") == [["ann", "eve"]]


# --- grouping -----------------------------------------------------------------


def test_nulls_group_together_and_groups_keep_first_seen_order() -> None:
    assert run("SELECT dept, count(*) FROM t GROUP BY dept") == [["a", 2], ["b", 1], [None, 2]]


def test_group_by_expression_and_having() -> None:
    rows = run("SELECT length(name) AS l, count(*) FROM t GROUP BY length(name) HAVING count(*) > 1")
    assert rows == [[3, 4]]


def test_non_grouped_column_in_select_raises() -> None:
    with pytest.raises(GroupingError):
        run("SELECT name FROM t GROUP BY dept")
    with pytest.raises(GroupingError):
        run("SELECT name, count(*) FROM t")


def test_having_without_group_by_is_single_group() -> None:
    assert run("SELECT count(*) FROM t HAVING count(*) > 100") == []
    assert run("SELECT count(*) FROM t HAVING count(*) > 1") == [[5]]


def test_grouping_keys_distinguish_bool_from_int() -> None:
    g = Table("g", [Column("i", "INT"), Column("b", "BOOL")], [[1, True], [1, True], [0, False]])
    assert execute("SELECT i, count(*) FROM g GROUP BY i", {"g": g}).rows == [[1, 2], [0, 1]]
    assert execute("SELECT b, count(*) FROM g GROUP BY b", {"g": g}).rows == [[True, 2], [False, 1]]


# --- ordering -----------------------------------------------------------------


def test_nulls_sort_last_in_both_directions() -> None:
    assert run("SELECT age FROM t ORDER BY age") == [[25], [30], [40], [50], [None]]
    assert run("SELECT age FROM t ORDER BY age DESC") == [[50], [40], [30], [25], [None]]


def test_sort_is_stable() -> None:
    rows = run("SELECT id, dept FROM t ORDER BY dept")
    assert rows == [[1, "a"], [4, "a"], [2, "b"], [3, None], [5, None]]
    rows = run("SELECT id, dept FROM t ORDER BY dept DESC")
    assert rows == [[2, "b"], [1, "a"], [4, "a"], [3, None], [5, None]]


def test_multi_key_sort() -> None:
    rows = run("SELECT id FROM t ORDER BY dept DESC, age DESC")
    assert rows == [[2], [1], [4], [5], [3]]


def test_sort_type_mismatch_raises() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t ORDER BY coalesce(dept, age)")


def test_order_by_after_distinct_sees_only_output_columns() -> None:
    assert run("SELECT DISTINCT dept FROM t ORDER BY dept DESC") == [["b"], ["a"], [None]]
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT dept FROM t ORDER BY age")
    # Without DISTINCT, input columns remain visible.
    assert run("SELECT dept FROM t ORDER BY age DESC LIMIT 1") == [[None]]


def test_distinct_removes_duplicates_including_null_rows() -> None:
    assert run("SELECT DISTINCT dept, age IS NULL FROM t") == [["a", False], ["b", True], [None, False]]


def test_offset_before_limit() -> None:
    assert run("SELECT id FROM t ORDER BY id LIMIT 2 OFFSET 1") == [[2], [3]]
    assert run("SELECT id FROM t ORDER BY id OFFSET 4") == [[5]]
    assert run("SELECT id FROM t LIMIT 0") == []


# --- joins --------------------------------------------------------------------


def test_inner_join() -> None:
    rows = run("SELECT t.id, d.label FROM t INNER JOIN d ON t.dept = d.code")
    assert rows == [[1, "Alpha"], [2, "Beta"], [4, "Alpha"]]
    assert run("SELECT id FROM t JOIN d ON dept = code") == [[1], [2], [4]]


def test_left_join_fills_nulls_and_keeps_order() -> None:
    res = execute("SELECT * FROM t LEFT JOIN d ON t.dept = d.code", TABLES)
    assert res.columns == ["id", "name", "age", "dept", "code", "label"]
    assert res.rows == [
        [1, "ann", 30, "a", "a", "Alpha"],
        [2, "bob", None, "b", "b", "Beta"],
        [3, "cy", 40, None, None, None],
        [4, "dee", 25, "a", "a", "Alpha"],
        [5, "eve", 50, None, None, None],
    ]


def test_join_column_resolution_errors() -> None:
    d2 = Table("d2", [Column("id", "INT"), Column("label", "TEXT")], [[1, "x"]])
    tabs = {"t": people(), "d2": d2}
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM t JOIN d2 ON t.id = d2.id", tabs)
    with pytest.raises(UnknownTableError):
        execute("SELECT zz.id FROM t JOIN d2 ON t.id = d2.id", tabs)
    with pytest.raises(UnknownTableError):
        execute("SELECT zz.* FROM t", tabs)
    with pytest.raises(UnknownTableError):
        execute("SELECT 1 FROM nope", tabs)
    assert execute("SELECT d2.*, t.id FROM t JOIN d2 ON t.id = d2.id", tabs).columns == ["id", "label", "id"]


# --- result columns and plan --------------------------------------------------


def test_output_column_names() -> None:
    res = execute("SELECT id, t.name, age   +   1, count(*) AS n, upper( name ) FROM t GROUP BY id, name, age", TABLES)
    assert res.columns == ["id", "name", "age + 1", "n", "upper( name )"]


def test_plan_is_inspectable_sequence() -> None:
    p = plan(parse("SELECT DISTINCT dept FROM t WHERE age > 1 GROUP BY dept HAVING count(*) > 0 ORDER BY dept LIMIT 1 OFFSET 1"))
    assert [s.name for s in p] == [
        "scan", "filter", "group", "having", "project", "distinct", "sort", "offset", "limit"
    ]
    assert len(p) == 9 and p[0].table == "t"
    # WHERE drops bob (NULL age), leaving depts a, None; OFFSET 1 selects the NULL group.
    assert execute_plan(p, TABLES).rows == [[None]]


def test_public_api_surface() -> None:
    assert len(microdb.__all__) > 0
    for name in microdb.__all__:
        assert hasattr(microdb, name)


# --- CLI ----------------------------------------------------------------------


def write_csv(tmp_path: Path, text: str, name: str = "people.csv") -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    return str(path)


CSV = "id:INT,name:TEXT,age:INT,active:BOOL\n1,ann,34,true\n2,bob,28,FALSE\n3,\"cy, jr\",45,true\n4,'',,false\n"


def test_cli_success_and_csv_formatting(tmp_path: Path, capsys) -> None:
    path = write_csv(tmp_path, CSV)
    code = main(["--table", "t=" + path, "SELECT count(*) FROM t WHERE age > 30"])
    assert code == 0
    assert capsys.readouterr().out == "count(*)\n2\n"
    code = main(["--table", "t=" + path, "SELECT name, age, active, length(name) FROM t ORDER BY id"])
    assert code == 0
    out = capsys.readouterr().out
    assert out == "name,age,active,length(name)\nann,34,true,3\nbob,28,false,3\n\"cy, jr\",45,true,6\n,,false,0\n"


def test_cli_quotes_double_quotes_and_null_column(tmp_path: Path, capsys) -> None:
    path = write_csv(tmp_path, 'v:TEXT\n"say ""hi"""\n\n')
    assert main(["--table", "t=" + path, "SELECT v FROM t"]) == 0
    assert capsys.readouterr().out == 'v\n"say ""hi"""\n\n'


def test_cli_exit_code_2_on_usage_errors(tmp_path: Path, capsys) -> None:
    assert main([]) == 2
    assert main(["SELECT 1 FROM t"]) == 2
    assert main(["--table", "t=" + str(tmp_path / "missing.csv"), "SELECT 1 FROM t"]) == 2
    bad = write_csv(tmp_path, "id,name\n1,x\n", "bad.csv")
    assert main(["--table", "t=" + bad, "SELECT 1 FROM t"]) == 2
    assert main(["--table", "t", "SELECT 1 FROM t"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err


def test_cli_exit_code_3_on_query_errors(tmp_path: Path, capsys) -> None:
    path = write_csv(tmp_path, CSV)
    assert main(["--table", "t=" + path, "SELECT nope FROM t"]) == 3
    assert main(["--table", "t=" + path, "SELECT 1 < 2 < 3 FROM t"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nope" in captured.err


def test_cli_as_module_subprocess(tmp_path: Path) -> None:
    path = write_csv(tmp_path, CSV)
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", "t=" + path, "SELECT count(*) FROM t WHERE age > 30"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == ["count(*)", "2"]

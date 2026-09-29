"""Test suite for microdb."""

from __future__ import annotations

import os
import subprocess
import sys

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
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)
from microdb.__main__ import main
from microdb.lexer import tokenize
from microdb.parser import BinaryOp, Not, parse
from microdb.planner import plan

T, F, U = True, False, None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tables() -> dict[str, Table]:
    people = Table(
        "people",
        [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT"), Column("dept", "TEXT")],
        [
            [1, "ann", 34, "eng"],
            [2, "bob", 25, "ops"],
            [3, "cy", None, "eng"],
            [4, "dee", 41, None],
            [5, "ed", 25, None],
        ],
    )
    depts = Table("depts", [Column("dept", "TEXT"), Column("floor", "INT")],
                  [["eng", 3], ["ops", 1], ["eng", 4]])
    empty = Table("empty", [Column("x", "INT")], [])
    return {"people": people, "depts": depts, "empty": empty}


def rows(query: str, tables: dict[str, Table]) -> list[list[object]]:
    return execute(query, tables).rows


# ---------------------------------------------------------------- value model


def test_type_of_distinguishes_bool_from_int() -> None:
    assert type_of(True) == "BOOL"
    assert type_of(1) == "INT"
    assert type_of(1.0) == "FLOAT"
    assert type_of("a") == "TEXT"
    assert type_of(None) == "NULL"


def test_is_numeric_excludes_bool_and_none() -> None:
    assert is_numeric(1) and is_numeric(2.5)
    assert not is_numeric(True) and not is_numeric(None) and not is_numeric("1")


@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, F), (T, U, U), (F, T, F), (F, F, F), (F, U, F),
     (U, T, U), (U, F, F), (U, U, U)],
)
def test_and_truth_table(a: bool | None, b: bool | None, expected: bool | None) -> None:
    assert and_(a, b) is expected


@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, T), (T, U, T), (F, T, T), (F, F, F), (F, U, U),
     (U, T, T), (U, F, U), (U, U, U)],
)
def test_or_truth_table(a: bool | None, b: bool | None, expected: bool | None) -> None:
    assert or_(a, b) is expected


def test_not_truth_table() -> None:
    assert not_(T) is F and not_(F) is T and not_(U) is U


def test_null_equals_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_lt(None, 1) is None


def test_numeric_comparison_across_int_and_float() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True
    assert compare_lt(False, True) is True


def test_incompatible_comparisons_raise() -> None:
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("1", 1)


def test_arithmetic_types() -> None:
    assert arith("+", 1, 2) == 3 and type(arith("+", 1, 2)) is int
    assert type(arith("*", 2, 1.5)) is float
    assert arith("/", 7, 2) == 3.5
    assert type(arith("/", 4, 2)) is float
    assert arith("%", -7, 3) == 2


def test_division_and_modulo_by_zero_yield_null() -> None:
    assert arith("/", 1, 0) is None
    assert arith("/", 1.0, 0.0) is None
    assert arith("%", 5, 0) is None


def test_arithmetic_null_and_type_errors() -> None:
    assert arith("+", None, 1) is None
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        arith("+", "a", "b")
    with pytest.raises(TypeMismatchError):
        arith("%", 5.0, 2)


def test_negate() -> None:
    assert negate(3) == -3 and type(negate(3)) is int
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        negate(True)


# ---------------------------------------------------------------- schema


def test_table_validation_errors() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])
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


def test_table_float_widening_and_case_sensitive_names() -> None:
    t = Table("t", [Column("a", "FLOAT"), Column("A", "INT")], [[1, 2]])
    assert t.rows == [[1.0, 2]] and type(t.rows[0][0]) is float
    assert t.column_index("A") == 1
    with pytest.raises(SchemaError):
        t.column_index("b")


# ---------------------------------------------------------------- lexer / parser


def test_lexer_numbers_and_text() -> None:
    toks = tokenize("1 1. .5 1e3 1.5E-2 'it''s\nok' -- comment\n x")
    kinds = [(t.kind, t.value) for t in toks[:-1]]
    assert kinds == [("INT", 1), ("FLOAT", 1.0), ("FLOAT", 0.5), ("FLOAT", 1000.0),
                     ("FLOAT", 0.015), ("TEXT", "it's\nok"), ("IDENT", "x")]


def test_lex_error_offset() -> None:
    with pytest.raises(LexError) as info:
        tokenize("SELECT a # b")
    assert info.value.offset == 9


def test_keywords_case_insensitive_and_not_identifiers(tables: dict[str, Table]) -> None:
    assert rows("select ID from people where ID = 1", {"people": Table(
        "people", [Column("ID", "INT")], [[1]])}) == [[1]]
    with pytest.raises(ParseError):
        parse("SELECT order FROM t")


def test_comparison_not_associative() -> None:
    with pytest.raises(ParseError) as info:
        parse("SELECT a FROM t WHERE 1 < 2 < 3")
    assert info.value.offset == 28


def test_not_binds_looser_than_comparison() -> None:
    where = parse("SELECT a FROM t WHERE NOT a = b").where
    assert isinstance(where, Not) and isinstance(where.operand, BinaryOp)
    assert where.operand.op == "="


def test_nested_aggregate_is_parse_error() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT sum(*) FROM t")


def test_plan_is_inspectable() -> None:
    p = plan(parse("SELECT DISTINCT a FROM t WHERE a > 1 ORDER BY a LIMIT 2 OFFSET 1"))
    assert [s.name for s in p] == ["scan", "filter", "project", "distinct", "sort",
                                   "offset", "limit"]
    assert len(p) == 7


# ---------------------------------------------------------------- execution


def test_where_keeps_only_true(tables: dict[str, Table]) -> None:
    assert rows("SELECT id FROM people WHERE age > 30", tables) == [[1], [4]]
    assert rows("SELECT id FROM people WHERE age = NULL", tables) == []
    assert rows("SELECT id FROM people WHERE age IS NULL", tables) == [[3]]


def test_where_non_boolean_raises(tables: dict[str, Table]) -> None:
    with pytest.raises(TypeMismatchError):
        execute("SELECT id FROM people WHERE 1", tables)


def test_sum_of_empty_group_is_null(tables: dict[str, Table]) -> None:
    result = execute("SELECT count(*), count(x), sum(x), avg(x), min(x), max(x) FROM empty",
                     tables)
    assert result.rows == [[0, 0, None, None, None, None]]


def test_count_star_over_empty_table_yields_one_row(tables: dict[str, Table]) -> None:
    result = execute("SELECT count(*) FROM empty", tables)
    assert result.columns == ["count(*)"] and result.rows == [[0]]


def test_group_by_on_empty_table_yields_no_rows(tables: dict[str, Table]) -> None:
    assert rows("SELECT x, count(*) FROM empty GROUP BY x", tables) == []


def test_aggregates_ignore_null(tables: dict[str, Table]) -> None:
    result = rows("SELECT count(*), count(age), sum(age), avg(age), min(name), max(age) "
                  "FROM people", tables)
    assert result == [[5, 4, 125, 31.25, "ann", 41]]
    assert type(result[0][2]) is int


def test_aggregate_type_errors(tables: dict[str, Table]) -> None:
    with pytest.raises(TypeMismatchError):
        execute("SELECT sum(name) FROM people", tables)
    with pytest.raises(TypeMismatchError):
        execute("SELECT avg(age > 1) FROM people", tables)


def test_nulls_group_together_in_first_appearance_order(tables: dict[str, Table]) -> None:
    result = rows("SELECT dept, count(*) FROM people GROUP BY dept", tables)
    assert result == [["eng", 2], ["ops", 1], [None, 2]]


def test_group_by_expression(tables: dict[str, Table]) -> None:
    result = rows("SELECT length(name) AS n, count(*) FROM people GROUP BY length(name)",
                  tables)
    assert result == [[3, 3], [2, 2]]


def test_grouping_error(tables: dict[str, Table]) -> None:
    with pytest.raises(GroupingError):
        execute("SELECT dept, name FROM people GROUP BY dept", tables)


def test_having_filters_groups(tables: dict[str, Table]) -> None:
    result = rows("SELECT age FROM people GROUP BY age HAVING count(*) > 1", tables)
    assert result == [[25]]


def test_aggregate_in_where_raises(tables: dict[str, Table]) -> None:
    with pytest.raises(AggregateError):
        execute("SELECT id FROM people WHERE count(*) > 1", tables)


def test_nulls_sort_last_under_desc_and_asc(tables: dict[str, Table]) -> None:
    assert rows("SELECT age FROM people ORDER BY age DESC", tables) == [
        [41], [34], [25], [25], [None]]
    assert rows("SELECT age FROM people ORDER BY age ASC", tables) == [
        [25], [25], [34], [41], [None]]


def test_sort_is_stable(tables: dict[str, Table]) -> None:
    assert rows("SELECT id FROM people ORDER BY age", tables) == [[2], [5], [1], [4], [3]]
    assert rows("SELECT id FROM people ORDER BY dept DESC", tables) == [
        [2], [1], [3], [4], [5]]


def test_multi_key_sort(tables: dict[str, Table]) -> None:
    result = rows("SELECT id FROM people ORDER BY age DESC, name DESC", tables)
    assert result == [[4], [1], [5], [2], [3]]


def test_alias_visible_in_order_by_not_where(tables: dict[str, Table]) -> None:
    assert rows("SELECT age * 2 AS dbl FROM people ORDER BY dbl LIMIT 2", tables) == [
        [50], [50]]
    with pytest.raises(UnknownColumnError):
        execute("SELECT age * 2 AS dbl FROM people WHERE dbl > 1", tables)


def test_alias_wins_over_input_column_in_order_by(tables: dict[str, Table]) -> None:
    result = rows("SELECT id, -id AS age FROM people ORDER BY age", tables)
    assert [r[0] for r in result] == [5, 4, 3, 2, 1]


def test_order_by_input_column_not_selected(tables: dict[str, Table]) -> None:
    assert rows("SELECT name FROM people WHERE age IS NOT NULL ORDER BY age, id", tables) == [
        ["bob"], ["ed"], ["ann"], ["dee"]]


def test_distinct_then_order_by_output_only(tables: dict[str, Table]) -> None:
    assert rows("SELECT DISTINCT dept FROM people ORDER BY dept DESC", tables) == [
        ["ops"], ["eng"], [None]]
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT dept FROM people ORDER BY age", tables)


def test_offset_before_limit(tables: dict[str, Table]) -> None:
    assert rows("SELECT id FROM people LIMIT 2 OFFSET 1", tables) == [[2], [3]]


def test_left_join_fills_nulls(tables: dict[str, Table]) -> None:
    result = execute("SELECT * FROM people LEFT JOIN depts ON people.dept = depts.dept",
                     tables)
    assert result.columns == ["id", "name", "age", "dept", "dept", "floor"]
    assert [r[0] for r in result.rows] == [1, 1, 2, 3, 3, 4, 5]
    assert result.rows[5] == [4, "dee", 41, None, None, None]


def test_inner_join_order_and_qualified_star(tables: dict[str, Table]) -> None:
    result = execute("SELECT people.id, depts.* FROM people INNER JOIN depts "
                     "ON people.dept = depts.dept", tables)
    assert result.columns == ["id", "dept", "floor"]
    assert result.rows == [[1, "eng", 3], [1, "eng", 4], [2, "ops", 1],
                           [3, "eng", 3], [3, "eng", 4]]


def test_join_name_resolution_errors(tables: dict[str, Table]) -> None:
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT dept FROM people JOIN depts ON people.dept = depts.dept", tables)
    with pytest.raises(UnknownTableError):
        execute("SELECT nope.id FROM people", tables)
    with pytest.raises(UnknownTableError):
        execute("SELECT id FROM missing", tables)


def test_scalar_functions(tables: dict[str, Table]) -> None:
    result = rows("SELECT concat(name, '-', dept), upper(name), coalesce(age, 0), "
                  "abs(-age), concat(name, '!') FROM people WHERE id = 3 OR id = 4", tables)
    assert result == [["cy-eng", "CY", 0, None, "cy!"], [None, "DEE", 41, 41, "dee!"]]


def test_function_errors(tables: dict[str, Table]) -> None:
    with pytest.raises(ArityError):
        execute("SELECT concat(name) FROM people", tables)
    with pytest.raises(UnknownFunctionError):
        execute("SELECT nosuch(name) FROM people", tables)
    with pytest.raises(TypeMismatchError):
        execute("SELECT upper(age) FROM people", tables)


def test_output_column_names(tables: dict[str, Table]) -> None:
    result = execute("SELECT id, people.name, age  +   1, count(*) AS n FROM people "
                     "GROUP BY id, people.name, age  +   1", tables)
    assert result.columns == ["id", "name", "age + 1", "n"]


def test_three_valued_where(tables: dict[str, Table]) -> None:
    assert rows("SELECT id FROM people WHERE age > 30 OR dept = 'eng'", tables) == [
        [1], [3], [4]]
    assert rows("SELECT id FROM people WHERE NOT age > 30", tables) == [[2], [5]]


def test_public_all() -> None:
    assert "execute" in microdb.__all__ and len(microdb.__all__) > 10


# ---------------------------------------------------------------- CLI


def _write(path: object, text: str) -> str:
    with open(str(path), "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return str(path)


PEOPLE_CSV = "id:INT,name:TEXT,age:INT,ok:BOOL\n1,ann,34,true\n2,\"b,ob\",25,FALSE\n" \
             "3,'',41,\n4,,,True\n"


def test_cli_success_output(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(os.path.join(str(tmp_path), "p.csv"), PEOPLE_CSV)
    code = main(["--table", f"t={path}", "SELECT name, ok, age / 2 FROM t"])
    out = capsys.readouterr().out
    assert code == 0
    assert out == 'name,ok,age / 2\nann,true,17.0\n"b,ob",false,12.5\n,,20.5\n,true,\n'


def test_cli_empty_quoted_is_empty_string(tmp_path: object,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(os.path.join(str(tmp_path), "p.csv"), 'a:TEXT\n""\n\nx\n')
    code = main(["--table", f"t={path}", "SELECT a IS NULL, length(a), a FROM t"])
    assert code == 0
    assert capsys.readouterr().out == "a IS NULL,length(a),a\nfalse,0,\ntrue,,\nfalse,1,x\n"


def test_cli_count_example(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(os.path.join(str(tmp_path), "people.csv"), PEOPLE_CSV)
    assert main(["--table", f"t={path}", "SELECT count(*) FROM t WHERE age > 30"]) == 0
    assert capsys.readouterr().out == "count(*)\n2\n"


def test_cli_usage_errors(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["SELECT 1 FROM t"]) == 2
    assert main(["--table", "t=does_not_exist.csv", "SELECT a FROM t"]) == 2
    bad = _write(os.path.join(str(tmp_path), "bad.csv"), "a,b\n1,2\n")
    assert main(["--table", f"t={bad}", "SELECT a FROM t"]) == 2
    assert main(["--table", "t"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err != ""


def test_cli_engine_error_exit_3(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(os.path.join(str(tmp_path), "p.csv"), PEOPLE_CSV)
    assert main(["--table", f"t={path}", "SELECT nope FROM t"]) == 3
    assert main(["--table", f"t={path}", "SELECT FROM t"]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "nope" in captured.err


def test_cli_subprocess(tmp_path: object) -> None:
    path = _write(os.path.join(str(tmp_path), "p.csv"), PEOPLE_CSV)
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", f"t={path}",
         "SELECT id FROM t ORDER BY id DESC LIMIT 2"],
        cwd=ROOT, capture_output=True,
    )
    assert proc.returncode == 0
    assert proc.stdout == b"id\n4\n3\n"

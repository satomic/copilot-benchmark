"""Comprehensive test suite for microdb."""

from __future__ import annotations

import os
import tempfile
import pytest

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
from microdb.executor import Result, execute
from microdb.lexer import lex
from microdb.parser import parse
from microdb.planner import plan
from microdb.schema import Column, Table
from microdb.value import (
    and_,
    arith,
    compare_eq,
    compare_lt,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)
from microdb.__main__ import main


def test_truth_table_and() -> None:
    assert and_(True, True) is True
    assert and_(True, False) is False
    assert and_(True, None) is None
    assert and_(False, True) is False
    assert and_(False, False) is False
    assert and_(False, None) is False
    assert and_(None, True) is None
    assert and_(None, False) is False
    assert and_(None, None) is None


def test_truth_table_or() -> None:
    assert or_(True, True) is True
    assert or_(True, False) is True
    assert or_(True, None) is True
    assert or_(False, True) is True
    assert or_(False, False) is False
    assert or_(False, None) is None
    assert or_(None, True) is True
    assert or_(None, False) is None
    assert or_(None, None) is None


def test_truth_table_not() -> None:
    assert not_(True) is False
    assert not_(False) is True
    assert not_(None) is None


def test_boolean_validation() -> None:
    with pytest.raises(TypeMismatchError):
        and_(1, True)  # type: ignore[arg-type]
    with pytest.raises(TypeMismatchError):
        or_(False, "x")  # type: ignore[arg-type]
    with pytest.raises(TypeMismatchError):
        not_(0)  # type: ignore[arg-type]


def test_type_of_and_is_numeric() -> None:
    assert type_of(None) == "NULL"
    assert type_of(True) == "BOOL"
    assert type_of(False) == "BOOL"
    assert type_of(1) == "INT"
    assert type_of(1.5) == "FLOAT"
    assert type_of("hello") == "TEXT"
    assert is_numeric(1) is True
    assert is_numeric(1.5) is True
    assert is_numeric(True) is False
    assert is_numeric(False) is False
    assert is_numeric(None) is False
    assert is_numeric("1") is False


def test_null_equality_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(1, None) is None
    assert compare_eq(None, "a") is None
    assert compare_lt(None, None) is None
    assert compare_lt(1, None) is None


def test_compare_numerics_int_float() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_eq(2, 2.5) is False
    assert compare_lt(1, 1.5) is True
    assert compare_lt(2.5, 2) is False


def test_compare_text_and_bool() -> None:
    assert compare_eq("abc", "abc") is True
    assert compare_lt("abc", "abd") is True
    assert compare_eq(True, True) is True
    assert compare_eq(True, False) is False
    assert compare_lt(False, True) is True
    assert compare_lt(True, False) is False


def test_compare_type_mismatch() -> None:
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt(1, "1")
    with pytest.raises(TypeMismatchError):
        compare_lt(False, 0)


def test_arith_null_propagation() -> None:
    assert arith("+", None, 1) is None
    assert arith("-", 1, None) is None
    assert arith("*", None, None) is None
    assert arith("/", 5, None) is None
    assert arith("%", None, 2) is None


def test_arith_int_float() -> None:
    assert arith("+", 1, 2) == 3
    assert isinstance(arith("+", 1, 2), int)
    assert arith("+", 1, 2.0) == 3.0
    assert isinstance(arith("+", 1, 2.0), float)
    assert arith("-", 5, 2) == 3
    assert arith("*", 3, 4) == 12


def test_arith_division_always_float() -> None:
    res = arith("/", 7, 2)
    assert res == 3.5
    assert isinstance(res, float)
    res2 = arith("/", 6, 2)
    assert res2 == 3.0
    assert isinstance(res2, float)


def test_arith_division_and_modulo_by_zero_yield_null() -> None:
    assert arith("/", 10, 0) is None
    assert arith("/", 10.0, 0.0) is None
    assert arith("%", 10, 0) is None


def test_arith_modulo_rules() -> None:
    assert arith("%", -7, 3) == 2
    assert arith("%", 7, 3) == 1
    with pytest.raises(TypeMismatchError):
        arith("%", 7.0, 3)
    with pytest.raises(TypeMismatchError):
        arith("%", 7, 3.0)


def test_negate() -> None:
    assert negate(None) is None
    assert negate(5) == -5
    assert isinstance(negate(5), int)
    assert negate(5.5) == -5.5
    assert isinstance(negate(5.5), float)
    with pytest.raises(TypeMismatchError):
        negate(True)
    with pytest.raises(TypeMismatchError):
        negate("5")


def test_schema_valid_and_float_widening() -> None:
    cols = [Column("a", "INT"), Column("b", "FLOAT"), Column("c", "TEXT"), Column("d", "BOOL")]
    rows: list[list[object]] = [[1, 2, "hello", True], [None, 3.5, None, False]]
    tbl = Table("t", cols, rows)
    assert tbl.name == "t"
    assert len(tbl.columns) == 4
    assert tbl.rows[0][1] == 2.0
    assert isinstance(tbl.rows[0][1], float)
    assert tbl.column_index("b") == 1


def test_schema_validation_errors() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INVALID")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BOOL")], [[1]])


def test_lexer_numbers_and_floats() -> None:
    toks = lex("123 12.34 .56 1. 1e3 1.5E-2")
    assert [t.kind for t in toks[:-1]] == ["INT", "FLOAT", "FLOAT", "FLOAT", "FLOAT", "FLOAT"]
    assert toks[0].value == 123
    assert toks[1].value == 12.34
    assert toks[2].value == 0.56
    assert toks[3].value == 1.0
    assert toks[4].value == 1000.0
    assert toks[5].value == 0.015


def test_lexer_strings_and_comments() -> None:
    toks = lex("'hello' 'it''s' -- comment to ignore\n'next'")
    assert [t.value for t in toks[:-1]] == ["hello", "it's", "next"]


def test_lexer_lex_error() -> None:
    with pytest.raises(LexError) as exc_info:
        lex("SELECT @")
    assert exc_info.value.offset == 7


def test_parser_predicate_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("SELECT 1 FROM t WHERE 1 < 2 < 3")


def test_parser_not_precedence() -> None:
    q = parse("SELECT * FROM t WHERE NOT a = b")
    assert q.where.__class__.__name__ == "NotOp"


def test_parser_aggregates_nesting_error() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")


def test_scalar_functions() -> None:
    tbl = Table("t", [Column("s", "TEXT"), Column("n", "INT")], [["hello", -5], [None, None]])
    res = execute("SELECT upper(s), lower(s), length(s), abs(n) FROM t", {"t": tbl})
    assert res.rows[0] == ["HELLO", "hello", 5, 5]
    assert res.rows[1] == [None, None, None, None]


def test_scalar_concat_and_coalesce() -> None:
    tbl = Table("t", [Column("a", "TEXT"), Column("b", "TEXT")], [["foo", "bar"], ["foo", None]])
    res = execute("SELECT concat(a, b), coalesce(b, a, 'default') FROM t", {"t": tbl})
    assert res.rows[0] == ["foobar", "bar"]
    assert res.rows[1] == [None, "foo"]


def test_scalar_function_errors() -> None:
    tbl = Table("t", [Column("a", "INT")], [[1]])
    with pytest.raises(UnknownFunctionError):
        execute("SELECT bogus(a) FROM t", {"t": tbl})
    with pytest.raises(ArityError):
        execute("SELECT abs(a, a) FROM t", {"t": tbl})
    with pytest.raises(TypeMismatchError):
        execute("SELECT upper(a) FROM t", {"t": tbl})


def test_count_star_over_empty_table_yields_one_row() -> None:
    tbl = Table("empty", [Column("id", "INT")], [])
    res = execute("SELECT count(*) FROM empty", {"empty": tbl})
    assert res.columns == ["count(*)"]
    assert res.rows == [[0]]


def test_sum_of_empty_group_is_null() -> None:
    tbl = Table("t", [Column("x", "INT")], [])
    res = execute("SELECT sum(x), avg(x), min(x), max(x) FROM t", {"t": tbl})
    assert res.rows == [[None, None, None, None]]


def test_sum_all_nulls_is_null() -> None:
    tbl = Table("t", [Column("x", "INT")], [[None], [None]])
    res = execute("SELECT count(*), count(x), sum(x) FROM t", {"t": tbl})
    assert res.rows == [[2, 0, None]]


def test_sum_and_avg_numeric_types() -> None:
    tbl = Table("t", [Column("i", "INT"), Column("f", "FLOAT")], [[1, 1.5], [2, 2.5]])
    res = execute("SELECT sum(i), sum(f), avg(i) FROM t", {"t": tbl})
    assert res.rows[0][0] == 3
    assert isinstance(res.rows[0][0], int)
    assert res.rows[0][1] == 4.0
    assert isinstance(res.rows[0][1], float)
    assert res.rows[0][2] == 1.5
    assert isinstance(res.rows[0][2], float)


def test_min_max_type_preservation() -> None:
    tbl = Table("t", [Column("s", "TEXT"), Column("b", "BOOL")], [["banana", True], ["apple", False]])
    res = execute("SELECT min(s), max(s), min(b), max(b) FROM t", {"t": tbl})
    assert res.rows[0] == ["apple", "banana", False, True]


def test_where_drops_null_and_unknown() -> None:
    tbl = Table("t", [Column("a", "INT")], [[1], [None], [2]])
    res = execute("SELECT a FROM t WHERE a = NULL", {"t": tbl})
    assert res.rows == []
    res2 = execute("SELECT a FROM t WHERE a > 1", {"t": tbl})
    assert res2.rows == [[2]]


def test_where_non_boolean_raises() -> None:
    tbl = Table("t", [Column("a", "INT")], [[1]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT a FROM t WHERE 1", {"t": tbl})


def test_where_cannot_see_aliases() -> None:
    tbl = Table("t", [Column("a", "INT")], [[10]])
    with pytest.raises(UnknownColumnError):
        execute("SELECT a * 2 AS doubled FROM t WHERE doubled > 10", {"t": tbl})


def test_where_cannot_contain_aggregate() -> None:
    tbl = Table("t", [Column("a", "INT")], [[10]])
    with pytest.raises(AggregateError):
        execute("SELECT a FROM t WHERE count(*) > 0", {"t": tbl})


def test_nulls_group_together() -> None:
    tbl = Table("t", [Column("k", "TEXT"), Column("v", "INT")], [[None, 10], ["a", 20], [None, 30]])
    res = execute("SELECT k, sum(v) FROM t GROUP BY k", {"t": tbl})
    assert len(res.rows) == 2
    assert res.rows[0] == [None, 40]
    assert res.rows[1] == ["a", 20]


def test_group_by_preserves_first_seen_order() -> None:
    tbl = Table("t", [Column("k", "TEXT")], [["c"], ["b"], ["a"], ["b"], ["c"]])
    res = execute("SELECT k FROM t GROUP BY k", {"t": tbl})
    assert [r[0] for r in res.rows] == ["c", "b", "a"]


def test_grouping_error_for_ungrouped_column() -> None:
    tbl = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    with pytest.raises(GroupingError):
        execute("SELECT a, b FROM t GROUP BY a", {"t": tbl})


def test_having_clause() -> None:
    tbl = Table("t", [Column("k", "TEXT"), Column("v", "INT")], [["a", 10], ["a", 20], ["b", 5]])
    res = execute("SELECT k, sum(v) FROM t GROUP BY k HAVING sum(v) > 10", {"t": tbl})
    assert res.rows == [["a", 30]]


def test_select_distinct() -> None:
    tbl = Table("t", [Column("a", "INT"), Column("b", "TEXT")], [[1, "x"], [1, "x"], [None, "y"], [None, "y"]])
    res = execute("SELECT DISTINCT a, b FROM t", {"t": tbl})
    assert res.rows == [[1, "x"], [None, "y"]]


def test_order_by_asc_and_desc_nulls_last() -> None:
    tbl = Table("t", [Column("v", "INT")], [[3], [None], [1], [None], [2]])
    res_asc = execute("SELECT v FROM t ORDER BY v ASC", {"t": tbl})
    assert [r[0] for r in res_asc.rows] == [1, 2, 3, None, None]
    res_desc = execute("SELECT v FROM t ORDER BY v DESC", {"t": tbl})
    assert [r[0] for r in res_desc.rows] == [3, 2, 1, None, None]


def test_order_by_stability() -> None:
    tbl = Table(
        "t",
        [Column("k", "INT"), Column("tag", "TEXT")],
        [[1, "first"], [2, "two"], [1, "second"], [1, "third"]],
    )
    res = execute("SELECT tag FROM t ORDER BY k ASC", {"t": tbl})
    assert [r[0] for r in res.rows] == ["first", "second", "third", "two"]


def test_order_by_alias_wins() -> None:
    tbl = Table("t", [Column("x", "INT")], [[10], [5]])
    res = execute("SELECT -x AS x FROM t ORDER BY x ASC", {"t": tbl})
    assert [r[0] for r in res.rows] == [-10, -5]


def test_order_by_distinct_column_restriction() -> None:
    tbl = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT a FROM t ORDER BY b", {"t": tbl})


def test_left_join_null_filling() -> None:
    t1 = Table("t1", [Column("id", "INT"), Column("val", "TEXT")], [[1, "one"], [2, "two"]])
    t2 = Table("t2", [Column("t1_id", "INT"), Column("extra", "TEXT")], [[1, "first"]])
    res = execute("SELECT t1.id, t1.val, t2.extra FROM t1 LEFT JOIN t2 ON t1.id = t2.t1_id", {"t1": t1, "t2": t2})
    assert res.rows == [[1, "one", "first"], [2, "two", None]]


def test_inner_join() -> None:
    t1 = Table("t1", [Column("id", "INT")], [[1], [2], [3]])
    t2 = Table("t2", [Column("id", "INT"), Column("info", "TEXT")], [[2, "two"], [3, "three"], [4, "four"]])
    res = execute("SELECT t1.id, t2.info FROM t1 INNER JOIN t2 ON t1.id = t2.id", {"t1": t1, "t2": t2})
    assert res.rows == [[2, "two"], [3, "three"]]


def test_join_ambiguous_and_unknown_table() -> None:
    t1 = Table("t1", [Column("id", "INT")], [[1]])
    t2 = Table("t2", [Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM t1 JOIN t2 ON t1.id = t2.id", {"t1": t1, "t2": t2})
    with pytest.raises(UnknownTableError):
        execute("SELECT bad.id FROM t1", {"t1": t1})


def test_offset_then_limit() -> None:
    tbl = Table("t", [Column("v", "INT")], [[1], [2], [3], [4], [5]])
    res = execute("SELECT v FROM t LIMIT 2 OFFSET 2", {"t": tbl})
    assert [r[0] for r in res.rows] == [3, 4]


def test_planner_pipeline_stages() -> None:
    q = parse("SELECT a FROM t WHERE a > 1 ORDER BY a LIMIT 10")
    p = plan(q)
    stage_names = [s.name for s in p]
    assert stage_names == ["FROM", "WHERE", "SELECT", "ORDER BY", "SLICE"]


def test_cli_exit_code_success(tmp_path: pytest.TempPathFactory) -> None:
    csv_file = os.path.join(str(tmp_path), "test.csv")
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("id:INT,name:TEXT,age:INT\n1,Alice,25\n2,Bob,35\n3,Charlie,42\n")
    code = main(["--table", f"t={csv_file}", "SELECT count(*) FROM t WHERE age > 30"])
    assert code == 0


def test_cli_exit_code_2_usage_and_bad_header(tmp_path: pytest.TempPathFactory) -> None:
    assert main([]) == 2
    assert main(["--bogus"]) == 2
    bad_csv = os.path.join(str(tmp_path), "bad.csv")
    with open(bad_csv, "w", encoding="utf-8") as f:
        f.write("id_without_type\n1\n")
    assert main(["--table", f"t={bad_csv}", "SELECT * FROM t"]) == 2


def test_cli_exit_code_3_microdb_error(tmp_path: pytest.TempPathFactory) -> None:
    csv_file = os.path.join(str(tmp_path), "t.csv")
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("id:INT\n1\n")
    code = main(["--table", f"t={csv_file}", "SELECT count(*) FROM t WHERE count(*) > 0"])
    assert code == 3

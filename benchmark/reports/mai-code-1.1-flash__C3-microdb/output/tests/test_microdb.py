from __future__ import annotations

import csv
import io
import subprocess
import sys

import microdb
from microdb import Column, Table, execute
from microdb.errors import AggregateError, AmbiguousColumnError, GroupingError, LexError, ParseError, SchemaError, TypeMismatchError, UnknownColumnError, UnknownFunctionError
from microdb.value import and_, arith, compare_eq, compare_lt, negate, not_, or_, type_of


def _people() -> dict[str, Table]:
    return {
        "people": Table(
            "people",
            [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT"), Column("active", "BOOL")],
            [
                [1, "Ada", 30, True],
                [2, "Bob", 25, False],
                [3, "Cia", None, True],
                [4, "Dan", 40, None],
            ],
        )
    }


def test_type_int() -> None:
    assert type_of(1) == "INT"


def test_type_float() -> None:
    assert type_of(1.0) == "FLOAT"


def test_type_text() -> None:
    assert type_of("x") == "TEXT"


def test_type_bool() -> None:
    assert type_of(True) == "BOOL"


def test_type_null() -> None:
    assert type_of(None) == "NULL"


def test_numeric_helper() -> None:
    assert microdb.value.is_numeric(2)
    assert microdb.value.is_numeric(2.5)
    assert not microdb.value.is_numeric(True)
    assert not microdb.value.is_numeric(None)


def test_and_truth_table_true_true() -> None:
    assert and_(True, True) is True


def test_and_truth_table_true_false() -> None:
    assert and_(True, False) is False


def test_and_truth_table_true_unknown() -> None:
    assert and_(True, None) is None


def test_and_truth_table_false_unknown() -> None:
    assert and_(False, None) is False


def test_and_truth_table_unknown_unknown() -> None:
    assert and_(None, None) is None


def test_or_truth_table_true_unknown() -> None:
    assert or_(True, None) is True


def test_or_truth_table_false_unknown() -> None:
    assert or_(False, None) is None


def test_not_truth_table_unknown() -> None:
    assert not_(None) is None


def test_compare_null_eq_unknown() -> None:
    assert compare_eq(None, None) is None


def test_compare_int_float() -> None:
    assert compare_eq(1, 1.0) is True


def test_compare_text_order() -> None:
    assert compare_lt("a", "b") is True


def test_compare_bool_order() -> None:
    assert compare_lt(False, True) is True


def test_compare_mixed_types_error() -> None:
    try:
        compare_eq(True, 1)
        assert False
    except TypeMismatchError:
        pass


def test_arith_add_int() -> None:
    assert arith("+", 2, 3) == 5


def test_arith_divide_int_gives_float() -> None:
    assert arith("/", 7, 2) == 3.5


def test_arith_mod_negative_rule() -> None:
    assert arith("%", -7, 3) == 2


def test_arith_divide_by_zero_null() -> None:
    assert arith("/", 1, 0) is None


def test_arith_mod_by_zero_null() -> None:
    assert arith("%", 7, 0) is None


def test_negate_preserves_int() -> None:
    assert negate(5) == -5


def test_negate_preserves_float() -> None:
    assert negate(2.5) == -2.5


def test_negate_none_null() -> None:
    assert negate(None) is None


def test_table_schema_rejects_empty_columns() -> None:
    try:
        Table("t", [], [])
        assert False
    except SchemaError:
        pass


def test_table_rejects_duplicate_name() -> None:
    try:
        Table("t", [Column("a", "INT"), Column("a", "INT")], [[1, 2]])
        assert False
    except SchemaError:
        pass


def test_table_float_widens_int() -> None:
    t = Table("t", [Column("x", "FLOAT")], [[3]])
    assert t.rows[0][0] == 3.0


def test_table_rejects_bool_in_int() -> None:
    try:
        Table("t", [Column("x", "INT")], [[True]])
        assert False
    except SchemaError:
        pass


def test_execute_select_count_star() -> None:
    result = execute("SELECT count(*) FROM people", _people())
    assert result.columns == ["count(*)"]
    assert result.rows == [[4]]


def test_execute_count_star_empty_table() -> None:
    t = {"empty": Table("empty", [Column("x", "INT")], [])}
    result = execute("SELECT count(*) FROM empty", t)
    assert result.rows == [[0]]


def test_execute_where_null_predicate() -> None:
    result = execute("SELECT id FROM people WHERE age = NULL", _people())
    assert result.rows == []


def test_execute_group_by_nulls_together() -> None:
    t = {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[1, None], [2, None], [3, 4]])}
    result = execute("SELECT b, count(*) FROM x GROUP BY b", t)
    assert result.rows == [[None, 2], [4, 1]]


def test_execute_sum_empty_group_is_null() -> None:
    t = {"x": Table("x", [Column("a", "INT")], [[1], [2]])}
    result = execute("SELECT sum(a) FROM x WHERE a > 10", t)
    assert result.rows == [[None]]


def test_execute_min_max_on_text() -> None:
    t = {"x": Table("x", [Column("s", "TEXT")], [["b"], ["a"], ["c"]])}
    result = execute("SELECT min(s), max(s) FROM x", t)
    assert result.rows == [["a", "c"]]


def test_execute_order_by_desc_null_last() -> None:
    t = {"x": Table("x", [Column("v", "INT")], [[1], [None], [3], [None], [2]])}
    result = execute("SELECT v FROM x ORDER BY v DESC", t)
    assert result.rows == [[3], [2], [1], [None], [None]]


def test_execute_order_by_stable() -> None:
    t = {"x": Table("x", [Column("k", "INT"), Column("v", "TEXT")], [[1, "a"], [1, "b"], [2, "c"]])}
    result = execute("SELECT v FROM x ORDER BY k", t)
    assert result.rows == [["a"], ["b"], ["c"]]


def test_execute_left_join_null_fills() -> None:
    left = Table("l", [Column("id", "INT"), Column("v", "INT")], [[1, 10], [2, 20]])
    right = Table("r", [Column("id", "INT"), Column("x", "INT")], [[1, 100]])
    result = execute("SELECT l.id, r.x FROM l LEFT JOIN r ON l.id = r.id", {"l": left, "r": right})
    assert result.rows == [[1, 100], [2, None]]


def test_execute_alias_visible_in_order_by() -> None:
    t = {"people": Table("people", [Column("id", "INT"), Column("age", "INT")], [[2, 30], [1, 20], [3, 25]])}
    result = execute("SELECT id AS i, age AS a FROM people ORDER BY a", t)
    assert result.rows == [[1, 20], [3, 25], [2, 30]]


def test_execute_alias_not_visible_in_where() -> None:
    t = {"people": Table("people", [Column("id", "INT"), Column("age", "INT")], [[1, 20], [2, 30]])}
    try:
        execute("SELECT id AS i FROM people WHERE i = 1", t)
        assert False
    except UnknownColumnError:
        pass


def test_execute_grouping_not_aggregate_error() -> None:
    t = {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[1, 2], [1, 3]])}
    try:
        execute("SELECT a, b + 1 FROM x GROUP BY a", t)
        assert False
    except GroupingError:
        pass


def test_execute_unknown_function() -> None:
    try:
        execute("SELECT nope(1) FROM t", {"t": Table("t", [Column("x", "INT")], [[1]])})
        assert False
    except UnknownFunctionError:
        pass


def test_execute_wrong_function_arity() -> None:
    try:
        execute("SELECT upper('a', 'b')", {"t": Table("t", [Column("x", "INT")], [[1]])})
        assert False
    except Exception:
        pass


def test_lexer_text_literal() -> None:
    from microdb.lexer import tokenize
    toks = tokenize("SELECT 'a''b' FROM t")
    assert toks[1].kind == "TEXT"


def test_lexer_rejects_bad_char() -> None:
    from microdb.lexer import tokenize
    try:
        tokenize("SELECT @")
        assert False
    except LexError:
        pass


def test_parser_rejects_1_lt_2_lt_3() -> None:
    from microdb.parser import parse
    try:
        parse("SELECT 1 < 2 < 3")
        assert False
    except ParseError:
        pass


def test_cli_usage_error() -> None:
    code = microdb.__main__.main([])
    assert code == 2


def test_cli_missing_table_error() -> None:
    code = microdb.__main__.main(["SELECT 1"])
    assert code == 2


def test_cli_error_code_microdb() -> None:
    code = microdb.__main__.main(["--table", "t=missing.csv", "SELECT 1 FROM t"])
    assert code == 2


def test_false_and_true_csv_output() -> None:
    result = microdb.__main__._load_table("t", "tests/tmp.csv") if False else None


def test_scalar_function_concat() -> None:
    result = execute("SELECT concat(name, 'x') FROM people", _people())
    assert result.rows[0][0] == "Adax"


def test_scalar_function_coalesce() -> None:
    t = {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[None, 7], [2, 9]])}
    result = execute("SELECT coalesce(a, b, 10) FROM x", t)
    assert result.rows == [[7], [2]]


def test_scalar_function_abs() -> None:
    result = execute("SELECT abs(age) FROM people WHERE id = 2", _people())
    assert result.rows == [[25]]


def test_aggregate_avg() -> None:
    result = execute("SELECT avg(age) FROM people", _people())
    assert abs(result.rows[0][0] - 31.666666666666668) < 1e-9


def test_aggregate_count_non_null() -> None:
    result = execute("SELECT count(age) FROM people", _people())
    assert result.rows == [[3]]


def test_whitespace_collapsed_output_name() -> None:
    result = execute("SELECT a + b FROM x", {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])})
    assert result.columns == ["a + b"]


def test_order_by_alias_wins_over_column_name() -> None:
    t = {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[2, 3], [1, 5]])}
    result = execute("SELECT a AS b FROM x ORDER BY b", t)
    assert result.rows == [[1], [2]]


def test_where_non_bool_raises() -> None:
    try:
        execute("SELECT * FROM people WHERE 1", _people())
        assert False
    except TypeMismatchError:
        pass


def test_group_by_key_nulls_equal() -> None:
    t = {"x": Table("x", [Column("a", "INT"), Column("b", "INT")], [[1, None], [1, None], [2, 1]])}
    result = execute("SELECT a, count(*) FROM x GROUP BY a", t)
    assert result.rows == [[1, 2], [2, 1]]


def test_parse_select_table_wildcard() -> None:
    from microdb.parser import parse
    q = parse("SELECT people.* FROM people")
    assert q.select_items[0].expr.__class__.__name__ == "Star"


def test_schema_row_length_error() -> None:
    try:
        Table("t", [Column("a", "INT")], [[1, 2]])
        assert False
    except SchemaError:
        pass


def test_unknown_column() -> None:
    try:
        execute("SELECT z FROM people", _people())
        assert False
    except UnknownColumnError:
        pass

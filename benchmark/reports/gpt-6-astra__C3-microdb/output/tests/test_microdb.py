"""Regression coverage for values, relational stages, parsing, and the CSV CLI."""

from dataclasses import FrozenInstanceError
import inspect
import io
import itertools
import os
from pathlib import Path
import subprocess
import sys
import tokenize as py_tokenize
from unittest.mock import patch

import pytest

import microdb
from microdb import (
    AggregateError, AmbiguousColumnError, ArityError, Column, GroupingError,
    LexError, MicroDBError, ParseError, SchemaError, Table, TypeMismatchError,
    UnknownColumnError, UnknownFunctionError, UnknownTableError, and_, arith,
    compare_eq, compare_lt, execute, execute_plan, is_numeric, negate, not_,
    or_, parse, plan, tokenize, type_of,
)
from microdb.__main__ import main
from microdb.aggregate import aggregate
from microdb.expr import scalar


def table(rows: list[list[object]], kinds: str = "x:INT", name: str = "t") -> Table:
    return Table(name, [Column(*part.split(":")) for part in kinds.split(",")], rows)


def query(sql: str, rows: list[list[object]],
          kinds: str = "x:INT") -> microdb.Result:
    return execute(sql, {"t": table(rows, kinds)})


def cli(argv: list[str], content: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch("builtins.open", return_value=io.StringIO(content)):
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


def test_value_kinds() -> None:
    assert [type_of(v) for v in (1, 1.0, "a", True, None)] == [
        "INT", "FLOAT", "TEXT", "BOOL", "NULL"]


def test_unknown_value_type() -> None:
    with pytest.raises(TypeMismatchError):
        type_of([])


def test_numeric_excludes_bool() -> None:
    assert [is_numeric(v) for v in (1, 1.0, True, False, None, "1")] == [
        True, True, False, False, False, False]


def test_and_truth_table() -> None:
    expected = [True, False, None, False, False, False, None, False, None]
    assert [and_(a, b) for a, b in itertools.product((True, False, None), repeat=2)] == expected


def test_or_truth_table() -> None:
    expected = [True, True, True, True, False, None, True, None, None]
    assert [or_(a, b) for a, b in itertools.product((True, False, None), repeat=2)] == expected


def test_not_truth_table() -> None:
    assert [not_(v) for v in (True, False, None)] == [False, True, None]


def test_logical_operands_are_strict() -> None:
    for function, args in ((and_, (False, 1)), (or_, (True, 1)), (not_, (0,))):
        with pytest.raises(TypeMismatchError):
            function(*args)


def test_null_equals_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_lt(None, None) is None


def test_null_comparison_propagates() -> None:
    for value in (1, 1.0, "x", True):
        assert compare_eq(value, None) is None
        assert compare_lt(None, value) is None


def test_numeric_comparisons() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True
    assert compare_lt(2.0, 2) is False


def test_text_and_bool_ordering() -> None:
    assert compare_lt("Z", "a") is True
    assert compare_lt(False, True) is True
    assert compare_eq(True, True) is True


def test_incompatible_comparisons() -> None:
    for a, b in ((True, 1), (False, 0.0), ("1", 1), (True, "true")):
        for function in (compare_eq, compare_lt):
            with pytest.raises(TypeMismatchError):
                function(a, b)


def test_arithmetic_types() -> None:
    for op, expected in (("+", 9), ("-", 5), ("*", 14)):
        value = arith(op, 7, 2)
        assert value == expected and type(value) is int
        value = arith(op, 7, 2.0)
        assert value == expected and type(value) is float


def test_division_always_float() -> None:
    assert arith("/", 7, 2) == 3.5
    assert type(arith("/", 8, 2)) is float


def test_division_and_modulo_zero_are_null() -> None:
    assert arith("/", 1, 0) is None
    assert arith("/", 1, 0.0) is None
    assert arith("%", 1, 0) is None


def test_modulo_sign_and_types() -> None:
    assert arith("%", -7, 3) == 2
    assert arith("%", 7, -3) == -2
    for operands in ((7.0, 3), (7, 3.0), (True, 3)):
        with pytest.raises(TypeMismatchError):
            arith("%", *operands)


def test_arithmetic_null_propagation() -> None:
    for op in "+-*/%":
        assert arith(op, None, "not numeric") is None
        assert arith(op, True, None) is None


def test_arithmetic_rejects_text_and_bool() -> None:
    for op in "+-*/%":
        for value in (True, "a"):
            with pytest.raises(TypeMismatchError):
                arith(op, value, 1)


def test_negate() -> None:
    assert negate(None) is None
    assert negate(3) == -3 and type(negate(3)) is int
    assert negate(3.0) == -3.0 and type(negate(3.0)) is float
    with pytest.raises(TypeMismatchError):
        negate(True)


def test_table_float_widening() -> None:
    result = table([[1], [None], [2.5]], "x:FLOAT")
    assert result.rows == [[1.0], [None], [2.5]]
    assert type(result.rows[0][0]) is float


def test_table_rejects_invalid_cells() -> None:
    for kind, value in (("INT", True), ("INT", 3.0), ("FLOAT", True),
                        ("BOOL", 1), ("TEXT", 3), ("INT", [])):
        with pytest.raises(SchemaError):
            table([[value]], f"x:{kind}")


def test_table_rejects_invalid_schema() -> None:
    for columns in ([], [Column("x", "BAD")], [Column("x", "INT")] * 2):
        with pytest.raises(SchemaError):
            Table("t", columns, [])
    with pytest.raises(SchemaError):
        table([[1, 2]])


def test_table_names_are_case_sensitive() -> None:
    result = table([[1, 2]], "a:INT,A:INT")
    assert result.column_index("a") == 0
    assert result.column_index("A") == 1
    with pytest.raises(SchemaError):
        result.column_index("missing")


def test_table_defensive_copies() -> None:
    rows, columns = [[1]], [Column("x", "INT")]
    result = Table("t", columns, rows)
    rows[0][0] = "bad"
    columns.clear()
    result.rows[0][0] = 9
    result.columns.clear()
    assert result.name == "t" and result.rows == [[1]]
    assert result.columns == [Column("x", "INT")]


def test_column_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        Column("x", "INT").name = "y"


def test_lexer_number_forms() -> None:
    tokens = tokenize("1 1. .5 1e3 1.5E-2 1.e2")
    assert [t.value for t in tokens[:-1]] == [1, 1.0, .5, 1000.0, .015, 100.0]
    assert [t.kind for t in tokens[:-1]] == ["INT"] + ["FLOAT"] * 5


def test_lexer_string_escaping_and_newlines() -> None:
    tokens = tokenize("'it''s\nfine' ''")
    assert [t.value for t in tokens[:-1]] == ["it's\nfine", ""]


def test_lexer_comments_and_keyword_case() -> None:
    tokens = tokenize("sElEcT A -- SELECT ignored\nFROM t")
    assert [t.kind for t in tokens] == ["SELECT", "IDENT", "FROM", "IDENT", "EOF"]
    assert tokens[1].value == "A"


def test_lexer_error_offsets() -> None:
    for text, offset in (("a !", 2), ("'oops", 0), ("a; b", 1)):
        with pytest.raises(LexError) as error:
            tokenize(text)
        assert error.value.offset == offset


def test_parser_precedence() -> None:
    result = query("SELECT 1 + 2 * 3, (1 + 2) * 3, - -2, -7 % 3 FROM t", [[0]])
    assert result.rows == [[7, 9, 2, 2]]


def test_not_binds_below_comparison() -> None:
    assert query("SELECT NOT x = 2 FROM t", [[1], [2], [None]]).rows == [
        [True], [False], [None]]


def test_boolean_precedence() -> None:
    assert query("SELECT TRUE OR FALSE AND FALSE, NOT TRUE AND FALSE FROM t", [[1]]).rows == [
        [True, False]]


def test_nonassociative_predicates_rejected() -> None:
    for expr in ("1 < 2 < 3", "1 = 1 = TRUE", "x IS NULL IS NULL", "x = 1 IS NULL"):
        with pytest.raises(ParseError):
            parse(f"SELECT {expr} FROM t")


def test_parser_offsets() -> None:
    with pytest.raises(ParseError) as error:
        parse("SELECT FROM t")
    assert error.value.offset == 7
    with pytest.raises(ParseError) as error:
        parse("SELECT x FROM")
    assert error.value.offset == len("SELECT x FROM")


def test_clause_order_and_unsupported_syntax() -> None:
    for sql in ("SELECT x FROM t LIMIT 1 WHERE TRUE", "SELECT x FROM t OFFSET -1",
                "SELECT x FROM t LIMIT 1.0", "SELECT x FROM t JOIN u ON TRUE JOIN v ON TRUE",
                "SELECT x y FROM t", "SELECT order FROM t", "SELECT +1 FROM t"):
        with pytest.raises(ParseError):
            parse(sql)


def test_parenthesized_predicates() -> None:
    assert query("SELECT (1 < 2) = TRUE, NOT (x IS NOT NULL) FROM t", [[None]]).rows == [
        [True, True]]


def test_projection_names() -> None:
    result = query("SELECT x, t.x, x  +\n 1, count(*) AS n FROM t GROUP BY x", [[2]])
    assert result.columns == ["x", "x", "x + 1", "n"]
    assert result.rows == [[2, 2, 3, 1]]


def test_star_projection() -> None:
    result = query("SELECT *, t.*, x AS y FROM t", [[1, "v"]], "x:INT,s:TEXT")
    assert result.columns == ["x", "s", "x", "s", "y"]
    assert result.rows == [[1, "v", 1, "v", 1]]


def test_scalar_functions() -> None:
    result = query("SELECT concat('a', 'b', 'c'), upper('hi'), lower('HI'), "
                   "length('abc'), abs(-2), abs(-2.5) FROM t", [[0]])
    assert result.rows == [["abc", "HI", "hi", 3, 2, 2.5]]
    assert type(result.rows[0][-1]) is float


def test_scalar_null_propagation() -> None:
    result = query("SELECT concat('a', NULL), upper(NULL), lower(NULL), "
                   "length(NULL), abs(NULL) FROM t", [[0]])
    assert result.rows == [[None] * 5]


def test_scalar_unicode_codepoints() -> None:
    assert scalar("length", ["\U0001f600e\u0301"]) == 3
    assert scalar("upper", ["stra\u00dfe"]) == "STRASSE"


def test_coalesce_first_present() -> None:
    result = query("SELECT coalesce(NULL, FALSE, 2), coalesce(NULL, 0, 1), "
                   "coalesce(NULL, '', 'x'), coalesce(NULL), coalesce(3, 1 / 0) "
                   "FROM t", [[0]])
    assert result.rows == [[False, 0, "", None, 3]]


def test_coalesce_short_circuits() -> None:
    assert query("SELECT coalesce(1, abs('bad')) FROM t", [[0]]).rows == [[1]]


def test_scalar_wrong_types() -> None:
    for expr in ("upper(1)", "lower(TRUE)", "length(1.0)", "abs('a')", "abs(TRUE)",
                 "concat('a', 1)", "concat(NULL, TRUE)"):
        with pytest.raises(TypeMismatchError):
            query(f"SELECT {expr} FROM t", [[0]])


def test_function_arity_message() -> None:
    for expr, name, actual, expected in (
            ("upper()", "upper", 0, 1), ("concat('a')", "concat", 1, 2),
            ("coalesce()", "coalesce", 0, 1), ("abs(1, 2)", "abs", 2, 1),
            ("count()", "count", 0, 1), ("sum(1,2)", "sum", 2, 1)):
        with pytest.raises(ArityError) as error:
            query(f"SELECT {expr} FROM t", [])
        assert all(part in str(error.value) for part in (name, str(actual), str(expected)))


def test_unknown_function_even_without_rows() -> None:
    with pytest.raises(UnknownFunctionError):
        query("SELECT mystery(x) FROM t", [])


def test_functions_case_insensitive() -> None:
    assert query("SELECT SuM(x), CoUnT(*), UpPeR('ok') FROM t", [[1], [2]]).rows == [
        [3, 2, "OK"]]


def test_where_true_only() -> None:
    assert query("SELECT x FROM t WHERE x > 1", [[None], [0], [2], [3]]).rows == [[2], [3]]
    assert query("SELECT x FROM t WHERE NULL", [[1]]).rows == []


def test_where_equals_null_returns_no_rows() -> None:
    assert query("SELECT x FROM t WHERE x = NULL", [[1], [None]]).rows == []


def test_where_rejects_nonlogical_values() -> None:
    for expr in ("1", "0", "1.0", "'true'"):
        with pytest.raises(TypeMismatchError):
            query(f"SELECT x FROM t WHERE {expr}", [[1]])


def test_is_null_predicates() -> None:
    assert query("SELECT x IS NULL, x IS NOT NULL FROM t", [[None], [1]]).rows == [
        [True, False], [False, True]]


def test_all_comparisons_propagate_null() -> None:
    for op in ("=", "<>", "<", "<=", ">", ">="):
        assert query(f"SELECT NULL {op} NULL FROM t", [[1]]).rows == [[None]]


def test_comparison_operators() -> None:
    assert query("SELECT 2 <> 1, 2 >= 2, 2 <= 2, 2 > 1, 2 < 1 FROM t", [[0]]).rows == [
        [True, True, True, True, False]]


def test_alias_not_visible_in_where() -> None:
    with pytest.raises(UnknownColumnError):
        query("SELECT x AS renamed FROM t WHERE renamed > 0", [[1]])


def test_where_input_wins_alias_collision() -> None:
    assert query("SELECT -x AS x FROM t WHERE x > 0", [[1], [-2]]).rows == [[-1]]


def test_unknown_columns_and_tables_on_empty_input() -> None:
    with pytest.raises(UnknownColumnError):
        query("SELECT missing FROM t", [])
    with pytest.raises(UnknownTableError):
        query("SELECT other.x FROM t", [])
    with pytest.raises(UnknownTableError):
        query("SELECT other.* FROM t", [])
    with pytest.raises(UnknownTableError):
        execute("SELECT x FROM missing", {})


def test_where_cannot_aggregate() -> None:
    with pytest.raises(AggregateError):
        query("SELECT x FROM t WHERE count(*) > 0", [[1]])


def test_count_star_empty_table_is_one_row() -> None:
    result = query("SELECT count(*) FROM t", [])
    assert result.columns == ["count(*)"]
    assert result.rows == [[0]]


def test_sum_empty_group_is_null() -> None:
    assert query("SELECT sum(x), avg(x), min(x), max(x), count(x) FROM t", []).rows == [
        [None, None, None, None, 0]]


def test_aggregate_all_null_inputs() -> None:
    assert query("SELECT count(*), count(x), sum(x), avg(x), min(x), max(x) FROM t",
                 [[None], [None]]).rows == [[2, 0, None, None, None, None]]


def test_aggregates_ignore_nulls() -> None:
    assert query("SELECT count(*), count(x), sum(x), avg(x), min(x), max(x) FROM t",
                 [[1], [None], [3]]).rows == [[3, 2, 4, 2.0, 1, 3]]


def test_sum_and_avg_result_types() -> None:
    assert type(aggregate("sum", [1, 2])) is int
    assert type(aggregate("sum", [1, 2.0])) is float
    assert type(aggregate("avg", [2, 4])) is float
    assert aggregate("avg", [None, 2, 4]) == 3.0


def test_aggregate_rejects_nonnumeric_inputs() -> None:
    for function in ("sum", "avg"):
        for values in ([True], ["1"], [1, True]):
            with pytest.raises(TypeMismatchError):
                aggregate(function, values)


def test_min_max_types_and_mismatches() -> None:
    assert aggregate("min", [None, "z", "a"]) == "a"
    assert aggregate("max", [False, True]) is True
    assert type(aggregate("min", [1.5, 1])) is int
    assert type(aggregate("max", [1, 1.5])) is float
    for name in ("min", "max"):
        for values in (["1", 2], [True, 1]):
            with pytest.raises(TypeMismatchError):
                aggregate(name, values)


def test_nested_aggregates_rejected() -> None:
    for expr in ("sum(count(x))", "max(abs(avg(x)))", "COUNT(sum(x))"):
        with pytest.raises(ParseError):
            parse(f"SELECT {expr} FROM t")


def test_only_count_accepts_star() -> None:
    for expr in ("sum(*)", "upper(*)", "count(t.*)", "count(*, x)", "1 + *"):
        with pytest.raises(ParseError):
            parse(f"SELECT {expr} FROM t")


def test_where_precedes_aggregation() -> None:
    assert query("SELECT count(*), sum(x) FROM t WHERE x > 1", [[1], [2], [3]]).rows == [
        [2, 5]]
    assert query("SELECT count(*), sum(x) FROM t WHERE FALSE", [[1]]).rows == [[0, None]]


def test_null_grouping_keys_equal() -> None:
    assert query("SELECT x, count(*) FROM t GROUP BY x",
                 [[None], [1], [None], [1]]).rows == [[None, 2], [1, 2]]


def test_group_first_seen_order() -> None:
    assert query("SELECT x, count(*) FROM t GROUP BY x",
                 [[3], [1], [3], [2], [1]]).rows == [[3, 2], [1, 2], [2, 1]]


def test_group_by_expression() -> None:
    result = query("SELECT length(s), count(*) FROM t GROUP BY length(s)",
                   [["abc"], [""], ["def"], [None]], "s:TEXT")
    assert result.rows == [[3, 2], [0, 1], [None, 1]]


def test_group_multiple_keys() -> None:
    result = query("SELECT x, y, count(*) FROM t GROUP BY x, y",
                   [[1, None], [1, 2], [1, None], [None, None]], "x:INT,y:INT")
    assert result.rows == [[1, None, 2], [1, 2, 1], [None, None, 1]]


def test_group_numeric_equivalence_not_bool_equivalence() -> None:
    result = query("SELECT coalesce(b, x), count(*) FROM t GROUP BY coalesce(b, x)",
                   [[True, None], [None, 1], [False, None], [None, 0]],
                   "b:BOOL,x:INT")
    assert result.rows == [[True, 1], [1, 1], [False, 1], [0, 1]]
    result = query("SELECT coalesce(x, y), count(*) FROM t GROUP BY coalesce(x, y)",
                   [[1, None], [None, 1.0]], "x:INT,y:FLOAT")
    assert result.rows == [[1, 2]]


def test_empty_explicit_group_by_has_no_groups() -> None:
    assert query("SELECT x, count(*) FROM t GROUP BY x", []).rows == []


def test_invalid_group_projection() -> None:
    for sql in ("SELECT y, count(*) FROM t GROUP BY x",
                "SELECT x, count(*) FROM t", "SELECT * FROM t GROUP BY x",
                "SELECT x FROM t GROUP BY x + 1"):
        with pytest.raises(GroupingError):
            query(sql, [], "x:INT,y:INT")


def test_group_qualified_and_unqualified_equivalent() -> None:
    assert query("SELECT t.x, count(*) FROM t GROUP BY x", [[1], [1]]).rows == [[1, 2]]


def test_group_expressions_can_compose_keys_and_aggregates() -> None:
    assert query("SELECT x + sum(y), upper('ok') FROM t GROUP BY x",
                 [[1, 2], [1, 3]], "x:INT,y:INT").rows == [[6, "OK"]]


def test_group_by_cannot_contain_aggregate() -> None:
    with pytest.raises(AggregateError):
        query("SELECT x FROM t GROUP BY sum(x)", [[1]])


def test_having_filters_groups() -> None:
    assert query("SELECT x, count(*) AS n FROM t GROUP BY x HAVING count(*) > 1",
                 [[1], [2], [1], [None]]).rows == [[1, 2]]


def test_having_unknown_and_false_drop_groups() -> None:
    assert query("SELECT sum(x) FROM t HAVING sum(x) > 0", []).rows == []
    assert query("SELECT count(*) FROM t HAVING FALSE", []).rows == []


def test_having_nonlogical_rejected() -> None:
    with pytest.raises(TypeMismatchError):
        query("SELECT count(*) FROM t HAVING 1", [])


def test_having_only_aggregate_forms_global_group() -> None:
    assert query("SELECT 42 FROM t HAVING count(*) = 0", []).rows == [[42]]
    assert query("SELECT 42 FROM t HAVING count(*) > 0", [[1], [2]]).rows == [[42]]


def test_having_cannot_see_projection_alias() -> None:
    with pytest.raises(UnknownColumnError):
        query("SELECT count(*) AS n FROM t HAVING n > 0", [[1]])


def test_having_ungrouped_reference_rejected() -> None:
    with pytest.raises(GroupingError):
        query("SELECT count(*) FROM t HAVING x > 0", [[1]])


def test_inner_join_left_major_order() -> None:
    tables = {"l": table([[2], [1], [None]], name="l"),
              "r": table([[1, "a"], [2, "b"], [1, "c"]],
                         "x:INT,s:TEXT", "r")}
    result = execute("SELECT l.x, r.s FROM l JOIN r ON l.x = r.x", tables)
    assert result.rows == [[2, "b"], [1, "a"], [1, "c"]]


def test_left_join_null_filling() -> None:
    tables = {"l": table([[1], [2], [None]], name="l"),
              "r": table([[1, "a"], [1, "b"]], "x:INT,s:TEXT", "r")}
    result = execute("SELECT * FROM l LEFT JOIN r ON l.x = r.x", tables)
    assert result.columns == ["x", "x", "s"]
    assert result.rows == [[1, 1, "a"], [1, 1, "b"], [2, None, None], [None, None, None]]


def test_left_join_empty_right() -> None:
    tables = {"l": table([[1], [2]], name="l"), "r": table([], name="r")}
    assert execute("SELECT * FROM l LEFT JOIN r ON TRUE", tables).rows == [
        [1, None], [2, None]]
    assert execute("SELECT * FROM l INNER JOIN r ON TRUE", tables).rows == []


def test_join_null_not_equal_to_null() -> None:
    tables = {"l": table([[None]], name="l"), "r": table([[None]], name="r")}
    assert execute("SELECT * FROM l JOIN r ON l.x = r.x", tables).rows == []


def test_join_ambiguous_unqualified_column() -> None:
    tables = {"l": table([], name="l"), "r": table([], name="r")}
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT x FROM l JOIN r ON TRUE", tables)
    with pytest.raises(UnknownTableError):
        execute("SELECT z.x FROM l JOIN r ON TRUE", tables)


def test_join_on_requires_logical_value() -> None:
    tables = {"l": table([[1]], name="l"), "r": table([[1]], name="r")}
    with pytest.raises(TypeMismatchError):
        execute("SELECT * FROM l JOIN r ON 1", tables)
    with pytest.raises(AggregateError):
        execute("SELECT * FROM l JOIN r ON count(*) > 0", tables)


def test_left_join_filter_and_aggregate() -> None:
    tables = {"l": table([[1], [2]], name="l"), "r": table([[1]], name="r")}
    result = execute("SELECT l.x, count(*), count(r.x) FROM l LEFT JOIN r ON l.x = r.x "
                     "GROUP BY l.x ORDER BY l.x DESC", tables)
    assert result.rows == [[2, 1, 0], [1, 1, 1]]


def test_nulls_sort_last_ascending_and_descending() -> None:
    rows = [[None], [2], [1], [None], [3]]
    assert query("SELECT x FROM t ORDER BY x", rows).rows == [[1], [2], [3], [None], [None]]
    assert query("SELECT x FROM t ORDER BY x DESC", rows).rows == [
        [3], [2], [1], [None], [None]]


def test_sort_is_stable() -> None:
    rows = [[1, "a"], [2, "b"], [1, "c"], [None, "d"], [None, "e"]]
    assert query("SELECT s FROM t ORDER BY x DESC", rows, "x:INT,s:TEXT").rows == [
        ["b"], ["a"], ["c"], ["d"], ["e"]]


def test_sort_multiple_keys() -> None:
    rows = [[1, 1], [2, 3], [1, 2], [1, None], [None, 9], [2, 1]]
    assert query("SELECT * FROM t ORDER BY x, y DESC", rows, "x:INT,y:INT").rows == [
        [1, 2], [1, 1], [1, None], [2, 3], [2, 1], [None, 9]]


def test_alias_visible_in_order_by() -> None:
    assert query("SELECT -x AS y FROM t ORDER BY y", [[1], [3], [2]]).rows == [
        [-3], [-2], [-1]]


def test_order_alias_wins_input_collision() -> None:
    assert query("SELECT -x AS x FROM t ORDER BY x", [[1], [3], [2]]).rows == [
        [-3], [-2], [-1]]
    assert query("SELECT -x AS x FROM t ORDER BY t.x", [[1], [3], [2]]).rows == [
        [-1], [-2], [-3]]


def test_order_by_alias_in_expression() -> None:
    assert query("SELECT x AS y FROM t ORDER BY -y", [[1], [3], [2]]).rows == [[3], [2], [1]]


def test_order_by_nonprojected_input() -> None:
    assert query("SELECT s FROM t ORDER BY x", [[2, "a"], [1, "b"]],
                 "x:INT,s:TEXT").rows == [["b"], ["a"]]


def test_order_incompatible_types() -> None:
    with pytest.raises(TypeMismatchError):
        query("SELECT coalesce(s, x) AS v FROM t ORDER BY v",
              [["a", None], [None, 1]], "s:TEXT,x:INT")
    with pytest.raises(TypeMismatchError):
        query("SELECT coalesce(b, x) AS v FROM t ORDER BY v",
              [[True, None], [None, 1]], "b:BOOL,x:INT")


def test_sort_bool_and_text() -> None:
    assert query("SELECT x FROM t ORDER BY x", [[True], [None], [False]], "x:BOOL").rows == [
        [False], [True], [None]]
    assert query("SELECT x FROM t ORDER BY x", [["a"], ["Z"]], "x:TEXT").rows == [["Z"], ["a"]]


def test_order_aggregate_and_alias() -> None:
    rows = [[1, 2], [2, 9], [1, 3]]
    for key in ("total", "sum(y)"):
        assert query(f"SELECT x, sum(y) AS total FROM t GROUP BY x ORDER BY {key} DESC",
                     rows, "x:INT,y:INT").rows == [[2, 9], [1, 5]]


def test_order_aggregate_argument_is_input() -> None:
    assert query("SELECT x, sum(x) FROM t GROUP BY x ORDER BY sum(x) DESC",
                 [[1], [2], [1], [1]]).rows == [[1, 3], [2, 2]]


def test_order_ungrouped_column_rejected() -> None:
    with pytest.raises(GroupingError):
        query("SELECT sum(x) FROM t ORDER BY x", [[1]])


def test_distinct_preserves_first_seen() -> None:
    assert query("SELECT DISTINCT x FROM t", [[2], [None], [1], [2], [None]]).rows == [
        [2], [None], [1]]


def test_distinct_bool_is_not_number() -> None:
    result = query("SELECT DISTINCT coalesce(b, x) FROM t",
                   [[True, None], [None, 1], [None, 1]], "b:BOOL,x:INT")
    assert len(result.rows) == 2
    assert type(result.rows[0][0]) is bool and type(result.rows[1][0]) is int


def test_distinct_numeric_equivalence() -> None:
    assert query("SELECT DISTINCT coalesce(x, y) FROM t",
                 [[1, None], [None, 1.0]], "x:INT,y:FLOAT").rows == [[1]]


def test_distinct_order_alias_and_expression() -> None:
    assert query("SELECT DISTINCT x + 1 AS y FROM t ORDER BY y DESC",
                 [[1], [2], [1]]).rows == [[3], [2]]
    assert query("SELECT DISTINCT x + 1 AS y FROM t ORDER BY x + 1 DESC",
                 [[1], [2], [1]]).rows == [[3], [2]]


def test_distinct_rejects_nonoutput_order_columns() -> None:
    with pytest.raises(UnknownColumnError):
        query("SELECT DISTINCT s FROM t ORDER BY x",
              [[1, "a"], [2, "a"]], "x:INT,s:TEXT")
    with pytest.raises(UnknownColumnError):
        query("SELECT DISTINCT x + 1 FROM t ORDER BY x", [])


def test_distinct_grouped_order_aggregate() -> None:
    assert query("SELECT DISTINCT x, sum(x) FROM t GROUP BY x ORDER BY sum(x) DESC",
                 [[1], [2], [1], [1]]).rows == [[1, 3], [2, 2]]


def test_offset_before_limit() -> None:
    assert query("SELECT x FROM t ORDER BY x LIMIT 2 OFFSET 1",
                 [[4], [2], [1], [3]]).rows == [[2], [3]]


def test_offset_without_limit_and_zero_limit() -> None:
    assert query("SELECT x FROM t OFFSET 2", [[1], [2], [3]]).rows == [[3]]
    assert query("SELECT x FROM t LIMIT 0", [[1]]).rows == []
    assert query("SELECT count(*) FROM t LIMIT 0", []).rows == []


def test_distinct_before_order_and_slice() -> None:
    assert query("SELECT DISTINCT x FROM t ORDER BY x DESC LIMIT 2 OFFSET 1",
                 [[1], [3], [3], [2], [None], [None]]).rows == [[2], [1]]


def test_plan_sequence_and_execution() -> None:
    sql = ("SELECT DISTINCT x, count(*) FROM t WHERE x IS NOT NULL GROUP BY x "
           "HAVING count(*) > 0 ORDER BY x LIMIT 2 OFFSET 1")
    pipeline = plan(parse(sql))
    assert [stage.name for stage in pipeline] == [
        "FROM", "WHERE", "GROUP BY", "AGGREGATE", "HAVING", "SELECT",
        "DISTINCT", "ORDER BY", "OFFSET", "LIMIT"]
    assert pipeline[0].name == "FROM" and len(pipeline[:2]) == 2
    tables = {"t": table([[1], [3], [2], [3], [None]])}
    assert execute_plan(pipeline, tables) == execute(sql, tables)
    assert execute_plan(pipeline, tables).rows == [[2, 1], [3, 2]]


def test_plan_join_precedes_where() -> None:
    pipeline = plan(parse("SELECT * FROM t LEFT JOIN r ON TRUE WHERE TRUE"))
    assert [stage.name for stage in pipeline] == ["FROM", "JOIN", "WHERE", "SELECT"]


def test_result_is_frozen() -> None:
    result = query("SELECT x FROM t", [[1]])
    with pytest.raises(FrozenInstanceError):
        result.columns = []


def test_public_exports_exist() -> None:
    assert microdb.__all__
    assert len(microdb.__all__) == len(set(microdb.__all__))
    assert all(hasattr(microdb, name) for name in microdb.__all__)


def test_exact_exception_hierarchy() -> None:
    from microdb import errors
    expected = {"LexError", "ParseError", "SchemaError", "TypeMismatchError",
                "UnknownColumnError", "AmbiguousColumnError", "UnknownTableError",
                "UnknownFunctionError", "ArityError", "AggregateError", "GroupingError"}
    actual = {name for name, value in vars(errors).items()
              if inspect.isclass(value) and value.__bases__ == (MicroDBError,)}
    assert actual == expected


def test_cli_acceptance_count() -> None:
    code, out, err = cli(
        ["--table", "t=people.csv", "SELECT count(*) FROM t WHERE age > 30"],
        "id:INT,name:TEXT,age:INT\n1,Ada,40\n2,Bob,20\n3,Cid,50\n")
    assert (code, out, err) == (0, "count(*)\n2\n", "")


def test_cli_null_empty_string_and_bool() -> None:
    code, out, err = cli(
        ["--table", "t=data.csv", "SELECT * FROM t"],
        "i:INT,f:FLOAT,b:BOOL,s:TEXT\n1,2,TrUe,''\n,,,hello\n")
    assert (code, out, err) == (0, "i,f,b,s\n1,2.0,true,\n,,,hello\n", "")


def test_cli_single_null_column_is_empty_line() -> None:
    assert cli(["--table", "t=data.csv", "SELECT x FROM t"], "x:INT\n\n") == (
        0, "x\n\n", "")


def test_cli_precise_quoting() -> None:
    code, out, err = cli(
        ["--table", "t=data.csv", "SELECT s FROM t"],
        's:TEXT\n"a,b"\n"a""b"\n"a\nb"\nplain\n\'\'\n')
    assert (code, out, err) == (0, 's\n"a,b"\n"a""b"\n"a\nb"\nplain\n\n', "")


def test_cli_bad_arguments() -> None:
    for args in ([], ["SELECT 1 FROM t"], ["--table", "bad", "SELECT 1 FROM t"],
                 ["--table", "t=", "SELECT 1 FROM t"]):
        code, out, err = cli(args, "")
        assert code == 2 and out == "" and err


def test_cli_unreadable_file() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch("builtins.open", side_effect=OSError("not readable")):
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            assert main(["--table", "t=data.csv", "SELECT * FROM t"]) == 2
    assert stdout.getvalue() == "" and "not readable" in stderr.getvalue()


def test_cli_malformed_header() -> None:
    for content in ("", "\n", "x\n", "x:INTEGER\n", "x:INT,x:INT\n",
                    "order:INT\n", '"x:INT\n'):
        code, out, err = cli(["--table", "t=data.csv", "SELECT * FROM t"], content)
        assert code == 2 and out == "" and err


def test_cli_invalid_data_is_database_error() -> None:
    for content in ("x:INT\nabc\n", "x:BOOL\n1\n", "x:INT\n1,2\n",
                    "x:INT\n''\n", 'x:TEXT\n"unterminated\n'):
        code, out, err = cli(["--table", "t=data.csv", "SELECT * FROM t"], content)
        assert code == 3 and out == "" and err


def test_cli_query_errors_have_no_stdout() -> None:
    for sql in ("SELECT missing FROM t", "SELECT x + TRUE FROM t",
                "SELECT FROM t", "SELECT ! FROM t"):
        code, out, err = cli(["--table", "t=data.csv", sql], "x:INT\n1\n")
        assert code == 3 and out == "" and err


def test_cli_late_failure_does_not_emit_partial_rows() -> None:
    code, out, err = cli(["--table", "t=data.csv", "SELECT coalesce(x, abs(s)) FROM t"],
                         "x:INT,s:TEXT\n1,ok\n,bad\n")
    assert code == 3 and out == "" and err


def test_cli_multiple_tables() -> None:
    streams = [io.StringIO("x:INT\n1\n2\n"), io.StringIO("y:TEXT\nok\n")]
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch("builtins.open", side_effect=streams):
        with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            code = main(["--table", "l=left.csv", "--table", "r=right.csv",
                         "SELECT * FROM l JOIN r ON TRUE"])
    assert code == 0 and stderr.getvalue() == ""
    assert stdout.getvalue() == "x,y\n1,ok\n2,ok\n"


def test_cli_duplicate_table_name() -> None:
    code, out, err = cli(["--table", "t=a.csv", "--table", "t=b.csv",
                          "SELECT * FROM t"], "x:INT\n1\n")
    assert code == 2 and out == "" and err


def test_module_cli_exit_code() -> None:
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-B", "-m", "microdb", "SELECT 1 FROM t"],
                            capture_output=True, env=environment, check=False)
    assert result.returncode == 2 and result.stdout == b"" and result.stderr


def test_cli_success_bytes_have_only_lf() -> None:
    script = (
        "import io,sys; from unittest.mock import patch; "
        "from microdb.__main__ import main; "
        "p=patch('builtins.open',return_value=io.StringIO('x:INT\\n1\\n')); "
        "p.start(); sys.exit(main(['--table','t=data.csv','SELECT x FROM t']))")
    result = subprocess.run([sys.executable, "-B", "-c", script],
                            capture_output=True, check=False)
    assert result.returncode == 0 and result.stdout == b"x\n1\n" and not result.stderr


def test_public_function_annotations() -> None:
    for name in ("value", "schema", "lexer", "parser", "expr", "aggregate",
                 "planner", "executor", "errors", "__main__"):
        module = sys.modules[f"microdb.{name}"]
        for value in vars(module).values():
            if inspect.isfunction(value) and value.__module__ == module.__name__:
                _assert_annotations(value)
            if inspect.isclass(value) and value.__module__ == module.__name__:
                for method_name, method in vars(value).items():
                    if isinstance(method, property):
                        _assert_annotations(method.fget)
                    elif inspect.isfunction(method) and method_name != "__repr__":
                        if method.__code__.co_filename != "<string>":
                            _assert_annotations(method)


def _assert_annotations(function: object) -> None:
    signature = inspect.signature(function)
    assert signature.return_annotation is not inspect.Signature.empty, function
    for name, parameter in signature.parameters.items():
        if name not in ("self", "cls"):
            assert parameter.annotation is not inspect.Parameter.empty, (function, name)


def test_function_bodies_at_most_sixty_lines() -> None:
    paths = [*Path("microdb").glob("*.py"), Path("tests") / "test_microdb.py"]
    for path in paths:
        tokens = list(py_tokenize.generate_tokens(io.StringIO(path.read_text()).readline))
        _check_function_lengths(tokens, path)


def _check_function_lengths(tokens: list[py_tokenize.TokenInfo], path: Path) -> None:
    functions = []
    depth, pending = 0, None
    for token in tokens:
        if token.type == py_tokenize.NAME and token.string == "def":
            pending = token.start[0]
        elif token.type == py_tokenize.INDENT:
            depth += 1
            if pending is not None:
                functions.append((depth, pending))
                pending = None
        elif token.type == py_tokenize.DEDENT:
            while functions and functions[-1][0] == depth:
                _, start = functions.pop()
                assert token.start[0] - start <= 60, (path, start, token.start[0])
            depth -= 1
        elif token.type == py_tokenize.NEWLINE and pending is not None:
            # A one-line overload has no INDENT token.
            line = token.line.strip()
            if line.endswith("..."):
                pending = None

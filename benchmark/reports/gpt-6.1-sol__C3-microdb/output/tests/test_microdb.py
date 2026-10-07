"""Value, relational, parser, planner, and CLI regression tests."""

from dataclasses import FrozenInstanceError
import inspect
import io
from pathlib import Path
import subprocess
import sys
import tokenize as python_tokens

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


def table(rows: list[list[object]] | None = None) -> Table:
    return Table("t", [Column("id", "INT"), Column("name", "TEXT"),
                       Column("age", "INT"), Column("active", "BOOL")],
                 rows if rows is not None else
                 [[1, "Ada", 40, True], [2, "Bob", None, False],
                  [3, "Cy", 35, None], [4, "Di", 20, True]])


def run(query: str, rows: list[list[object]] | None = None) -> list[list[object]]:
    return execute(query, {"t": table(rows)}).rows


def mock_csv(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    def open_csv(*args: object, **kwargs: object) -> io.StringIO:
        return io.StringIO(content)
    monkeypatch.setattr("builtins.open", open_csv)


@pytest.mark.parametrize("value,kind", [(1, "INT"), (1.0, "FLOAT"), ("", "TEXT"),
                                       (True, "BOOL"), (False, "BOOL"), (None, "NULL")])
def test_type_of(value: object, kind: str) -> None:
    assert type_of(value) == kind


def test_unsupported_value_type() -> None:
    with pytest.raises(TypeMismatchError):
        type_of([])


def test_bool_not_numeric() -> None:
    assert is_numeric(1) and is_numeric(1.0)
    assert not any(is_numeric(v) for v in [True, False, None, "1"])


def test_and_truth_table() -> None:
    values = [True, False, None]
    expected = [[True, False, None], [False, False, False], [None, False, None]]
    assert [[and_(a, b) for b in values] for a in values] == expected


def test_or_truth_table() -> None:
    values = [True, False, None]
    expected = [[True, True, True], [True, False, None], [True, None, None]]
    assert [[or_(a, b) for b in values] for a in values] == expected


def test_not_truth_table() -> None:
    assert [not_(v) for v in [True, False, None]] == [False, True, None]


def test_logical_rejects_non_bool() -> None:
    with pytest.raises(TypeMismatchError):
        and_(False, 1)


def test_null_equality_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(None, "x") is None
    assert compare_lt(1, None) is None


def test_comparison_numeric_widening() -> None:
    assert compare_eq(3, 3.0) is True
    assert compare_lt(3, 3.5) is True


def test_text_unicode_order() -> None:
    assert compare_lt("Z", "a") is True
    assert compare_lt("a", "\u00e9") is True


def test_bool_order() -> None:
    assert compare_lt(False, True) is True
    assert compare_eq(True, False) is False


@pytest.mark.parametrize("a,b", [(True, 1), (False, 0.0), ("3", 3), ("x", True)])
def test_incompatible_comparisons(a: object, b: object) -> None:
    with pytest.raises(TypeMismatchError):
        compare_eq(a, b)
    with pytest.raises(TypeMismatchError):
        compare_lt(a, b)


def test_arithmetic_result_types() -> None:
    for op in ("+", "-", "*"):
        assert type(arith(op, 2, 3)) is int
        assert type(arith(op, 2.0, 3)) is float
    assert arith("/", 7, 2) == 3.5
    assert type(arith("/", 8, 2)) is float


def test_division_and_modulo_zero() -> None:
    assert arith("/", 2, 0) is None
    assert arith("/", 2, 0.0) is None
    assert arith("%", 2, 0) is None


def test_modulo_sign_and_types() -> None:
    assert arith("%", -7, 3) == 2
    assert arith("%", 7, -3) == -2
    with pytest.raises(TypeMismatchError):
        arith("%", 2.0, 1)


def test_arithmetic_null_and_wrong_types() -> None:
    assert arith("+", None, "x") is None
    for value in [True, "x"]:
        with pytest.raises(TypeMismatchError):
            arith("+", value, 1)


def test_negation() -> None:
    assert negate(None) is None
    assert negate(2) == -2 and type(negate(2)) is int
    assert type(negate(2.0)) is float
    with pytest.raises(TypeMismatchError):
        negate(True)


def test_empty_schema() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])


def test_duplicate_column_names() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])
    assert len(Table("t", [Column("a", "INT"), Column("A", "INT")], []).columns) == 2


def test_invalid_column_type() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("x", "NULL")], [])


def test_row_width_validation() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


@pytest.mark.parametrize("kind,value", [("INT", True), ("INT", 3.0), ("BOOL", 1),
                                        ("FLOAT", True), ("TEXT", 3), ("BOOL", "true")])
def test_cell_type_validation(kind: str, value: object) -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", kind)], [[value]])


def test_float_column_widening() -> None:
    t = Table("t", [Column("a", "FLOAT")], [[3], [None]])
    assert t.rows == [[3.0], [None]]
    assert type(t.rows[0][0]) is float


def test_schema_nulls_and_column_lookup() -> None:
    t = Table("t", [Column("a", "BOOL")], [[None]])
    assert t.column_index("a") == 0
    with pytest.raises(SchemaError):
        t.column_index("A")


def test_column_frozen_and_table_defensive_copy() -> None:
    column = Column("a", "INT")
    with pytest.raises(FrozenInstanceError):
        column.name = "b"
    rows = [[1]]
    t = Table("t", [column], rows)
    rows[0][0] = True
    t.rows[0][0] = False
    assert t.rows == [[1]]


def test_lexer_floats() -> None:
    tokens = tokenize("1. .5 1e3 1.5E-2 0 2.e+1")
    assert [token.value for token in tokens[:-1]] == [1.0, .5, 1000.0, .015, 0, 20.0]
    assert [token.kind for token in tokens[:-1]] == ["FLOAT"] * 4 + ["INT", "FLOAT"]


def test_lexer_quoted_text_and_comments() -> None:
    tokens = tokenize("'a''b\n--not a comment' -- comment\n SELECT")
    assert tokens[0].value == "a'b\n--not a comment"
    assert tokens[1].kind == "SELECT"


def test_lex_error_offsets() -> None:
    with pytest.raises(LexError) as error:
        tokenize("SELECT @")
    assert error.value.offset == 7
    with pytest.raises(LexError) as error:
        tokenize(" 'unfinished")
    assert error.value.offset == 1


def test_parser_precedence() -> None:
    assert run("SELECT 1 + 2 * 3, -7 % 3 FROM t LIMIT 1") == [[7, 2]]
    assert run("SELECT NOT 1 = 1, TRUE OR FALSE AND FALSE FROM t LIMIT 1") == [[False, True]]


def test_parenthesized_expression() -> None:
    result = execute("SELECT ( 1 + 2 ) * 3 FROM t LIMIT 1", {"t": table()})
    assert result.rows == [[9]]
    assert result.columns == ["( 1 + 2 ) * 3"]


@pytest.mark.parametrize("query", ["SELECT 1 < 2 < 3 FROM t", "SELECT id FROM t OFFSET -1",
                                  "SELECT id FROM t LIMIT 1.0", "SELECT order FROM t",
                                  "SELECT id FROM t WHERE id = 1 WHERE TRUE",
                                  "SELECT id FROM t ORDER BY id WHERE TRUE"])
def test_parse_invalid_queries(query: str) -> None:
    with pytest.raises(ParseError) as error:
        parse(query)
    assert type(error.value.offset) is int


def test_nested_aggregates_rejected() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(id)) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT sum(abs(max(id))) FROM t")


def test_star_only_count_call() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(*) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT upper(*) FROM t")


def test_functions_case_insensitive() -> None:
    assert run("select UPPER(name), Length(name), ABS(-id) from t limit 1") == [["ADA", 3, 1]]


def test_concat_and_null_propagation() -> None:
    assert scalar("concat", ["a", "", "b"]) == "ab"
    assert scalar("concat", ["a", None]) is None
    with pytest.raises(TypeMismatchError):
        scalar("concat", [None, 1])


def test_text_scalar_functions() -> None:
    assert scalar("lower", ["ABC"]) == "abc"
    assert scalar("upper", ["abc"]) == "ABC"
    assert scalar("length", ["a\u00e9"]) == 2
    for name in ["upper", "lower", "length"]:
        assert scalar(name, [None]) is None
        with pytest.raises(TypeMismatchError):
            scalar(name, [True])


def test_abs_scalar() -> None:
    assert scalar("abs", [-1]) == 1
    assert type(scalar("abs", [-1.5])) is float
    assert scalar("abs", [None]) is None
    with pytest.raises(TypeMismatchError):
        scalar("abs", [False])


def test_coalesce_first_nonnull() -> None:
    assert scalar("coalesce", [None, False, 1]) is False
    assert scalar("coalesce", [None, "", 1]) == ""
    assert scalar("coalesce", [None, None]) is None


@pytest.mark.parametrize("call,expected,actual", [("upper()", "1", "0"),
                                                  ("abs(1, 2)", "1", "2"),
                                                  ("concat('a')", "2", "1"),
                                                  ("coalesce()", "1", "0"),
                                                  ("count()", "1", "0"),
                                                  ("sum(1, 2)", "1", "2")])
def test_arity_errors(call: str, expected: str, actual: str) -> None:
    with pytest.raises(ArityError) as error:
        run(f"SELECT {call} FROM t", [])
    assert call.split("(")[0] in str(error.value)
    assert expected in str(error.value) and actual in str(error.value)


def test_unknown_function_on_empty_input() -> None:
    with pytest.raises(UnknownFunctionError):
        run("SELECT mystery(id) FROM t", [])


def test_where_true_only() -> None:
    assert run("SELECT id FROM t WHERE active") == [[1], [4]]
    assert run("SELECT id FROM t WHERE age = NULL") == []
    assert run("SELECT id FROM t WHERE age IS NULL") == [[2]]
    assert run("SELECT id FROM t WHERE age IS NOT NULL") == [[1], [3], [4]]


def test_where_requires_boolean() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t WHERE 1")


def test_where_alias_not_visible() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT id AS alias FROM t WHERE alias = 1")


def test_where_aggregate_rejected() -> None:
    with pytest.raises(AggregateError):
        run("SELECT id FROM t WHERE count(*) > 0", [])


def test_aggregate_empty_input() -> None:
    assert aggregate("sum", []) is None
    assert aggregate("avg", [None]) is None
    assert aggregate("min", []) is None
    assert aggregate("max", [None]) is None
    assert aggregate("count", []) == 0


def test_global_aggregate_empty_table() -> None:
    assert run("SELECT count(*), count(age), sum(age), avg(age), min(age), max(age) FROM t",
               []) == [[0, 0, None, None, None, None]]


def test_aggregates_ignore_nulls() -> None:
    assert run("SELECT count(*), count(age), sum(age), avg(age), min(age), max(age) FROM t") == [
        [4, 3, 95, 95 / 3, 20, 40]]


def test_sum_and_avg_types() -> None:
    assert type(aggregate("sum", [1, None, 2])) is int
    assert type(aggregate("sum", [1, 2.0])) is float
    assert type(aggregate("avg", [1, 3])) is float


def test_aggregates_reject_bool_numeric() -> None:
    for name in ["sum", "avg"]:
        with pytest.raises(TypeMismatchError):
            aggregate(name, [True])
        with pytest.raises(TypeMismatchError):
            aggregate(name, ["x"])


def test_min_max_order_and_preservation() -> None:
    assert aggregate("min", ["z", None, "a"]) == "a"
    assert aggregate("max", [False, True]) is True
    assert type(aggregate("min", [1, 2.0])) is int
    with pytest.raises(TypeMismatchError):
        aggregate("min", [1, "x"])


def test_null_group_keys_and_first_seen_order() -> None:
    rows = [[1, "a", None, True], [2, "b", 4, False],
            [3, "c", None, True], [4, "d", 2, False]]
    assert run("SELECT age, count(*) FROM t GROUP BY age", rows) == [[None, 2], [4, 1], [2, 1]]


def test_multiple_group_keys() -> None:
    rows = [[1, "x", None, True], [2, "x", None, False], [3, "x", None, True]]
    assert run("SELECT age, active, count(*) FROM t GROUP BY age, active", rows) == [
        [None, True, 2], [None, False, 1]]


def test_group_expression() -> None:
    rows = [[1, "aa", 1, True], [2, "bb", 2, True], [3, "c", 3, False]]
    assert run("SELECT length(name) AS n, sum(age) FROM t GROUP BY length(name)", rows) == [
        [2, 3], [1, 3]]


def test_grouping_error() -> None:
    with pytest.raises(GroupingError):
        run("SELECT name, count(*) FROM t GROUP BY age")
    with pytest.raises(GroupingError):
        run("SELECT id, count(*) FROM t")


def test_group_projection_requires_exact_expression() -> None:
    with pytest.raises(GroupingError):
        run("SELECT age + 1 FROM t GROUP BY age")
    assert run("SELECT t.age FROM t GROUP BY age") == [[40], [None], [35], [20]]


def test_group_empty_vs_global_empty() -> None:
    assert run("SELECT age, count(*) FROM t GROUP BY age", []) == []
    assert run("SELECT count(*) FROM t WHERE FALSE") == [[0]]


def test_having_after_where() -> None:
    rows = [[1, "a", 10, True], [2, "b", 10, False], [3, "c", 20, True]]
    assert run("SELECT age, count(*) FROM t WHERE active GROUP BY age HAVING count(*) > 1",
               rows) == []
    assert run("SELECT age, count(*) FROM t GROUP BY age HAVING count(*) > 1", rows) == [[10, 2]]


def test_having_unknown_drops_group() -> None:
    assert run("SELECT count(*) FROM t HAVING sum(age) = NULL") == []
    with pytest.raises(TypeMismatchError):
        run("SELECT count(*) FROM t HAVING 1")


def test_having_aggregate_triggers_global_group() -> None:
    assert run("SELECT 1 FROM t HAVING count(*) = 0", []) == [[1]]
    assert run("SELECT 1 FROM t HAVING count(*) > 0") == [[1]]


def test_having_alias_not_visible() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT count(*) AS n FROM t HAVING n > 0")


def test_aggregate_expression_and_group_order() -> None:
    rows = [[1, "a", 10, True], [2, "b", 10, False], [3, "c", 20, True]]
    assert run("SELECT age, sum(id) + 1 AS total FROM t GROUP BY age ORDER BY total DESC",
               rows) == [[10, 4], [20, 4]]


def test_order_alias_visible() -> None:
    assert run("SELECT -id AS n FROM t ORDER BY n") == [[-4], [-3], [-2], [-1]]


def test_alias_shadows_input() -> None:
    assert run("SELECT -id AS id FROM t ORDER BY id") == [[-4], [-3], [-2], [-1]]
    assert run("SELECT -id AS id FROM t ORDER BY t.id") == [[-1], [-2], [-3], [-4]]
    assert run("SELECT -id AS id FROM t ORDER BY id + 1") == [[-4], [-3], [-2], [-1]]


def test_order_nonselected_input() -> None:
    assert run("SELECT name FROM t ORDER BY age") == [["Di"], ["Cy"], ["Ada"], ["Bob"]]


def test_nulls_last_desc() -> None:
    assert run("SELECT age FROM t ORDER BY age DESC") == [[40], [35], [20], [None]]


def test_sort_stability() -> None:
    rows = [[4, "d", 1, True], [2, "b", 1, True], [3, "c", None, True],
            [1, "a", None, True]]
    assert run("SELECT id FROM t ORDER BY age DESC", rows) == [[4], [2], [3], [1]]


def test_multiple_sort_keys() -> None:
    rows = [[1, "a", 1, True], [2, "b", 2, True], [3, "c", 1, False],
            [4, "d", None, False]]
    assert run("SELECT id FROM t ORDER BY age ASC, id DESC", rows) == [[3], [1], [2], [4]]


def test_sort_incompatible_values() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t ORDER BY coalesce(age, name)")


def test_distinct_reflexive_nulls() -> None:
    rows = [[1, "a", None, True], [2, "b", None, False], [3, "c", 2, False]]
    assert run("SELECT DISTINCT age FROM t", rows) == [[None], [2]]


def test_distinct_bool_distinct_from_number() -> None:
    rows = [[1, "a", 1, None], [2, "b", None, True]]
    assert run("SELECT DISTINCT coalesce(active, age) FROM t", rows) == [[1], [True]]


def test_distinct_before_sort_and_slice() -> None:
    rows = [[1, "a", 2, True], [2, "b", 2, True], [3, "c", 1, False]]
    assert run("SELECT DISTINCT age FROM t ORDER BY age LIMIT 1 OFFSET 1", rows) == [[2]]


def test_distinct_order_only_output() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT name FROM t ORDER BY age")
    assert run("SELECT DISTINCT id + 1 AS n FROM t ORDER BY id + 1 DESC") == [[5], [4], [3], [2]]
    assert run("SELECT DISTINCT id AS n FROM t ORDER BY n DESC") == [[4], [3], [2], [1]]


def test_distinct_selected_aggregate_order() -> None:
    assert run("SELECT DISTINCT sum(age) AS total FROM t ORDER BY sum(age)") == [[95]]


def test_order_aggregate_input_not_alias() -> None:
    assert run("SELECT sum(age) AS age FROM t ORDER BY sum(age)") == [[95]]
    assert run("SELECT age, sum(id) AS id FROM t GROUP BY age ORDER BY avg(id) DESC") == [
        [20, 4], [35, 3], [None, 2], [40, 1]]


def test_offset_before_limit() -> None:
    assert run("SELECT id FROM t LIMIT 2 OFFSET 1") == [[2], [3]]
    assert run("SELECT id FROM t OFFSET 3") == [[4]]
    assert run("SELECT id FROM t LIMIT 0") == []


def joined_tables() -> dict[str, Table]:
    return {"l": Table("l", [Column("id", "INT")], [[2], [1], [None], [3]]),
            "r": Table("r", [Column("id", "INT"), Column("label", "TEXT")],
                       [[1, "a"], [2, "b"], [2, "c"], [None, "null"]])}


def test_inner_join_left_major_order() -> None:
    assert execute("SELECT l.id, r.label FROM l JOIN r ON l.id = r.id",
                   joined_tables()).rows == [[2, "b"], [2, "c"], [1, "a"]]


def test_left_join_null_fill() -> None:
    assert execute("SELECT * FROM l LEFT JOIN r ON l.id = r.id", joined_tables()).rows == [
        [2, 2, "b"], [2, 2, "c"], [1, 1, "a"], [None, None, None], [3, None, None]]


def test_join_unknown_and_ambiguous_columns() -> None:
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM l JOIN r ON l.id = r.id", joined_tables())
    with pytest.raises(UnknownTableError):
        execute("SELECT z.id FROM l JOIN r ON l.id = r.id", joined_tables())


def test_join_on_true_only() -> None:
    assert execute("SELECT * FROM l JOIN r ON NULL", joined_tables()).rows == []
    with pytest.raises(TypeMismatchError):
        execute("SELECT * FROM l JOIN r ON 1", joined_tables())


def test_qualified_wildcard() -> None:
    result = execute("SELECT r.*, l.id FROM l JOIN r ON l.id = r.id", joined_tables())
    assert result.columns == ["id", "label", "id"]
    assert result.rows == [[2, "b", 2], [2, "c", 2], [1, "a", 1]]


def test_unknown_table_and_column_on_empty() -> None:
    with pytest.raises(UnknownTableError):
        execute("SELECT * FROM missing", {})
    with pytest.raises(UnknownColumnError):
        run("SELECT missing FROM t", [])
    with pytest.raises(UnknownTableError):
        run("SELECT z.* FROM t", [])


def test_case_sensitive_identifiers() -> None:
    t = Table("t", [Column("a", "INT"), Column("A", "INT")], [[1, 2]])
    assert execute("select a, A from t", {"t": t}).rows == [[1, 2]]
    with pytest.raises(UnknownTableError):
        execute("SELECT a FROM T", {"t": t})


def test_output_column_names() -> None:
    result = execute("SELECT t.name, age  +\n  1, count(*) AS n FROM t GROUP BY name, age + 1",
                     {"t": table()})
    assert result.columns == ["name", "age + 1", "n"]


def test_result_frozen() -> None:
    result = execute("SELECT id FROM t", {"t": table()})
    with pytest.raises(FrozenInstanceError):
        result.rows = []


def test_plan_inspection_and_execute() -> None:
    pipeline = plan(parse("SELECT count(*) FROM t WHERE active"))
    assert [stage.name for stage in pipeline] == [
        "FROM", "WHERE", "GROUP BY", "AGGREGATE", "HAVING", "SELECT", "DISTINCT",
        "ORDER BY", "OFFSET", "LIMIT"]
    assert pipeline[0].name == "FROM" and len(pipeline[:2]) == 2
    assert execute_plan(pipeline, {"t": table()}).rows == [[2]]


def test_plan_join_stage() -> None:
    pipeline = plan(parse("SELECT * FROM l LEFT JOIN r ON TRUE"))
    assert [stage.name for stage in pipeline][:3] == ["FROM", "JOIN", "WHERE"]


def test_public_exports() -> None:
    assert microdb.__all__
    assert all(hasattr(microdb, name) for name in microdb.__all__)
    assert len(set(microdb.__all__)) == len(microdb.__all__)


def test_error_hierarchy_exact() -> None:
    assert {cls.__name__ for cls in MicroDBError.__subclasses__()} == {
        "LexError", "ParseError", "SchemaError", "TypeMismatchError", "UnknownColumnError",
        "AmbiguousColumnError", "UnknownTableError", "UnknownFunctionError", "ArityError",
        "AggregateError", "GroupingError"}


def test_cli_success_count(monkeypatch: pytest.MonkeyPatch,
                           capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "id:INT,name:TEXT,age:INT\n1,Ada,40\n2,Bob,20\n3,Cy,35\n")
    assert main(["--table", "t=people.csv", "SELECT count(*) FROM t WHERE age > 30"]) == 0
    assert capsys.readouterr().out == "count(*)\n2\n"


def test_cli_null_single_field(monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "a:INT\n\n")
    assert main(["--table", "t=data.csv", "SELECT a FROM t"]) == 0
    assert capsys.readouterr().out == "a\n\n"


def test_cli_empty_string_and_bool(monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "s:TEXT,b:BOOL,f:FLOAT\n'',TRUE,3\n,FALSE,1.5\n")
    assert main(["--table", "t=data.csv", "SELECT s, b, f FROM t"]) == 0
    assert capsys.readouterr().out == "s,b,f\n,true,3.0\n,false,1.5\n"


def test_cli_csv_quoting(monkeypatch: pytest.MonkeyPatch,
                         capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, 's:TEXT\n"a,b"\n"a""b"\n"a\nb"\n')
    assert main(["--table", "t=data.csv", "SELECT s FROM t"]) == 0
    assert capsys.readouterr().out == 's\n"a,b"\n"a""b"\n"a\nb"\n'


def test_cli_usage_missing_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["SELECT 1 FROM t"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err


def test_cli_bad_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--unknown"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err


def test_cli_unreadable_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--table", "t=nonexistent-file-microdb.csv", "SELECT * FROM t"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err


@pytest.mark.parametrize("header", ["", "a", "a:INT,a:TEXT\n", "a:BAD\n", "order:INT\n"])
def test_cli_malformed_header(monkeypatch: pytest.MonkeyPatch,
                              capsys: pytest.CaptureFixture[str], header: str) -> None:
    mock_csv(monkeypatch, header)
    assert main(["--table", "t=data.csv", "SELECT * FROM t"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err


def test_cli_query_error_no_stdout(monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "a:INT\n1\n")
    assert main(["--table", "t=data.csv", "SELECT missing FROM t"]) == 3
    captured = capsys.readouterr()
    assert not captured.out and "Unknown column" in captured.err


def test_cli_data_error_no_stdout(monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "a:BOOL\nmaybe\n")
    assert main(["--table", "t=data.csv", "SELECT * FROM t"]) == 3
    captured = capsys.readouterr()
    assert not captured.out and "BOOL" in captured.err


def test_cli_bad_table_spec(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--table", "bad-spec", "SELECT * FROM t"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err


def test_cli_duplicate_tables(monkeypatch: pytest.MonkeyPatch,
                              capsys: pytest.CaptureFixture[str]) -> None:
    mock_csv(monkeypatch, "a:INT\n1\n")
    assert main(["--table", "t=one.csv", "--table", "t=two.csv", "SELECT * FROM t"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "Duplicate table" in captured.err


def test_cli_module_entrypoint() -> None:
    result = subprocess.run([sys.executable, "-B", "-m", "microdb", "SELECT 1 FROM t"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 2 and result.stdout == "" and result.stderr


def test_public_function_annotations() -> None:
    for name in microdb.__all__:
        value = getattr(microdb, name)
        if not inspect.isfunction(value):
            continue
        signature = inspect.signature(value)
        assert signature.return_annotation is not inspect.Signature.empty, name
        assert all(p.annotation is not inspect.Parameter.empty
                   for p in signature.parameters.values()), name


def test_function_bodies_at_most_sixty_lines() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in list((root / "microdb").glob("*.py")) + [Path(__file__)]:
        tokens = list(python_tokens.generate_tokens(io.StringIO(path.read_text()).readline))
        _check_function_lengths(tokens, path)


def _check_function_lengths(tokens: list[python_tokens.TokenInfo], path: Path) -> None:
    for index, token in enumerate(tokens):
        if token.type != python_tokens.NAME or token.string != "def":
            continue
        newline = next(i for i in range(index, len(tokens))
                       if tokens[i].type == python_tokens.NEWLINE)
        if tokens[newline + 1].type != python_tokens.INDENT:
            continue
        start = tokens[newline + 1].start[0]
        depth = 1
        end = start
        for body_token in tokens[newline + 2:]:
            if body_token.type == python_tokens.INDENT:
                depth += 1
            elif body_token.type == python_tokens.DEDENT:
                depth -= 1
                if depth == 0:
                    break
            if body_token.type not in (python_tokens.NL, python_tokens.NEWLINE,
                                       python_tokens.COMMENT):
                end = body_token.end[0]
        assert end - start + 1 <= 60, f"{path.name}:{token.start[0]} exceeds 60 lines"

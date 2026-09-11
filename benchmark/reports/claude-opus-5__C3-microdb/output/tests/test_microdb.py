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
    execute,
    parse,
    plan,
    tokenize,
)
from microdb.__main__ import main, quote_field, render_value, split_csv
from microdb.executor import execute_plan
from microdb.value import and_, arith, compare_eq, compare_lt, is_numeric, negate, not_, or_, type_of

ROOT = Path(__file__).resolve().parent.parent


def _people() -> Table:
    return Table(
        "t",
        [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT")],
        [[1, "Ada", 36], [2, "Bob", 25], [3, "Cleo", 41], [4, "Dan", None]],
    )


def _nulls() -> Table:
    return Table(
        "t",
        [Column("a", "INT"), Column("b", "TEXT")],
        [[1, "x"], [None, "y"], [2, None], [1, "z"]],
    )


def _empty() -> Table:
    return Table("e", [Column("a", "INT")], [])


def run(sql: str, tables: dict[str, Table] | None = None) -> microdb.Result:
    return execute(sql, tables if tables is not None else {"t": _people()})


# --------------------------------------------------------------- value model


def test_type_of_covers_every_kind() -> None:
    assert [type_of(v) for v in (1, 1.5, "a", True, None)] == [
        "INT", "FLOAT", "TEXT", "BOOL", "NULL"
    ]


def test_bool_is_not_numeric() -> None:
    assert is_numeric(1) and is_numeric(1.5)
    assert not is_numeric(True) and not is_numeric(None) and not is_numeric("1")


def test_and_truth_table() -> None:
    table = {
        (True, True): True, (True, False): False, (True, None): None,
        (False, True): False, (False, False): False, (False, None): False,
        (None, True): None, (None, False): False, (None, None): None,
    }
    assert {(a, b): and_(a, b) for a, b in table} == table


def test_or_truth_table() -> None:
    table = {
        (True, True): True, (True, False): True, (True, None): True,
        (False, True): True, (False, False): False, (False, None): None,
        (None, True): True, (None, False): None, (None, None): None,
    }
    assert {(a, b): or_(a, b) for a, b in table} == table


def test_not_truth_table() -> None:
    assert (not_(True), not_(False), not_(None)) == (False, True, None)


def test_null_equals_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(1, None) is None
    assert compare_lt(None, "a") is None


def test_numeric_cross_type_comparison() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True


def test_text_and_bool_comparison() -> None:
    assert compare_lt("a", "b") is True
    assert compare_lt(False, True) is True


def test_incompatible_comparison_raises() -> None:
    for a, b in ((True, 1), ("a", 1), (True, "a")):
        with pytest.raises(TypeMismatchError):
            compare_lt(a, b)


def test_arith_types_and_null() -> None:
    assert arith("+", 1, 2) == 3 and type_of(arith("+", 1, 2)) == "INT"
    assert type_of(arith("*", 2, 1.5)) == "FLOAT"
    assert arith("-", None, 1) is None


def test_division_always_float() -> None:
    assert arith("/", 7, 2) == 3.5
    assert type_of(arith("/", 4, 2)) == "FLOAT"


def test_division_and_modulo_by_zero_is_null() -> None:
    assert arith("/", 1, 0) is None
    assert arith("/", 1, 0.0) is None
    assert arith("%", 1, 0) is None


def test_modulo_rules() -> None:
    assert arith("%", -7, 3) == 2
    with pytest.raises(TypeMismatchError):
        arith("%", 7.0, 3)


def test_arith_rejects_text_and_bool() -> None:
    for bad in ("a", True):
        with pytest.raises(TypeMismatchError):
            arith("+", 1, bad)


def test_negate() -> None:
    assert negate(3) == -3 and type_of(negate(3.0)) == "FLOAT"
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        negate("a")


# ------------------------------------------------------------------- schema


def test_schema_rejects_empty_columns() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])


def test_schema_duplicate_names_are_case_sensitive() -> None:
    Table("t", [Column("a", "INT"), Column("A", "INT")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])


def test_schema_bad_type_and_row_length() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "NUMBER")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_schema_cell_type_checks() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BOOL")], [[1]])


def test_schema_float_widening_and_column_index() -> None:
    table = Table("t", [Column("a", "FLOAT")], [[3], [None]])
    assert table.rows[0][0] == 3.0 and type_of(table.rows[0][0]) == "FLOAT"
    assert table.column_index("a") == 0
    with pytest.raises(SchemaError):
        table.column_index("z")


# -------------------------------------------------------------------- lexer


def test_lexer_numbers() -> None:
    kinds = [(t.kind, t.value) for t in tokenize("1 1. .5 1e3 1.5E-2")][:-1]
    assert kinds == [("INT", 1), ("FLOAT", 1.0), ("FLOAT", 0.5), ("FLOAT", 1000.0),
                     ("FLOAT", 0.015)]


def test_lexer_strings_and_comments() -> None:
    tokens = tokenize("'it''s' -- comment\n'a\nb'")
    assert [t.value for t in tokens[:-1]] == ["it's", "a\nb"]


def test_lexer_keywords_are_case_insensitive() -> None:
    tokens = tokenize("SeLeCt order")
    assert tokens[0].kind == "KEYWORD" and tokens[1].value == "ORDER"


def test_lexer_error_offset() -> None:
    with pytest.raises(LexError) as info:
        tokenize("a ? b")
    assert info.value.offset == 2


# ------------------------------------------------------------------- parser


def test_parser_predicate_is_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("SELECT a FROM t WHERE 1 < 2 < 3")


def test_parser_not_binds_looser_than_comparison() -> None:
    query = parse("SELECT a FROM t WHERE NOT a = 1")
    assert type(query.where).__name__ == "Not"


def test_parser_rejects_nested_aggregates() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(a)) FROM t")


def test_parser_error_has_offset() -> None:
    with pytest.raises(ParseError) as info:
        parse("SELECT FROM t")
    assert info.value.offset == 7


def test_plan_is_a_named_sequence() -> None:
    steps = plan(parse("SELECT count(*) FROM t WHERE id > 1 GROUP BY name "
                       "HAVING count(*) > 0 ORDER BY name LIMIT 1"))
    assert [stage.name for stage in steps] == [
        "SCAN", "WHERE", "GROUP", "HAVING", "PROJECT", "ORDER", "SLICE"
    ]
    assert len(steps) == 7 and steps[0].name == "SCAN"


def test_execute_plan_matches_execute() -> None:
    tables = {"t": _people()}
    compiled = plan(parse("SELECT name FROM t WHERE age > 30"))
    assert execute_plan(compiled, tables).rows == [["Ada"], ["Cleo"]]


# ------------------------------------------------------------- expressions


def test_output_names() -> None:
    result = run("SELECT id, age + 1 FROM t")
    assert result.columns == ["id", "age + 1"]
    assert run("SELECT count(*) AS c, min(age) FROM t").columns == ["c", "min(age)"]


def test_bare_column_with_aggregate_needs_grouping() -> None:
    with pytest.raises(GroupingError):
        run("SELECT id, count(*) FROM t")


def test_output_name_collapses_whitespace() -> None:
    assert run("SELECT id\n   +\t1 FROM t").columns == ["id + 1"]


def test_scalar_functions() -> None:
    result = run("SELECT upper('ab'), lower('AB'), length('abc'), abs(-2) FROM t LIMIT 1")
    assert result.rows == [["AB", "ab", 3, 2]]


def test_concat_propagates_null_but_coalesce_does_not() -> None:
    result = run("SELECT concat('a', NULL), coalesce(NULL, NULL, 'z') FROM t LIMIT 1")
    assert result.rows == [[None, "z"]]


def test_function_errors() -> None:
    with pytest.raises(UnknownFunctionError):
        run("SELECT nope(1) FROM t")
    with pytest.raises(ArityError):
        run("SELECT concat('a') FROM t")
    with pytest.raises(TypeMismatchError):
        run("SELECT upper(1) FROM t")


def test_is_null_predicates() -> None:
    assert run("SELECT id FROM t WHERE age IS NULL").rows == [[4]]
    assert len(run("SELECT id FROM t WHERE age IS NOT NULL").rows) == 3


# ------------------------------------------------------------ where/having


def test_where_keeps_only_true_rows() -> None:
    assert run("SELECT id FROM t WHERE age = NULL").rows == []


def test_where_requires_a_boolean() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t WHERE 1")


def test_where_rejects_aggregates() -> None:
    with pytest.raises(AggregateError):
        run("SELECT id FROM t WHERE count(id) > 1")


def test_where_cannot_see_aliases() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT age AS years FROM t WHERE years > 30")


def test_order_by_can_see_aliases_and_alias_wins() -> None:
    result = run("SELECT id AS age FROM t ORDER BY age DESC")
    assert result.rows == [[4], [3], [2], [1]]


def test_having_filters_groups() -> None:
    result = run("SELECT age, count(*) AS c FROM t GROUP BY age HAVING count(*) > 0")
    assert len(result.rows) == 4


# ------------------------------------------------------------- aggregation


def test_count_star_over_empty_table_yields_one_row() -> None:
    assert run("SELECT count(*) FROM e", {"e": _empty()}).rows == [[0]]


def test_sum_of_empty_group_is_null() -> None:
    assert run("SELECT sum(a) FROM e", {"e": _empty()}).rows == [[None]]
    assert run("SELECT avg(a), min(a), max(a) FROM e", {"e": _empty()}).rows == [
        [None, None, None]
    ]


def test_count_expr_ignores_nulls() -> None:
    result = run("SELECT count(*), count(age) FROM t")
    assert result.rows == [[4, 3]]


def test_sum_and_avg_types() -> None:
    table = Table("t", [Column("a", "INT"), Column("b", "FLOAT")], [[1, 1.5], [3, None]])
    result = execute("SELECT sum(a), avg(a), sum(b) FROM t", {"t": table})
    assert result.rows == [[4, 2.0, 1.5]]
    assert type_of(result.rows[0][0]) == "INT" and type_of(result.rows[0][1]) == "FLOAT"


def test_min_max_preserve_type() -> None:
    result = run("SELECT min(name), max(age) FROM t")
    assert result.rows == [["Ada", 41]]


def test_aggregate_type_errors() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT sum(name) FROM t")


def test_min_rejects_mixed_types() -> None:
    table = Table("m", [Column("a", "INT"), Column("b", "TEXT")],
                  [[1, None], [None, "y"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT min(coalesce(a, b)) FROM m", {"m": table})


def test_grouping_rejects_non_grouped_columns() -> None:
    with pytest.raises(GroupingError):
        run("SELECT name, count(*) FROM t GROUP BY age")


def test_group_by_expression() -> None:
    result = run("SELECT length(name) AS n, count(*) AS c FROM t GROUP BY length(name)")
    assert result.rows == [[3, 3], [4, 1]]


def test_nulls_group_together_and_keep_first_seen_order() -> None:
    result = run("SELECT a, count(*) AS c FROM t GROUP BY a", {"t": _nulls()})
    assert result.rows == [[1, 2], [None, 1], [2, 1]]


# ---------------------------------------------------------------- ordering


def test_nulls_sort_last_in_both_directions() -> None:
    assert run("SELECT a FROM t ORDER BY a", {"t": _nulls()}).rows == [
        [1], [1], [2], [None]
    ]
    assert run("SELECT a FROM t ORDER BY a DESC", {"t": _nulls()}).rows == [
        [2], [1], [1], [None]
    ]


def test_sort_is_stable() -> None:
    table = Table("t", [Column("k", "INT"), Column("v", "TEXT")],
                  [[1, "a"], [1, "b"], [0, "c"], [1, "d"]])
    assert execute("SELECT v FROM t ORDER BY k", {"t": table}).rows == [
        ["c"], ["a"], ["b"], ["d"]
    ]


def test_multiple_sort_keys() -> None:
    result = run("SELECT name FROM t ORDER BY age IS NULL, name DESC")
    assert result.rows[-1] == ["Dan"]


def test_sort_type_mismatch() -> None:
    table = Table("t", [Column("a", "INT"), Column("b", "TEXT")],
                  [[1, None], [None, "y"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT coalesce(a, b) AS c FROM t ORDER BY c", {"t": table})


def test_distinct_then_order_then_slice() -> None:
    result = run("SELECT DISTINCT a FROM t ORDER BY a LIMIT 2 OFFSET 1", {"t": _nulls()})
    assert result.rows == [[2], [None]]


def test_distinct_hides_input_columns_from_order_by() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT a FROM t ORDER BY b", {"t": _nulls()})


def test_offset_applied_before_limit() -> None:
    assert run("SELECT id FROM t ORDER BY id LIMIT 2 OFFSET 2").rows == [[3], [4]]


def test_order_by_aggregate_not_in_select() -> None:
    table = Table("t", [Column("g", "TEXT")], [["a"], ["b"], ["b"]])
    result = execute("SELECT g FROM t GROUP BY g ORDER BY count(*) DESC", {"t": table})
    assert result.rows == [["b"], ["a"]]


def test_distinct_treats_nulls_as_equal() -> None:
    table = Table("t", [Column("a", "INT")], [[None], [None], [1]])
    assert execute("SELECT DISTINCT a FROM t", {"t": table}).rows == [[None], [1]]


# ------------------------------------------------------------------- joins


def _join_tables() -> dict[str, Table]:
    left = Table("l", [Column("id", "INT"), Column("n", "TEXT")],
                 [[1, "a"], [2, "b"], [3, "c"]])
    right = Table("r", [Column("id", "INT"), Column("v", "INT")],
                  [[1, 10], [1, 20], [2, 30]])
    return {"l": left, "r": right}


def test_inner_join_order_is_left_major() -> None:
    result = execute("SELECT * FROM l INNER JOIN r ON l.id = r.id", _join_tables())
    assert result.rows == [[1, "a", 1, 10], [1, "a", 1, 20], [2, "b", 2, 30]]


def test_left_join_fills_nulls() -> None:
    result = execute("SELECT l.n, r.v FROM l LEFT JOIN r ON l.id = r.id", _join_tables())
    assert result.rows[-1] == ["c", None]


def test_join_ambiguous_and_unknown_names() -> None:
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM l JOIN r ON l.id = r.id", _join_tables())
    with pytest.raises(UnknownTableError):
        execute("SELECT x.id FROM l JOIN r ON l.id = r.id", _join_tables())


def test_qualified_star() -> None:
    result = execute("SELECT l.* FROM l LEFT JOIN r ON l.id = r.id", _join_tables())
    assert result.columns == ["id", "n"] and len(result.rows) == 4


def test_unknown_table_and_column() -> None:
    with pytest.raises(UnknownTableError):
        run("SELECT id FROM nope")
    with pytest.raises(UnknownColumnError):
        run("SELECT nope FROM t")


# --------------------------------------------------------------------- CLI


def test_cli_success(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--table", f"t={ROOT / 'people.csv'}",
                 "SELECT count(*) FROM t WHERE age > 30"])
    assert code == 0
    assert capsys.readouterr().out.replace("\r\n", "\n") == "count(*)\n2\n"


def test_cli_subprocess_prints_two() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", "t=people.csv",
         "SELECT count(*) FROM t WHERE age > 30"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0 and proc.stdout.strip().splitlines()[-1] == "2"


def test_cli_usage_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["SELECT 1 FROM t"]) == 2
    assert main(["--table", "t=missing_file.csv", "SELECT count(*) FROM t"]) == 2
    assert main(["--table", f"t={ROOT / 'people.csv'}"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_query_error_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--table", f"t={ROOT / 'people.csv'}", "SELECT nope FROM t"])
    captured = capsys.readouterr()
    assert code == 3 and captured.out == "" and "nope" in captured.err


def test_cli_null_and_bool_rendering() -> None:
    assert render_value(None) == "" and render_value(True) == "true"
    assert render_value(False) == "false" and render_value(1.5) == "1.5"


def test_cli_quoting_rule() -> None:
    assert quote_field("") == ""
    assert quote_field("a,b") == '"a,b"'
    assert quote_field('a"b') == '"a""b"'
    assert quote_field("plain") == "plain"


def test_cli_csv_empty_field_is_null(tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text('a:TEXT,b:INT\n"",1\n,2\n', encoding="utf-8")
    code = main(["--table", f"d={path}", "SELECT a FROM d WHERE a IS NULL"])
    assert code == 0


def test_split_csv_tracks_quoting() -> None:
    rows = split_csv('a,"",\n')
    assert rows == [[("a", False), ("", True), ("", False)]]


def test_public_surface() -> None:
    assert len(microdb.__all__) >= 30
    for name in microdb.__all__:
        assert hasattr(microdb, name)

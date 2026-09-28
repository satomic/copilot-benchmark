import io
from pathlib import Path

import pytest

from microdb import (
    AmbiguousColumnError, ArityError, Column, GroupingError, LexError,
    ParseError, SchemaError, Table, TypeMismatchError, UnknownColumnError,
    UnknownFunctionError, UnknownTableError, and_, arith, compare_eq, compare_lt,
    execute, is_numeric, negate, not_, or_, parse, plan, tokenize, type_of,
)


def table(name="t", columns=None, rows=None):
    return Table(name, columns or [Column("x", "INT")], rows or [])


def test_type_of_values():
    assert [type_of(v) for v in (1, 1.5, "a", True, None)] == [
        "INT", "FLOAT", "TEXT", "BOOL", "NULL"
    ]


def test_bool_is_not_numeric():
    assert not is_numeric(True)


def test_int_is_numeric():
    assert is_numeric(1)


def test_float_is_numeric():
    assert is_numeric(1.0)


def test_null_is_not_numeric():
    assert not is_numeric(None)


def test_and_false_unknown():
    assert and_(False, None) is False


def test_and_true_unknown():
    assert and_(True, None) is None


def test_and_unknown_unknown():
    assert and_(None, None) is None


def test_or_true_unknown():
    assert or_(True, None) is True


def test_or_false_unknown():
    assert or_(False, None) is None


def test_or_unknown_unknown():
    assert or_(None, None) is None


def test_not_unknown():
    assert not_(None) is None


def test_null_equals_null_is_unknown():
    assert compare_eq(None, None) is None


def test_int_float_compare_numerically():
    assert compare_eq(1, 1.0) is True


def test_text_number_comparison_fails():
    with pytest.raises(TypeMismatchError):
        compare_lt("1", 1)


def test_bool_number_comparison_fails():
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)


def test_divide_by_zero_returns_null():
    assert arith("/", 3, 0) is None


def test_modulo_by_zero_returns_null():
    assert arith("%", 3, 0) is None


def test_division_always_float():
    assert arith("/", 7, 2) == 3.5


def test_modulo_uses_python_sign_rule():
    assert arith("%", -7, 3) == 2


def test_boolean_arithmetic_fails():
    with pytest.raises(TypeMismatchError):
        arith("+", True, 2)


def test_negate_null():
    assert negate(None) is None


def test_empty_schema_fails():
    with pytest.raises(SchemaError):
        Table("t", [], [])


def test_duplicate_schema_names_fail():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])


def test_int_column_rejects_boolean():
    with pytest.raises(SchemaError):
        Table("t", [Column("n", "INT")], [[True]])


def test_float_column_widens_integer():
    result = Table("t", [Column("n", "FLOAT")], [[2]])
    assert result.rows == [[2.0]]


def test_table_returns_copies():
    source = Table("t", [Column("n", "INT")], [[2]])
    source.rows[0][0] = 9
    assert source.rows == [[2]]


def test_lexer_skips_comments():
    assert [token.kind for token in tokenize("SELECT -- comment\n 1")] == [
        "SELECT", "INT", "EOF"
    ]


def test_lexer_decodes_escaped_quote():
    assert tokenize("'it''s'")[0].value == "it's"


def test_lexer_reports_bad_character_offset():
    with pytest.raises(LexError) as error:
        tokenize("SELECT @")
    assert error.value.offset == 7


def test_parser_arithmetic_precedence():
    query = parse("SELECT 1 + 2 * 3 FROM t")
    assert query.items[0].expr.children[1].value == "*"


def test_parser_rejects_chained_comparisons():
    with pytest.raises(ParseError):
        parse("SELECT 1 < 2 < 3 FROM t")


def test_parser_recognizes_distinct_and_limit():
    query = parse("SELECT DISTINCT x FROM t LIMIT 2 OFFSET 1")
    assert query.distinct and query.limit == 2 and query.offset == 1


def test_concat_and_case_functions():
    result = execute("SELECT concat(upper('a'), lower('B')) FROM t", {"t": table(rows=[[0]])})
    assert result.rows == [["Ab"]]


def test_scalar_null_propagation():
    result = execute("SELECT upper(NULL), length(NULL), abs(NULL) FROM t", {"t": table(rows=[[0]])})
    assert result.rows == [[None, None, None]]


def test_coalesce_returns_first_present():
    result = execute("SELECT coalesce(NULL, 4, 5) FROM t", {"t": table(rows=[[0]])})
    assert result.rows == [[4]]


def test_concat_null_propagates():
    result = execute("SELECT concat('a', NULL) FROM t", {"t": table(rows=[[0]])})
    assert result.rows == [[None]]


def test_scalar_arity_error():
    with pytest.raises(ArityError):
        execute("SELECT upper('a', 'b') FROM t", {"t": table()})


def test_unknown_function_error():
    with pytest.raises(UnknownFunctionError):
        execute("SELECT mystery(1) FROM t", {"t": table()})


def test_sum_of_empty_input_is_null():
    result = execute("SELECT sum(x) FROM t", {"t": table()})
    assert result.rows == [[None]]


def test_count_star_empty_input_is_one_row_zero():
    result = execute("SELECT count(*) FROM t", {"t": table()})
    assert result.rows == [[0]]


def test_count_star_counts_all_null_rows():
    source = table(columns=[Column("x", "INT")], rows=[[None], [None]])
    assert execute("SELECT count(*) FROM t", {"t": source}).rows == [[2]]


def test_sum_preserves_integer_type():
    source = table(rows=[[2], [3]])
    result = execute("SELECT sum(x) FROM t", {"t": source})
    assert result.rows == [[5]] and isinstance(result.rows[0][0], int)


def test_avg_returns_float():
    source = table(rows=[[2], [3]])
    result = execute("SELECT avg(x) FROM t", {"t": source})
    assert result.rows == [[2.5]] and isinstance(result.rows[0][0], float)


def test_sum_text_fails():
    source = table(columns=[Column("x", "TEXT")], rows=[["a"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT sum(x) FROM t", {"t": source})


def test_null_group_keys_form_one_group():
    source = table(rows=[[None], [None], [2]])
    result = execute("SELECT x, count(*) FROM t GROUP BY x", {"t": source})
    assert result.rows == [[None, 2], [2, 1]]


def test_groups_keep_first_appearance_order():
    source = table(rows=[[2], [1], [2], [1]])
    result = execute("SELECT x, count(*) FROM t GROUP BY x", {"t": source})
    assert result.rows == [[2, 2], [1, 2]]


def test_null_sorts_last_in_descending_order():
    source = table(rows=[[None], [1], [3]])
    result = execute("SELECT x FROM t ORDER BY x DESC", {"t": source})
    assert result.rows == [[3], [1], [None]]


def test_sort_is_stable_for_equal_keys():
    source = Table("t", [Column("k", "INT"), Column("v", "TEXT")],
                   [[1, "a"], [1, "b"], [0, "c"]])
    result = execute("SELECT v FROM t ORDER BY k", {"t": source})
    assert result.rows == [["c"], ["a"], ["b"]]


def test_left_join_fills_right_columns_with_null():
    left = Table("a", [Column("id", "INT")], [[1], [2]])
    right = Table("b", [Column("id", "INT"), Column("v", "TEXT")], [[1, "one"]])
    result = execute("SELECT a.id, b.v FROM a LEFT JOIN b ON a.id = b.id",
                     {"a": left, "b": right})
    assert result.rows == [[1, "one"], [2, None]]


def test_unqualified_join_column_is_ambiguous():
    left = Table("a", [Column("id", "INT")], [[1]])
    right = Table("b", [Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM a JOIN b ON a.id = b.id", {"a": left, "b": right})


def test_alias_is_visible_in_order_by():
    source = Table("t", [Column("x", "INT"), Column("y", "INT")], [[1, 8], [2, 3]])
    result = execute("SELECT y AS x FROM t ORDER BY x", {"t": source})
    assert result.rows == [[3], [8]]


def test_alias_wins_inside_order_by_expression():
    source = Table("t", [Column("x", "INT"), Column("y", "INT")], [[1, 8], [2, 3]])
    result = execute("SELECT y AS x FROM t ORDER BY x + 0", {"t": source})
    assert result.rows == [[3], [8]]


def test_alias_is_not_visible_in_where():
    with pytest.raises(UnknownColumnError):
        execute("SELECT x AS y FROM t WHERE y > 1", {"t": table(rows=[[2]])})


def test_non_boolean_where_is_type_error():
    with pytest.raises(TypeMismatchError):
        execute("SELECT x FROM t WHERE 1", {"t": table(rows=[[1]])})


def test_where_null_comparison_drops_rows():
    source = table(rows=[[None], [1]])
    assert execute("SELECT x FROM t WHERE x = NULL", {"t": source}).rows == []


def test_aggregate_in_where_is_rejected():
    with pytest.raises(Exception) as error:
        execute("SELECT x FROM t WHERE count(*) > 0", {"t": table(rows=[[1]])})
    assert error.type.__name__ == "AggregateError"


def test_nested_aggregate_is_parse_error():
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")


def test_non_grouped_select_expression_fails():
    source = table(rows=[[1]])
    with pytest.raises(GroupingError):
        execute("SELECT x + 1 FROM t GROUP BY x", {"t": source})


def test_aggregate_expression_cannot_read_ungrouped_column():
    source = Table("t", [Column("x", "INT"), Column("y", "INT")], [[1, 2]])
    with pytest.raises(GroupingError):
        execute("SELECT sum(y) + x FROM t GROUP BY y", {"t": source})


def test_distinct_order_requires_output_column():
    source = Table("t", [Column("x", "INT"), Column("y", "INT")], [[1, 2]])
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT x FROM t ORDER BY y", {"t": source})


def test_offset_precedes_limit():
    source = table(rows=[[1], [2], [3], [4]])
    result = execute("SELECT x FROM t ORDER BY x LIMIT 2 OFFSET 1", {"t": source})
    assert result.rows == [[2], [3]]


def test_unknown_table_fails():
    with pytest.raises(UnknownTableError):
        execute("SELECT x FROM missing", {})


def test_planner_exposes_named_pipeline_stages():
    stages = plan(parse("SELECT x FROM t"))
    assert [stage.name for stage in stages][:3] == ["FROM/JOIN", "WHERE", "GROUP BY"]


def test_cli_success_outputs_csv(monkeypatch, capsys):
    import microdb.__main__ as cli
    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: io.StringIO("age:INT\n31\n20\n"))
    code = cli.main(["--table", "t=people.csv", "SELECT count(*) FROM t WHERE age > 30"])
    captured = capsys.readouterr()
    assert code == 0 and captured.out == "count(*)\n1\n" and captured.err == ""


def test_cli_usage_error_has_code_two_and_empty_stdout(capsys):
    import microdb.__main__ as cli
    code = cli.main(["SELECT 1 FROM t"])
    captured = capsys.readouterr()
    assert code == 2 and captured.out == "" and captured.err


def test_cli_query_error_has_code_three_and_empty_stdout(monkeypatch, capsys):
    import microdb.__main__ as cli
    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: io.StringIO("x:INT\n1\n"))
    code = cli.main(["--table", "t=data.csv", "SELECT absent FROM t"])
    captured = capsys.readouterr()
    assert code == 3 and captured.out == "" and captured.err


def test_cli_malformed_header_has_usage_code(monkeypatch, capsys):
    import microdb.__main__ as cli
    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: io.StringIO("bad-header\n"))
    code = cli.main(["--table", "t=data.csv", "SELECT 1 FROM t"])
    captured = capsys.readouterr()
    assert code == 2 and captured.out == ""


def test_cli_quotes_only_fields_requiring_csv_quotes(capsys):
    import microdb.__main__ as cli
    cli._write_result(["plain", "comma", "empty"], [["", "a,b", "x\"y"]])
    assert capsys.readouterr().out == 'plain,comma,empty\n,"a,b","x""y"\n'

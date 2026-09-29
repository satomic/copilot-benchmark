from pathlib import Path

import pytest

import microdb
from microdb.__main__ import main
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
)
from microdb.expr import evaluate
from microdb.parser import parse


def table() -> microdb.Table:
    return microdb.Table(
        "t",
        [
            microdb.Column("id", "INT"),
            microdb.Column("name", "TEXT"),
            microdb.Column("score", "FLOAT"),
            microdb.Column("ok", "BOOL"),
        ],
        [
            [1, "Ada", 3.0, True],
            [2, "Bob", None, False],
            [3, "Ada", 2, True],
            [4, None, 2.0, None],
        ],
    )


def run(query: str) -> microdb.Result:
    return microdb.execute(query, {"t": table()})


def test_public_surface() -> None:
    assert len(microdb.__all__) > 20


def test_type_of_bool_is_distinct() -> None:
    assert microdb.type_of(True) == "BOOL"
    assert not microdb.is_numeric(True)


def test_type_of_numbers() -> None:
    assert microdb.type_of(1) == "INT"
    assert microdb.type_of(1.0) == "FLOAT"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (True, True, True),
        (True, False, False),
        (True, None, None),
        (False, True, False),
        (False, False, False),
        (False, None, False),
        (None, True, None),
        (None, False, False),
        (None, None, None),
    ],
)
def test_and_truth_table(a: bool | None, b: bool | None, expected: bool | None) -> None:
    assert microdb.and_(a, b) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (True, True, True),
        (True, False, True),
        (True, None, True),
        (False, True, True),
        (False, False, False),
        (False, None, None),
        (None, True, True),
        (None, False, None),
        (None, None, None),
    ],
)
def test_or_truth_table(a: bool | None, b: bool | None, expected: bool | None) -> None:
    assert microdb.or_(a, b) is expected


def test_not_truth_table() -> None:
    assert [microdb.not_(x) for x in (True, False, None)] == [False, True, None]


def test_null_equality_unknown() -> None:
    assert microdb.compare_eq(None, None) is None


def test_numeric_cross_type_comparison() -> None:
    assert microdb.compare_eq(2, 2.0) is True


def test_bool_number_comparison_rejected() -> None:
    with pytest.raises(TypeMismatchError):
        microdb.compare_eq(True, 1)


def test_text_ordering() -> None:
    assert microdb.compare_lt("A", "B") is True


def test_division_is_float() -> None:
    assert microdb.arith("/", 7, 2) == 3.5


def test_division_by_zero_is_null() -> None:
    assert microdb.arith("/", 7, 0) is None


def test_modulo_by_zero_is_null() -> None:
    assert microdb.arith("%", 7, 0) is None


def test_modulo_requires_int() -> None:
    with pytest.raises(TypeMismatchError):
        microdb.arith("%", 7.0, 2)


def test_negate_preserves_type() -> None:
    assert microdb.negate(2) == -2
    assert isinstance(microdb.negate(2.0), float)


def test_schema_requires_columns() -> None:
    with pytest.raises(SchemaError):
        microdb.Table("x", [], [])


def test_schema_rejects_duplicate_columns() -> None:
    with pytest.raises(SchemaError):
        microdb.Table("x", [microdb.Column("a", "INT")] * 2, [])


def test_schema_column_names_case_sensitive() -> None:
    value = microdb.Table(
        "x", [microdb.Column("a", "INT"), microdb.Column("A", "INT")], []
    )
    assert value.column_index("A") == 1


def test_schema_float_widens_int() -> None:
    value = microdb.Table("x", [microdb.Column("a", "FLOAT")], [[2]])
    assert value.rows == [[2.0]]


def test_schema_int_rejects_bool() -> None:
    with pytest.raises(SchemaError):
        microdb.Table("x", [microdb.Column("a", "INT")], [[True]])


def test_lexer_comments_and_exponent() -> None:
    tokens = microdb.tokenize("1e3 -- hello\n .5")
    assert [token.value for token in tokens[:-1]] == [1000.0, 0.5]


def test_lexer_escaped_quote() -> None:
    assert microdb.tokenize("'it''s'")[0].value == "it's"


def test_lexer_error_has_offset() -> None:
    with pytest.raises(LexError) as caught:
        microdb.tokenize("@")
    assert caught.value.offset == 0


def test_predicate_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("SELECT 1 < 2 < 3 FROM t")


def test_not_binds_outside_comparison() -> None:
    assert run("SELECT NOT id = 1 FROM t LIMIT 1").rows == [[False]]


def test_nested_aggregate_rejected() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(id)) FROM t")


def test_scalar_functions() -> None:
    result = run("SELECT upper(name), lower(name), length(name) FROM t LIMIT 1")
    assert result.rows == [["ADA", "ada", 3]]


def test_concat_null_propagates() -> None:
    assert run("SELECT concat(name, NULL) FROM t LIMIT 1").rows == [[None]]


def test_coalesce_does_not_propagate_null() -> None:
    assert run("SELECT coalesce(NULL, name) FROM t LIMIT 1").rows == [["Ada"]]


def test_function_arity() -> None:
    with pytest.raises(ArityError):
        run("SELECT upper(name, name) FROM t")


def test_unknown_function() -> None:
    with pytest.raises(UnknownFunctionError):
        run("SELECT mystery(name) FROM t")


def test_where_unknown_drops_row() -> None:
    assert run("SELECT id FROM t WHERE name = NULL").rows == []


def test_where_non_bool_rejected() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT id FROM t WHERE 1")


def test_where_aggregate_rejected() -> None:
    with pytest.raises(AggregateError):
        run("SELECT id FROM t WHERE count(*) > 0")


def test_count_empty_table() -> None:
    empty = microdb.Table("e", [microdb.Column("x", "INT")], [])
    assert microdb.execute("SELECT count(*) FROM e", {"e": empty}).rows == [[0]]


def test_sum_empty_group_is_null() -> None:
    empty = microdb.Table("e", [microdb.Column("x", "INT")], [])
    assert microdb.execute("SELECT sum(x) FROM e", {"e": empty}).rows == [[None]]


def test_count_ignores_null_expression() -> None:
    assert run("SELECT count(score), count(*) FROM t").rows == [[3, 4]]


def test_avg_always_float() -> None:
    result = run("SELECT avg(id) FROM t")
    assert result.rows == [[2.5]]
    assert isinstance(result.rows[0][0], float)


def test_group_nulls_together() -> None:
    result = run("SELECT score, count(*) FROM t GROUP BY score ORDER BY score")
    assert result.rows[-1] == [None, 1]


def test_group_order_is_first_seen() -> None:
    assert run("SELECT name, count(*) FROM t GROUP BY name").rows == [
        ["Ada", 2], ["Bob", 1], [None, 1]
    ]


def test_grouping_error() -> None:
    with pytest.raises(GroupingError):
        run("SELECT id, count(*) FROM t GROUP BY name")


def test_having_aggregate() -> None:
    assert run(
        "SELECT name, count(*) AS n FROM t GROUP BY name HAVING count(*) > 1"
    ).rows == [["Ada", 2]]


def test_distinct_nulls_equal() -> None:
    assert run("SELECT DISTINCT ok FROM t ORDER BY ok").rows == [
        [False], [True], [None]
    ]


def test_nulls_last_descending() -> None:
    assert run("SELECT score FROM t ORDER BY score DESC").rows == [
        [3.0], [2.0], [2.0], [None]
    ]


def test_sort_is_stable() -> None:
    assert run("SELECT id, score FROM t ORDER BY score").rows[:2] == [[3, 2.0], [4, 2.0]]


def test_order_alias_visible_and_wins() -> None:
    assert run("SELECT -id AS id FROM t ORDER BY id").rows == [[-4], [-3], [-2], [-1]]


def test_where_alias_not_visible() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT id AS z FROM t WHERE z = 1")


def test_distinct_order_requires_output() -> None:
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT name FROM t ORDER BY id")


def test_limit_after_offset() -> None:
    assert run("SELECT id FROM t ORDER BY id LIMIT 2 OFFSET 1").rows == [[2], [3]]


def test_inner_join() -> None:
    other = microdb.Table("u", [microdb.Column("id", "INT")], [[2], [4]])
    result = microdb.execute(
        "SELECT t.id FROM t JOIN u ON t.id = u.id", {"t": table(), "u": other}
    )
    assert result.rows == [[2], [4]]


def test_left_join_null_fill() -> None:
    other = microdb.Table(
        "u", [microdb.Column("id", "INT"), microdb.Column("v", "TEXT")], [[2, "x"]]
    )
    result = microdb.execute(
        "SELECT t.id, u.v FROM t LEFT JOIN u ON t.id = u.id",
        {"t": table(), "u": other},
    )
    assert result.rows == [[1, None], [2, "x"], [3, None], [4, None]]


def test_ambiguous_join_column() -> None:
    other = microdb.Table("u", [microdb.Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        microdb.execute(
            "SELECT id FROM t JOIN u ON t.id = u.id", {"t": table(), "u": other}
        )


def test_star_projection() -> None:
    assert run("SELECT t.* FROM t LIMIT 1").rows == [[1, "Ada", 3.0, True]]


def test_output_names() -> None:
    assert run("SELECT id, count(*) AS n FROM t GROUP BY id LIMIT 1").columns == [
        "id", "n"
    ]


def test_plan_is_sequence() -> None:
    query_plan = microdb.plan(parse("SELECT id FROM t WHERE id > 1"))
    assert len(query_plan) >= 3
    assert query_plan[0].name == "FROM"


def test_cli_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id:INT,name:TEXT\n1,Ada\n2,\n", encoding="utf-8")
    assert main(["--table", f"t={path}", "SELECT name FROM t ORDER BY id"]) == 0
    assert capsys.readouterr().out == "name\nAda\n\n"


def test_cli_bool_and_empty_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "data.csv"
    path.write_text("ok:BOOL,s:TEXT\nTRUE,''\n", encoding="utf-8")
    assert main(["--table", f"t={path}", "SELECT * FROM t"]) == 0
    assert capsys.readouterr().out == "ok,s\ntrue,\n"


def test_cli_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def test_cli_query_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "data.csv"
    path.write_text("id:INT\n1\n", encoding="utf-8")
    assert main(["--table", f"t={path}", "SELECT missing FROM t"]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "unknown column" in output.err


def test_cli_csv_quoting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "data.csv"
    path.write_text('s:TEXT\n"a,b"\n', encoding="utf-8")
    assert main(["--table", f"t={path}", "SELECT s FROM t"]) == 0
    assert capsys.readouterr().out == 's\n"a,b"\n'

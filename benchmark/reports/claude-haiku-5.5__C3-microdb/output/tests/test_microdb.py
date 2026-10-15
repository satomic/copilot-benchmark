"""Tests for microdb. Run with: python -m pytest -q"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from microdb import (
    AggregateError,
    MicroDBError,
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
    plan,
    tokenize,
    type_of,
)
from microdb.__main__ import main
from microdb.parser import parse

T, F, U = True, False, None
TRUTH = [
    (T, T, T, T), (T, F, F, T), (T, U, U, T),
    (F, T, F, T), (F, F, F, F), (F, U, F, U),
    (U, T, U, T), (U, F, F, U), (U, U, U, U),
]

ROOT = Path(__file__).resolve().parent.parent


def people() -> Table:
    cols = [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT")]
    rows = [
        [1, "ann", 31],
        [2, "bob", 25],
        [3, "cy", None],
        [4, None, 40],
    ]
    return Table("people", cols, rows)


def tables() -> dict[str, Table]:
    return {"people": people()}


def run(q: str) -> list[list[object]]:
    return execute(q, tables()).rows


@pytest.mark.parametrize("a,b,conj,disj", TRUTH)
def test_truth_tables(a, b, conj, disj):
    assert and_(a, b) == conj
    assert or_(a, b) == disj


def test_not_truth_table():
    assert not_(T) is False
    assert not_(F) is True
    assert not_(U) is None


def test_null_equals_null_is_unknown():
    assert compare_eq(None, None) is None
    assert compare_eq(None, 1) is None


def test_int_float_compare_numerically():
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True


def test_bool_not_int():
    assert type_of(True) == "BOOL"
    assert is_numeric(True) is False
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)


def test_text_vs_number_raises():
    with pytest.raises(TypeMismatchError):
        compare_lt("a", 1)


def test_false_less_than_true():
    assert compare_lt(False, True) is True


def test_type_of_all_kinds():
    assert [type_of(v) for v in (1, 1.0, "x", True, None)] == [
        "INT", "FLOAT", "TEXT", "BOOL", "NULL",
    ]


def test_division_is_float():
    assert arith("/", 7, 2) == 3.5
    assert type(arith("/", 4, 2)) is float


def test_division_by_zero_is_null():
    assert arith("/", 1, 0) is None
    assert arith("/", 1.0, 0.0) is None
    assert arith("%", 5, 0) is None


def test_modulo_sign_rule():
    assert arith("%", -7, 3) == 2


def test_arith_null_propagates():
    assert arith("+", None, 1) is None


def test_arith_rejects_bool_and_text():
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        arith("+", "a", 1)


def test_int_plus_float_is_float():
    assert type(arith("+", 1, 2.0)) is float
    assert type(arith("+", 1, 2)) is int


def test_negate_preserves_type_and_null():
    assert negate(3) == -3
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        negate("x")


def test_float_column_accepts_int_and_widens():
    t = Table("t", [Column("x", "FLOAT")], [[1]])
    assert t.rows[0][0] == 1.0
    assert type(t.rows[0][0]) is float


def test_int_column_rejects_float():
    with pytest.raises(SchemaError):
        Table("t", [Column("x", "INT")], [[3.0]])


def test_int_column_rejects_bool():
    with pytest.raises(SchemaError):
        Table("t", [Column("x", "INT")], [[True]])


def test_schema_rejects_empty_and_bad_type():
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("x", "DATE")], [])


def test_schema_duplicate_names_case_sensitive():
    t = Table("t", [Column("a", "INT"), Column("A", "INT")], [[1, 2]])
    assert t.column_index("A") == 1
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])


def test_schema_row_length_mismatch():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_column_index_unknown_raises():
    with pytest.raises(SchemaError):
        people().column_index("nope")


def test_lexer_float_forms():
    kinds = [t.kind for t in tokenize("1. .5 1e3 1.5E-2")]
    assert kinds[:-1] == ["FLOAT"] * 4


def test_lexer_text_with_escaped_quote_and_comment():
    toks = tokenize("'it''s' -- ignored\n")
    assert toks[0].value == "it's"


def test_lexer_bad_character_offset():
    with pytest.raises(LexError) as info:
        tokenize("SELECT #")
    assert info.value.offset == 7


def test_keyword_cannot_be_identifier():
    with pytest.raises(ParseError):
        parse("SELECT order FROM people")


def test_chained_comparison_is_parse_error():
    with pytest.raises(ParseError):
        parse("SELECT 1 < 2 < 3 FROM people")


def test_nested_aggregate_is_parse_error():
    with pytest.raises(ParseError):
        parse("SELECT sum(count(id)) FROM people")


def test_not_binds_looser_than_comparison():
    q = parse("SELECT id FROM people WHERE NOT age = 31")
    assert q.where is not None


def test_count_star_empty_table_one_row():
    empty = Table("e", [Column("a", "INT")], [])
    res = execute("SELECT count(*) FROM e", {"e": empty})
    assert res.rows == [[0]]


def test_sum_of_empty_group_is_null():
    res = execute("SELECT sum(age) FROM people WHERE id > 100", tables())
    assert res.rows == [[None]]


def test_avg_min_max_empty_are_null():
    res = execute("SELECT avg(age), min(age), max(age) FROM people WHERE id > 100", tables())
    assert res.rows == [[None, None, None]]


def test_count_expr_skips_nulls():
    assert run("SELECT count(age) FROM people") == [[3]]


def test_count_star_counts_null_rows():
    assert run("SELECT count(*) FROM people") == [[4]]


def test_sum_int_and_avg_float():
    res = execute("SELECT sum(age), avg(age) FROM people", tables())
    assert res.rows == [[96, 32.0]]
    assert type(res.rows[0][0]) is int
    assert type(res.rows[0][1]) is float


def test_sum_text_raises():
    with pytest.raises(TypeMismatchError):
        execute("SELECT sum(name) FROM people", tables())


def test_min_max_text_uses_code_point_order():
    t = Table("m", [Column("v", "TEXT")], [["b"], ["B"], [None], ["a"]])
    res = execute("SELECT min(v), max(v) FROM m", {"m": t})
    assert res.rows == [["B", "b"]]


def test_min_text_and_number_mix_via_expression_raises():
    with pytest.raises(TypeMismatchError):
        execute("SELECT id FROM people WHERE id < 'x'", tables())


def test_where_drops_unknown():
    assert run("SELECT id FROM people WHERE age = NULL") == []


def test_where_non_bool_raises():
    with pytest.raises(TypeMismatchError):
        execute("SELECT id FROM people WHERE 1", tables())


def test_where_cannot_contain_aggregate():
    with pytest.raises(AggregateError):
        execute("SELECT id FROM people WHERE count(*) > 1", tables())


def test_where_cannot_see_alias():
    with pytest.raises(UnknownColumnError):
        execute("SELECT age AS a2 FROM people WHERE a2 > 1", tables())


def test_order_by_can_see_alias():
    res = run("SELECT id, age * 2 AS age FROM people ORDER BY age")
    assert [r[0] for r in res] == [2, 1, 4, 3]


def test_alias_wins_over_input_column():
    res = run("SELECT id AS age FROM people ORDER BY age")
    assert [r[0] for r in res] == [1, 2, 3, 4]


def test_nulls_sort_last_in_desc():
    res = run("SELECT age FROM people ORDER BY age DESC")
    assert [r[0] for r in res] == [40, 31, 25, None]


def test_nulls_sort_last_in_asc():
    res = run("SELECT age FROM people ORDER BY age ASC")
    assert [r[0] for r in res] == [25, 31, 40, None]


def test_sort_is_stable():
    t = Table("s", [Column("k", "INT"), Column("v", "INT")],
              [[1, 10], [0, 20], [1, 30], [0, 40]])
    res = execute("SELECT k, v FROM s ORDER BY k", {"s": t})
    assert res.rows == [[0, 20], [0, 40], [1, 10], [1, 30]]


def test_offset_before_limit():
    assert run("SELECT id FROM people ORDER BY id LIMIT 2 OFFSET 1") == [[2], [3]]


def test_distinct_removes_duplicates():
    t = Table("d", [Column("v", "INT")], [[1], [1], [2]])
    assert execute("SELECT DISTINCT v FROM d", {"d": t}).rows == [[1], [2]]


def test_distinct_order_by_input_column_rejected():
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT name FROM people ORDER BY age", tables())


def test_group_nulls_group_together():
    t = Table("g", [Column("k", "TEXT"), Column("v", "INT")],
              [[None, 1], [None, 2], ["a", 3]])
    res = execute("SELECT k, count(*) FROM g GROUP BY k", {"g": t})
    assert res.rows == [[None, 2], ["a", 1]]


def test_group_order_is_first_appearance():
    t = Table("g", [Column("k", "TEXT")], [["b"], ["a"], ["b"]])
    res = execute("SELECT k FROM g GROUP BY k", {"g": t})
    assert res.rows == [["b"], ["a"]]


def test_group_by_expression():
    res = run("SELECT length(name), count(*) FROM people GROUP BY length(name)")
    assert res == [[3, 2], [2, 1], [None, 1]]


def test_grouping_error_on_non_grouped_column():
    with pytest.raises(GroupingError):
        execute("SELECT name, count(*) FROM people GROUP BY age", tables())


def test_having_filters_groups():
    res = run("SELECT id, count(*) FROM people GROUP BY id HAVING id > 2")
    assert res == [[3, 1], [4, 1]]


def test_left_join_fills_nulls():
    orders = Table("o", [Column("pid", "INT"), Column("amt", "INT")], [[1, 5]])
    res = execute(
        "SELECT people.id, o.amt FROM people LEFT JOIN o ON people.id = o.pid ORDER BY people.id",
        {"people": people(), "o": orders},
    )
    assert res.rows[0] == [1, 5]
    assert res.rows[1] == [2, None]


def test_inner_join_keeps_matches_only():
    orders = Table("o", [Column("pid", "INT")], [[2], [9]])
    res = execute("SELECT people.id FROM people INNER JOIN o ON people.id = o.pid",
                  {"people": people(), "o": orders})
    assert res.rows == [[2]]


def test_join_ambiguous_column():
    orders = Table("o", [Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM people INNER JOIN o ON people.id = o.id",
                {"people": people(), "o": orders})


def test_join_unknown_qualifier():
    orders = Table("o", [Column("id", "INT")], [[1]])
    with pytest.raises(UnknownTableError):
        execute("SELECT x.id FROM people INNER JOIN o ON people.id = o.id",
                {"people": people(), "o": orders})


def test_unknown_function_and_arity():
    with pytest.raises(UnknownFunctionError):
        execute("SELECT nosuch(id) FROM people", tables())
    with pytest.raises(ArityError):
        execute("SELECT upper(name, name) FROM people", tables())


def test_coalesce_and_concat_null_rules():
    assert run("SELECT coalesce(NULL, 'x') FROM people LIMIT 1") == [["x"]]
    assert run("SELECT concat('a', NULL) FROM people LIMIT 1") == [[None]]


def test_scalar_type_mismatch():
    with pytest.raises(TypeMismatchError):
        execute("SELECT length(id) FROM people", tables())


def test_output_names_source_text():
    res = execute("SELECT id  +   age FROM people", {"people": people()})
    assert res.columns == ["id + age"]
    res = execute("SELECT count(*) FROM people", {"people": people()})
    assert res.columns == ["count(*)"]


def test_output_name_for_bare_column():
    assert execute("SELECT name FROM people", tables()).columns == ["name"]


def test_plan_is_inspectable():
    p = plan(parse("SELECT id FROM people WHERE id > 1 ORDER BY id LIMIT 1"))
    assert len(p) > 0
    assert all(getattr(stage, "name", None) for stage in p)


def test_lex_error_exposed_by_execute():
    with pytest.raises(LexError):
        execute("SELECT id FROM people WHERE id = @", tables())


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


@pytest.fixture()
def scratch():
    d = ROOT / ".pytest_scratch_microdb"
    d.mkdir(exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _cli(capsys, scratch: Path, text: str, query: str) -> tuple[int, str, str]:
    csv = _write(scratch / "t.csv", text)
    code = main(["--table", f"t={csv}", query])
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_count_example(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id:INT,age:INT\n1,31\n2,25\n3,40\n",
                        "SELECT count(*) FROM t WHERE age > 30")
    assert code == 0
    assert out == "count(*)\n2\n"


def test_cli_exit_2_missing_table(capsys):
    assert main(["SELECT 1 FROM t"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_exit_2_unreadable_file(capsys):
    assert main(["--table", "t=does_not_exist_xyz.csv", "SELECT * FROM t"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_exit_2_malformed_header(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id,age\n1,2\n", "SELECT * FROM t")
    assert code == 2
    assert out == ""


def test_cli_exit_3_on_engine_error(capsys, scratch):
    code, out, err = _cli(capsys, scratch, "id:INT\n1\n", "SELECT nosuch FROM t")
    assert code == 3
    assert out == ""
    assert err != ""


def test_cli_exit_3_on_lex_error(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id:INT\n1\n", "SELECT @ FROM t")
    assert code == 3
    assert out == ""


def test_cli_null_and_bool_output(capsys, scratch):
    text = 'id:INT,ok:BOOL,name:TEXT\n1,true,\n2,FALSE,""\n'
    code, out, _ = _cli(capsys, scratch, text, "SELECT id, ok, name FROM t ORDER BY id")
    assert code == 0
    assert out == "id,ok,name\n1,true,\n2,false,\n"


def test_cli_quotes_fields_with_comma_and_quote(capsys, scratch):
    text = 'id:INT,name:TEXT\n1,"a,b"\n2,"say ""hi"""\n'
    code, out, _ = _cli(capsys, scratch, text, "SELECT name FROM t ORDER BY id")
    assert code == 0
    assert out == 'name\n"a,b"\n"say ""hi"""\n'


def test_cli_single_null_column_renders_empty_line(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id:INT\n\n", "SELECT id FROM t")
    assert code == 0
    assert out == "id\n\n"


def test_cli_nonzero_exit_writes_no_stdout(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id:INT\n1\n", "SELECT id FROM t WHERE 1")
    assert code == 3
    assert out == ""


def test_cli_quoted_empty_text_is_empty_string(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, 'name:TEXT\n""\n', "SELECT name FROM t")
    assert code == 0
    assert out == "name\n\n"


def test_cli_bad_int_cell_is_schema_error(capsys, scratch):
    code, out, _ = _cli(capsys, scratch, "id:INT\nabc\n", "SELECT id FROM t")
    assert code == 3
    assert out == ""


def test_cli_no_arguments_is_usage_error(capsys):
    assert main([]) == 2


def test_cli_duplicate_table_name(capsys, scratch):
    csv = _write(scratch / "d.csv", "id:INT\n1\n")
    assert main(["--table", f"t={csv}", "--table", f"t={csv}", "SELECT id FROM t"]) == 2


def test_error_hierarchy_is_micro_db_error():
    for cls in (LexError, ParseError, GroupingError, SchemaError, TypeMismatchError,
                ArityError, AggregateError, UnknownColumnError, UnknownTableError,
                UnknownFunctionError, AmbiguousColumnError):
        assert issubclass(cls, MicroDBError)


def test_lex_and_parse_errors_carry_offset():
    with pytest.raises(ParseError) as info:
        parse("SELECT FROM people")
    assert isinstance(info.value.offset, int)

"""Test suite for microdb."""

from __future__ import annotations

import dataclasses

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
)
from microdb.__main__ import main
from microdb.lexer import tokenize
from microdb.parser import parse
from microdb.planner import plan
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


@pytest.fixture()
def people() -> Table:
    return Table(
        "people",
        [Column("id", "INT"), Column("name", "TEXT"), Column("age", "INT")],
        [
            [1, "alice", 25],
            [2, "bob", 35],
            [3, "carol", None],
            [4, None, 41],
            [5, "dave", 35],
        ],
    )


@pytest.fixture()
def pets() -> Table:
    return Table(
        "pets",
        [Column("owner", "INT"), Column("pet", "TEXT")],
        [[1, "rex"], [1, "tom"], [3, "mo"]],
    )


# ---------------------------------------------------------------------------
# Value model and three-valued logic
# ---------------------------------------------------------------------------

def test_type_of_kinds() -> None:
    assert type_of(1) == "INT"
    assert type_of(1.5) == "FLOAT"
    assert type_of("x") == "TEXT"
    assert type_of(True) == "BOOL"
    assert type_of(None) == "NULL"


def test_bool_is_not_int() -> None:
    assert type_of(True) == "BOOL"
    assert not is_numeric(True)
    assert not is_numeric(False)


def test_is_numeric() -> None:
    assert is_numeric(1)
    assert is_numeric(1.5)
    assert not is_numeric("1")
    assert not is_numeric(None)
    assert not is_numeric(True)


def test_and_truth_table() -> None:
    assert and_(True, True) is True
    assert and_(True, False) is False
    assert and_(True, None) is None
    assert and_(False, True) is False
    assert and_(False, False) is False
    assert and_(False, None) is False
    assert and_(None, True) is None
    assert and_(None, False) is False
    assert and_(None, None) is None


def test_or_truth_table() -> None:
    assert or_(True, True) is True
    assert or_(True, False) is True
    assert or_(True, None) is True
    assert or_(False, True) is True
    assert or_(False, False) is False
    assert or_(False, None) is None
    assert or_(None, True) is True
    assert or_(None, False) is None
    assert or_(None, None) is None


def test_not_truth_table() -> None:
    assert not_(True) is False
    assert not_(False) is True
    assert not_(None) is None


# ---------------------------------------------------------------------------
# Comparison and arithmetic
# ---------------------------------------------------------------------------

def test_null_eq_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_lt(None, 1) is None
    assert compare_eq(1, None) is None


def test_compare_numeric_mixed() -> None:
    assert compare_eq(1, 1.0) is True
    assert compare_lt(2, 2.5) is True
    assert compare_eq(2, 2.0) is True


def test_compare_text_codepoint() -> None:
    assert compare_lt("abc", "abd") is True
    assert compare_eq("a", "a") is True
    assert compare_lt("B", "a") is True  # Unicode code point order


def test_compare_bool() -> None:
    assert compare_lt(False, True) is True
    assert compare_eq(True, True) is True


def test_compare_type_mismatch() -> None:
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("1", 1)
    with pytest.raises(TypeMismatchError):
        compare_eq("a", 1.0)


def test_arith_int_int() -> None:
    assert arith("+", 1, 2) == 3
    assert type_of(arith("-", 1, 2)) == "INT"
    assert arith("*", 3, 4) == 12


def test_arith_float_promotion() -> None:
    assert arith("+", 1, 0.5) == 1.5
    assert type_of(arith("*", 2, 3.0)) == "FLOAT"


def test_division_always_float() -> None:
    assert arith("/", 7, 2) == 3.5
    assert type_of(arith("/", 4, 2)) == "FLOAT"


def test_division_by_zero_is_null() -> None:
    assert arith("/", 7, 0) is None
    assert arith("/", 7.0, 0.0) is None
    assert arith("%", 7, 0) is None


def test_modulo_sign_rule() -> None:
    assert arith("%", -7, 3) == 2
    assert arith("%", 7, -3) == -2


def test_modulo_requires_int() -> None:
    with pytest.raises(TypeMismatchError):
        arith("%", 7.0, 2)


def test_arith_null_propagation() -> None:
    assert arith("+", None, 1) is None
    assert arith("*", 1, None) is None


def test_arith_rejects_bool_and_text() -> None:
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        arith("+", "a", "b")  # no string concatenation with +


def test_negate() -> None:
    assert negate(3) == -3
    assert negate(2.5) == -2.5
    assert negate(None) is None
    with pytest.raises(TypeMismatchError):
        negate("x")
    with pytest.raises(TypeMismatchError):
        negate(True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_table_basic() -> None:
    t = Table("t", [Column("a", "INT")], [[1], [None]])
    assert t.name == "t"
    assert [c.name for c in t.columns] == ["a"]
    assert t.rows == [[1], [None]]
    assert t.column_index("a") == 0


def test_table_rejects_empty_columns() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])


def test_table_rejects_duplicate_columns() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "INT")], [])


def test_table_column_names_case_sensitive() -> None:
    t = Table("t", [Column("a", "INT"), Column("A", "INT")], [[1, 2]])
    assert t.column_index("A") == 1


def test_table_rejects_bad_type() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "DATE")], [])


def test_table_rejects_wrong_row_length() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_table_int_rejects_bool_and_float() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])


def test_table_float_widens_int() -> None:
    t = Table("t", [Column("a", "FLOAT")], [[3]])
    assert t.rows == [[3.0]]
    assert type_of(t.rows[0][0]) == "FLOAT"


def test_column_index_unknown() -> None:
    t = Table("t", [Column("a", "INT")], [])
    with pytest.raises(SchemaError):
        t.column_index("b")


# ---------------------------------------------------------------------------
# Lexer and parser
# ---------------------------------------------------------------------------

def test_lexer_keywords_case_insensitive() -> None:
    toks = tokenize("select FROM Where")
    assert [t.value for t in toks[:3]] == ["SELECT", "FROM", "WHERE"]


def test_lexer_comment() -> None:
    toks = tokenize("SELECT -- a comment\nFROM")
    assert [t.value for t in toks[:2]] == ["SELECT", "FROM"]


def test_lexer_floats() -> None:
    toks = tokenize("1. .5 1.5 1e3 1.5E-2 2")
    assert [t.kind for t in toks[:-1]] == ["FLOAT"] * 5 + ["INT"]
    assert toks[0].value == 1.0
    assert toks[1].value == 0.5
    assert toks[3].value == 1000.0
    assert toks[4].value == 0.015


def test_lexer_text_escaped_quote() -> None:
    (tok,) = [t for t in tokenize("'it''s'") if t.kind != "EOF"]
    assert tok.value == "it's"


def test_lexer_error_offset() -> None:
    with pytest.raises(LexError) as exc:
        tokenize("SELECT @x")
    assert exc.value.offset == 7


def test_parse_not_binds_looser_than_comparison() -> None:
    q = parse("SELECT a FROM t WHERE NOT a = b")
    assert q.where is not None
    assert type(q.where).__name__ == "NotOp"


def test_parse_comparison_not_associative() -> None:
    with pytest.raises(ParseError):
        parse("SELECT a FROM t WHERE 1 < 2 < 3")


def test_parse_aggregate_nesting() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")


def test_parse_star_only_in_count() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(*) FROM t")


def test_parse_keyword_is_not_identifier() -> None:
    with pytest.raises(ParseError):
        parse("SELECT order FROM t")


def test_parse_error_has_offset() -> None:
    with pytest.raises(ParseError) as exc:
        parse("SELECT FROM t")
    assert isinstance(exc.value.offset, int)


# ---------------------------------------------------------------------------
# Execution: WHERE, projection, functions
# ---------------------------------------------------------------------------

def test_where_null_eq_null_returns_nothing(people: Table) -> None:
    r = execute("SELECT id FROM people WHERE age = NULL", {"people": people})
    assert r.rows == []


def test_where_requires_logical(people: Table) -> None:
    with pytest.raises(TypeMismatchError):
        execute("SELECT id FROM people WHERE 1", {"people": people})


def test_where_cannot_see_alias(people: Table) -> None:
    with pytest.raises(UnknownColumnError):
        execute("SELECT id AS x FROM people WHERE x > 1", {"people": people})


def test_where_cannot_contain_aggregate(people: Table) -> None:
    with pytest.raises(AggregateError):
        execute("SELECT id FROM people WHERE count(*) > 1",
                {"people": people})


def test_is_null_predicates(people: Table) -> None:
    r = execute("SELECT id FROM people WHERE age IS NULL", {"people": people})
    assert r.rows == [[3]]
    r = execute("SELECT id FROM people WHERE age IS NOT NULL",
                {"people": people})
    assert r.rows == [[1], [2], [4], [5]]


def test_scalar_functions(people: Table) -> None:
    r = execute(
        "SELECT upper(name), lower(name), length(name) FROM people "
        "WHERE id = 1", {"people": people})
    assert r.rows == [["ALICE", "alice", 5]]
    r = execute("SELECT concat(name, '!') FROM people WHERE id = 1",
                {"people": people})
    assert r.rows == [["alice!"]]
    r = execute("SELECT abs(0 - 5) FROM people WHERE id = 1",
                {"people": people})
    assert r.rows == [[5]]


def test_concat_null_propagates(people: Table) -> None:
    r = execute("SELECT concat(name, '!') FROM people WHERE id = 4",
                {"people": people})
    assert r.rows == [[None]]


def test_coalesce_returns_first_non_null(people: Table) -> None:
    r = execute("SELECT coalesce(name, 'anon') FROM people ORDER BY id",
                {"people": people})
    assert r.rows == [["alice"], ["bob"], ["carol"], ["anon"], ["dave"]]


def test_function_arity_and_unknown(people: Table) -> None:
    with pytest.raises(ArityError):
        execute("SELECT upper(name, name) FROM people", {"people": people})
    with pytest.raises(UnknownFunctionError):
        execute("SELECT nosuch(name) FROM people", {"people": people})
    with pytest.raises(TypeMismatchError):
        execute("SELECT upper(age) FROM people WHERE id = 1",
                {"people": people})


# ---------------------------------------------------------------------------
# Aggregates and grouping
# ---------------------------------------------------------------------------

def test_count_star_empty_table() -> None:
    empty = Table("e", [Column("a", "INT")], [])
    r = execute("SELECT count(*) FROM e", {"e": empty})
    assert r.rows == [[0]]  # exactly one row even when the input is empty


def test_sum_of_empty_group_is_null() -> None:
    empty = Table("e", [Column("a", "INT")], [])
    r = execute("SELECT sum(a), avg(a), min(a), max(a) FROM e", {"e": empty})
    assert r.rows == [[None, None, None, None]]


def test_count_expr_ignores_nulls(people: Table) -> None:
    r = execute("SELECT count(*), count(age), count(name) FROM people",
                {"people": people})
    assert r.rows == [[5, 4, 4]]


def test_avg_is_float_and_skips_nulls(people: Table) -> None:
    r = execute("SELECT avg(age) FROM people", {"people": people})
    assert r.rows == [[34.0]]
    assert type_of(r.rows[0][0]) == "FLOAT"


def test_sum_type(people: Table) -> None:
    r = execute("SELECT sum(age) FROM people", {"people": people})
    assert r.rows == [[136]]
    assert type_of(r.rows[0][0]) == "INT"
    floats = Table("f", [Column("x", "FLOAT")], [[1.5], [2]])
    r = execute("SELECT sum(x) FROM f", {"f": floats})
    assert r.rows == [[3.5]]
    assert type_of(r.rows[0][0]) == "FLOAT"


def test_min_max(people: Table) -> None:
    r = execute("SELECT min(age), max(age), min(name) FROM people",
                {"people": people})
    assert r.rows == [[25, 41, "alice"]]
    assert type_of(r.rows[0][0]) == "INT"


def test_aggregate_mixed_types_raise() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "TEXT")],
              [[1, "x"], [None, "y"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT min(coalesce(a, b)) FROM t", {"t": t})


def test_sum_rejects_text() -> None:
    t = Table("t", [Column("b", "TEXT")], [["x"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT sum(b) FROM t", {"t": t})


def test_nulls_group_together(people: Table) -> None:
    extra = Table(
        "t", [Column("g", "INT")], [[None], [1], [None], [1]])
    r = execute("SELECT g, count(*) FROM t GROUP BY g", {"t": extra})
    assert sorted(r.rows, key=lambda row: (row[0] is not None, row[0])) == [
        [None, 2], [1, 2]]


def test_group_order_is_first_appearance() -> None:
    t = Table("t", [Column("g", "TEXT")], [["b"], ["a"], ["b"], ["c"], ["a"]])
    r = execute("SELECT g, count(*) FROM t GROUP BY g", {"t": t})
    assert [row[0] for row in r.rows] == ["b", "a", "c"]


def test_group_by_expression() -> None:
    t = Table("t", [Column("n", "TEXT")], [["ab"], ["c"], ["de"], ["f"]])
    r = execute("SELECT length(n), count(*) FROM t GROUP BY length(n)",
                {"t": t})
    assert r.rows == [[2, 2], [1, 2]]


def test_grouping_error(people: Table) -> None:
    with pytest.raises(GroupingError):
        execute("SELECT name, count(*) FROM people GROUP BY age",
                {"people": people})


def test_having_filters_groups(people: Table) -> None:
    r = execute(
        "SELECT age, count(*) FROM people GROUP BY age HAVING count(*) > 1",
        {"people": people})
    assert r.rows == [[35, 2]]


def test_having_unknown_drops_group(people: Table) -> None:
    r = execute(
        "SELECT age FROM people GROUP BY age HAVING min(name) = NULL",
        {"people": people})
    assert r.rows == []


def test_expression_over_grouping_expr() -> None:
    t = Table("t", [Column("n", "TEXT")], [["ab"], ["cd"]])
    r = execute("SELECT upper(n), count(*) FROM t GROUP BY n", {"t": t})
    assert sorted(r.rows) == [["AB", 1], ["CD", 1]]


# ---------------------------------------------------------------------------
# DISTINCT, ORDER BY, LIMIT/OFFSET
# ---------------------------------------------------------------------------

def test_distinct_removes_duplicates() -> None:
    t = Table("t", [Column("a", "INT")], [[1], [2], [1], [None], [None]])
    r = execute("SELECT DISTINCT a FROM t", {"t": t})
    assert r.rows == [[1], [2], [None]]


def test_nulls_sort_last_asc_and_desc(people: Table) -> None:
    r = execute("SELECT age FROM people ORDER BY age", {"people": people})
    assert r.rows == [[25], [35], [35], [41], [None]]
    r = execute("SELECT age FROM people ORDER BY age DESC",
                {"people": people})
    assert r.rows == [[41], [35], [35], [25], [None]]


def test_sort_is_stable() -> None:
    t = Table("t", [Column("k", "INT"), Column("v", "TEXT")],
              [[1, "a"], [1, "b"], [1, "c"], [0, "z"]])
    r = execute("SELECT v FROM t ORDER BY k", {"t": t})
    assert r.rows == [["z"], ["a"], ["b"], ["c"]]


def test_order_by_multiple_keys(people: Table) -> None:
    r = execute(
        "SELECT id FROM people WHERE age IS NOT NULL "
        "ORDER BY age DESC, id ASC", {"people": people})
    assert r.rows == [[4], [2], [5], [1]]


def test_order_by_alias_wins() -> None:
    t = Table("t", [Column("a", "INT")], [[3], [1], [2]])
    r = execute("SELECT 10 - a AS a FROM t ORDER BY a", {"t": t})
    assert r.rows == [[7], [8], [9]]  # alias (10-a), not the input column


def test_order_by_alias_visible(people: Table) -> None:
    r = execute("SELECT id AS x FROM people ORDER BY x DESC LIMIT 1",
                {"people": people})
    assert r.rows == [[5]]


def test_order_by_type_mismatch() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "TEXT")],
              [[1, "x"], [None, "y"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT coalesce(a, b) AS c FROM t ORDER BY c", {"t": t})


def test_distinct_order_by_needs_output_column() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT a FROM t ORDER BY b", {"t": t})


def test_offset_before_limit(people: Table) -> None:
    r = execute("SELECT id FROM people ORDER BY id LIMIT 2 OFFSET 1",
                {"people": people})
    assert r.rows == [[2], [3]]
    r = execute("SELECT id FROM people ORDER BY id OFFSET 3",
                {"people": people})
    assert r.rows == [[4], [5]]


# ---------------------------------------------------------------------------
# Joins
# ---------------------------------------------------------------------------

def test_inner_join(people: Table, pets: Table) -> None:
    r = execute(
        "SELECT name, pet FROM people INNER JOIN pets ON id = owner",
        {"people": people, "pets": pets})
    assert r.rows == [["alice", "rex"], ["alice", "tom"], ["carol", "mo"]]


def test_left_join_null_filling(people: Table, pets: Table) -> None:
    r = execute(
        "SELECT id, pet FROM people LEFT JOIN pets ON id = owner ORDER BY id",
        {"people": people, "pets": pets})
    assert r.rows == [
        [1, "rex"], [1, "tom"], [2, None], [3, "mo"], [4, None], [5, None]]


def test_join_row_order_is_left_major(people: Table, pets: Table) -> None:
    r = execute(
        "SELECT id, pet FROM people JOIN pets ON id = owner",
        {"people": people, "pets": pets})
    assert r.rows == [[1, "rex"], [1, "tom"], [3, "mo"]]


def test_join_output_column_order(people: Table, pets: Table) -> None:
    r = execute("SELECT * FROM people JOIN pets ON id = owner LIMIT 1",
                {"people": people, "pets": pets})
    assert r.columns == ["id", "name", "age", "owner", "pet"]


def test_ambiguous_column(people: Table, pets: Table) -> None:
    # both tables would need the same column name; build one
    a = Table("a", [Column("x", "INT")], [[1]])
    b = Table("b", [Column("x", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT x FROM a JOIN b ON a.x = b.x", {"a": a, "b": b})


def test_qualified_reference_resolves(people: Table, pets: Table) -> None:
    r = execute("SELECT people.id FROM people JOIN pets ON id = owner "
                "LIMIT 1", {"people": people, "pets": pets})
    assert r.rows == [[1]]


def test_unknown_table_in_qualified_ref(people: Table) -> None:
    with pytest.raises(UnknownTableError):
        execute("SELECT nope.id FROM people", {"people": people})


def test_unknown_from_table() -> None:
    with pytest.raises(UnknownTableError):
        execute("SELECT a FROM nope", {})


def test_unknown_column(people: Table) -> None:
    with pytest.raises(UnknownColumnError):
        execute("SELECT nope FROM people", {"people": people})


def test_left_join_on_unknown_is_not_a_match() -> None:
    a = Table("a", [Column("x", "INT")], [[None]])
    b = Table("b", [Column("y", "INT")], [[None]])
    r = execute("SELECT x, y FROM a LEFT JOIN b ON x = y", {"a": a, "b": b})
    assert r.rows == [[None, None]]  # ON UNKNOWN never matches


# ---------------------------------------------------------------------------
# Output naming, planner, Result
# ---------------------------------------------------------------------------

def test_output_column_names(people: Table) -> None:
    r = execute("SELECT id, age + 1 FROM people LIMIT 1", {"people": people})
    assert r.columns == ["id", "age + 1"]
    r = execute("SELECT count(*) AS n FROM people", {"people": people})
    assert r.columns == ["n"]
    r = execute("SELECT count(*) FROM people", {"people": people})
    assert r.columns == ["count(*)"]


def test_output_name_collapses_whitespace(people: Table) -> None:
    r = execute("SELECT age   +\n 1 FROM people LIMIT 1",
                {"people": people})
    assert r.columns == ["age + 1"]


def test_result_is_frozen(people: Table) -> None:
    r = execute("SELECT id FROM people LIMIT 1", {"people": people})
    assert isinstance(r.columns, list)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.columns = []  # type: ignore[misc]


def test_planner_exposes_named_stages(people: Table) -> None:
    q = parse(
        "SELECT DISTINCT age FROM people WHERE id > 0 GROUP BY age "
        "HAVING count(*) > 0 ORDER BY age LIMIT 3 OFFSET 1")
    p = plan(q)
    assert p.stage_names() == [
        "FROM", "WHERE", "GROUP BY", "AGGREGATE", "HAVING", "SELECT",
        "DISTINCT", "ORDER BY", "OFFSET", "LIMIT"]
    assert len(p) == 10
    assert p[0].name == "FROM"


def test_execute_plan_roundtrip(people: Table) -> None:
    q = parse("SELECT count(*) FROM people WHERE age > 30")
    r = microdb.execute_plan(microdb.plan(q), {"people": people})
    assert r.rows == [[3]]  # ages 35, 41, 35


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_csv(tmp_path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv",
                   "id:INT,name:TEXT,age:INT\n1,alice,25\n2,bob,35\n3,c,41\n")
    code = main(["--table", f"t={p}", "SELECT count(*) FROM t WHERE age > 30"])
    assert code == 0
    assert capsys.readouterr().out == "count(*)\n2\n"


def test_cli_usage_errors(tmp_path, capsys) -> None:
    assert main([]) == 2
    assert main(["SELECT 1"]) == 2  # missing --table
    assert main(["--table", "bad", "SELECT 1"]) == 2
    assert main(["--table", "t=x.csv", "SELECT 1", "extra"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_unreadable_file(tmp_path, capsys) -> None:
    code = main(["--table", f"t={tmp_path / 'nope.csv'}", "SELECT 1 FROM t"])
    assert code == 2
    assert capsys.readouterr().out == ""


def test_cli_malformed_header(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "bad.csv", "idINT\n1\n")
    assert main(["--table", f"t={p}", "SELECT id FROM t"]) == 2
    p = _write_csv(tmp_path, "bad2.csv", "id:DATE\n1\n")
    assert main(["--table", f"t={p}", "SELECT id FROM t"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_microdb_error_exit_3(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv", "id:INT\n1\n")
    code = main(["--table", f"t={p}", "SELECT nope FROM t"])
    assert code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nope" in captured.err


def test_cli_data_type_error_exit_3(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv", "id:INT\nabc\n")
    assert main(["--table", f"t={p}", "SELECT id FROM t"]) == 3
    assert capsys.readouterr().out == ""


def test_cli_null_bool_and_empty_string(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv",
                   "b:BOOL,s:TEXT\nTrUe,x\n,\nfalse,''\n")
    code = main(["--table", f"t={p}", "SELECT b, s FROM t ORDER BY s"])
    assert code == 0
    out = capsys.readouterr().out
    # ORDER BY s ASC: '' < 'x', NULL sorts last
    assert out == "b,s\nfalse,\ntrue,x\n,\n"


def test_cli_csv_quoting(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv", 's:TEXT\n"a,b"\n')
    code = main(["--table", f"t={p}",
                 "SELECT concat(s, ' it''s \"x\"') FROM t"])
    assert code == 0
    out = capsys.readouterr().out
    # the header field itself contains a comma and quotes, so it is quoted
    assert out == '"concat(s, \' it\'\'s ""x""\')"\n"a,b it\'s ""x"""\n'


def test_cli_float_rendering(tmp_path, capsys) -> None:
    p = _write_csv(tmp_path, "p.csv", "f:FLOAT\n1\n2.5\n")
    code = main(["--table", f"t={p}", "SELECT f, f / 2 FROM t ORDER BY f"])
    assert code == 0
    assert capsys.readouterr().out == "f,f / 2\n1.0,0.5\n2.5,1.25\n"


def test_public_api_all() -> None:
    assert len(microdb.__all__) > 0
    for name in microdb.__all__:
        assert hasattr(microdb, name)

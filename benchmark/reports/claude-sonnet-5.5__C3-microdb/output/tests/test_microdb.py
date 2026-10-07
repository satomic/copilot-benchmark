import itertools
import pathlib
import subprocess
import sys

import pytest

import microdb
from microdb import (AggregateError, AmbiguousColumnError, ArityError, Column,
                     GroupingError, LexError, ParseError, SchemaError, Table,
                     TypeMismatchError, UnknownColumnError,
                     UnknownFunctionError, UnknownTableError, execute)
from microdb.__main__ import main
from microdb.aggregate import aggregate
from microdb.lexer import tokenize
from microdb.parser import parse
from microdb.planner import plan
from microdb.value import (and_, arith, compare_eq, compare_lt, is_numeric,
                           negate, not_, or_, type_of)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def make_tables():
    t = Table("t", [Column("id", "INT"), Column("g", "TEXT"), Column("v", "INT")], [
        [1, "a", 10], [2, "b", None], [3, None, 30], [4, "a", 5], [5, None, None],
    ])
    empty = Table("e", [Column("x", "INT")], [])
    l = Table("l", [Column("id", "INT"), Column("name", "TEXT")],
              [[1, "one"], [2, "two"], [3, "three"]])
    r = Table("r", [Column("lid", "INT"), Column("tag", "TEXT")],
              [[1, "x"], [1, "y"], [3, "z"], [None, "n"]])
    return {"t": t, "e": empty, "l": l, "r": r}


def q(sql):
    return execute(sql, make_tables())


def rows(sql):
    return q(sql).rows


# ---- value model ----
def test_type_of_and_bool_is_not_int():
    assert [type_of(x) for x in (1, 1.5, "s", True, None)] == \
        ["INT", "FLOAT", "TEXT", "BOOL", "NULL"]
    assert not is_numeric(True) and not is_numeric(None) and is_numeric(2.0)


def test_and_truth_table():
    T, F, U = True, False, None
    expected = {(T, T): T, (T, F): F, (T, U): U, (F, T): F, (F, F): F,
                (F, U): F, (U, T): U, (U, F): F, (U, U): U}
    for (a, b), want in expected.items():
        assert and_(a, b) is want


def test_or_truth_table():
    T, F, U = True, False, None
    expected = {(T, T): T, (T, F): T, (T, U): T, (F, T): T, (F, F): F,
                (F, U): U, (U, T): T, (U, F): U, (U, U): U}
    for (a, b), want in expected.items():
        assert or_(a, b) is want


def test_not_truth_table():
    assert not_(True) is False and not_(False) is True and not_(None) is None


def test_null_equals_null_is_unknown():
    assert compare_eq(None, None) is None
    assert compare_lt(None, 1) is None and compare_eq(1, None) is None


def test_comparison_types():
    assert compare_eq(1, 1.0) is True
    assert compare_lt("a", "b") is True
    assert compare_lt(False, True) is True
    for a, b in ((True, 1), (1, "1"), ("a", True)):
        with pytest.raises(TypeMismatchError):
            compare_eq(a, b)


def test_arithmetic_types():
    assert arith("+", 1, 2) == 3 and type(arith("+", 1, 2)) is int
    assert type(arith("*", 2, 1.5)) is float
    assert arith("/", 7, 2) == 3.5
    assert arith("%", -7, 3) == 2
    assert arith("+", None, 1) is None


def test_division_and_modulo_by_zero_are_null():
    assert arith("/", 1, 0) is None and arith("/", 1.0, 0.0) is None
    assert arith("%", 5, 0) is None
    assert rows("SELECT 1 / 0 FROM e") == []
    assert rows("SELECT 1 / 0 FROM l LIMIT 1") == [[None]]


def test_arithmetic_type_errors():
    for op, a, b in (("+", True, 1), ("+", "a", "b"), ("%", 1.0, 2)):
        with pytest.raises(TypeMismatchError):
            arith(op, a, b)
    with pytest.raises(TypeMismatchError):
        negate("x")
    assert negate(None) is None and negate(2.5) == -2.5


# ---- schema ----
def test_table_validation():
    with pytest.raises(SchemaError):
        Table("x", [], [])
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "INT"), Column("a", "INT")], [])
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "DATE")], [])
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "INT")], [[1, 2]])
    Table("x", [Column("a", "INT"), Column("A", "INT")], [])


def test_table_cell_typing():
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "INT")], [[3.0]])
    with pytest.raises(SchemaError):
        Table("x", [Column("a", "BOOL")], [[1]])
    t = Table("x", [Column("a", "FLOAT")], [[3], [None]])
    assert t.rows == [[3.0], [None]] and type(t.rows[0][0]) is float
    assert t.column_index("a") == 0
    with pytest.raises(SchemaError):
        t.column_index("zz")


# ---- lexer ----
def test_lexer_numbers_and_comments():
    kinds = [(t.kind, t.value) for t in tokenize("1 1. .5 1e3 1.5E-2 -- hi\n 7")[:-1]]
    assert kinds == [("INT", 1), ("FLOAT", 1.0), ("FLOAT", 0.5), ("FLOAT", 1000.0),
                     ("FLOAT", 0.015), ("INT", 7)]


def test_lexer_text_and_keywords():
    toks = tokenize("select 'it''s\nok'")
    assert toks[0].kind == "KW" and toks[0].value == "SELECT"
    assert toks[1].value == "it's\nok"


def test_lex_error_offset():
    with pytest.raises(LexError) as info:
        tokenize("SELECT a ! b")
    assert info.value.offset == 9
    with pytest.raises(LexError):
        tokenize("'open")


# ---- parser ----
def test_predicate_not_associative():
    with pytest.raises(ParseError):
        parse("SELECT 1 < 2 < 3 FROM t")


def test_not_binds_looser_than_comparison():
    assert rows("SELECT NOT id = 1 FROM t WHERE id <= 2") == [[False], [True]]


def test_parse_errors_carry_offset():
    with pytest.raises(ParseError) as info:
        parse("SELECT FROM t")
    assert info.value.offset == 7
    for bad in ("SELECT a FROM t LIMIT x", "SELECT a FROM t ORDER a",
                "SELECT sum(*) FROM t", "SELECT a FROM t WHERE a IS 1",
                "SELECT a FROM t JOIN u ON 1=1 JOIN w ON 1=1"):
        with pytest.raises(ParseError):
            parse(bad)


def test_nested_aggregate_is_parse_error():
    with pytest.raises(ParseError):
        parse("SELECT sum(count(v)) FROM t")


def test_keyword_not_identifier():
    with pytest.raises(ParseError):
        parse("SELECT order FROM t")


# ---- functions ----
def test_scalar_functions():
    assert rows("SELECT concat('a', 'b', 'c'), upper('x'), lower('X'), "
                "length('héé'), abs(-2), abs(-2.5) FROM e") == []
    r = rows("SELECT concat('a', 'b'), UPPER('x'), lower('X'), length('hé'), "
             "abs(-2), coalesce(NULL, NULL, 3) FROM l LIMIT 1")
    assert r == [["ab", "X", "x", 2, 2, 3]]


def test_null_propagation_in_functions():
    r = rows("SELECT concat('a', NULL), upper(NULL), length(NULL), abs(NULL), "
             "coalesce(NULL, NULL) FROM l LIMIT 1")
    assert r == [[None] * 5]


def test_function_errors():
    with pytest.raises(ArityError, match="upper"):
        rows("SELECT upper('a', 'b') FROM l")
    with pytest.raises(ArityError):
        rows("SELECT concat('a') FROM l")
    with pytest.raises(ArityError):
        rows("SELECT coalesce() FROM l")
    with pytest.raises(UnknownFunctionError):
        rows("SELECT nope(1) FROM l")
    with pytest.raises(TypeMismatchError):
        rows("SELECT upper(1) FROM l")
    with pytest.raises(TypeMismatchError):
        rows("SELECT concat('a', 1) FROM l")


# ---- aggregates ----
def test_count_variants():
    assert rows("SELECT count(*), count(v), count(g) FROM t") == [[5, 3, 3]]


def test_sum_avg_min_max():
    assert rows("SELECT sum(v), avg(v), min(v), max(v) FROM t") == [[45, 15.0, 5, 30]]
    assert type(rows("SELECT avg(id) FROM t")[0][0]) is float
    assert rows("SELECT min(g), max(g) FROM t") == [["a", "b"]]


def test_empty_group_aggregates():
    assert rows("SELECT count(*) FROM e") == [[0]]
    assert rows("SELECT count(x), sum(x), avg(x), min(x), max(x) FROM e") == \
        [[0, None, None, None, None]]
    assert rows("SELECT sum(v) FROM t WHERE v IS NULL") == [[None]]


def test_sum_type_rules():
    assert aggregate("sum", [1, 2]) == 3 and type(aggregate("sum", [1, 2])) is int
    assert type(aggregate("sum", [1, 2.0])) is float
    for bad in (["a"], [True]):
        with pytest.raises(TypeMismatchError):
            aggregate("sum", bad)
    with pytest.raises(TypeMismatchError):
        aggregate("max", ["a", 1])


# ---- execution semantics ----
def test_where_keeps_only_true():
    assert rows("SELECT id FROM t WHERE v = NULL") == []
    assert rows("SELECT id FROM t WHERE v > 5") == [[1], [3]]
    assert rows("SELECT id FROM t WHERE v IS NULL") == [[2], [5]]


def test_non_boolean_predicate_raises():
    with pytest.raises(TypeMismatchError):
        rows("SELECT id FROM t WHERE 1")


def test_where_rejects_aggregates():
    with pytest.raises(AggregateError):
        rows("SELECT id FROM t WHERE count(*) > 1")


def test_alias_in_order_by_not_where():
    assert rows("SELECT id AS k FROM t ORDER BY k DESC LIMIT 2") == [[5], [4]]
    with pytest.raises(UnknownColumnError):
        rows("SELECT id AS k FROM t WHERE k > 1")


def test_alias_wins_over_input_column():
    assert rows("SELECT -id AS id FROM t ORDER BY id LIMIT 2") == [[-5], [-4]]


def test_nulls_group_together_in_first_seen_order():
    assert rows("SELECT g, count(*) FROM t GROUP BY g") == [["a", 2], ["b", 1], [None, 2]]
    assert rows("SELECT g FROM t GROUP BY g ORDER BY g") == [["a"], ["b"], [None]]


def test_group_by_expression_and_having():
    assert rows("SELECT length(g), count(*) FROM t GROUP BY length(g)") == \
        [[1, 3], [None, 2]]
    assert rows("SELECT g, sum(v) FROM t GROUP BY g HAVING sum(v) > 10") == [["a", 15], [None, 30]]
    assert rows("SELECT count(*) FROM t HAVING count(*) > 100") == []


def test_grouping_error():
    with pytest.raises(GroupingError):
        rows("SELECT id, count(*) FROM t GROUP BY g")
    with pytest.raises(GroupingError):
        rows("SELECT id, count(*) FROM t")


def test_group_by_with_empty_input_gives_no_rows():
    assert rows("SELECT x, count(*) FROM e GROUP BY x") == []


def test_nulls_sort_last_in_both_directions():
    assert rows("SELECT v FROM t ORDER BY v") == [[5], [10], [30], [None], [None]]
    assert rows("SELECT v FROM t ORDER BY v DESC") == [[30], [10], [5], [None], [None]]


def test_sort_is_stable_and_multi_key():
    assert rows("SELECT id FROM t ORDER BY g") == [[1], [4], [2], [3], [5]]
    assert rows("SELECT id FROM t ORDER BY g DESC") == [[2], [1], [4], [3], [5]]
    assert rows("SELECT id FROM t ORDER BY g, v DESC") == [[1], [4], [2], [3], [5]]


def test_sort_type_mismatch():
    from microdb.executor import _cmp
    with pytest.raises(TypeMismatchError):
        _cmp(1, "a")


def test_distinct_treats_nulls_as_equal_and_orders_after():
    assert rows("SELECT DISTINCT g FROM t ORDER BY g DESC") == [["b"], ["a"], [None]]
    assert rows("SELECT DISTINCT g AS k FROM t ORDER BY k") == [["a"], ["b"], [None]]


def test_distinct_order_by_only_output_columns():
    with pytest.raises(UnknownColumnError):
        rows("SELECT DISTINCT g FROM t ORDER BY id")
    assert rows("SELECT g FROM t ORDER BY id DESC LIMIT 1") == [[None]]


def test_offset_before_limit():
    assert rows("SELECT id FROM t ORDER BY id LIMIT 2 OFFSET 1") == [[2], [3]]
    assert rows("SELECT id FROM t ORDER BY id OFFSET 4") == [[5]]
    assert rows("SELECT id FROM t LIMIT 0") == []


def test_inner_join_left_major_order():
    assert rows("SELECT l.id, tag FROM l INNER JOIN r ON l.id = r.lid") == \
        [[1, "x"], [1, "y"], [3, "z"]]
    assert rows("SELECT id FROM l JOIN r ON id = lid") == [[1], [1], [3]]


def test_left_join_null_fills():
    assert rows("SELECT l.id, tag FROM l LEFT JOIN r ON l.id = r.lid") == \
        [[1, "x"], [1, "y"], [2, None], [3, "z"]]
    assert q("SELECT * FROM l LEFT JOIN r ON l.id = r.lid").columns == \
        ["id", "name", "lid", "tag"]


def test_join_ambiguity_and_unknown_table():
    tables = make_tables()
    tables["r2"] = Table("r2", [Column("id", "INT")], [[1]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM l JOIN r2 ON l.id = r2.id", tables)
    with pytest.raises(UnknownTableError):
        execute("SELECT z.id FROM l", tables)
    with pytest.raises(UnknownTableError):
        execute("SELECT id FROM nope", tables)
    assert execute("SELECT l.id, r2.id FROM l JOIN r2 ON l.id = r2.id", tables).rows == [[1, 1]]


def test_join_group_and_star_table():
    assert rows("SELECT l.name, count(tag) FROM l LEFT JOIN r ON l.id = r.lid "
                "GROUP BY l.name") == [["one", 2], ["two", 0], ["three", 1]]
    assert q("SELECT r.* FROM l JOIN r ON l.id = r.lid").columns == ["lid", "tag"]


def test_output_column_names():
    res = q("SELECT id AS k, count(*), v  +   1 FROM t GROUP BY id, v")
    assert res.columns == ["k", "count(*)", "v + 1"]


def test_plan_is_inspectable():
    p = plan(parse("SELECT g, count(*) FROM t WHERE v > 1 GROUP BY g HAVING count(*) > 0 "
                   "ORDER BY g LIMIT 1"))
    assert p.names == ["scan", "filter", "group", "aggregate", "having", "project",
                       "sort", "limit"]
    assert len(p) == 8 and p[0].name == "scan"


def test_public_surface():
    assert "execute" in microdb.__all__ and len(microdb.__all__) > 5


# ---- CLI ----
def write_csv(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="")
    return str(path)


def test_cli_count(tmp_path, capsys):
    p = write_csv(tmp_path, "people.csv", "name:TEXT,age:INT\nann,31\nbob,\ncy,45\nd,20\n")
    assert main(["--table", "t=" + p, "SELECT count(*) FROM t WHERE age > 30"]) == 0
    assert capsys.readouterr().out == "count(*)\n2\n"


def test_cli_formatting(tmp_path, capsys):
    p = write_csv(tmp_path, "d.csv",
                  'a:TEXT,b:BOOL,c:FLOAT\n"x,y",TRUE,1.5\n\'\',false,\n"q""r",True,2\n')
    assert main(["--table", "t=" + p, "SELECT a, b, c FROM t"]) == 0
    out = capsys.readouterr().out
    assert out == 'a,b,c\n"x,y",true,1.5\n,false,\n"q""r",true,2.0\n'


def test_cli_null_only_column_renders_empty_line(tmp_path, capsys):
    p = write_csv(tmp_path, "d.csv", "a:INT\n\n1\n")
    assert main(["--table", "t=" + p, "SELECT a FROM t"]) == 0
    assert capsys.readouterr().out == "a\n\n1\n"


def test_cli_usage_errors(tmp_path, capsys):
    p = write_csv(tmp_path, "d.csv", "a:INT\n1\n")
    bad = write_csv(tmp_path, "bad.csv", "a\n1\n")
    assert main([]) == 2
    assert main(["SELECT a FROM t"]) == 2
    assert main(["--table", "t=" + p]) == 2
    assert main(["--table", "t=" + str(tmp_path / "missing.csv"), "SELECT a FROM t"]) == 2
    assert main(["--table", "t=" + bad, "SELECT a FROM t"]) == 2
    assert main(["--table", "nopath", "SELECT a FROM t"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_engine_errors_exit_3(tmp_path, capsys):
    p = write_csv(tmp_path, "d.csv", "a:INT\n1\n")
    assert main(["--table", "t=" + p, "SELECT FROM t"]) == 3
    assert main(["--table", "t=" + p, "SELECT a FROM t WHERE a"]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err != ""


def test_cli_module_invocation(tmp_path):
    p = write_csv(tmp_path, "people.csv", "name:TEXT,age:INT\nann,31\ncy,45\nd,20\n")
    proc = subprocess.run(
        [sys.executable, "-m", "microdb", "--table", "t=" + p,
         "SELECT count(*) FROM t WHERE age > 30"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.replace("\r\n", "\n") == "count(*)\n2\n"
    proc = subprocess.run([sys.executable, "-m", "microdb"], cwd=ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 2 and proc.stdout == ""

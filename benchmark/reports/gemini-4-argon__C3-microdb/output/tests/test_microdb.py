from __future__ import annotations

from collections.abc import Sequence
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
    MicroDBError,
    ParseError,
    Plan,
    Result,
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
    execute_plan,
    is_numeric,
    main,
    negate,
    not_,
    or_,
    parse,
    plan,
    tokenize,
    type_of,
)


def _sample_people() -> Table:
    return Table(
        "people",
        [
            Column("id", "INT"),
            Column("name", "TEXT"),
            Column("age", "INT"),
            Column("score", "FLOAT"),
            Column("active", "BOOL"),
            Column("dept", "TEXT"),
        ],
        [
            [1, "Alice", 35, 90.5, True, "eng"],
            [2, "Bob", 28, 80, False, "eng"],
            [3, "Carol", 42, None, True, "sales"],
            [4, "Dave", None, 70.0, False, "sales"],
            [5, "Eve", 30, 85.0, None, None],
        ],
    )


def test_public_surface_all() -> None:
    assert isinstance(microdb.__all__, list)
    assert len(microdb.__all__) >= 30
    for name in microdb.__all__:
        assert hasattr(microdb, name)


def test_error_hierarchy() -> None:
    subclasses = [
        LexError,
        ParseError,
        SchemaError,
        TypeMismatchError,
        UnknownColumnError,
        AmbiguousColumnError,
        UnknownTableError,
        UnknownFunctionError,
        ArityError,
        AggregateError,
        GroupingError,
    ]
    for cls in subclasses:
        assert issubclass(cls, MicroDBError)
    lex_err = LexError("bad", offset=7)
    parse_err = ParseError("bad", offset=12)
    assert lex_err.offset == 7
    assert parse_err.offset == 12


def test_value_type_of_and_is_numeric() -> None:
    assert type_of(42) == "INT"
    assert type_of(3.14) == "FLOAT"
    assert type_of("hi") == "TEXT"
    assert type_of(True) == "BOOL"
    assert type_of(False) == "BOOL"
    assert type_of(None) == "NULL"

    assert is_numeric(0) is True
    assert is_numeric(-3.5) is True
    assert is_numeric(True) is False
    assert is_numeric(False) is False
    assert is_numeric(None) is False
    assert is_numeric("1") is False


def test_three_valued_logic_truth_tables() -> None:
    u = None
    and_cases = [
        (True, True, True),
        (True, False, False),
        (True, u, u),
        (False, True, False),
        (False, False, False),
        (False, u, False),
        (u, True, u),
        (u, False, False),
        (u, u, u),
    ]
    for a, b, expected in and_cases:
        assert and_(a, b) is expected

    or_cases = [
        (True, True, True),
        (True, False, True),
        (True, u, True),
        (False, True, True),
        (False, False, False),
        (False, u, u),
        (u, True, True),
        (u, False, u),
        (u, u, u),
    ]
    for a, b, expected in or_cases:
        assert or_(a, b) is expected

    assert not_(True) is False
    assert not_(False) is True
    assert not_(u) is u


def test_comparison_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(1, None) is None
    assert compare_eq(None, "a") is None
    assert compare_lt(None, None) is None
    assert compare_lt(1, None) is None
    assert compare_lt(None, True) is None


def test_comparison_valid_and_invalid_types() -> None:
    assert compare_eq(3, 3.0) is True
    assert compare_lt(2, 2.5) is True
    assert compare_lt("abc", "abd") is True
    assert compare_lt(False, True) is True
    assert compare_lt(True, False) is False
    assert compare_eq(True, True) is True

    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt(False, 0)
    with pytest.raises(TypeMismatchError):
        compare_eq("1", 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("a", 1.0)


def test_arithmetic_rules_and_types() -> None:
    assert arith("+", 2, 3) == 5
    assert type_of(arith("+", 2, 3)) == "INT"
    assert arith("*", 2, 3.0) == 6.0
    assert type_of(arith("*", 2, 3.0)) == "FLOAT"
    div_res = arith("/", 7, 2)
    assert div_res == 3.5
    assert type_of(div_res) == "FLOAT"
    assert arith("%", -7, 3) == 2
    assert negate(5) == -5
    assert type_of(negate(5)) == "INT"
    assert negate(2.5) == -2.5
    assert type_of(negate(2.5)) == "FLOAT"
    assert negate(None) is None


def test_arithmetic_null_and_zero_division() -> None:
    assert arith("+", None, 5) is None
    assert arith("-", 5, None) is None
    assert arith("/", 10, 0) is None
    assert arith("/", 10, 0.0) is None
    assert arith("/", 10.0, 0) is None
    assert arith("%", 10, 0) is None


def test_arithmetic_type_mismatch() -> None:
    with pytest.raises(TypeMismatchError):
        arith("+", "a", "b")
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        arith("%", 5.0, 2)
    with pytest.raises(TypeMismatchError):
        negate(True)
    with pytest.raises(TypeMismatchError):
        negate("abc")


def test_schema_validation_rules() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])
    # Case sensitive column names allowed
    t_case = Table("t", [Column("a", "INT"), Column("A", "INT")], [[1, 2]])
    assert t_case.column_index("a") == 0
    assert t_case.column_index("A") == 1
    with pytest.raises(SchemaError):
        t_case.column_index("missing")
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "DECIMAL")], [])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[1, 2]])


def test_schema_cell_type_rules_and_float_widening() -> None:
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.0]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BOOL")], [[1]])
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "FLOAT")], [[True]])

    t_float = Table("t", [Column("f", "FLOAT")], [[3], [None], [4.5]])
    assert t_float.rows[0][0] == 3.0
    assert isinstance(t_float.rows[0][0], float)
    assert t_float.rows[1][0] is None


def test_lexer_tokens_and_comments() -> None:
    sql = "SELECT 1., .5, 1e3, 1.5E-2, 'it''s\nok' -- comment\nFROM t"
    tokens = tokenize(sql)
    values = [t.value for t in tokens]
    assert values == ["SELECT", 1.0, ",", 0.5, ",", 1000.0, ",", 0.015, ",", "it's\nok", "FROM", "t"]


def test_lexer_errors_with_offset() -> None:
    with pytest.raises(LexError) as exc_info:
        tokenize("SELECT a != 1 FROM t")
    assert exc_info.value.offset == 9

    with pytest.raises(LexError) as exc_info2:
        tokenize("SELECT 'unterminated FROM t")
    assert exc_info2.value.offset == 7

    with pytest.raises(LexError) as exc_info3:
        tokenize("SELECT 1.5e FROM t")
    assert exc_info3.value.offset == 7


def test_parser_precedence_and_non_associative_predicate() -> None:
    # NOT binds looser than =
    q = parse("SELECT * FROM t WHERE NOT a = b AND c < d + 1 * 2")
    assert q.where is not None

    with pytest.raises(ParseError):
        parse("SELECT * FROM t WHERE 1 < 2 < 3")
    with pytest.raises(ParseError):
        parse("SELECT * FROM t WHERE a = b = c")
    with pytest.raises(ParseError):
        parse("SELECT order FROM t")


def test_parser_nested_aggregates_and_star_errors() -> None:
    with pytest.raises(ParseError):
        parse("SELECT sum(count(x)) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT max(1 + min(x)) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT sum(*) FROM t")
    with pytest.raises(ParseError):
        parse("SELECT concat(*) FROM t")


def test_scalar_functions_execution() -> None:
    t = _sample_people()
    res = execute(
        "SELECT concat(name, '-', dept), upper(name), lower(name), length(name), abs(-age), coalesce(dept, 'none') FROM people WHERE id = 1",
        {"people": t},
    )
    assert res.rows == [["Alice-eng", "ALICE", "alice", 5, 35, "eng"]]

    res_null = execute(
        "SELECT concat(name, dept), upper(dept), length(dept), abs(age), coalesce(score, age, 99) FROM people WHERE id = 5",
        {"people": t},
    )
    assert res_null.rows == [[None, None, None, 30, 85.0]]


def test_scalar_function_errors() -> None:
    t = _sample_people()
    with pytest.raises(UnknownFunctionError):
        execute("SELECT unknown_fn(age) FROM people", {"people": t})
    with pytest.raises(ArityError):
        execute("SELECT concat('a') FROM people", {"people": t})
    with pytest.raises(ArityError):
        execute("SELECT upper('a', 'b') FROM people", {"people": t})
    with pytest.raises(ArityError):
        execute("SELECT coalesce() FROM people", {"people": t})
    with pytest.raises(TypeMismatchError):
        execute("SELECT upper(age) FROM people", {"people": t})
    with pytest.raises(TypeMismatchError):
        execute("SELECT abs(name) FROM people", {"people": t})
    with pytest.raises(TypeMismatchError):
        execute("SELECT concat(NULL, 123) FROM people", {"people": t})


def test_where_null_and_non_boolean_errors() -> None:
    t = _sample_people()
    # WHERE a = NULL returns nothing
    res = execute("SELECT id FROM people WHERE age = NULL", {"people": t})
    assert res.rows == []

    res_is_null = execute("SELECT id FROM people WHERE age IS NULL", {"people": t})
    assert res_is_null.rows == [[4]]

    res_is_not_null = execute("SELECT id FROM people WHERE dept IS NOT NULL ORDER BY id", {"people": t})
    assert res_is_not_null.rows == [[1], [2], [3], [4]]

    with pytest.raises(TypeMismatchError):
        execute("SELECT id FROM people WHERE 1", {"people": t})
    with pytest.raises(AggregateError):
        execute("SELECT id FROM people WHERE count(*) > 0", {"people": t})


def test_aggregates_over_empty_table_and_null_group() -> None:
    empty = Table("empty", [Column("x", "INT"), Column("y", "FLOAT")], [])
    res_count = execute("SELECT count(*) FROM empty", {"empty": empty})
    assert res_count.columns == ["count(*)"]
    assert res_count.rows == [[0]]

    res_all = execute(
        "SELECT count(*), count(x), sum(x), avg(x), min(x), max(x) FROM empty",
        {"empty": empty},
    )
    assert res_all.rows == [[0, 0, None, None, None, None]]

    all_null = Table("n", [Column("g", "INT"), Column("v", "INT")], [[1, None], [1, None]])
    res_grp = execute(
        "SELECT g, count(*), count(v), sum(v), avg(v), min(v), max(v) FROM n GROUP BY g",
        {"n": all_null},
    )
    assert res_grp.rows == [[1, 2, 0, None, None, None, None]]


def test_aggregates_return_types_and_errors() -> None:
    t = Table(
        "nums",
        [Column("i", "INT"), Column("f", "FLOAT"), Column("s", "TEXT")],
        [[1, 1.5, "b"], [2, 2.5, "a"], [None, None, None]],
    )
    res = execute("SELECT sum(i), sum(f), avg(i), min(s), max(s) FROM nums", {"nums": t})
    assert res.rows == [[3, 4.0, 1.5, "a", "b"]]
    assert type_of(res.rows[0][0]) == "INT"
    assert type_of(res.rows[0][1]) == "FLOAT"
    assert type_of(res.rows[0][2]) == "FLOAT"

    with pytest.raises(TypeMismatchError):
        execute("SELECT sum(s) FROM nums", {"nums": t})
    with pytest.raises(TypeMismatchError):
        execute("SELECT avg(s) FROM nums", {"nums": t})


def test_aggregate_mixed_types_via_coalesce() -> None:
    t = Table(
        "mix",
        [Column("i", "INT"), Column("s", "TEXT")],
        [[1, "a"], [None, "b"]],
    )
    with pytest.raises(TypeMismatchError):
        execute("SELECT min(coalesce(i, s)) FROM mix", {"mix": t})


def test_group_by_nulls_and_first_seen_order() -> None:
    t = Table(
        "items",
        [Column("cat", "TEXT"), Column("val", "INT")],
        [
            ["b", 10],
            [None, 5],
            ["a", 20],
            [None, 15],
            ["b", 30],
        ],
    )
    res = execute("SELECT cat, count(*), sum(val) FROM items GROUP BY cat", {"items": t})
    assert res.rows == [
        ["b", 2, 40],
        [None, 2, 20],
        ["a", 1, 20],
    ]


def test_group_by_expression_and_having() -> None:
    t = _sample_people()
    res = execute(
        "SELECT length(name), count(*) FROM people GROUP BY length(name) HAVING count(*) >= 2",
        {"people": t},
    )
    assert res.rows == [[5, 2], [3, 2]]


def test_grouping_error_on_ungrouped_column() -> None:
    t = _sample_people()
    with pytest.raises(GroupingError):
        execute("SELECT dept, name, count(*) FROM people GROUP BY dept", {"people": t})
    with pytest.raises(GroupingError):
        execute("SELECT name, count(*) FROM people", {"people": t})
    with pytest.raises(GroupingError):
        execute("SELECT dept FROM people GROUP BY dept HAVING age > 20", {"people": t})


def test_order_by_nulls_last_asc_and_desc() -> None:
    t = Table("t", [Column("x", "INT")], [[2], [None], [1], [3], [None]])
    asc_res = execute("SELECT x FROM t ORDER BY x ASC", {"t": t})
    assert asc_res.rows == [[1], [2], [3], [None], [None]]

    desc_res = execute("SELECT x FROM t ORDER BY x DESC", {"t": t})
    assert desc_res.rows == [[3], [2], [1], [None], [None]]


def test_order_by_stability() -> None:
    t = Table(
        "t",
        [Column("k", "INT"), Column("tag", "TEXT")],
        [[2, "first_2"], [1, "first_1"], [2, "second_2"], [1, "second_1"], [2, "third_2"]],
    )
    res = execute("SELECT k, tag FROM t ORDER BY k ASC", {"t": t})
    assert res.rows == [
        [1, "first_1"],
        [1, "second_1"],
        [2, "first_2"],
        [2, "second_2"],
        [2, "third_2"],
    ]


def test_order_by_incompatible_types_raises() -> None:
    t = Table("t", [Column("i", "INT"), Column("s", "TEXT")], [[1, "a"], [None, "b"]])
    with pytest.raises(TypeMismatchError):
        execute("SELECT i, s FROM t ORDER BY coalesce(i, s)", {"t": t})


def test_alias_visibility_in_order_by_and_where() -> None:
    t = _sample_people()
    with pytest.raises(UnknownColumnError):
        execute("SELECT age AS years FROM people WHERE years > 30", {"people": t})

    res = execute(
        "SELECT name, age AS years FROM people WHERE age IS NOT NULL ORDER BY years DESC LIMIT 2",
        {"people": t},
    )
    assert res.columns == ["name", "years"]
    assert res.rows == [["Carol", 42], ["Alice", 35]]


def test_alias_wins_over_input_column_in_order_by() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 100], [2, 50]])
    # Alias 'a' refers to -a, which reverses the order compared to input column 'a'
    res = execute("SELECT -a AS a, b FROM t ORDER BY a ASC", {"t": t})
    assert res.rows == [[-2, 50], [-1, 100]]


def test_distinct_and_order_by_interaction() -> None:
    t = _sample_people()
    res = execute("SELECT DISTINCT dept FROM people ORDER BY dept ASC", {"people": t})
    assert res.rows == [["eng"], ["sales"], [None]]

    # With DISTINCT, ORDER BY cannot reference a non-projected input column
    with pytest.raises(UnknownColumnError):
        execute("SELECT DISTINCT dept FROM people ORDER BY age ASC", {"people": t})

    # Without DISTINCT, ORDER BY can reference a non-projected input column
    res_no_distinct = execute(
        "SELECT name FROM people WHERE age IS NOT NULL ORDER BY age ASC",
        {"people": t},
    )
    assert res_no_distinct.rows == [["Bob"], ["Eve"], ["Alice"], ["Carol"]]


def test_inner_and_left_join_semantics() -> None:
    users = Table(
        "u",
        [Column("id", "INT"), Column("name", "TEXT")],
        [[1, "Alice"], [2, "Bob"], [3, "Carol"]],
    )
    orders = Table(
        "o",
        [Column("uid", "INT"), Column("amount", "INT")],
        [[1, 100], [3, 50], [1, 200]],
    )
    inner_res = execute(
        "SELECT u.name, o.amount FROM u INNER JOIN o ON u.id = o.uid",
        {"u": users, "o": orders},
    )
    assert inner_res.columns == ["name", "amount"]
    assert inner_res.rows == [["Alice", 100], ["Alice", 200], ["Carol", 50]]

    left_res = execute(
        "SELECT u.name, o.amount FROM u LEFT JOIN o ON u.id = o.uid",
        {"u": users, "o": orders},
    )
    assert left_res.rows == [["Alice", 100], ["Alice", 200], ["Bob", None], ["Carol", 50]]


def test_join_column_errors_and_star_expansion() -> None:
    t1 = Table("t1", [Column("id", "INT"), Column("x", "INT")], [[1, 10]])
    t2 = Table("t2", [Column("id", "INT"), Column("y", "INT")], [[1, 20]])

    with pytest.raises(AmbiguousColumnError):
        execute("SELECT id FROM t1 JOIN t2 ON t1.id = t2.id", {"t1": t1, "t2": t2})
    with pytest.raises(UnknownTableError):
        execute("SELECT t3.id FROM t1 JOIN t2 ON t1.id = t2.id", {"t1": t1, "t2": t2})

    res_star = execute("SELECT t1.*, t2.y FROM t1 JOIN t2 ON t1.id = t2.id", {"t1": t1, "t2": t2})
    assert res_star.columns == ["id", "x", "y"]
    assert res_star.rows == [[1, 10, 20]]


def test_offset_and_limit_slicing() -> None:
    t = Table("t", [Column("x", "INT")], [[10], [20], [30], [40], [50]])
    res = execute("SELECT x FROM t ORDER BY x ASC LIMIT 2 OFFSET 1", {"t": t})
    assert res.rows == [[20], [30]]


def test_output_column_naming_rules() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 2]])
    res = execute("SELECT a, t.b, a   +   b, count(*) AS total FROM t GROUP BY a, b", {"t": t})
    assert res.columns == ["a", "b", "a + b", "total"]


def test_planner_pipeline_inspection() -> None:
    q = parse(
        "SELECT DISTINCT dept, count(*) FROM people WHERE age > 20 GROUP BY dept HAVING count(*) > 1 ORDER BY dept LIMIT 5 OFFSET 1"
    )
    p = plan(q)
    assert isinstance(p, Plan)
    assert isinstance(p, Sequence)
    stage_names = [s.name for s in p]
    assert stage_names == [
        "FROM",
        "WHERE",
        "GROUP_BY",
        "AGGREGATE",
        "HAVING",
        "SELECT",
        "DISTINCT",
        "ORDER_BY",
        "SLICE",
    ]
    res = execute_plan(p, {"people": _sample_people()})
    assert isinstance(res, Result)


def test_cli_success_and_acceptance_query(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_file = tmp_path / "people.csv"
    csv_file.write_text(
        "id:INT,name:TEXT,age:INT,active:BOOL\n"
        "1,Alice,35,true\n"
        "2,Bob,28,FALSE\n"
        "3,Carol,42,True\n"
        "4,Dave,,\n",
        encoding="utf-8",
    )
    code = main(["--table", f"t={csv_file}", "SELECT count(*) FROM t WHERE age > 30"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out == "count(*)\n2\n"


def test_cli_csv_formatting_and_quoting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_file = tmp_path / "data.csv"
    csv_file.write_text(
        "id:INT,txt:TEXT,flag:BOOL,num:FLOAT\n"
        '1,"a,b",true,1.5\n'
        '2,"say ""hi""",false,2\n'
        "3,'',,\n",
        encoding="utf-8",
    )
    code = main(["--table", f"d={csv_file}", "SELECT txt, flag, num FROM d ORDER BY id"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == 'txt,flag,num\n"a,b",true,1.5\n"say ""hi""",false,2.0\n,,\n'


def test_cli_single_null_column_renders_empty_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_file = tmp_path / "single.csv"
    csv_file.write_text("x:INT\n\n", encoding="utf-8")
    code = main(["--table", f"s={csv_file}", "SELECT x FROM s"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "x\n\n"


def test_cli_usage_errors_exit_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Missing --table
    assert main(["SELECT 1 FROM t"]) == 2
    assert capsys.readouterr().out == ""

    # Unreadable file
    assert main(["--table", f"t={tmp_path / 'missing.csv'}", "SELECT * FROM t"]) == 2
    assert capsys.readouterr().out == ""

    # Malformed header
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("id,name\n1,a\n", encoding="utf-8")
    assert main(["--table", f"t={bad_csv}", "SELECT * FROM t"]) == 2
    assert capsys.readouterr().out == ""


def test_cli_microdb_errors_exit_code_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_file = tmp_path / "t.csv"
    csv_file.write_text("id:INT\n1\n", encoding="utf-8")
    code = main(["--table", f"t={csv_file}", "SELECT missing_col FROM t"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert captured.err != ""


def test_unknown_table_in_from_and_join() -> None:
    t = _sample_people()
    with pytest.raises(UnknownTableError):
        execute("SELECT * FROM missing", {"people": t})
    with pytest.raises(UnknownTableError):
        execute("SELECT * FROM people JOIN missing ON people.id = missing.id", {"people": t})


def test_unknown_column_in_select_and_where() -> None:
    t = _sample_people()
    with pytest.raises(UnknownColumnError):
        execute("SELECT nope FROM people", {"people": t})
    with pytest.raises(UnknownColumnError):
        execute("SELECT people.nope FROM people", {"people": t})
    with pytest.raises(UnknownColumnError):
        execute("SELECT id FROM people WHERE nope = 1", {"people": t})


def test_compare_operators_all_six() -> None:
    t = Table("t", [Column("x", "INT")], [[1], [2], [3], [None]])
    assert execute("SELECT x FROM t WHERE x = 2", {"t": t}).rows == [[2]]
    assert execute("SELECT x FROM t WHERE x <> 2 ORDER BY x", {"t": t}).rows == [[1], [3]]
    assert execute("SELECT x FROM t WHERE x < 2", {"t": t}).rows == [[1]]
    assert execute("SELECT x FROM t WHERE x <= 2 ORDER BY x", {"t": t}).rows == [[1], [2]]
    assert execute("SELECT x FROM t WHERE x > 2", {"t": t}).rows == [[3]]
    assert execute("SELECT x FROM t WHERE x >= 2 ORDER BY x", {"t": t}).rows == [[2], [3]]


def test_three_valued_logic_in_where_and_having() -> None:
    t = _sample_people()
    # score is NULL for id=3, active is True for id=3 -> NULL OR True is True
    res = execute("SELECT id FROM people WHERE score > 100 OR active ORDER BY id", {"people": t})
    assert res.rows == [[1], [3]]

    # NULL AND False is False, NULL AND True is UNKNOWN (dropped)
    res2 = execute("SELECT id FROM people WHERE score > 100 AND active", {"people": t})
    assert res2.rows == []


def test_having_without_group_by() -> None:
    t = _sample_people()
    res = execute("SELECT count(*) FROM people HAVING count(*) > 3", {"people": t})
    assert res.rows == [[5]]

    res_empty = execute("SELECT count(*) FROM people HAVING count(*) > 10", {"people": t})
    assert res_empty.rows == []


def test_having_non_boolean_raises_type_mismatch() -> None:
    t = _sample_people()
    with pytest.raises(TypeMismatchError):
        execute("SELECT dept, count(*) FROM people GROUP BY dept HAVING count(*)", {"people": t})


def test_order_by_multiple_keys_mixed_directions() -> None:
    t = Table(
        "t",
        [Column("a", "TEXT"), Column("b", "INT")],
        [["x", 1], ["x", None], ["x", 3], ["a", 2], [None, 5]],
    )
    res = execute("SELECT a, b FROM t ORDER BY a ASC, b DESC", {"t": t})
    assert res.rows == [["a", 2], ["x", 3], ["x", 1], ["x", None], [None, 5]]


def test_order_by_aggregate_expression() -> None:
    t = _sample_people()
    res = execute(
        "SELECT dept FROM people WHERE dept IS NOT NULL GROUP BY dept ORDER BY sum(age) DESC",
        {"people": t},
    )
    assert res.rows == [["eng"], ["sales"]]


def test_order_by_alias_in_grouped_query() -> None:
    t = _sample_people()
    res = execute(
        "SELECT dept, count(*) AS cnt FROM people GROUP BY dept ORDER BY cnt DESC, dept ASC",
        {"people": t},
    )
    assert res.rows == [["eng", 2], ["sales", 2], [None, 1]]


def test_distinct_preserves_types_bool_vs_int() -> None:
    t = Table("t", [Column("b", "BOOL"), Column("i", "INT")], [[True, None], [None, 1]])
    res = execute("SELECT DISTINCT coalesce(b, i) FROM t", {"t": t})
    assert len(res.rows) == 2
    assert res.rows[0][0] is True
    assert res.rows[1][0] == 1


def test_group_by_preserves_types_bool_vs_int() -> None:
    t = Table("t", [Column("b", "BOOL"), Column("i", "INT")], [[True, None], [None, 1]])
    res = execute("SELECT coalesce(b, i), count(*) FROM t GROUP BY coalesce(b, i)", {"t": t})
    assert len(res.rows) == 2


def test_join_with_where_and_group_by() -> None:
    depts = Table("d", [Column("name", "TEXT"), Column("floor", "INT")], [["eng", 2], ["hr", 1]])
    people = _sample_people()
    res = execute(
        "SELECT d.name, count(people.id) FROM d LEFT JOIN people ON d.name = people.dept GROUP BY d.name ORDER BY d.name",
        {"d": depts, "people": people},
    )
    assert res.rows == [["eng", 2], ["hr", 0]]


def test_cli_multiple_tables_join(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    u_csv = tmp_path / "u.csv"
    o_csv = tmp_path / "o.csv"
    u_csv.write_text("id:INT,name:TEXT\n1,Alice\n2,Bob\n", encoding="utf-8")
    o_csv.write_text("uid:INT,item:TEXT\n1,Book\n", encoding="utf-8")
    code = main(
        [
            "--table",
            f"u={u_csv}",
            f"--table=o={o_csv}",
            "SELECT u.name, o.item FROM u LEFT JOIN o ON u.id = o.uid ORDER BY u.id",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == "name,item\nAlice,Book\nBob,\n"


def test_cli_schema_error_in_csv_data_exit_code_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_file = tmp_path / "invalid_int.csv"
    csv_file.write_text("id:INT\nnot_an_int\n", encoding="utf-8")
    code = main(["--table", f"t={csv_file}", "SELECT * FROM t"])
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    assert captured.err != ""


def test_parse_error_offsets_and_trailing_tokens() -> None:
    with pytest.raises(ParseError) as exc1:
        parse("")
    assert exc1.value.offset == 0

    with pytest.raises(ParseError) as exc2:
        parse("SELECT a FROM t EXTRA")
    assert exc2.value.offset == 16


def test_aggregate_in_join_on_and_group_by_raises() -> None:
    t = _sample_people()
    with pytest.raises(AggregateError):
        execute("SELECT a.id FROM people JOIN people ON count(*) = 1", {"people": t})
    with pytest.raises(AggregateError):
        execute("SELECT count(*) FROM people GROUP BY count(*)", {"people": t})


def test_parenthesized_expressions_and_unary_minus() -> None:
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[2, 3]])
    res = execute("SELECT -(a + b) * 2, (a) FROM t", {"t": t})
    assert res.columns == ["-(a + b) * 2", "(a)"]
    assert res.rows == [[-10, 2]]


"""Acceptance tests for the microdb query engine."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from microdb import (
    Column,
    Result,
    Table,
    and_,
    arith,
    compare_eq,
    compare_lt,
    execute,
    is_numeric,
    negate,
    not_,
    or_,
    type_of,
)
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
    UnknownTableError,
)
from microdb.lexer import tokenize
from microdb.parser import parse
from microdb.planner import plan

ROOT = Path(__file__).resolve().parents[1]


def table(name: str, cols: list[tuple[str, str]], rows: list[list[object]]) -> Table:
    return Table(name, [Column(n, t) for n, t in cols], rows)


def run(sql: str, **tables: Table) -> Result:
    return execute(sql, tables)


def test_and_truth_table() -> None:
    pairs = (True, False, None)
    expected = {
        (True, True): True,
        (True, False): False,
        (True, None): None,
        (False, True): False,
        (False, False): False,
        (False, None): False,
        (None, True): None,
        (None, False): False,
        (None, None): None,
    }
    for left in pairs:
        for right in pairs:
            assert and_(left, right) is expected[(left, right)]


def test_or_truth_table() -> None:
    expected = {
        (True, True): True,
        (True, False): True,
        (True, None): True,
        (False, True): True,
        (False, False): False,
        (False, None): None,
        (None, True): True,
        (None, False): None,
        (None, None): None,
    }
    for left in (True, False, None):
        for right in (True, False, None):
            assert or_(left, right) is expected[(left, right)]


def test_not_truth_table() -> None:
    assert not_(True) is False
    assert not_(False) is True
    assert not_(None) is None


def test_null_equals_null_is_unknown() -> None:
    assert compare_eq(None, None) is None
    assert compare_eq(1, None) is None
    assert compare_lt(None, "a") is None
    result = run("SELECT a FROM t WHERE a = NULL", t=table("t", [("a", "INT")], [[1], [None]]))
    assert result.rows == []


def test_division_by_zero_is_null() -> None:
    assert arith("/", 7, 0) is None
    assert arith("/", 1.5, 0.0) is None
    assert arith("%", -7, 0) is None
    result = run("SELECT 1 / 0, 4 % 0 FROM t", t=table("t", [("a", "INT")], [[1]]))
    assert result.rows == [[None, None]]


def test_sum_of_empty_group_is_null() -> None:
    empty = table("t", [("a", "INT")], [])
    assert run("SELECT sum(a) FROM t", t=empty).rows == [[None]]
    filtered = table("t", [("a", "INT")], [[1]])
    assert run("SELECT sum(a) FROM t WHERE a < 0", t=filtered).rows == [[None]]


def test_count_star_empty_table_one_row() -> None:
    result = run("SELECT count(*) FROM t", t=table("t", [("a", "INT")], []))
    assert result.columns == ["count(*)"]
    assert result.rows == [[0]]


def test_nulls_group_together() -> None:
    src = table("t", [("k", "INT")], [[None], [1], [None]])
    result = run("SELECT k, count(*) FROM t GROUP BY k", t=src)
    assert result.rows == [[None, 2], [1, 1]]


def test_nulls_sort_last_under_desc() -> None:
    src = table("t", [("n", "INT")], [[1], [None], [3]])
    result = run("SELECT n FROM t ORDER BY n DESC", t=src)
    assert result.rows == [[3], [1], [None]]
    asc = run("SELECT n FROM t ORDER BY n ASC", t=src)
    assert asc.rows == [[1], [3], [None]]


def test_sort_is_stable() -> None:
    src = table("t", [("k", "INT"), ("v", "TEXT")], [[1, "b"], [1, "a"], [2, "c"]])
    result = run("SELECT v FROM t ORDER BY k ASC", t=src)
    assert result.rows == [["b"], ["a"], ["c"]]


def test_left_join_null_fill() -> None:
    left = table("a", [("id", "INT"), ("name", "TEXT")], [[1, "x"], [2, "y"]])
    right = table("b", [("id", "INT"), ("n", "INT")], [[1, 9]])
    result = run("SELECT a.name, b.n FROM a LEFT JOIN b ON a.id = b.id", a=left, b=right)
    assert result.columns == ["name", "n"]
    assert result.rows == [["x", 9], ["y", None]]


def test_alias_visible_in_order_by_not_where() -> None:
    src = table("t", [("a", "INT")], [[1], [2], [3]])
    ordered = run("SELECT a + 1 AS a FROM t ORDER BY a DESC", t=src)
    assert ordered.rows == [[4], [3], [2]]
    with pytest.raises(UnknownColumnError):
        run("SELECT a AS b FROM t WHERE b > 1", t=src)


def test_cli_exit_codes(tmp_path: Path) -> None:
    csv = tmp_path / "t.csv"
    csv.write_text("age:INT\n40\n20\n31\n", encoding="utf-8")
    ok = _cli(tmp_path, "--table", f"t={csv}", "SELECT count(*) FROM t WHERE age > 30")
    assert ok.returncode == 0 and ok.stdout == b"count(*)\n2\n" and ok.stderr == b""
    usage = _cli(tmp_path, "SELECT 1")
    assert usage.returncode == 2 and usage.stdout == b""
    missing = _cli(tmp_path, "--table", "t=missing.csv", "SELECT 1")
    assert missing.returncode == 2 and missing.stdout == b""
    bad = _cli(tmp_path, "--table", f"t={csv}", "SELECT")
    assert bad.returncode == 3 and bad.stdout == b"" and bad.stderr


def test_type_of_and_numeric() -> None:
    assert type_of(1) == "INT" and type_of(1.0) == "FLOAT"
    assert type_of("a") == "TEXT" and type_of(True) == "BOOL" and type_of(None) == "NULL"
    assert is_numeric(1) and is_numeric(1.0)
    assert not is_numeric(True) and not is_numeric(False) and not is_numeric(None)


def test_bool_is_not_int() -> None:
    with pytest.raises(TypeMismatchError):
        arith("+", True, 1)
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(SchemaError):
        table("t", [("n", "INT")], [[True]])


def test_arithmetic_types_and_signs() -> None:
    assert arith("+", 1, 2) == 3 and type(arith("+", 1, 2)) is int
    assert arith("+", 1, 2.0) == 3.0 and type(arith("+", 1, 2.0)) is float
    assert arith("/", 7, 2) == 3.5 and type(arith("/", 7, 2)) is float
    assert arith("%", -7, 3) == 2
    assert negate(None) is None and negate(3) == -3 and type(negate(1.5)) is float


def test_schema_rules() -> None:
    with pytest.raises(SchemaError):
        Table("t", [], [])
    with pytest.raises(SchemaError):
        table("t", [("a", "INT"), ("a", "INT")], [])
    with pytest.raises(SchemaError):
        table("t", [("a", "NOPE")], [])
    with pytest.raises(SchemaError):
        table("t", [("a", "INT")], [[1, 2]])
    with pytest.raises(SchemaError):
        table("t", [("a", "INT")], [[3.0]])
    widened = table("t", [("a", "FLOAT")], [[3]])
    assert widened.rows == [[3.0]] and type(widened.rows[0][0]) is float
    assert table("t", [("a", "INT"), ("A", "TEXT")], [[1, "x"]]).column_index("A") == 1


def test_lexer_numbers_strings_comments() -> None:
    kinds = [(tok.kind, tok.value) for tok in tokenize("SELECT 1. .5 1e3 'it''s' -- c\nFROM t")]
    assert ("FLOAT", 1.0) in kinds and ("FLOAT", 0.5) in kinds and ("FLOAT", 1000.0) in kinds
    assert ("TEXT", "it's") in kinds
    assert "c" not in [tok.value for tok in tokenize("SELECT 1 -- c")]


def test_lex_error_offset() -> None:
    with pytest.raises(LexError) as caught:
        tokenize("SELECT @")
    assert caught.value.offset == 7


def test_parse_error_offset_and_chain() -> None:
    with pytest.raises(ParseError) as chained:
        parse("SELECT 1 < 2 < 3 FROM t")
    assert chained.value.offset == 13
    with pytest.raises(ParseError) as nested:
        parse("SELECT sum(count(a)) FROM t")
    assert nested.value.offset >= 0


def test_where_keeps_only_true() -> None:
    src = table("t", [("a", "INT")], [[1], [2], [None]])
    assert run("SELECT a FROM t WHERE a > 1", t=src).rows == [[2]]
    assert run("SELECT a FROM t WHERE a > 0 AND NULL", t=src).rows == []
    assert run("SELECT a FROM t WHERE a = 1 OR NULL", t=src).rows == [[1]]
    with pytest.raises(TypeMismatchError):
        run("SELECT a FROM t WHERE 1", t=src)


def test_aggregate_forbidden_in_where() -> None:
    src = table("t", [("a", "INT")], [[1]])
    with pytest.raises(AggregateError):
        run("SELECT a FROM t WHERE count(a) > 0", t=src)


def test_count_expr_ignores_null() -> None:
    src = table("t", [("a", "INT")], [[None], [1], [None]])
    assert run("SELECT count(a), count(*) FROM t", t=src).rows == [[1, 3]]


def test_avg_always_float_and_sum_type() -> None:
    ints = table("t", [("a", "INT")], [[1], [2]])
    assert run("SELECT avg(a), sum(a) FROM t", t=ints).rows == [[1.5, 3]]
    floats = table("t", [("a", "FLOAT")], [[1], [2]])
    summed = run("SELECT sum(a) FROM t", t=floats).rows[0][0]
    assert summed == 3.0 and type(summed) is float


def test_min_max_preserve_type() -> None:
    src = table("t", [("a", "INT"), ("s", "TEXT")], [[3, "b"], [1, "a"]])
    result = run("SELECT min(a), max(s) FROM t", t=src)
    assert result.rows == [[1, "b"]]
    assert type(result.rows[0][0]) is int
    mixed = table("u", [("n", "INT"), ("s", "TEXT")], [[1, None], [None, "a"]])
    with pytest.raises(TypeMismatchError):
        run("SELECT min(coalesce(n, s)) FROM u", u=mixed)


def test_scalar_functions_and_null() -> None:
    src = table("t", [("a", "INT"), ("s", "TEXT")], [[-2, "Ab"]])
    result = run("SELECT abs(a), upper(s), lower(s), length(s), coalesce(NULL, a) FROM t", t=src)
    assert result.rows == [[2, "AB", "ab", 2, -2]]
    assert run("SELECT concat(s, NULL) FROM t", t=src).rows == [[None]]
    assert run("SELECT upper(NULL) FROM t", t=src).rows == [[None]]


def test_arity_and_unknown_function() -> None:
    src = table("t", [("a", "INT")], [[1]])
    with pytest.raises(ArityError) as arity:
        run("SELECT abs(a, a) FROM t", t=src)
    assert arity.value.name == "abs" and arity.value.expected == 1 and arity.value.actual == 2
    with pytest.raises(UnknownFunctionError):
        run("SELECT foo(a) FROM t", t=src)
    with pytest.raises(ArityError):
        run("SELECT concat(s) FROM t", t=table("t", [("s", "TEXT")], [["a"]]))


def test_grouping_error_and_expression_group() -> None:
    src = table("t", [("name", "TEXT"), ("a", "INT")], [["ab", 1], ["a", 1], ["ab", 2]])
    with pytest.raises(GroupingError):
        run("SELECT a FROM t GROUP BY name", t=src)
    grouped = run("SELECT length(name), count(*) FROM t GROUP BY length(name)", t=src)
    assert grouped.rows[0] == [2, 2]
    assert run("SELECT t.a FROM t GROUP BY a", t=src).rows == [[1], [2]]


def test_group_order_is_first_seen() -> None:
    src = table("t", [("k", "TEXT")], [["b"], ["a"], ["b"]])
    assert run("SELECT k FROM t GROUP BY k", t=src).rows == [["b"], ["a"]]


def test_empty_group_by_yields_no_rows() -> None:
    result = run("SELECT count(*) FROM t GROUP BY a", t=table("t", [("a", "INT")], []))
    assert result.rows == []


def test_having_filters_groups() -> None:
    src = table("t", [("k", "INT")], [[1], [1], [2]])
    result = run("SELECT k FROM t GROUP BY k HAVING count(*) > 1", t=src)
    assert result.rows == [[1]]
    assert run("SELECT k FROM t GROUP BY k HAVING count(*) > 10", t=src).rows == []


def test_inner_join_and_ambiguity() -> None:
    left = table("a", [("id", "INT"), ("name", "TEXT")], [[1, "x"], [2, "y"]])
    right = table("b", [("id", "INT")], [[2]])
    assert run("SELECT name FROM a INNER JOIN b ON a.id = b.id", a=left, b=right).rows == [["y"]]
    with pytest.raises(AmbiguousColumnError):
        run("SELECT id FROM a INNER JOIN b ON a.id = b.id", a=left, b=right)
    assert run("SELECT b.id FROM a INNER JOIN b ON a.id = b.id", a=left, b=right).rows == [[2]]


def test_unknown_table_and_column() -> None:
    src = table("t", [("a", "INT")], [[1]])
    with pytest.raises(UnknownColumnError):
        run("SELECT missing FROM t", t=src)
    with pytest.raises(UnknownTableError):
        run("SELECT z.a FROM t", t=src)
    with pytest.raises(UnknownTableError):
        run("SELECT a FROM missing", t=src)


def test_not_binds_looser_than_compare() -> None:
    src = table("t", [("a", "INT")], [[1], [2]])
    result = run("SELECT NOT a = 1 FROM t", t=src)
    assert result.rows == [[False], [True]]
    assert run("SELECT a FROM t WHERE NOT a IS NULL", t=src).rows == [[1], [2]]


def test_is_null_and_is_not_null() -> None:
    src = table("t", [("a", "INT")], [[1], [None]])
    assert run("SELECT a FROM t WHERE a IS NULL", t=src).rows == [[None]]
    assert run("SELECT a FROM t WHERE a IS NOT NULL", t=src).rows == [[1]]


def test_distinct_treats_nulls_as_equal() -> None:
    src = table("t", [("a", "INT")], [[1], [1], [None], [None], [2]])
    assert run("SELECT DISTINCT a FROM t", t=src).rows == [[1], [None], [2]]


def test_distinct_order_by_output_only() -> None:
    src = table("t", [("a", "INT"), ("b", "INT")], [[1, 9], [1, 8]])
    with pytest.raises(UnknownColumnError):
        run("SELECT DISTINCT a FROM t ORDER BY b", t=src)
    ordered = run("SELECT DISTINCT a FROM t ORDER BY a DESC", t=src)
    assert ordered.rows == [[1]]


def test_limit_after_offset() -> None:
    src = table("t", [("a", "INT")], [[1], [2], [3], [4]])
    result = run("SELECT a FROM t ORDER BY a LIMIT 2 OFFSET 1", t=src)
    assert result.rows == [[2], [3]]
    assert run("SELECT a FROM t ORDER BY a OFFSET 10", t=src).rows == []


def test_star_and_qualified_star() -> None:
    src = table("t", [("a", "INT"), ("b", "TEXT")], [[1, "x"]])
    assert run("SELECT * FROM t", t=src).rows == [[1, "x"]]
    other = table("u", [("id", "INT")], [[7]])
    joined = run("SELECT u.* FROM t INNER JOIN u ON t.a > 0", t=src, u=other)
    assert joined.columns == ["id"] and joined.rows == [[7]]


def test_case_sensitive_identifiers() -> None:
    src = table("t", [("A", "INT"), ("a", "INT")], [[1, 2]])
    assert run("SELECT A, a FROM t", t=src).rows == [[1, 2]]
    assert run("select a from t", t=src).rows == [[2]]


def test_keywords_are_case_insensitive() -> None:
    src = table("t", [("a", "INT")], [[1]])
    assert run("SeLeCt a FrOm t WhErE a = 1", t=src).rows == [[1]]


def test_string_literal_newline_and_escape() -> None:
    src = table("t", [("a", "INT")], [[1]])
    result = run("SELECT 'it''s\nline' FROM t", t=src)
    assert result.rows == [["it's\nline"]]


def test_sort_type_mismatch() -> None:
    src = table("t", [("n", "INT"), ("s", "TEXT")], [[1, None], [None, "b"]])
    with pytest.raises(TypeMismatchError):
        run("SELECT coalesce(n, s) AS v FROM t ORDER BY v", t=src)


def test_bool_ordering_and_filter() -> None:
    src = table("t", [("f", "BOOL")], [[False], [True], [None], [False]])
    assert run("SELECT f FROM t ORDER BY f DESC", t=src).rows == [[True], [False], [False], [None]]
    assert run("SELECT f FROM t WHERE f", t=src).rows == [[True]]


def test_text_comparison() -> None:
    src = table("t", [("s", "TEXT")], [["b"], ["a"], [None]])
    assert run("SELECT s FROM t WHERE s < 'b' ORDER BY s", t=src).rows == [["a"]]


def test_plan_is_a_sequence_of_stages() -> None:
    stages = list(plan(parse("SELECT DISTINCT a FROM t WHERE a > 1 ORDER BY a LIMIT 1 OFFSET 2")))
    names = [type(stage).__name__ for stage in stages]
    assert names == ["Scan", "Where", "Project", "Distinct", "OrderBy", "Offset", "Limit"]
    grouped = list(plan(parse("SELECT count(*) FROM t")))
    assert [type(stage).__name__ for stage in grouped] == ["Scan", "GroupBy", "Aggregate", "Project"]


def test_multi_key_sort_desc_keeps_nulls_last() -> None:
    src = table("t", [("k", "INT"), ("v", "INT")], [[1, 2], [1, None], [1, 1], [None, 5]])
    result = run("SELECT v FROM t ORDER BY k ASC, v DESC", t=src)
    assert result.rows == [[2], [1], [None], [5]]


def test_left_join_unknown_predicate_fills_null() -> None:
    left = table("a", [("id", "INT")], [[1]])
    right = table("b", [("id", "INT"), ("v", "INT")], [[1, 9]])
    result = run("SELECT b.v FROM a LEFT JOIN b ON a.id = NULL", a=left, b=right)
    assert result.rows == [[None]]


def test_concat_requires_text() -> None:
    src = table("t", [("a", "INT")], [[1]])
    with pytest.raises(TypeMismatchError):
        run("SELECT concat(a, 'x') FROM t", t=src)


def test_modulo_rejects_float() -> None:
    with pytest.raises(TypeMismatchError):
        arith("%", 1.0, 2)
    with pytest.raises(TypeMismatchError):
        run("SELECT 1.0 % 2 FROM t", t=table("t", [("a", "INT")], [[1]]))


def test_no_string_concatenation() -> None:
    with pytest.raises(TypeMismatchError):
        run("SELECT s + s FROM t", t=table("t", [("s", "TEXT")], [["a"]]))


def test_parentheses_and_precedence() -> None:
    src = table("t", [("a", "INT")], [[1]])
    assert run("SELECT (1 + 2) * 3, 1 + 2 * 3 FROM t", t=src).rows == [[9, 7]]
    assert run("SELECT NOT NOT a = 1 FROM t", t=src).rows == [[True]]


def test_output_names() -> None:
    src = table("t", [("a", "INT")], [[1]])
    result = run("SELECT t.a, a + 1 AS s, a  +   1 FROM t", t=src)
    assert result.columns == ["a", "s", "a + 1"]


def test_cli_null_empty_string_and_quoting(tmp_path: Path) -> None:
    csv = tmp_path / "q.csv"
    csv.write_text('s:TEXT,n:INT,f:BOOL\n"a,b",1,true\n\'\',2,FALSE\n,3,True\n', encoding="utf-8")
    done = _cli(tmp_path, "--table", f"q={csv}", "SELECT s, n, f FROM q ORDER BY n")
    assert done.returncode == 0
    assert done.stdout == b's,n,f\n"a,b",1,true\n,2,false\n,3,true\n'


def test_cli_single_null_is_empty_line(tmp_path: Path) -> None:
    csv = tmp_path / "n.csv"
    csv.write_text("a:INT\n\n1\n", encoding="utf-8")
    done = _cli(tmp_path, "--table", f"n={csv}", "SELECT a FROM n WHERE a IS NULL")
    assert done.returncode == 0
    assert done.stdout == b"a\n\n"


def test_cli_malformed_header(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text("age\n1\n", encoding="utf-8")
    done = _cli(tmp_path, "--table", f"t={csv}", "SELECT age FROM t")
    assert done.returncode == 2 and done.stdout == b""


def test_public_annotations() -> None:
    for name in ("execute", "type_of", "is_numeric", "and_", "or_", "not_", "compare_eq", "compare_lt", "arith", "negate"):
        sig = inspect.signature(getattr(__import__("microdb"), name))
        assert sig.return_annotation is not inspect.Signature.empty
    assert inspect.signature(Table.__init__).return_annotation is not inspect.Signature.empty
    assert inspect.signature(Table.column_index).return_annotation in (int, "int")


def test_function_bodies_are_short() -> None:
    longest = 0
    for path in (ROOT / "microdb").glob("*.py"):
        longest = max(longest, _longest_body(path.read_text(encoding="utf-8").splitlines()))
    assert longest <= 60


def test_count_after_where_on_empty_is_zero() -> None:
    src = table("t", [("a", "INT")], [[1], [2]])
    assert run("SELECT count(*) FROM t WHERE a > 10", t=src).rows == [[0]]


def test_join_row_order_is_left_major() -> None:
    left = table("a", [("id", "INT")], [[1], [2]])
    right = table("b", [("id", "INT"), ("v", "TEXT")], [[1, "x"], [1, "y"], [2, "z"]])
    result = run("SELECT b.v FROM a INNER JOIN b ON a.id = b.id", a=left, b=right)
    assert result.rows == [["x"], ["y"], ["z"]]


def test_float_int_compare_in_query() -> None:
    src = table("t", [("a", "FLOAT")], [[1]])
    assert run("SELECT a FROM t WHERE a = 1", t=src).rows == [[1.0]]


def test_result_is_frozen() -> None:
    result = run("SELECT 1 AS n FROM t", t=table("t", [("a", "INT")], [[0]]))
    assert isinstance(result, Result)
    with pytest.raises(AttributeError):
        result.columns = ["x"]  # type: ignore[misc]


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    del cwd
    return subprocess.run(
        [sys.executable, "-m", "microdb", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )


def _longest_body(lines: list[str]) -> int:
    longest = 0
    index = 0
    while index < len(lines):
        if lines[index].lstrip().startswith("def ") or lines[index].lstrip().startswith("async def "):
            longest = max(longest, _body_len(lines, index))
        index += 1
    return longest


def _body_len(lines: list[str], index: int) -> int:
    indent = len(lines[index]) - len(lines[index].lstrip())
    end = index + 1
    while end < len(lines):
        if lines[end].strip() and len(lines[end]) - len(lines[end].lstrip()) <= indent:
            break
        end += 1
    return end - index - 1

"""Comprehensive test suite for microdb.

Run with: python -m pytest -q tests/test_microdb.py
"""
from microdb.value import (
    type_of, is_numeric, and_, or_, not_,
    compare_eq, compare_lt, arith, negate,
)
from microdb.schema import Column, Table
from microdb.errors import (
    LexError, ParseError, SchemaError, TypeMismatchError,
    UnknownColumnError, AmbiguousColumnError, UnknownTableError,
    UnknownFunctionError, ArityError, AggregateError, GroupingError,
)
from microdb import execute, Result
import pytest


# ── Helpers ────────────────────────────────────────────────────────────

def make_t(name: str, cols: list, rows: list) -> dict:
    return {name: Table(name, cols, rows)}


T1 = [Column("a", "INT"), Column("b", "TEXT")]
T1_DATA = [[1, "x"], [2, "y"], [3, "z"]]


# ══════════════════════════════════════════════════════════════════════
# 1. value.py: type_of, is_numeric
# ══════════════════════════════════════════════════════════════════════

def test_type_of_int():
    assert type_of(42) == "INT"

def test_type_of_float():
    assert type_of(3.14) == "FLOAT"

def test_type_of_text():
    assert type_of("hello") == "TEXT"

def test_type_of_bool():
    assert type_of(True) == "BOOL"
    assert type_of(False) == "BOOL"

def test_type_of_null():
    assert type_of(None) == "NULL"

def test_is_numeric_int():
    assert is_numeric(42) is True

def test_is_numeric_float():
    assert is_numeric(3.14) is True

def test_is_numeric_bool_false():
    assert is_numeric(True) is False
    assert is_numeric(False) is False

def test_is_numeric_null_false():
    assert is_numeric(None) is False


# ══════════════════════════════════════════════════════════════════════
# 2. Three-valued logic
# ══════════════════════════════════════════════════════════════════════

def test_and_truth_table():
    # T AND T = T
    assert and_(True, True) is True
    # T AND F = F
    assert and_(True, False) is False
    # T AND U = U
    assert and_(True, None) is None
    # F AND T = F
    assert and_(False, True) is False
    # F AND F = F
    assert and_(False, False) is False
    # F AND U = F
    assert and_(False, None) is False
    # U AND T = U
    assert and_(None, True) is None
    # U AND F = F
    assert and_(None, False) is False
    # U AND U = U
    assert and_(None, None) is None

def test_or_truth_table():
    assert or_(True, True) is True
    assert or_(True, False) is True
    assert or_(True, None) is True
    assert or_(False, True) is True
    assert or_(False, False) is False
    assert or_(False, None) is None
    assert or_(None, True) is True
    assert or_(None, False) is None
    assert or_(None, None) is None

def test_not_truth_table():
    assert not_(True) is False
    assert not_(False) is True
    assert not_(None) is None


# ══════════════════════════════════════════════════════════════════════
# 3. Comparison
# ══════════════════════════════════════════════════════════════════════

def test_null_eq_null_is_unknown():
    """NULL = NULL is UNKNOWN, not TRUE."""
    assert compare_eq(None, None) is None

def test_null_lt_null_is_unknown():
    assert compare_lt(None, None) is None

def test_null_compare_any_is_unknown():
    assert compare_eq(None, 1) is None
    assert compare_lt(1, None) is None
    assert compare_eq("a", None) is None

def test_int_float_compare():
    assert compare_eq(1, 1.0) is True
    assert compare_lt(1, 1.5) is True
    assert compare_lt(1.5, 2) is True

def test_text_compare():
    assert compare_eq("a", "a") is True
    assert compare_lt("a", "b") is True
    assert compare_lt("b", "a") is False

def test_bool_compare():
    assert compare_eq(True, True) is True
    assert compare_eq(False, False) is True
    assert compare_lt(False, True) is True
    assert compare_lt(True, False) is False

def test_incompatible_compare_raises():
    with pytest.raises(TypeMismatchError):
        compare_eq(1, "a")
    with pytest.raises(TypeMismatchError):
        compare_eq(True, 1)
    with pytest.raises(TypeMismatchError):
        compare_lt("a", 1)


# ══════════════════════════════════════════════════════════════════════
# 4. Arithmetic
# ══════════════════════════════════════════════════════════════════════

def test_arith_null():
    assert arith("+", None, 1) is None
    assert arith("*", 1, None) is None

def test_arith_int_int():
    assert arith("+", 2, 3) == 5
    assert arith("-", 5, 3) == 2
    assert arith("*", 4, 3) == 12
    assert arith("%", 7, 3) == 1

def test_arith_float():
    assert arith("+", 1.5, 2) == 3.5
    assert arith("*", 1.5, 2) == 3.0
    assert arith("-", 5, 2.5) == 2.5

def test_division_yields_float():
    assert arith("/", 7, 2) == 3.5
    assert isinstance(arith("/", 7, 2), float)

def test_division_by_zero_yields_null():
    assert arith("/", 1, 0) is None
    assert arith("/", 1.0, 0.0) is None

def test_modulo_by_zero_yields_null():
    assert arith("%", 1, 0) is None

def test_negate():
    assert negate(5) == -5
    assert negate(-3.0) == 3.0
    assert negate(None) is None


# ══════════════════════════════════════════════════════════════════════
# 5. Schema
# ══════════════════════════════════════════════════════════════════════

def test_table_creation():
    t = Table("t", [Column("a", "INT")], [[1]])
    assert t.name == "t"
    assert len(t.columns) == 1
    assert len(t.rows) == 1

def test_schema_empty_columns():
    with pytest.raises(SchemaError):
        Table("t", [], [])

def test_schema_duplicate_column():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("a", "TEXT")], [])

def test_schema_invalid_type():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "BIGINT")], [])

def test_schema_row_length_mismatch():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT"), Column("b", "TEXT")], [[1]])

def test_schema_int_accepts_int_rejects_float():
    t = Table("t", [Column("a", "INT")], [[42]])
    assert t.rows[0][0] == 42
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[3.14]])

def test_schema_float_accepts_int():
    t = Table("t", [Column("a", "FLOAT")], [[42]])
    assert t.rows[0][0] == 42.0
    assert isinstance(t.rows[0][0], float)

def test_schema_int_rejects_bool():
    with pytest.raises(SchemaError):
        Table("t", [Column("a", "INT")], [[True]])

def test_column_index():
    t = Table("t", [Column("a", "INT"), Column("b", "TEXT")], [])
    assert t.column_index("a") == 0
    assert t.column_index("b") == 1
    with pytest.raises(SchemaError):
        t.column_index("c")


# ══════════════════════════════════════════════════════════════════════
# 6. Basic query execution
# ══════════════════════════════════════════════════════════════════════

def test_select_all():
    r = execute("SELECT * FROM t", make_t("t", T1, T1_DATA))
    assert r.columns == ["*"]
    assert r.rows == [[1, "x"], [2, "y"], [3, "z"]]

def test_select_columns():
    r = execute("SELECT a FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[1], [2], [3]]

def test_where_filter():
    r = execute("SELECT a FROM t WHERE a > 1", make_t("t", T1, T1_DATA))
    assert r.rows == [[2], [3]]

def test_where_is_null():
    t = Table("t", [Column("a", "INT")], [[1], [None], [3]])
    r = execute("SELECT a FROM t WHERE a IS NULL", {"t": t})
    assert r.rows == [[None]]

def test_where_is_not_null():
    t = Table("t", [Column("a", "INT")], [[1], [None], [3]])
    r = execute("SELECT a FROM t WHERE a IS NOT NULL", {"t": t})
    assert r.rows == [[1], [3]]

def test_where_eq_null_returns_nothing():
    """WHERE a = NULL should return nothing since NULL = NULL is UNKNOWN."""
    t = Table("t", [Column("a", "INT")], [[1], [None]])
    r = execute("SELECT count(*) FROM t WHERE a = NULL", {"t": t})
    assert r.rows == [[0]]

def test_order_by_asc():
    t = Table("t", [Column("a", "INT")], [[3], [1], [2]])
    r = execute("SELECT a FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1], [2], [3]]

def test_order_by_desc():
    t = Table("t", [Column("a", "INT")], [[3], [1], [2]])
    r = execute("SELECT a FROM t ORDER BY a DESC", {"t": t})
    assert r.rows == [[3], [2], [1]]

def test_order_by_null_asc():
    """NULLs sort last in ASC."""
    t = Table("t", [Column("a", "INT")], [[3], [None], [1]])
    r = execute("SELECT a FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1], [3], [None]]

def test_order_by_null_desc():
    """NULLs sort last in DESC too."""
    t = Table("t", [Column("a", "INT")], [[3], [None], [1]])
    r = execute("SELECT a FROM t ORDER BY a DESC", {"t": t})
    assert r.rows == [[3], [1], [None]]


# ══════════════════════════════════════════════════════════════════════
# 7. Aggregates
# ══════════════════════════════════════════════════════════════════════

def test_count_star():
    r = execute("SELECT count(*) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[3]]

def test_count_star_empty():
    t = Table("t", [Column("a", "INT")], [])
    r = execute("SELECT count(*) FROM t", {"t": t})
    assert r.rows == [[0]]

def test_count_expr():
    t = Table("t", [Column("a", "INT")], [[1], [None], [3]])
    r = execute("SELECT count(a) FROM t", {"t": t})
    assert r.rows == [[2]]

def test_sum():
    r = execute("SELECT sum(a) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[6]]

def test_sum_empty_is_null():
    t = Table("t", [Column("a", "INT")], [])
    r = execute("SELECT sum(a) FROM t", {"t": t})
    assert r.rows == [[None]]

def test_avg():
    r = execute("SELECT avg(a) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[2.0]]

def test_min():
    r = execute("SELECT min(a) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[1]]

def test_max():
    r = execute("SELECT max(a) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[3]]

def test_aggregate_ignores_null():
    t = Table("t", [Column("a", "INT")], [[1], [None], [3], [None]])
    r = execute("SELECT sum(a), avg(a), min(a), max(a), count(a) FROM t", {"t": t})
    assert r.rows == [[4, 2.0, 1, 3, 2]]


# ══════════════════════════════════════════════════════════════════════
# 8. GROUP BY
# ══════════════════════════════════════════════════════════════════════

def test_group_by_basic():
    t = Table("t", [Column("dept", "TEXT"), Column("sal", "INT")],
              [["Eng", 100], ["Eng", 200], ["Sales", 150]])
    r = execute("SELECT dept, sum(sal) FROM t GROUP BY dept ORDER BY dept", {"t": t})
    assert r.rows == [["Eng", 300], ["Sales", 150]]

def test_group_by_nulls_group_together():
    t = Table("t", [Column("a", "INT")], [[None], [None], [1]])
    r = execute("SELECT a, count(*) FROM t GROUP BY a ORDER BY a", {"t": t})
    assert r.rows == [[1, 1], [None, 2]]


# ══════════════════════════════════════════════════════════════════════
# 9. JOIN
# ══════════════════════════════════════════════════════════════════════

def test_inner_join():
    users = Table("users", [Column("id", "INT")], [[1], [2]])
    orders = Table("orders", [Column("uid", "INT")], [[1], [1], [3]])
    r = execute(
        "SELECT users.id, orders.uid FROM users INNER JOIN orders ON users.id = orders.uid",
        {"users": users, "orders": orders},
    )
    assert r.rows == [[1, 1], [1, 1]]

def test_left_join():
    users = Table("users", [Column("id", "INT")], [[1], [2]])
    orders = Table("orders", [Column("uid", "INT")], [[1], [3]])
    r = execute(
        "SELECT users.id, orders.uid FROM users LEFT JOIN orders ON users.id = orders.uid",
        {"users": users, "orders": orders},
    )
    assert r.rows == [[1, 1], [2, None]]


# ══════════════════════════════════════════════════════════════════════
# 10. DISTINCT
# ══════════════════════════════════════════════════════════════════════

def test_distinct():
    t = Table("t", [Column("a", "INT")], [[1], [1], [2], [2], [3]])
    r = execute("SELECT DISTINCT a FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1], [2], [3]]


# ══════════════════════════════════════════════════════════════════════
# 11. HAVING
# ══════════════════════════════════════════════════════════════════════

def test_having():
    t = Table("t", [Column("dept", "TEXT"), Column("sal", "INT")],
              [["Eng", 100], ["Eng", 200], ["Sales", 150]])
    r = execute("SELECT dept, sum(sal) FROM t GROUP BY dept HAVING sum(sal) > 150", {"t": t})
    assert r.rows == [["Eng", 300]]


# ══════════════════════════════════════════════════════════════════════
# 12. LIMIT / OFFSET
# ══════════════════════════════════════════════════════════════════════

def test_limit():
    r = execute("SELECT a FROM t ORDER BY a LIMIT 2", make_t("t", T1, T1_DATA))
    assert r.rows == [[1], [2]]

def test_offset_before_limit():
    r = execute("SELECT a FROM t ORDER BY a LIMIT 1 OFFSET 1", make_t("t", T1, T1_DATA))
    assert r.rows == [[2]]


# ══════════════════════════════════════════════════════════════════════
# 13. Aliases and expressions
# ══════════════════════════════════════════════════════════════════════

def test_alias():
    r = execute("SELECT a AS val FROM t", make_t("t", T1, T1_DATA))
    assert r.columns == ["val"]

def test_order_by_alias():
    r = execute("SELECT a AS val FROM t ORDER BY val", make_t("t", T1, T1_DATA))
    assert r.rows == [[1], [2], [3]]

def test_arithmetic_in_select():
    r = execute("SELECT a + 1 FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[2], [3], [4]]


# ══════════════════════════════════════════════════════════════════════
# 14. Scalar functions
# ══════════════════════════════════════════════════════════════════════

def test_upper():
    r = execute("SELECT upper(b) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [["X"], ["Y"], ["Z"]]

def test_lower():
    t = Table("t", [Column("a", "TEXT")], [["HELLO"]])
    r = execute("SELECT lower(a) FROM t", {"t": t})
    assert r.rows == [["hello"]]

def test_length():
    r = execute("SELECT length(b) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [[1], [1], [1]]

def test_concat():
    r = execute("SELECT concat(b, b) FROM t", make_t("t", T1, T1_DATA))
    assert r.rows == [["xx"], ["yy"], ["zz"]]

def test_abs():
    t = Table("t", [Column("a", "INT")], [[-5], [3]])
    r = execute("SELECT abs(a) FROM t ORDER BY a", {"t": t})
    assert r.rows == [[3], [5]]

def test_coalesce():
    t = Table("t", [Column("a", "INT")], [[1], [None], [None]])
    r = execute("SELECT coalesce(a, 99) FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1], [99], [99]]

def test_function_null_propagates():
    t = Table("t", [Column("a", "TEXT")], [[None], ["hi"]])
    r = execute("SELECT upper(a) FROM t", {"t": t})
    assert r.rows == [[None], ["HI"]]

def test_concat_null_returns_null():
    t = Table("t", [Column("a", "TEXT"), Column("b", "TEXT")], [["a", None]])
    r = execute("SELECT concat(a, b) FROM t", {"t": t})
    assert r.rows == [[None]]


# ══════════════════════════════════════════════════════════════════════
# 15. Error cases
# ══════════════════════════════════════════════════════════════════════

def test_lex_error():
    with pytest.raises(LexError):
        execute("SELECT @ FROM t", make_t("t", T1, T1_DATA))

def test_aggregate_in_where():
    with pytest.raises(AggregateError):
        execute("SELECT a FROM t WHERE count(*) > 1", make_t("t", T1, T1_DATA))

def test_unknown_column():
    with pytest.raises(UnknownColumnError):
        execute("SELECT z FROM t", make_t("t", T1, T1_DATA))

def test_ambiguous_column():
    """Unqualified column that exists in both joined tables."""
    a = Table("a", [Column("x", "INT")], [[1]])
    b = Table("b", [Column("x", "INT")], [[2]])
    with pytest.raises(AmbiguousColumnError):
        execute("SELECT x FROM a INNER JOIN b ON a.x = b.x", {"a": a, "b": b})

def test_unknown_table():
    a = Table("a", [Column("x", "INT")], [[1]])
    with pytest.raises(UnknownTableError):
        execute("SELECT b.x FROM a INNER JOIN b ON a.x = b.x", {"a": a})

def test_where_non_bool():
    """WHERE 1 should raise because 1 is INT, not BOOL."""
    with pytest.raises(TypeMismatchError):
        execute("SELECT a FROM t WHERE 1", make_t("t", T1, T1_DATA))

def test_division_by_zero_in_query():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 0]])
    r = execute("SELECT a / b FROM t", {"t": t})
    assert r.rows == [[None]]

def test_grouping_error():
    """With GROUP BY, SELECT must contain only aggregates or group keys."""
    t = Table("t", [Column("a", "INT"), Column("b", "INT")], [[1, 10]])
    with pytest.raises(GroupingError):
        execute("SELECT b FROM t GROUP BY a", {"t": t})

def test_plan_inspect():
    """Callers should be able to inspect plans."""
    from microdb import plan, parse
    q = parse("SELECT a FROM t WHERE a > 1")
    p = plan(q)
    assert len(p) >= 3
    assert any(s.__class__.__name__ == "ScanStage" for s in p)
    assert any(s.__class__.__name__ == "FilterStage" for s in p)
    assert any(s.__class__.__name__ == "SelectStage" for s in p)


# ══════════════════════════════════════════════════════════════════════
# 16. Sort stability
# ══════════════════════════════════════════════════════════════════════

def test_sort_stability():
    """When sort keys are equal, original order is preserved."""
    t = Table("t", [Column("a", "INT"), Column("b", "TEXT")],
              [[1, "c"], [1, "a"], [1, "b"]])
    # Sort by 'a' only - rows with equal 'a' should keep original order
    r = execute("SELECT a, b FROM t ORDER BY a", {"t": t})
    assert r.rows == [[1, "c"], [1, "a"], [1, "b"]]


# ══════════════════════════════════════════════════════════════════════
# 17. Edge cases
# ══════════════════════════════════════════════════════════════════════

def test_empty_table_select_star():
    t = Table("t", [Column("a", "INT")], [])
    r = execute("SELECT * FROM t", {"t": t})
    assert r.rows == []

def test_select_with_multiple_aggregates():
    r = execute(
        "SELECT count(*), sum(a), avg(a), min(a), max(a) FROM t",
        make_t("t", T1, T1_DATA),
    )
    assert r.rows == [[3, 6, 2.0, 1, 3]]

def test_where_with_and_or():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")],
              [[1, 10], [2, 20], [3, 30]])
    r = execute("SELECT a FROM t WHERE a > 1 AND b < 30 OR a = 1", {"t": t})
    assert r.rows == [[1], [2]]


# ══════════════════════════════════════════════════════════════════════
# 18. Comment handling
# ══════════════════════════════════════════════════════════════════════

def test_sql_comment():
    r = execute("SELECT a FROM t -- comment\nWHERE a > 1", make_t("t", T1, T1_DATA))
    assert r.rows == [[2], [3]]


# ══════════════════════════════════════════════════════════════════════
# 19. Three-valued logic in WHERE
# ══════════════════════════════════════════════════════════════════════

def test_where_unknown_drops_row():
    """WHERE NULL drops row because UNKNOWN is not TRUE."""
    t = Table("t", [Column("a", "INT")], [[1]])
    r = execute("SELECT count(*) FROM t WHERE NULL", {"t": t})
    assert r.rows == [[0]]

def test_where_and_null():
    t = Table("t", [Column("a", "INT")], [[1]])
    r = execute("SELECT count(*) FROM t WHERE a = 1 AND NULL", {"t": t})
    assert r.rows == [[0]]

def test_where_or_true():
    t = Table("t", [Column("a", "INT")], [[1]])
    r = execute("SELECT count(*) FROM t WHERE a = 2 OR NULL", {"t": t})
    assert r.rows == [[0]]


# ══════════════════════════════════════════════════════════════════════
# 20. GROUP BY with NULL and HAVING
# ══════════════════════════════════════════════════════════════════════

def test_group_by_expr():
    t = Table("t", [Column("a", "INT")], [[1], [2], [3]])
    r = execute("SELECT a % 2 AS grp, count(*) FROM t GROUP BY a % 2 ORDER BY grp", {"t": t})
    assert r.rows == [[0, 1], [1, 2]]


# ══════════════════════════════════════════════════════════════════════
# 21. Qualified column reference after join
# ══════════════════════════════════════════════════════════════════════

def test_qualified_column_after_join():
    users = Table("users", [Column("id", "INT"), Column("name", "TEXT")], [[1, "Alice"]])
    r = execute(
        "SELECT users.name FROM users",
        {"users": users},
    )
    assert r.rows == [["Alice"]]


# ══════════════════════════════════════════════════════════════════════
# 22. NOT operator
# ══════════════════════════════════════════════════════════════════════

def test_not_operator():
    t = Table("t", [Column("a", "INT")], [[1], [2]])
    r = execute("SELECT a FROM t WHERE NOT a = 1", {"t": t})
    assert r.rows == [[2]]

def test_not_null_is_unknown():
    """NOT NULL = U, which is not TRUE, so the row is dropped."""
    t = Table("t", [Column("a", "INT")], [[1]])
    r = execute("SELECT count(*) FROM t WHERE NOT NULL", {"t": t})
    assert r.rows == [[0]]


# ══════════════════════════════════════════════════════════════════════
# 23. Aggregate with alias
# ══════════════════════════════════════════════════════════════════════

def test_aggregate_alias():
    r = execute("SELECT count(*) AS cnt FROM t", make_t("t", T1, T1_DATA))
    assert r.columns == ["cnt"]
    assert r.rows == [[3]]


# ══════════════════════════════════════════════════════════════════════
# 24. Multiple ORDER BY keys
# ══════════════════════════════════════════════════════════════════════

def test_multi_order_by():
    t = Table("t", [Column("a", "INT"), Column("b", "INT")],
              [[1, 3], [2, 1], [1, 1]])
    r = execute("SELECT a, b FROM t ORDER BY a, b", {"t": t})
    assert r.rows == [[1, 1], [1, 3], [2, 1]]
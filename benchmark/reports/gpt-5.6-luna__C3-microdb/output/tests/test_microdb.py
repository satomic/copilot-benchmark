import pytest
from microdb import *
from microdb.errors import *
from microdb.__main__ import main


def tab():
    return Table("t", [Column("a", "INT"), Column("b", "TEXT"), Column("ok", "BOOL")],
                 [[1, "x", True], [2, "y", False], [None, None, True]])


def test_truth_and_true(): assert and_(True, True) is True
def test_truth_and_false(): assert and_(False, None) is False
def test_truth_and_unknown(): assert and_(True, None) is None
def test_truth_or_true(): assert or_(True, None) is True
def test_truth_or_false(): assert or_(False, False) is False
def test_truth_or_unknown(): assert or_(False, None) is None
def test_truth_not(): assert not_(None) is None
def test_null_equality(): assert compare_eq(None, None) is None
def test_numeric_compare(): assert compare_lt(1, 2.0) is True
def test_bad_compare(): 
    with pytest.raises(TypeMismatchError): compare_eq("x", 1)
def test_type_bool(): assert type_of(True) == "BOOL"
def test_numeric_bool_excluded(): assert not is_numeric(True)
def test_div_zero(): assert arith("/", 2, 0) is None
def test_mod_zero(): assert arith("%", 2, 0) is None
def test_div_float(): assert arith("/", 7, 2) == 3.5
def test_int_add(): assert arith("+", 2, 3) == 5
def test_float_add(): assert arith("+", 2, 3.0) == 5.0
def test_null_add(): assert arith("+", None, 2) is None
def test_negate(): assert negate(2) == -2
def test_schema_empty(): 
    with pytest.raises(SchemaError): Table("x", [], [])
def test_schema_bool_int_rejected():
    with pytest.raises(SchemaError): Table("x", [Column("a", "INT")], [[True]])
def test_schema_float_widen(): assert Table("x", [Column("a", "FLOAT")], [[1]]).rows == [[1.0]]
def test_schema_duplicate():
    with pytest.raises(SchemaError): Table("x", [Column("a", "INT"), Column("a", "INT")], [])
def test_lexer_comment(): assert tokenize("SELECT 1 -- hi\n")[-1].kind == "EOF"
def test_lexer_string(): assert tokenize("'a''b'")[0].text == "a'b"
def test_lexer_bad():
    with pytest.raises(LexError): tokenize("@")
def test_parse_query(): assert parse("SELECT a FROM t").table == "t"
def test_parse_chained():
    with pytest.raises(ParseError): parse("SELECT 1 < 2 < 3 FROM t")
def test_select(): assert execute("SELECT a FROM t", {"t": tab()}).rows == [[1], [2], [None]]
def test_where_unknown_drops(): assert execute("SELECT a FROM t WHERE a = NULL", {"t": tab()}).rows == []
def test_where_type_error():
    with pytest.raises(TypeMismatchError): execute("SELECT a FROM t WHERE 1", {"t": tab()})
def test_scalar_upper(): assert execute("SELECT upper(b) FROM t", {"t": tab()}).rows[0] == ["X"]
def test_scalar_coalesce(): assert execute("SELECT coalesce(a, 9) FROM t", {"t": tab()}).rows[-1] == [9]
def test_aggregate_sum(): assert execute("SELECT sum(a) FROM t", {"t": tab()}).rows == [[3]]
def test_aggregate_empty_sum():
    empty = Table("t", [Column("a", "INT")], [])
    assert execute("SELECT sum(a) FROM t", {"t": empty}).rows == [[None]]
def test_count_empty():
    empty = Table("t", [Column("a", "INT")], [])
    assert execute("SELECT count(*) FROM t", {"t": empty}).rows == [[0]]
def test_group_nulls(): assert execute("SELECT b,count(*) FROM t GROUP BY b", {"t": tab()}).rows[-1] == [None, 1]
def test_grouping_error():
    with pytest.raises(GroupingError): execute("SELECT a,b,count(*) FROM t GROUP BY a", {"t": tab()})
def test_left_join():
    u = Table("u", [Column("a", "INT")], [[1], [3]])
    assert execute("SELECT t.a,u.a FROM t LEFT JOIN u ON t.a = u.a", {"t": tab(), "u": u}).rows[-1] == [None, None]
def test_order_null_desc():
    rows = execute("SELECT a FROM t ORDER BY a DESC", {"t": tab()}).rows
    assert rows[-1] == [None]
def test_order_stable():
    assert execute("SELECT b FROM t ORDER BY ok", {"t": tab()}).rows[:2] == [["y"], ["x"]]
def test_alias_order(): assert execute("SELECT a AS z FROM t ORDER BY z DESC", {"t": tab()}).rows[0] == [2]
def test_alias_not_where():
    with pytest.raises(UnknownColumnError): execute("SELECT a AS z FROM t WHERE z > 1", {"t": tab()})
def test_distinct(): assert execute("SELECT DISTINCT ok FROM t", {"t": tab()}).rows == [[True], [False]]
def test_offset_limit(): assert execute("SELECT a FROM t LIMIT 1 OFFSET 1", {"t": tab()}).rows == [[2]]
def test_plan_stages(): assert [x.name for x in plan(parse("SELECT a FROM t"))]
def test_result_columns(): assert execute("SELECT a+1 FROM t", {"t": tab()}).columns == ["a + 1"]
def test_unknown_table():
    with pytest.raises(UnknownTableError): execute("SELECT a FROM no", {})
def test_unknown_function():
    with pytest.raises(UnknownFunctionError): execute("SELECT nope(a) FROM t", {"t": tab()})
def test_cli_usage(capsys): assert main([]) == 2

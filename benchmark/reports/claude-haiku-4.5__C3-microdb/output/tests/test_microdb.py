import pytest
from microdb.value import (
    type_of, is_numeric, and_, or_, not_, compare_eq, compare_lt, arith, negate
)
from microdb.schema import Table, Column
from microdb.lexer import Lexer
from microdb.parser import Parser
from microdb import execute
from microdb.errors import (
    TypeMismatchError, SchemaError, LexError, ParseError,
    UnknownColumnError, AggregateError, GroupingError
)


class TestValue:
    def test_type_of_int(self):
        assert type_of(42) == "INT"
    
    def test_type_of_float(self):
        assert type_of(3.14) == "FLOAT"
    
    def test_type_of_text(self):
        assert type_of("hello") == "TEXT"
    
    def test_type_of_bool(self):
        assert type_of(True) == "BOOL"
        assert type_of(False) == "BOOL"
    
    def test_type_of_null(self):
        assert type_of(None) == "NULL"
    
    def test_is_numeric_int(self):
        assert is_numeric(42)
    
    def test_is_numeric_float(self):
        assert is_numeric(3.14)
    
    def test_is_numeric_bool_false(self):
        assert not is_numeric(True)
    
    def test_is_numeric_null_false(self):
        assert not is_numeric(None)


class TestThreeValuedLogic:
    def test_and_truth_table(self):
        assert and_(True, True) is True
        assert and_(True, False) is False
        assert and_(True, None) is None
        assert and_(False, True) is False
        assert and_(False, False) is False
        assert and_(False, None) is False
        assert and_(None, True) is None
        assert and_(None, False) is False
        assert and_(None, None) is None
    
    def test_or_truth_table(self):
        assert or_(True, True) is True
        assert or_(True, False) is True
        assert or_(True, None) is True
        assert or_(False, True) is True
        assert or_(False, False) is False
        assert or_(False, None) is None
        assert or_(None, True) is True
        assert or_(None, False) is None
        assert or_(None, None) is None
    
    def test_not_truth_table(self):
        assert not_(True) is False
        assert not_(False) is True
        assert not_(None) is None


class TestComparison:
    def test_null_equality_is_unknown(self):
        assert compare_eq(None, None) is None
    
    def test_null_comparison_is_unknown(self):
        assert compare_lt(None, 5) is None
        assert compare_lt(5, None) is None
    
    def test_int_comparison(self):
        assert compare_eq(5, 5) is True
        assert compare_eq(5, 3) is False
        assert compare_lt(3, 5) is True
        assert compare_lt(5, 3) is False
    
    def test_float_comparison(self):
        assert compare_eq(3.14, 3.14) is True
        assert compare_lt(3.0, 3.5) is True
    
    def test_mixed_numeric_comparison(self):
        assert compare_eq(5, 5.0) is True
        assert compare_lt(3, 3.5) is True
    
    def test_text_comparison(self):
        assert compare_eq("a", "a") is True
        assert compare_eq("a", "b") is False
        assert compare_lt("a", "b") is True


class TestArithmetic:
    def test_null_arithmetic(self):
        assert arith("+", None, 5) is None
        assert arith("+", 5, None) is None
    
    def test_division_by_zero(self):
        assert arith("/", 5, 0) is None
        assert arith("/", 5.0, 0.0) is None
    
    def test_modulo_by_zero(self):
        assert arith("%", 5, 0) is None
    
    def test_int_addition(self):
        assert arith("+", 3, 5) == 8
    
    def test_division_yields_float(self):
        assert arith("/", 7, 2) == 3.5
        assert isinstance(arith("/", 7, 2), float)
    
    def test_negate_preserves_type(self):
        assert negate(5) == -5
        assert isinstance(negate(5), int)
        assert negate(3.14) == -3.14
        assert isinstance(negate(3.14), float)


class TestSchema:
    def test_table_creation(self):
        cols = [Column("id", "INT"), Column("name", "TEXT")]
        rows = [[1, "Alice"], [2, "Bob"]]
        table = Table("users", cols, rows)
        assert table.name == "users"
        assert len(table.columns) == 2
        assert len(table.rows) == 2
    
    def test_table_empty_columns_error(self):
        with pytest.raises(SchemaError):
            Table("users", [], [[]])
    
    def test_table_duplicate_column_names(self):
        cols = [Column("id", "INT"), Column("id", "TEXT")]
        with pytest.raises(SchemaError):
            Table("users", cols, [])
    
    def test_table_invalid_type(self):
        cols = [Column("id", "INVALID")]
        with pytest.raises(SchemaError):
            Table("users", cols, [])
    
    def test_table_row_length_mismatch(self):
        cols = [Column("id", "INT"), Column("name", "TEXT")]
        rows = [[1]]
        with pytest.raises(SchemaError):
            Table("users", cols, rows)
    
    def test_table_type_mismatch_int(self):
        cols = [Column("id", "INT")]
        rows = [["not a number"]]
        with pytest.raises(SchemaError):
            Table("users", cols, rows)
    
    def test_table_float_accepts_int(self):
        cols = [Column("value", "FLOAT")]
        rows = [[5]]
        table = Table("data", cols, rows)
        assert isinstance(table.rows[0][0], float)
    
    def test_table_column_index(self):
        cols = [Column("id", "INT"), Column("name", "TEXT")]
        table = Table("users", cols, [[1, "Alice"]])
        assert table.column_index("id") == 0
        assert table.column_index("name") == 1


class TestLexer:
    def test_lexer_keywords(self):
        lexer = Lexer("SELECT FROM WHERE")
        tokens = lexer.lex()
        assert tokens[0].type == "SELECT"
        assert tokens[1].type == "FROM"
        assert tokens[2].type == "WHERE"
    
    def test_lexer_identifiers(self):
        lexer = Lexer("table_name col1")
        tokens = lexer.lex()
        assert tokens[0].type == "IDENT"
        assert tokens[0].value == "table_name"
        assert tokens[1].type == "IDENT"
        assert tokens[1].value == "col1"
    
    def test_lexer_integers(self):
        lexer = Lexer("123 456")
        tokens = lexer.lex()
        assert tokens[0].type == "INT"
        assert tokens[0].value == 123
    
    def test_lexer_floats(self):
        lexer = Lexer("3.14 1.5E-2 1.")
        tokens = lexer.lex()
        assert tokens[0].type == "FLOAT"
        assert tokens[0].value == 3.14
        assert tokens[2].type == "FLOAT"
    
    def test_lexer_text_literals(self):
        lexer = Lexer("'hello' 'it''s'")
        tokens = lexer.lex()
        assert tokens[0].type == "TEXT"
        assert tokens[0].value == "hello"
        assert tokens[1].type == "TEXT"
        assert tokens[1].value == "it's"
    
    def test_lexer_comments(self):
        lexer = Lexer("SELECT -- comment\nFROM")
        tokens = lexer.lex()
        assert len(tokens) == 2
        assert tokens[0].type == "SELECT"
        assert tokens[1].type == "FROM"


class TestParser:
    def test_parser_simple_select(self):
        lexer = Lexer("SELECT id FROM users")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert not query.distinct
        assert query.from_table == "users"
    
    def test_parser_distinct(self):
        lexer = Lexer("SELECT DISTINCT name FROM users")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert query.distinct
    
    def test_parser_where_clause(self):
        lexer = Lexer("SELECT * FROM users WHERE age > 30")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert query.where_expr is not None
    
    def test_parser_group_by(self):
        lexer = Lexer("SELECT category, count(*) FROM items GROUP BY category")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert len(query.group_by) == 1
    
    def test_parser_having(self):
        lexer = Lexer("SELECT category, count(*) FROM items GROUP BY category HAVING count(*) > 5")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert query.having_expr is not None
    
    def test_parser_order_by(self):
        lexer = Lexer("SELECT * FROM users ORDER BY name ASC, age DESC")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert len(query.order_by) == 2
    
    def test_parser_limit_offset(self):
        lexer = Lexer("SELECT * FROM users LIMIT 10 OFFSET 5")
        tokens = lexer.lex()
        parser = Parser(tokens)
        query = parser.parse()
        assert query.limit == 10
        assert query.offset == 5


class TestExecutor:
    def test_simple_select(self):
        cols = [Column("id", "INT"), Column("name", "TEXT")]
        rows = [[1, "Alice"], [2, "Bob"]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT name FROM users", {"users": table})
        assert result.columns == ["name"]
        assert len(result.rows) == 2
    
    def test_select_all(self):
        cols = [Column("id", "INT"), Column("name", "TEXT")]
        rows = [[1, "Alice"]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT * FROM users", {"users": table})
        assert result.columns == ["id", "name"]
    
    def test_where_clause_true(self):
        cols = [Column("id", "INT"), Column("age", "INT")]
        rows = [[1, 25], [2, 35], [3, 20]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT * FROM users WHERE age > 30", {"users": table})
        assert len(result.rows) == 1
        assert result.rows[0][0] == 2
    
    def test_where_clause_null(self):
        cols = [Column("id", "INT"), Column("age", "INT")]
        rows = [[1, None], [2, 35]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT * FROM users WHERE age = NULL", {"users": table})
        assert len(result.rows) == 0
    
    def test_count_star(self):
        cols = [Column("id", "INT")]
        rows = [[1], [2], [3]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT count(*) FROM data", {"data": table})
        assert result.rows[0][0] == 3
    
    def test_count_star_empty(self):
        cols = [Column("id", "INT")]
        rows = []
        table = Table("data", cols, rows)
        
        result = execute("SELECT count(*) FROM data", {"data": table})
        assert result.rows[0][0] == 0
    
    def test_sum_empty_is_null(self):
        cols = [Column("value", "INT")]
        rows = []
        table = Table("data", cols, rows)
        
        result = execute("SELECT sum(value) FROM data", {"data": table})
        assert result.rows[0][0] is None
    
    def test_group_by_basic(self):
        cols = [Column("category", "TEXT"), Column("value", "INT")]
        rows = [["A", 10], ["B", 20], ["A", 30]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT category, sum(value) FROM data GROUP BY category", {"data": table})
        assert len(result.rows) == 2
    
    def test_distinct(self):
        cols = [Column("name", "TEXT")]
        rows = [["Alice"], ["Bob"], ["Alice"]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT DISTINCT name FROM users", {"users": table})
        assert len(result.rows) == 2
    
    def test_order_by_asc(self):
        cols = [Column("age", "INT")]
        rows = [[35], [20], [30]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT age FROM users ORDER BY age ASC", {"users": table})
        assert result.rows[0][0] == 20
        assert result.rows[1][0] == 30
        assert result.rows[2][0] == 35
    
    def test_order_by_null_sorts_last(self):
        cols = [Column("value", "INT")]
        rows = [[30], [None], [10]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT value FROM data ORDER BY value ASC", {"data": table})
        assert result.rows[0][0] == 10
        assert result.rows[1][0] == 30
        assert result.rows[2][0] is None
    
    def test_limit_offset(self):
        cols = [Column("id", "INT")]
        rows = [[1], [2], [3], [4], [5]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT id FROM data LIMIT 2 OFFSET 1", {"data": table})
        assert len(result.rows) == 2
        assert result.rows[0][0] == 2
    
    def test_aggregate_without_group_by(self):
        cols = [Column("value", "INT")]
        rows = [[10], [20], [30]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT count(*), sum(value) FROM data", {"data": table})
        assert len(result.rows) == 1
        assert result.rows[0][0] == 3
        assert result.rows[0][1] == 60
    
    def test_inner_join(self):
        cols_a = [Column("id", "INT"), Column("name", "TEXT")]
        rows_a = [[1, "Alice"], [2, "Bob"]]
        table_a = Table("users", cols_a, rows_a)
        
        cols_b = [Column("user_id", "INT"), Column("city", "TEXT")]
        rows_b = [[1, "NYC"], [2, "LA"]]
        table_b = Table("cities", cols_b, rows_b)
        
        result = execute(
            "SELECT users.name, cities.city FROM users INNER JOIN cities ON users.id = cities.user_id",
            {"users": table_a, "cities": table_b}
        )
        assert len(result.rows) == 2
    
    def test_left_join(self):
        cols_a = [Column("id", "INT"), Column("name", "TEXT")]
        rows_a = [[1, "Alice"], [2, "Bob"], [3, "Charlie"]]
        table_a = Table("users", cols_a, rows_a)
        
        cols_b = [Column("user_id", "INT"), Column("city", "TEXT")]
        rows_b = [[1, "NYC"], [2, "LA"]]
        table_b = Table("cities", cols_b, rows_b)
        
        result = execute(
            "SELECT users.name, cities.city FROM users LEFT JOIN cities ON users.id = cities.user_id",
            {"users": table_a, "cities": table_b}
        )
        assert len(result.rows) == 3
        assert result.rows[2][1] is None


class TestFunctions:
    def test_concat(self):
        cols = [Column("a", "TEXT"), Column("b", "TEXT")]
        rows = [["Hello", "World"]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT concat(a, b) FROM data", {"data": table})
        assert result.rows[0][0] == "HelloWorld"
    
    def test_upper(self):
        cols = [Column("text", "TEXT")]
        rows = [["hello"]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT upper(text) FROM data", {"data": table})
        assert result.rows[0][0] == "HELLO"
    
    def test_lower(self):
        cols = [Column("text", "TEXT")]
        rows = [["HELLO"]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT lower(text) FROM data", {"data": table})
        assert result.rows[0][0] == "hello"
    
    def test_length(self):
        cols = [Column("text", "TEXT")]
        rows = [["hello"]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT length(text) FROM data", {"data": table})
        assert result.rows[0][0] == 5
    
    def test_abs(self):
        cols = [Column("value", "INT")]
        rows = [[-42]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT abs(value) FROM data", {"data": table})
        assert result.rows[0][0] == 42
    
    def test_coalesce(self):
        cols = [Column("a", "INT"), Column("b", "INT")]
        rows = [[None, 42]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT coalesce(a, b) FROM data", {"data": table})
        assert result.rows[0][0] == 42


class TestAliases:
    def test_column_alias(self):
        cols = [Column("id", "INT")]
        rows = [[42]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT id AS user_id FROM data", {"data": table})
        assert result.columns == ["user_id"]
    
    def test_alias_in_order_by(self):
        cols = [Column("name", "TEXT"), Column("age", "INT")]
        rows = [["Charlie", 30], ["Alice", 25]]
        table = Table("users", cols, rows)
        
        result = execute("SELECT name AS full_name FROM users ORDER BY full_name ASC", {"users": table})
        assert result.rows[0][0] == "Alice"


class TestEdgeCases:
    def test_null_grouping_together(self):
        cols = [Column("category", "INT"), Column("value", "INT")]
        rows = [[None, 10], [None, 20], [1, 30]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT category, count(*) FROM data GROUP BY category", {"data": table})
        assert len(result.rows) == 2
        assert result.rows[0][1] == 2
    
    def test_sort_stability(self):
        cols = [Column("key", "INT"), Column("seq", "INT")]
        rows = [[1, 0], [2, 1], [1, 2]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT key, seq FROM data ORDER BY key ASC", {"data": table})
        assert result.rows[0][1] == 0
        assert result.rows[1][1] == 2
        assert result.rows[2][1] == 1
    
    def test_count_null_values(self):
        cols = [Column("value", "INT")]
        rows = [[1], [None], [3]]
        table = Table("data", cols, rows)
        
        result = execute("SELECT count(value) FROM data", {"data": table})
        assert result.rows[0][0] == 2

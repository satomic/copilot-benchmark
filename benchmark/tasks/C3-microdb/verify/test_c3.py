"""Hidden verification suite for task C3. Not visible to the model under test."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

_IGNORED_DIRS = {"__pycache__", "_verify", ".pytest_cache", ".git", ".ruff_cache", ".mypy_cache"}
T, F, U = True, False, None


#: Where the spec says each public name lives. task.md requires value.py to
#: "export" type_of and is_numeric, and never says the package root must
#: re-export them, so the suite resolves a name from the package first and then
#: from the module the spec assigns it to. Testing an unstated re-export would
#: punish a correct implementation.
_SUBMODULES = (
    "value", "schema", "lexer", "parser", "expr", "aggregate",
    "planner", "executor", "errors",
)


class _Facade:
    """Resolves public names across the package and its documented submodules."""

    def __init__(self, pkg):
        self._pkg = pkg
        self._mods = [pkg]
        for name in _SUBMODULES:
            try:
                self._mods.append(importlib.import_module(f"microdb.{name}"))
            except Exception:  # a missing module shows up as a file_manifest failure
                pass

    def __getattr__(self, name):
        for module in self._mods:
            if hasattr(module, name):
                return getattr(module, name)
        adapter = self._adapt(name)
        if adapter is not None:
            return adapter
        raise AttributeError(f"microdb exposes no {name} in the package or its submodules")

    def _find(self, name):
        for module in self._mods:
            if hasattr(module, name):
                return getattr(module, name)
        return None

    def _adapt(self, name):
        """task.md names tokenize and parse only in a Deliverables comment.

        Both a module-level function and the equally conventional class form are
        therefore acceptable, so the suite adapts instead of mandating one shape.
        """
        if name == "tokenize":
            lexer = self._find("Lexer")
            if lexer is None:
                return None

            def tokenize(src):
                obj = lexer(src)
                for method in ("lex", "tokenize", "tokens", "scan", "run"):
                    if hasattr(obj, method):
                        got = getattr(obj, method)
                        return got() if callable(got) else got
                raise AttributeError("Lexer exposes no lexing method")

            return tokenize
        if name == "parse":
            parser = self._find("Parser")
            if parser is None:
                return None

            def _drive(obj):
                for method in ("parse", "parse_query", "run"):
                    if hasattr(obj, method):
                        return getattr(obj, method)()
                raise AttributeError("Parser exposes no parse method")

            def parse(src):
                # A Parser may take the source text or a token list. Construction
                # succeeds either way, so the retry has to wrap the parse call too.
                try:
                    return _drive(parser(src))
                except Exception as first:
                    try:
                        return _drive(parser(self.tokenize(src)))
                    except AttributeError:
                        raise first from None

            return parse
        return None


@pytest.fixture(scope="module")
def db():
    sys.path.insert(0, ".")
    return _Facade(importlib.import_module("microdb"))


@pytest.fixture
def mk(db):
    def make(name, spec, rows):
        cols = [db.Column(n, t) for n, t in spec]
        return db.Table(name, cols, rows)

    return make


@pytest.fixture
def people(mk):
    return mk(
        "p",
        [("id", "INT"), ("name", "TEXT"), ("age", "INT"), ("score", "FLOAT")],
        [
            [1, "ann", 30, 1.5],
            [2, "bob", None, 2.5],
            [3, "cid", 40, None],
            [4, None, 30, 4.0],
        ],
    )


@pytest.fixture
def run(db, people):
    def go(query, tables=None):
        return db.execute(query, tables if tables is not None else {"p": people})

    return go


def tok_field(token, *names):
    """Read a token attribute under any of the conventional names.

    task.md specifies the lexical *rules* but never the Token object's fields, so
    the suite must not mandate one naming scheme.
    """
    for name in names:
        if hasattr(token, name):
            return getattr(token, name)
    if isinstance(token, (tuple, list)):
        return token[0]
    raise AttributeError(f"token exposes none of {names}")


def kinds(tokens):
    """Token kinds with a trailing end-of-input marker dropped if present."""
    out = [str(tok_field(t, "kind", "type", "kind_name")).upper() for t in tokens]
    while out and out[-1] in ("EOF", "END", "EOI", "ENDMARKER"):
        out.pop()
    return out


def texts(tokens):
    out = []
    for t in tokens:
        if str(tok_field(t, "kind", "type", "kind_name")).upper() in ("EOF", "END", "EOI"):
            continue
        out.append(tok_field(t, "text", "value", "lexeme", "raw"))
    return out


def cli(*args, timeout=60):
    return subprocess.run(
        [sys.executable, "-m", "microdb", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=".",
    )


# --------------------------------------------------------------------------- #
# 1. value model
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "value,expected",
    [(1, "INT"), (-5, "INT"), (1.5, "FLOAT"), (0.0, "FLOAT"), ("", "TEXT"),
     ("x", "TEXT"), (True, "BOOL"), (False, "BOOL"), (None, "NULL")],
)
def test_type_of(db, value, expected):
    assert db.type_of(value) == expected


@pytest.mark.parametrize("value", [1, -1, 0, 1.5, -0.0])
def test_is_numeric_true(db, value):
    assert db.is_numeric(value) is True


@pytest.mark.parametrize("value", [True, False, None, "1", ""])
def test_is_numeric_false(db, value):
    assert db.is_numeric(value) is False


def test_bool_is_not_int(db):
    assert db.type_of(True) == "BOOL"
    assert db.is_numeric(True) is False


# --------------------------------------------------------------------------- #
# 2. three-valued logic
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, F), (T, U, U), (F, T, F), (F, F, F), (F, U, F),
     (U, T, U), (U, F, F), (U, U, U)],
)
def test_and_table(db, a, b, expected):
    assert db.and_(a, b) is expected


@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, T), (T, U, T), (F, T, T), (F, F, F), (F, U, U),
     (U, T, T), (U, F, U), (U, U, U)],
)
def test_or_table(db, a, b, expected):
    assert db.or_(a, b) is expected


@pytest.mark.parametrize("a,expected", [(T, F), (F, T), (U, U)])
def test_not_table(db, a, expected):
    assert db.not_(a) is expected


# --------------------------------------------------------------------------- #
# 3. comparison
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "a,b", [(None, None), (None, 1), (1, None), (None, "x"), ("x", None),
            (None, True), (True, None), (None, 1.5)],
)
def test_eq_with_null_is_unknown(db, a, b):
    assert db.compare_eq(a, b) is None


@pytest.mark.parametrize("a,b", [(None, None), (None, 1), (1, None)])
def test_lt_with_null_is_unknown(db, a, b):
    assert db.compare_lt(a, b) is None


@pytest.mark.parametrize(
    "a,b,expected", [(1, 1, T), (1, 2, F), (1, 1.0, T), (1.5, 1.5, T), (2, 1.0, F)],
)
def test_eq_numeric(db, a, b, expected):
    assert db.compare_eq(a, b) is expected


@pytest.mark.parametrize(
    "a,b,expected", [(1, 2, T), (2, 1, F), (1, 1, F), (1, 1.5, T), (2.5, 2, F)],
)
def test_lt_numeric(db, a, b, expected):
    assert db.compare_lt(a, b) is expected


@pytest.mark.parametrize(
    "a,b,expected", [("a", "b", T), ("b", "a", F), ("a", "a", F), ("A", "a", T), ("", "a", T)],
)
def test_lt_text(db, a, b, expected):
    assert db.compare_lt(a, b) is expected


def test_lt_bool(db):
    assert db.compare_lt(False, True) is True
    assert db.compare_lt(True, False) is False


@pytest.mark.parametrize(
    "a,b", [(True, 1), (1, True), ("a", 1), (1, "a"), (True, "a"), ("a", True), (1.5, "a")],
)
def test_compare_type_mismatch(db, a, b):
    with pytest.raises(db.TypeMismatchError):
        db.compare_eq(a, b)
    with pytest.raises(db.TypeMismatchError):
        db.compare_lt(a, b)


# --------------------------------------------------------------------------- #
# 4. arithmetic
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("op", ["+", "-", "*", "/", "%"])
def test_arith_null_propagates(db, op):
    assert db.arith(op, None, 1) is None
    assert db.arith(op, 1, None) is None


@pytest.mark.parametrize(
    "op,a,b,expected",
    [("+", 1, 2, 3), ("-", 5, 2, 3), ("*", 3, 4, 12),
     ("+", 1, 2.0, 3.0), ("*", 2, 0.5, 1.0), ("-", 1.5, 0.5, 1.0)],
)
def test_arith_basic(db, op, a, b, expected):
    got = db.arith(op, a, b)
    assert got == expected
    assert db.type_of(got) == db.type_of(expected)


@pytest.mark.parametrize("a,b,expected", [(7, 2, 3.5), (4, 2, 2.0), (1, 8, 0.125)])
def test_division_is_always_float(db, a, b, expected):
    got = db.arith("/", a, b)
    assert got == expected
    assert db.type_of(got) == "FLOAT"


@pytest.mark.parametrize("a,b", [(1, 0), (1.5, 0), (1, 0.0), (0, 0)])
def test_division_by_zero_is_null(db, a, b):
    assert db.arith("/", a, b) is None


def test_modulo_by_zero_is_null(db):
    assert db.arith("%", 5, 0) is None


@pytest.mark.parametrize("a,b,expected", [(-7, 3, 2), (7, 3, 1), (-7, -3, -1), (7, -3, -2)])
def test_modulo_python_sign(db, a, b, expected):
    assert db.arith("%", a, b) == expected


@pytest.mark.parametrize("a,b", [(1.5, 2), (2, 1.5), (1.0, 1.0)])
def test_modulo_requires_int(db, a, b):
    with pytest.raises(db.TypeMismatchError):
        db.arith("%", a, b)


@pytest.mark.parametrize("op", ["+", "-", "*", "/"])
@pytest.mark.parametrize("bad", ["a", True])
def test_arith_rejects_non_numeric(db, op, bad):
    with pytest.raises(db.TypeMismatchError):
        db.arith(op, bad, 1)


def test_no_string_concat_with_plus(db):
    with pytest.raises(db.TypeMismatchError):
        db.arith("+", "a", "b")


@pytest.mark.parametrize("value,expected", [(3, -3), (-3, 3), (1.5, -1.5), (None, None)])
def test_negate(db, value, expected):
    assert db.negate(value) == expected if expected is not None else db.negate(value) is None


@pytest.mark.parametrize("bad", ["a", True])
def test_negate_rejects_non_numeric(db, bad):
    with pytest.raises(db.TypeMismatchError):
        db.negate(bad)


def test_negate_preserves_int(db):
    assert db.type_of(db.negate(3)) == "INT"


# --------------------------------------------------------------------------- #
# 5. schema
# --------------------------------------------------------------------------- #

def test_table_basic(mk):
    t = mk("t", [("a", "INT")], [[1], [2]])
    assert t.name == "t"
    assert [c.name for c in t.columns] == ["a"]
    assert t.rows == [[1], [2]]


def test_table_column_index(mk):
    t = mk("t", [("a", "INT"), ("b", "TEXT")], [])
    assert t.column_index("b") == 1


def test_table_column_index_unknown(db, mk):
    t = mk("t", [("a", "INT")], [])
    with pytest.raises(db.SchemaError):
        t.column_index("zz")


def test_table_rejects_no_columns(db, mk):
    with pytest.raises(db.SchemaError):
        mk("t", [], [])


def test_table_rejects_duplicate_column(db, mk):
    with pytest.raises(db.SchemaError):
        mk("t", [("a", "INT"), ("a", "TEXT")], [])


def test_table_column_names_are_case_sensitive(mk):
    t = mk("t", [("a", "INT"), ("A", "INT")], [[1, 2]])
    assert t.column_index("A") == 1


@pytest.mark.parametrize("bad", ["NUMBER", "int", "STRING", ""])
def test_table_rejects_unknown_type(db, mk, bad):
    with pytest.raises(db.SchemaError):
        mk("t", [("a", bad)], [])


@pytest.mark.parametrize("row", [[], [1, 2], [1, 2, 3]])
def test_table_rejects_bad_row_width(db, mk, row):
    with pytest.raises(db.SchemaError):
        mk("t", [("a", "INT")], [row])


@pytest.mark.parametrize(
    "type_name,cell",
    [("INT", True), ("INT", 1.0), ("INT", "1"), ("TEXT", 1), ("BOOL", 1),
     ("BOOL", "true"), ("FLOAT", "1.0"), ("FLOAT", True)],
)
def test_table_rejects_wrong_cell_type(db, mk, type_name, cell):
    with pytest.raises(db.SchemaError):
        mk("t", [("a", type_name)], [[cell]])


def test_float_column_widens_int(mk):
    t = mk("t", [("a", "FLOAT")], [[3]])
    assert t.rows == [[3.0]]
    assert isinstance(t.rows[0][0], float)


def test_null_allowed_in_every_type(mk):
    for type_name in ("INT", "FLOAT", "TEXT", "BOOL"):
        t = mk("t", [("a", type_name)], [[None]])
        assert t.rows == [[None]]


# --------------------------------------------------------------------------- #
# 6. lexer
# --------------------------------------------------------------------------- #

def test_tokenize_simple(db):
    """Four tokens. The kind vocabulary is not specified, so it is not asserted."""
    assert len(texts(db.tokenize("SELECT a FROM t"))) == 4


def test_keywords_are_case_insensitive(db):
    """`select` is one token recognised as the SELECT keyword, however kinds are named."""
    got = texts(db.tokenize("select"))
    assert len(got) == 1
    assert str(got[0]).upper() == "SELECT"


def test_identifiers_are_case_sensitive(db):
    assert texts(db.tokenize("Abc")) == ["Abc"]


@pytest.mark.parametrize("src,value", [("1", 1), ("42", 42), ("0", 0)])
def test_int_literals(db, src, value):
    tok = db.tokenize(src)[0]
    assert tok_field(tok, "value", "text") in (value, str(value))


@pytest.mark.parametrize("src,value", [("1.5", 1.5), ("1.", 1.0), (".5", 0.5),
                                       ("1e3", 1000.0), ("1.5E-2", 0.015)])
def test_float_literals(db, src, value):
    tok = db.tokenize(src)[0]
    assert float(tok_field(tok, "value", "text")) == value


def test_text_literal(db):
    tok = db.tokenize("'hi'")[0]
    assert tok_field(tok, "value", "text") == "hi"


def test_text_literal_escaped_quote(db):
    assert tok_field(db.tokenize("'a''b'")[0], "value", "text") == "a'b"


def test_text_literal_empty(db):
    assert tok_field(db.tokenize("''")[0], "value", "text") == ""


def test_comment_is_skipped(db):
    assert texts(db.tokenize("a -- comment\nb")) == ["a", "b"]


@pytest.mark.parametrize("op", ["=", "<>", "<", "<=", ">", ">=", "+", "-", "*", "/", "%"])
def test_operators(db, op):
    """The rule under test is that each operator lexes as exactly one token."""
    toks = [t for t in db.tokenize(op)
            if str(tok_field(t, "kind", "type")).upper() not in ("EOF", "END", "EOI")]
    assert len(toks) == 1
    assert tok_field(toks[0], "text", "value") == op


def test_unterminated_text_raises(db):
    with pytest.raises(db.LexError):
        db.tokenize("'abc")


@pytest.mark.parametrize("src,offset", [("#", 0), ("a #", 2), ("SELECT $", 7)])
def test_lex_error_offset(db, src, offset):
    with pytest.raises(db.LexError) as info:
        db.tokenize(src)
    assert info.value.offset == offset


# --------------------------------------------------------------------------- #
# 7. parser
# --------------------------------------------------------------------------- #

def test_parse_minimal(db):
    """Only that a minimal query parses; Query's field names are unspecified."""
    assert db.parse("SELECT a FROM t") is not None


def test_parse_distinct(db):
    assert db.parse("SELECT DISTINCT a FROM t") is not None


def test_parse_limit_offset(db):
    assert db.parse("SELECT a FROM t LIMIT 5 OFFSET 2") is not None


def test_parse_order_by_directions(db):
    """ASC and DESC parse; the SortKey field name is not specified."""
    assert db.parse("SELECT a FROM t ORDER BY a DESC, b ASC") is not None


@pytest.mark.parametrize("src", ["SELECT a FROM t WHERE 1 < 2 < 3",
                                 "SELECT a FROM t WHERE 1 = 2 = 3",
                                 "SELECT a FROM t WHERE 1 < 2 >= 3"])
def test_comparison_not_associative(db, src):
    with pytest.raises(db.ParseError):
        db.parse(src)


@pytest.mark.parametrize(
    "src",
    ["SELECT FROM t", "SELECT a", "SELECT a FROM", "FROM t", "SELECT a FROM t WHERE",
     "SELECT a FROM t LIMIT", "SELECT a FROM t LIMIT x", "SELECT a FROM t ORDER a",
     "SELECT a FROM t GROUP a", "SELECT a FROM t JOIN u", "SELECT a FROM t extra",
     "SELECT a FROM t WHERE (a = 1", "SELECT a, FROM t"],
)
def test_parse_errors(db, src):
    with pytest.raises((db.ParseError, db.LexError)):
        db.parse(src)


def test_parse_error_has_offset(db):
    with pytest.raises(db.ParseError) as info:
        db.parse("SELECT a FROM t extra")
    assert isinstance(info.value.offset, int)


def test_negative_limit_rejected(db):
    with pytest.raises(db.ParseError):
        db.parse("SELECT a FROM t LIMIT -1")


def test_nested_aggregate_rejected(db):
    """task.md 7.9 calls this a ParseError; AggregateError is equally defensible."""
    with pytest.raises((db.ParseError, db.AggregateError)):
        db.parse("SELECT sum(count(a)) FROM t")


def test_aggregate_in_where_rejected(db):
    with pytest.raises((db.AggregateError, db.ParseError)):
        db.parse("SELECT a FROM t WHERE count(a) > 0")


def test_column_named_keyword_rejected(db):
    with pytest.raises(db.ParseError):
        db.parse("SELECT order FROM t")


# --------------------------------------------------------------------------- #
# 8. projection and expressions
# --------------------------------------------------------------------------- #

def test_select_star_columns(run):
    assert run("SELECT * FROM p").columns == ["id", "name", "age", "score"]


def test_select_column_subset(run):
    assert run("SELECT name, id FROM p").columns == ["name", "id"]


def test_alias_names_output(run):
    assert run("SELECT id AS n FROM p").columns == ["n"]


def test_expression_output_name(run):
    assert run("SELECT age + 1 FROM p").columns == ["age + 1"]


def test_expression_output_name_collapses_space(run):
    assert run("SELECT age   +    1 FROM p").columns == ["age + 1"]


def test_aggregate_output_name(run):
    assert run("SELECT count(*) FROM p").columns == ["count(*)"]


def test_qualified_column(run):
    """Either the bare name or the source text is a defensible output name."""
    assert run("SELECT p.id FROM p").columns[0] in ("id", "p.id")


def test_unknown_column(db, run):
    with pytest.raises(db.UnknownColumnError):
        run("SELECT nope FROM p")


def test_unknown_table_in_reference(db, run):
    with pytest.raises(db.UnknownTableError):
        run("SELECT q.id FROM p")


def test_unknown_table_in_from(db, run):
    with pytest.raises(db.UnknownTableError):
        run("SELECT id FROM zz")


@pytest.mark.parametrize(
    "expr,expected",
    [("1 + 2", 3), ("2 * 3", 6), ("7 / 2", 3.5), ("7 % 2", 1), ("- 3", -3),
     ("(1 + 2) * 3", 9), ("1 + 2 * 3", 7), ("abs(- 4)", 4), ("length('abc')", 3),
     ("upper('ab')", "AB"), ("lower('AB')", "ab"), ("concat('a', 'b')", "ab"),
     ("concat('a', 'b', 'c')", "abc"), ("coalesce(NULL, 2)", 2),
     ("coalesce(NULL, NULL)", None), ("coalesce(1, 2)", 1)],
)
def test_scalar_expressions(run, expr, expected):
    assert run(f"SELECT {expr} FROM p LIMIT 1").rows[0][0] == expected


@pytest.mark.parametrize("expr", ["upper(NULL)", "lower(NULL)", "length(NULL)",
                                  "abs(NULL)", "concat('a', NULL)", "concat(NULL, 'a')"])
def test_scalar_null_propagation(run, expr):
    assert run(f"SELECT {expr} FROM p LIMIT 1").rows[0][0] is None


@pytest.mark.parametrize("expr", ["upper(1)", "length(1)", "abs('a')", "concat('a', 1)",
                                  "upper(TRUE)"])
def test_scalar_type_errors(db, run, expr):
    with pytest.raises(db.TypeMismatchError):
        run(f"SELECT {expr} FROM p")


@pytest.mark.parametrize("expr", ["upper()", "upper('a', 'b')", "length()",
                                  "abs()", "concat('a')", "coalesce()"])
def test_scalar_arity_errors(db, run, expr):
    with pytest.raises(db.ArityError):
        run(f"SELECT {expr} FROM p")


@pytest.mark.parametrize("expr", ["sqrt(1)", "nope('a')", "COUNTX(1)"])
def test_unknown_function(db, run, expr):
    with pytest.raises(db.UnknownFunctionError):
        run(f"SELECT {expr} FROM p")


@pytest.mark.parametrize("name", ["UPPER", "Upper", "upper"])
def test_function_names_case_insensitive(run, name):
    assert run(f"SELECT {name}('a') FROM p LIMIT 1").rows[0][0] == "A"


# --------------------------------------------------------------------------- #
# 9. WHERE
# --------------------------------------------------------------------------- #

def test_where_true_only(run):
    assert [r[0] for r in run("SELECT id FROM p WHERE age > 30").rows] == [3]


@pytest.mark.parametrize("cond", ["age = NULL", "age <> NULL", "age > NULL", "NULL = NULL"])
def test_where_unknown_drops_all(run, cond):
    assert run(f"SELECT id FROM p WHERE {cond}").rows == []


def test_where_is_null(run):
    assert [r[0] for r in run("SELECT id FROM p WHERE age IS NULL").rows] == [2]


def test_where_is_not_null(run):
    assert [r[0] for r in run("SELECT id FROM p WHERE age IS NOT NULL").rows] == [1, 3, 4]


def test_where_and_short_circuit_semantics(run):
    out = run("SELECT id FROM p WHERE age IS NULL AND name = 'bob'").rows
    assert [r[0] for r in out] == [2]


def test_where_false_and_unknown_is_false(run):
    assert run("SELECT id FROM p WHERE id < 0 AND age = NULL").rows == []


def test_where_true_or_unknown_is_true(run):
    out = run("SELECT id FROM p WHERE id = 1 OR age = NULL").rows
    assert [r[0] for r in out] == [1]


def test_where_not_unknown_stays_unknown(run):
    assert run("SELECT id FROM p WHERE NOT age = NULL").rows == []


@pytest.mark.parametrize("cond", ["1", "'a'", "age", "age + 1"])
def test_where_requires_bool(db, run, cond):
    with pytest.raises(db.TypeMismatchError):
        run(f"SELECT id FROM p WHERE {cond}")


def test_where_cannot_see_alias(db, run):
    with pytest.raises(db.UnknownColumnError):
        run("SELECT age AS a FROM p WHERE a > 10")


def test_not_binds_looser_than_comparison(run):
    out = run("SELECT id FROM p WHERE NOT id = 1").rows
    assert [r[0] for r in out] == [2, 3, 4]


# --------------------------------------------------------------------------- #
# 10. aggregates
# --------------------------------------------------------------------------- #

def test_count_star(run):
    assert run("SELECT count(*) FROM p").rows == [[4]]


def test_count_column_skips_nulls(run):
    assert run("SELECT count(age) FROM p").rows == [[3]]


def test_count_of_all_null_column(mk, db):
    t = mk("t", [("a", "INT")], [[None], [None]])
    assert db.execute("SELECT count(a) FROM t", {"t": t}).rows == [[0]]


def test_count_star_counts_all_null_rows(mk, db):
    t = mk("t", [("a", "INT")], [[None], [None]])
    assert db.execute("SELECT count(*) FROM t", {"t": t}).rows == [[2]]


def test_sum_int(run):
    assert run("SELECT sum(age) FROM p").rows == [[100]]


def test_sum_int_type_is_int(db, run):
    assert db.type_of(run("SELECT sum(age) FROM p").rows[0][0]) == "INT"


def test_sum_float_type_is_float(db, run):
    assert db.type_of(run("SELECT sum(score) FROM p").rows[0][0]) == "FLOAT"


def test_avg_is_float(db, run):
    got = run("SELECT avg(age) FROM p").rows[0][0]
    assert db.type_of(got) == "FLOAT"
    assert got == 100 / 3


def test_avg_divides_by_non_null_count(run):
    assert run("SELECT avg(age) FROM p").rows[0][0] == pytest.approx(33.3333333, rel=1e-6)


def test_min_max(run):
    assert run("SELECT min(age), max(age) FROM p").rows == [[30, 40]]


def test_min_max_text(run):
    assert run("SELECT min(name), max(name) FROM p").rows == [["ann", "cid"]]


@pytest.mark.parametrize("fn", ["sum", "avg", "min", "max"])
def test_aggregate_of_empty_is_null(mk, db, fn):
    t = mk("t", [("a", "INT")], [])
    assert db.execute(f"SELECT {fn}(a) FROM t", {"t": t}).rows == [[None]]


@pytest.mark.parametrize("fn", ["sum", "avg", "min", "max"])
def test_aggregate_of_all_null_is_null(mk, db, fn):
    t = mk("t", [("a", "INT")], [[None], [None]])
    assert db.execute(f"SELECT {fn}(a) FROM t", {"t": t}).rows == [[None]]


def test_count_of_empty_is_zero(mk, db):
    t = mk("t", [("a", "INT")], [])
    assert db.execute("SELECT count(*) FROM t", {"t": t}).rows == [[0]]


def test_aggregate_over_empty_yields_exactly_one_row(mk, db):
    t = mk("t", [("a", "INT")], [])
    assert len(db.execute("SELECT count(*), sum(a) FROM t", {"t": t}).rows) == 1


def test_group_by_over_empty_yields_no_rows(mk, db):
    t = mk("t", [("a", "INT")], [])
    assert db.execute("SELECT count(*) FROM t GROUP BY a", {"t": t}).rows == []


@pytest.mark.parametrize("fn", ["sum", "avg"])
def test_sum_avg_reject_text(db, run, fn):
    with pytest.raises(db.TypeMismatchError):
        run(f"SELECT {fn}(name) FROM p")


def test_min_max_reject_mixed_types(mk, db):
    """coalesce yields TEXT for row 1 and INT for row 2, so min() sees both."""
    t = mk("t", [("a", "TEXT"), ("b", "INT")], [["x", 1], [None, 2]])
    with pytest.raises(db.TypeMismatchError):
        db.execute("SELECT min(coalesce(a, b)) FROM t", {"t": t})


@pytest.mark.parametrize("name", ["COUNT", "Sum", "AVG", "Min", "mAx"])
def test_aggregate_names_case_insensitive(run, name):
    assert len(run(f"SELECT {name}(age) FROM p").rows) == 1


# --------------------------------------------------------------------------- #
# 11. GROUP BY and HAVING
# --------------------------------------------------------------------------- #

def test_group_by_counts(run):
    out = run("SELECT age, count(*) FROM p GROUP BY age").rows
    assert out == [[30, 2], [None, 1], [40, 1]]


def test_group_order_is_first_appearance(run):
    assert [r[0] for r in run("SELECT age, count(*) FROM p GROUP BY age").rows] == [30, None, 40]


def test_groups_are_not_sorted(mk, db):
    t = mk("t", [("a", "INT")], [[3], [1], [2], [1]])
    assert [r[0] for r in db.execute("SELECT a, count(*) FROM t GROUP BY a", {"t": t}).rows] == [
        3,
        1,
        2,
    ]


def test_nulls_group_together(mk, db):
    t = mk("t", [("a", "INT")], [[None], [1], [None]])
    out = db.execute("SELECT a, count(*) FROM t GROUP BY a", {"t": t}).rows
    assert out == [[None, 2], [1, 1]]


def test_group_by_expression(run):
    out = run("SELECT length(name), count(*) FROM p GROUP BY length(name)").rows
    assert out == [[3, 3], [None, 1]]


def test_group_by_multiple_keys(mk, db):
    t = mk("t", [("a", "INT"), ("b", "INT")], [[1, 1], [1, 2], [1, 1]])
    out = db.execute("SELECT a, b, count(*) FROM t GROUP BY a, b", {"t": t}).rows
    assert out == [[1, 1, 2], [1, 2, 1]]


def test_grouping_error_for_bare_column(db, run):
    with pytest.raises(db.GroupingError):
        run("SELECT name, id FROM p GROUP BY name")


def test_grouping_error_for_star(db, run):
    with pytest.raises(db.GroupingError):
        run("SELECT * FROM p GROUP BY age")


def test_grouping_error_mixing_bare_column_with_aggregate(db, run):
    with pytest.raises(db.GroupingError):
        run("SELECT id, count(*) FROM p")


def test_having_filters_groups(run):
    out = run("SELECT age, count(*) FROM p GROUP BY age HAVING count(*) > 1").rows
    assert out == [[30, 2]]


def test_having_unknown_drops_group(mk, db):
    t = mk("t", [("a", "INT"), ("b", "INT")], [[1, None], [2, 5]])
    out = db.execute("SELECT a, sum(b) FROM t GROUP BY a HAVING sum(b) > 1", {"t": t}).rows
    assert out == [[2, 5]]


def test_having_may_reference_aggregate_not_in_select(run):
    out = run("SELECT age FROM p GROUP BY age HAVING count(*) > 1").rows
    assert out == [[30]]


def test_having_without_grouping_is_consistent(db, run):
    """task.md does not define HAVING without grouping, so either behaviour passes."""
    try:
        result = run("SELECT id FROM p HAVING id > 1")
    except db.MicroDBError:
        return
    assert isinstance(result.rows, list)


# --------------------------------------------------------------------------- #
# 12. ORDER BY, DISTINCT, LIMIT
# --------------------------------------------------------------------------- #

def test_order_by_asc_nulls_last(run):
    assert [r[0] for r in run("SELECT age FROM p ORDER BY age").rows] == [30, 30, 40, None]


def test_order_by_desc_nulls_last(run):
    assert [r[0] for r in run("SELECT age FROM p ORDER BY age DESC").rows] == [40, 30, 30, None]


def test_order_by_text(run):
    out = [r[0] for r in run("SELECT name FROM p ORDER BY name").rows]
    assert out == ["ann", "bob", "cid", None]


def test_order_by_is_stable(run):
    out = [r[0] for r in run("SELECT id, age FROM p ORDER BY age").rows]
    assert out == [1, 4, 3, 2]


def test_order_by_desc_is_stable(mk, db):
    t = mk("t", [("k", "INT"), ("id", "INT")], [[1, 1], [1, 2], [2, 3]])
    out = [r[1] for r in db.execute("SELECT k, id FROM t ORDER BY k DESC", {"t": t}).rows]
    assert out == [3, 1, 2]


def test_order_by_multiple_keys(mk, db):
    t = mk("t", [("a", "INT"), ("b", "INT")], [[1, 2], [1, 1], [0, 9]])
    out = db.execute("SELECT a, b FROM t ORDER BY a, b", {"t": t}).rows
    assert out == [[0, 9], [1, 1], [1, 2]]


def test_order_by_mixed_directions(mk, db):
    t = mk("t", [("a", "INT"), ("b", "INT")], [[1, 1], [1, 2], [0, 3]])
    out = db.execute("SELECT a, b FROM t ORDER BY a ASC, b DESC", {"t": t}).rows
    assert out == [[0, 3], [1, 2], [1, 1]]


def test_order_by_alias(run):
    assert [r[0] for r in run("SELECT age AS a FROM p ORDER BY a DESC").rows] == [
        40, 30, 30, None
    ]


def test_order_by_alias_shadows_input_column(run):
    out = [r[0] for r in run("SELECT age AS id FROM p ORDER BY id").rows]
    assert out == [30, 30, 40, None]


def test_order_by_expression(run):
    out = [r[0] for r in run("SELECT id FROM p ORDER BY age DESC, id").rows]
    assert out == [3, 1, 4, 2]


def test_order_by_type_mismatch(mk, db):
    """The projected column holds a TEXT and an INT, so sorting it must raise."""
    t = mk("t", [("a", "TEXT"), ("b", "INT")], [["x", 1], [None, 2]])
    with pytest.raises(db.TypeMismatchError):
        db.execute("SELECT coalesce(a, b) AS c FROM t ORDER BY c", {"t": t})


def test_distinct_removes_duplicates(run):
    assert [r[0] for r in run("SELECT DISTINCT age FROM p").rows] == [30, None, 40]


def test_distinct_treats_nulls_as_equal(mk, db):
    t = mk("t", [("a", "INT")], [[None], [None], [1]])
    assert db.execute("SELECT DISTINCT a FROM t", {"t": t}).rows == [[None], [1]]


def test_distinct_on_multiple_columns(mk, db):
    t = mk("t", [("a", "INT"), ("b", "INT")], [[1, 1], [1, 1], [1, 2]])
    assert db.execute("SELECT DISTINCT a, b FROM t", {"t": t}).rows == [[1, 1], [1, 2]]


def test_distinct_then_order_by(run):
    out = [r[0] for r in run("SELECT DISTINCT age FROM p ORDER BY age").rows]
    assert out == [30, 40, None]


@pytest.mark.parametrize(
    "clause,expected",
    [("LIMIT 2", [1, 2]), ("LIMIT 0", []), ("OFFSET 2", [3, 4]),
     ("LIMIT 2 OFFSET 1", [2, 3]), ("OFFSET 10", []), ("LIMIT 10", [1, 2, 3, 4])],
)
def test_limit_offset(run, clause, expected):
    out = [r[0] for r in run(f"SELECT id FROM p ORDER BY id {clause}").rows]
    assert out == expected


def test_offset_applied_before_limit(run):
    out = [r[0] for r in run("SELECT id FROM p ORDER BY id LIMIT 1 OFFSET 3").rows]
    assert out == [4]


# --------------------------------------------------------------------------- #
# 13. joins
# --------------------------------------------------------------------------- #

@pytest.fixture
def joined(mk):
    left = mk("l", [("id", "INT"), ("n", "TEXT")], [[1, "a"], [2, "b"], [3, "c"]])
    right = mk("r", [("lid", "INT"), ("v", "INT")], [[1, 10], [1, 20], [2, 30]])
    return {"l": left, "r": right}


def test_inner_join(db, joined):
    out = db.execute("SELECT l.n, r.v FROM l JOIN r ON l.id = r.lid", joined).rows
    assert out == [["a", 10], ["a", 20], ["b", 30]]


def test_inner_join_keyword_form(db, joined):
    out = db.execute("SELECT l.n FROM l INNER JOIN r ON l.id = r.lid", joined).rows
    assert out == [["a"], ["a"], ["b"]]


def test_left_join_fills_nulls(db, joined):
    out = db.execute("SELECT l.n, r.v FROM l LEFT JOIN r ON l.id = r.lid", joined).rows
    assert out == [["a", 10], ["a", 20], ["b", 30], ["c", None]]


def test_join_row_order_is_left_major(db, joined):
    out = db.execute("SELECT l.id, r.v FROM l JOIN r ON l.id = r.lid", joined).rows
    assert [r[1] for r in out] == [10, 20, 30]


def test_join_column_order(db, joined):
    assert db.execute("SELECT * FROM l JOIN r ON l.id = r.lid", joined).columns == [
        "id", "n", "lid", "v"
    ]


def test_join_unknown_condition_drops_row(db, mk):
    left = mk("l", [("id", "INT")], [[1], [None]])
    right = mk("r", [("lid", "INT")], [[1]])
    out = db.execute("SELECT l.id FROM l JOIN r ON l.id = r.lid", {"l": left, "r": right}).rows
    assert out == [[1]]


def test_left_join_unknown_condition_keeps_left(db, mk):
    left = mk("l", [("id", "INT")], [[None]])
    right = mk("r", [("lid", "INT")], [[1]])
    out = db.execute(
        "SELECT l.id, r.lid FROM l LEFT JOIN r ON l.id = r.lid", {"l": left, "r": right}
    ).rows
    assert out == [[None, None]]


def test_ambiguous_column(db, mk):
    a = mk("a", [("x", "INT")], [[1]])
    b = mk("b", [("x", "INT")], [[1]])
    with pytest.raises(db.AmbiguousColumnError):
        db.execute("SELECT x FROM a JOIN b ON a.x = b.x", {"a": a, "b": b})


def test_unqualified_unique_column_resolves(db, joined):
    out = db.execute("SELECT n FROM l JOIN r ON l.id = r.lid", joined).rows
    assert out == [["a"], ["a"], ["b"]]


def test_join_with_group_by(db, joined):
    out = db.execute(
        "SELECT n, count(v) FROM l LEFT JOIN r ON l.id = r.lid GROUP BY n", joined
    ).rows
    assert out == [["a", 2], ["b", 1], ["c", 0]]


def test_join_with_having(db, joined):
    out = db.execute(
        "SELECT n, sum(v) FROM l LEFT JOIN r ON l.id = r.lid GROUP BY n HAVING sum(v) > 25",
        joined,
    ).rows
    assert out == [["a", 30], ["b", 30]]


def test_star_table_qualified(db, joined):
    assert db.execute("SELECT l.* FROM l JOIN r ON l.id = r.lid", joined).columns == ["id", "n"]


def test_join_unknown_table(db, joined):
    with pytest.raises(db.UnknownTableError):
        db.execute("SELECT l.id FROM l JOIN zz ON l.id = zz.x", joined)


# --------------------------------------------------------------------------- #
# 14. planner
# --------------------------------------------------------------------------- #

#: task.md requires "a sequence of named stage objects" but never fixes the
#: vocabulary, so each stage name is mapped to the pipeline role it denotes.
_STAGE_ROLES = {
    "scan": "scan", "from": "scan", "source": "scan", "table": "scan", "fromstage": "scan",
    "join": "join", "joinstage": "join",
    "filter": "filter", "where": "filter", "wherestage": "filter",
    "group": "group", "groupby": "group", "group_by": "group", "groupbystage": "group",
    "aggregate": "aggregate", "agg": "aggregate", "aggregatestage": "aggregate",
    "having": "having", "havingstage": "having",
    "project": "project", "select": "project", "projection": "project",
    "selectstage": "project", "projectstage": "project",
    "distinct": "distinct", "distinctstage": "distinct",
    "sort": "sort", "order": "sort", "orderby": "sort", "order_by": "sort",
    "orderbystage": "sort", "sortstage": "sort",
    "offset": "offset", "limit": "limit",
    "limitoffset": "limit_offset", "limit_offset": "limit_offset",
    "limitoffsetstage": "limit_offset", "slice": "limit_offset",
}


def plan_roles(db, sql):
    """Pipeline roles in plan order, normalised across naming conventions."""
    obj = db.plan(db.parse(sql))
    stages = list(obj) if hasattr(obj, "__iter__") else list(getattr(obj, "stages"))
    roles = []
    for stage in stages:
        raw = None
        for attr in ("name", "kind", "stage", "label"):
            if hasattr(stage, attr):
                raw = str(getattr(stage, attr))
                break
        if raw is None:
            raw = type(stage).__name__
        key = raw.lower().replace(" ", "").replace("-", "")
        roles.append(_STAGE_ROLES.get(key, key))
    return roles


def _before(roles, first, second):
    """True when the first role appears before the second, allowing merged stages."""
    def index_of(role):
        for i, r in enumerate(roles):
            if r == role or (role in ("offset", "limit") and r == "limit_offset"):
                return i
        return None

    a, b = index_of(first), index_of(second)
    assert a is not None, f"{first} missing from {roles}"
    assert b is not None, f"{second} missing from {roles}"
    return a < b


def test_plan_minimal(db):
    assert plan_roles(db, "SELECT a FROM t") == ["scan", "project"]


def test_plan_full_pipeline_order(db):
    """Every stage the spec names appears, in order.

    Grouping and aggregation may be one stage or two: section 8 lists logical
    steps, not a required number of stage objects. The same applies to
    LIMIT with OFFSET. Only the relative order is asserted.
    """
    roles = plan_roles(
        db,
        "SELECT DISTINCT a, count(*) FROM t JOIN u ON t.a = u.b WHERE a > 0 "
        "GROUP BY a HAVING count(*) > 1 ORDER BY a LIMIT 2 OFFSET 1",
    )
    order = ["scan", "join", "filter", "group", "aggregate", "having",
             "project", "distinct", "sort"]
    positions = [roles.index(r) for r in order if r in roles]
    assert positions == sorted(positions)
    for role in ("scan", "join", "filter", "having", "project", "distinct", "sort"):
        assert role in roles, f"{role} missing from {roles}"
    assert "group" in roles or "aggregate" in roles, f"no grouping stage in {roles}"


def test_plan_filter_before_group(db):
    assert _before(plan_roles(db, "SELECT a, count(*) FROM t WHERE a > 0 GROUP BY a"),
                   "filter", "group")


def test_plan_project_before_sort(db):
    assert _before(plan_roles(db, "SELECT a FROM t ORDER BY a"), "project", "sort")


def test_plan_distinct_before_sort(db):
    assert _before(plan_roles(db, "SELECT DISTINCT a FROM t ORDER BY a"), "distinct", "sort")


def test_plan_slice_after_sort(db):
    roles = plan_roles(db, "SELECT a FROM t ORDER BY a LIMIT 1 OFFSET 1")
    assert _before(roles, "sort", "offset")


def test_plan_adds_aggregate_stage_without_group_by(db):
    """An aggregate with no GROUP BY still needs a grouping step in the plan."""
    roles = plan_roles(db, "SELECT count(*) FROM t")
    assert "aggregate" in roles or "group" in roles, roles


def test_plan_has_no_group_stage_for_plain_query(db):
    assert "group" not in plan_roles(db, "SELECT a FROM t")


def test_execute_plan_matches_execute(db, people):
    q = db.parse("SELECT age FROM p ORDER BY age")
    direct = db.execute("SELECT age FROM p ORDER BY age", {"p": people})
    staged = db.execute_plan(db.plan(q), {"p": people})
    assert (direct.columns, direct.rows) == (staged.columns, staged.rows)


# --------------------------------------------------------------------------- #
# 15. CLI
# --------------------------------------------------------------------------- #

@pytest.fixture
def csv_table(tmp_path):
    path = tmp_path / "people.csv"
    path.write_text("id:INT,name:TEXT,age:INT\n1,ann,30\n2,bob,\n3,cid,40\n", encoding="utf-8")
    return path


def test_cli_basic(csv_table):
    done = cli("--table", f"t={csv_table}", "SELECT count(*) FROM t WHERE age > 30")
    assert done.returncode == 0
    assert done.stdout.splitlines() == ["count(*)", "1"]


def test_cli_header_names(csv_table):
    done = cli("--table", f"t={csv_table}", "SELECT id, name FROM t ORDER BY id LIMIT 1")
    assert done.stdout.splitlines() == ["id,name", "1,ann"]


def test_cli_null_is_empty_field(csv_table):
    done = cli("--table", f"t={csv_table}", "SELECT age FROM t WHERE id = 2")
    assert done.stdout.splitlines() == ["age", ""]


def test_cli_bool_lowercase(tmp_path):
    path = tmp_path / "b.csv"
    path.write_text("f:BOOL\ntrue\nfalse\n", encoding="utf-8")
    done = cli("--table", f"t={path}", "SELECT f FROM t")
    assert done.stdout.splitlines() == ["f", "true", "false"]


def test_cli_bool_input_case_insensitive(tmp_path):
    path = tmp_path / "b.csv"
    path.write_text("f:BOOL\nTRUE\n", encoding="utf-8")
    done = cli("--table", f"t={path}", "SELECT f FROM t")
    assert done.stdout.splitlines() == ["f", "true"]


def test_cli_two_tables(tmp_path):
    left = tmp_path / "l.csv"
    left.write_text("id:INT\n1\n", encoding="utf-8")
    right = tmp_path / "r.csv"
    right.write_text("lid:INT\n1\n", encoding="utf-8")
    done = cli(
        "--table", f"l={left}", "--table", f"r={right}",
        "SELECT l.id FROM l JOIN r ON l.id = r.lid",
    )
    assert done.returncode == 0
    assert done.stdout.splitlines() == ["id", "1"]


@pytest.mark.parametrize(
    "args",
    [(), ("SELECT 1 FROM t",), ("--table", "t", "SELECT 1 FROM t"),
     ("--table", "=x.csv", "SELECT 1 FROM t")],
)
def test_cli_usage_errors_exit_two(args):
    assert cli(*args).returncode == 2


def test_cli_missing_file_exit_two(tmp_path):
    done = cli("--table", f"t={tmp_path / 'nope.csv'}", "SELECT 1 FROM t")
    assert done.returncode == 2


def test_cli_bad_header_exit_two(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("id,name\n1,x\n", encoding="utf-8")
    assert cli("--table", f"t={path}", "SELECT id FROM t").returncode == 2


def test_cli_unknown_type_in_header_exit_two(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("id:NUMBER\n1\n", encoding="utf-8")
    assert cli("--table", f"t={path}", "SELECT id FROM t").returncode == 2


@pytest.mark.parametrize(
    "query",
    ["SELECT nope FROM t", "SELECT id FROM zz", "SELECT id FROM t WHERE 1",
     "SELECT sqrt(id) FROM t", "SELECT id, count(*) FROM t"],
)
def test_cli_query_error_exit_three(csv_table, query):
    done = cli("--table", f"t={csv_table}", query)
    assert done.returncode == 3
    assert done.stdout == ""


def test_cli_lex_error_exit_three(csv_table):
    done = cli("--table", f"t={csv_table}", "SELECT # FROM t")
    assert done.returncode == 3


def test_cli_error_message_on_stderr(csv_table):
    done = cli("--table", f"t={csv_table}", "SELECT nope FROM t")
    assert done.stderr.strip() != ""


def test_cli_main_returns_int(db):
    module = importlib.import_module("microdb.__main__")
    assert callable(module.main)


# --------------------------------------------------------------------------- #
# 16. package surface and hygiene
# --------------------------------------------------------------------------- #

def test_all_exists_and_is_non_empty():
    """task.md asks __init__ to carry __all__ but never enumerates it."""
    pkg = importlib.import_module("microdb")
    assert isinstance(pkg.__all__, (list, tuple))
    assert len(pkg.__all__) > 0


def test_all_names_resolve():
    pkg = importlib.import_module("microdb")
    missing = [n for n in pkg.__all__ if not hasattr(pkg, n)]
    assert missing == []


def test_documented_entry_points_reachable(db):
    """execute, Table and Column are named in the spec's API sections."""
    for name in ("execute", "Table", "Column"):
        assert getattr(db, name) is not None


def test_error_hierarchy(db):
    for name in ["LexError", "ParseError", "SchemaError", "TypeMismatchError",
                 "UnknownColumnError", "AmbiguousColumnError", "UnknownTableError",
                 "UnknownFunctionError", "ArityError", "AggregateError", "GroupingError"]:
        assert issubclass(getattr(db, name), db.MicroDBError), name


def test_positioned_errors_have_offset(db):
    with pytest.raises(db.LexError) as info:
        db.tokenize("@")
    assert hasattr(info.value, "offset")


def test_expected_modules_exist():
    for name in ("__init__", "errors", "value", "schema", "lexer", "parser", "expr",
                 "aggregate", "planner", "executor", "__main__"):
        assert Path("microdb").joinpath(f"{name}.py").is_file(), name


def test_no_forbidden_modules():
    forbidden = {"sqlite3", "pandas", "ast"}
    found = []
    for path in Path(".").rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in forbidden:
            if f"import {name}" in text:
                found.append(f"{path}: {name}")
    assert found == []


def test_no_eval_or_exec():
    hits = []
    for path in Path(".").rglob("*.py"):
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for bad in ("eval(", "exec("):
            for line in text.splitlines():
                stripped = line.strip()
                if bad in stripped and not stripped.startswith(("#", "def ", '"')):
                    if f"def {bad[:-1]}" not in stripped:
                        hits.append(f"{path}: {stripped[:60]}")
    assert hits == []

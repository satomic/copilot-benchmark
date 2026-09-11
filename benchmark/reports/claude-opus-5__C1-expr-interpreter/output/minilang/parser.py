"""Parser: turns a token stream into an AST.

The AST nodes are plain data holders; all behaviour lives in the evaluator.
"""

from .errors import ParseError
from .lexer import tokenize

_COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class Node:
    """Base class for AST nodes."""

    __slots__ = ("position",)

    _fields = ()

    def __repr__(self):
        parts = ", ".join(repr(getattr(self, name)) for name in self._fields)
        return f"{type(self).__name__}({parts})"

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return all(getattr(self, f) == getattr(other, f) for f in self._fields)

    def __hash__(self):
        return hash((type(self).__name__,) + tuple(
            tuple(v) if isinstance(v, list) else v
            for v in (getattr(self, f) for f in self._fields)
        ))


class Literal(Node):
    """A number, string or boolean constant."""

    __slots__ = ("value",)
    _fields = ("value",)

    def __init__(self, value, position=None):
        self.value = value
        self.position = position


class Variable(Node):
    """An identifier looked up in the environment."""

    __slots__ = ("name",)
    _fields = ("name",)

    def __init__(self, name, position=None):
        self.name = name
        self.position = position


class UnaryOp(Node):
    """``-x`` or ``not x``."""

    __slots__ = ("op", "operand")
    _fields = ("op", "operand")

    def __init__(self, op, operand, position=None):
        self.op = op
        self.operand = operand
        self.position = position


class BinaryOp(Node):
    """An arithmetic or comparison operation."""

    __slots__ = ("op", "left", "right")
    _fields = ("op", "left", "right")

    def __init__(self, op, left, right, position=None):
        self.op = op
        self.left = left
        self.right = right
        self.position = position


class LogicalOp(Node):
    """``and`` / ``or`` — kept separate because they short-circuit."""

    __slots__ = ("op", "left", "right")
    _fields = ("op", "left", "right")

    def __init__(self, op, left, right, position=None):
        self.op = op
        self.left = left
        self.right = right
        self.position = position


class Call(Node):
    """A call to a built-in function."""

    __slots__ = ("name", "args")
    _fields = ("name", "args")

    def __init__(self, name, args, position=None):
        self.name = name
        self.args = args
        self.position = position


class _Parser:
    def __init__(self, tokens, end_position):
        self._tokens = tokens
        self._index = 0
        self._end = end_position

    # -- token helpers -------------------------------------------------
    def _peek(self):
        if self._index < len(self._tokens):
            return self._tokens[self._index]
        return None

    def _position(self):
        token = self._peek()
        return self._end if token is None else token.position

    def _describe(self):
        token = self._peek()
        if token is None:
            return "end of input"
        if token.kind == "NUMBER":
            return f"number {token.value!r}"
        if token.kind == "STRING":
            return "string"
        return repr(token.value)

    def _advance(self):
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _check_op(self, *values):
        token = self._peek()
        return token is not None and token.kind == "OP" and token.value in values

    def _check_keyword(self, *values):
        token = self._peek()
        return token is not None and token.kind == "KEYWORD" and token.value in values

    def _expect_op(self, value):
        if not self._check_op(value):
            raise ParseError(
                f"expected {value!r} but found {self._describe()}", self._position()
            )
        return self._advance()

    # -- grammar -------------------------------------------------------
    def parse_program(self):
        if self._peek() is None:
            raise ParseError("unexpected end of input: expected an expression", self._end)
        node = self.parse_expr()
        if self._peek() is not None:
            raise ParseError(
                f"unexpected trailing input: {self._describe()}", self._position()
            )
        return node

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self._check_keyword("or"):
            token = self._advance()
            right = self.parse_and()
            node = LogicalOp("or", node, right, token.position)
        return node

    def parse_and(self):
        node = self.parse_not()
        while self._check_keyword("and"):
            token = self._advance()
            right = self.parse_not()
            node = LogicalOp("and", node, right, token.position)
        return node

    def parse_not(self):
        if self._check_keyword("not"):
            token = self._advance()
            return UnaryOp("not", self.parse_not(), token.position)
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_additive()
        if self._peek() is not None and self._check_op(*_COMPARISON_OPS):
            token = self._advance()
            right = self.parse_additive()
            node = BinaryOp(token.value, node, right, token.position)
            if self._check_op(*_COMPARISON_OPS):
                # Rule 11: comparison operators do not chain.
                raise ParseError(
                    "comparison operators are non-associative", self._position()
                )
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self._check_op("+", "-"):
            token = self._advance()
            right = self.parse_multiplicative()
            node = BinaryOp(token.value, node, right, token.position)
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while self._check_op("*", "/", "%"):
            token = self._advance()
            right = self.parse_unary()
            node = BinaryOp(token.value, node, right, token.position)
        return node

    def parse_unary(self):
        if self._check_op("-"):
            token = self._advance()
            return UnaryOp("-", self.parse_unary(), token.position)
        return self.parse_power()

    def parse_power(self):
        node = self.parse_primary()
        if self._check_op("^"):
            token = self._advance()
            # Right operand is a `unary`, which makes `^` right-associative
            # and allows `2 ^ -1`.
            right = self.parse_unary()
            node = BinaryOp("^", node, right, token.position)
        return node

    def parse_primary(self):
        token = self._peek()
        if token is None:
            raise ParseError("unexpected end of input: expected an expression", self._end)

        if token.kind == "NUMBER" or token.kind == "STRING":
            self._advance()
            return Literal(token.value, token.position)

        if token.kind == "KEYWORD":
            if token.value in ("true", "false"):
                self._advance()
                return Literal(token.value == "true", token.position)
            raise ParseError(
                f"unexpected keyword {token.value!r}", token.position
            )

        if token.kind == "IDENT":
            self._advance()
            if self._check_op("("):
                self._advance()
                args = []
                if not self._check_op(")"):
                    args.append(self.parse_expr())
                    while self._check_op(","):
                        self._advance()
                        args.append(self.parse_expr())
                self._expect_op(")")
                return Call(token.value, args, token.position)
            return Variable(token.value, token.position)

        if token.kind == "OP" and token.value == "(":
            self._advance()
            node = self.parse_expr()
            self._expect_op(")")
            return node

        raise ParseError(f"unexpected token {self._describe()}", token.position)


def parse(source):
    """Parse ``source`` and return the AST root node.

    Parsing performs no evaluation, so ``parse("1 / 0")`` succeeds.
    """
    tokens = tokenize(source)
    return _Parser(tokens, len(source)).parse_program()

"""Recursive-descent parser for minilang.

Grammar (loosest to tightest binding):

    expr          := or_expr
    or_expr       := and_expr ( "or" and_expr )*
    and_expr      := not_expr ( "and" not_expr )*
    not_expr      := "not" not_expr | comparison
    comparison    := additive ( ( "==" | "!=" | "<" | "<=" | ">" | ">=" ) additive )?
    additive      := multiplicative ( ( "+" | "-" ) multiplicative )*
    multiplicative:= unary ( ( "*" | "/" | "%" ) unary )*
    unary         := "-" unary | power
    power         := primary ( "^" unary )?
    primary       := NUMBER | STRING | "true" | "false"
                   | IDENT | IDENT "(" [ expr ( "," expr )* ] ")"
                   | "(" expr ")"
"""

from .errors import ParseError
from .lexer import tokenize

_COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})


class _Node:
    __slots__ = ()


class Num(_Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class Str(_Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class Bool(_Node):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class Var(_Node):
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class Call(_Node):
    __slots__ = ("name", "args")

    def __init__(self, name, args):
        self.name = name
        self.args = args


class Unary(_Node):
    __slots__ = ("op", "operand")

    def __init__(self, op, operand):
        self.op = op
        self.operand = operand


class Binary(_Node):
    __slots__ = ("op", "left", "right")

    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class _Parser:
    def __init__(self, tokens, source):
        self.tokens = tokens
        self.pos = 0
        self.source = source

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def error(self, message, token=None):
        # At end of input, report the position just past the last character.
        position = token.position if token is not None else len(self.source)
        raise ParseError(message, position)

    def is_op(self, token, *ops):
        return token is not None and token.kind == "OP" and token.value in ops

    def is_keyword(self, token, *words):
        return token is not None and token.kind == "KEYWORD" and token.value in words

    # expr := or_expr
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.is_keyword(self.peek(), "or"):
            self.advance()
            left = Binary("or", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.is_keyword(self.peek(), "and"):
            self.advance()
            left = Binary("and", left, self.parse_not())
        return left

    def parse_not(self):
        token = self.peek()
        if self.is_keyword(token, "not"):
            self.advance()
            return Unary("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        token = self.peek()
        if self.is_op(token, *_COMPARISON_OPS):
            op = self.advance().value
            right = self.parse_additive()
            nxt = self.peek()
            if self.is_op(nxt, *_COMPARISON_OPS):
                # Comparison is non-associative: "1 < 2 < 3" is a ParseError.
                raise ParseError("comparison operators are non-associative", nxt.position)
            return Binary(op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.is_op(self.peek(), "+", "-"):
            op = self.advance().value
            left = Binary(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.is_op(self.peek(), "*", "/", "%"):
            op = self.advance().value
            left = Binary(op, left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.is_op(self.peek(), "-"):
            self.advance()
            return Unary("-", self.parse_unary())
        return self.parse_power()

    def parse_power(self):
        # "^" is right-associative and its right operand is a unary, so
        # 2 ^ 3 ^ 2 == 2 ^ (3 ^ 2) and 2 ^ -1 is valid.
        base = self.parse_primary()
        if self.is_op(self.peek(), "^"):
            self.advance()
            return Binary("^", base, self.parse_unary())
        return base

    def parse_primary(self):
        token = self.peek()
        if token is None:
            self.error("unexpected end of input")
        if token.kind == "NUMBER":
            self.advance()
            return Num(token.value)
        if token.kind == "STRING":
            self.advance()
            return Str(token.value)
        if token.kind == "KEYWORD" and token.value in ("true", "false"):
            self.advance()
            return Bool(token.value == "true")
        if token.kind == "IDENT":
            self.advance()
            if self.is_op(self.peek(), "("):
                self.advance()
                args = []
                if not self.is_op(self.peek(), ")"):
                    args.append(self.parse_expr())
                    while self.is_op(self.peek(), ","):
                        self.advance()
                        args.append(self.parse_expr())
                closing = self.peek()
                if not self.is_op(closing, ")"):
                    self.error("expected ')'", closing)
                self.advance()
                return Call(token.value, args)
            return Var(token.value)
        if self.is_op(token, "("):
            self.advance()
            node = self.parse_expr()
            closing = self.peek()
            if not self.is_op(closing, ")"):
                self.error("expected ')'", closing)
            self.advance()
            return node
        self.error(f"unexpected token: {token.value!r}", token)


def parse(source):
    """Parse source into an AST. Never evaluates anything."""
    tokens = tokenize(source)
    parser = _Parser(tokens, source)
    node = parser.parse_expr()
    leftover = parser.peek()
    if leftover is not None:
        raise ParseError(f"unexpected trailing input: {leftover.value!r}", leftover.position)
    return node

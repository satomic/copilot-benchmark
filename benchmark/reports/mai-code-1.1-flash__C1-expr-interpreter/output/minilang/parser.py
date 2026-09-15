from dataclasses import dataclass, field

from .errors import ParseError
from .lexer import Token


@dataclass
class NumberNode:
    value: float


@dataclass
class StringNode:
    value: str


@dataclass
class BoolNode:
    value: bool


@dataclass
class NameNode:
    name: str


@dataclass
class UnaryNode:
    op: str
    operand: object


@dataclass
class BinaryNode:
    op: str
    left: object
    right: object


@dataclass
class CallNode:
    name: str
    args: list[object] = field(default_factory=list)


COMPARATORS = {"==", "!=", "<", "<=", ">", ">="}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    def current(self) -> Token | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current()
        if token is None:
            raise ParseError("unexpected end of input", None)
        self.index += 1
        return token

    def match_keyword(self, *values: str) -> bool:
        token = self.current()
        if token is None or token.kind != "KEYWORD":
            return False
        if token.value in values:
            self.index += 1
            return True
        return False

    def match_op(self, *values: str) -> bool:
        token = self.current()
        if token is None or token.kind != "OP":
            return False
        if token.value in values:
            self.index += 1
            return True
        return False

    def parse(self):
        if not self.tokens:
            raise ParseError("empty input", 0)
        node = self.parse_expr()
        if self.index != len(self.tokens):
            token = self.current()
            raise ParseError("trailing input", token.position if token else 0)
        return node

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.match_keyword("or"):
            node = BinaryNode("or", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.match_keyword("and"):
            node = BinaryNode("and", node, self.parse_not())
        return node

    def parse_not(self):
        if self.match_keyword("not"):
            return UnaryNode("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_additive()
        token = self.current()
        if token is not None and token.kind == "OP" and token.value in COMPARATORS:
            op = self.advance().value
            right = self.parse_additive()
            if self.current() is not None and self.current().kind == "OP" and self.current().value in COMPARATORS:
                raise ParseError("non-associative comparison", self.current().position)
            return BinaryNode(op, node, right)
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while True:
            if self.match_op("+"):
                node = BinaryNode("+", node, self.parse_multiplicative())
            elif self.match_op("-"):
                node = BinaryNode("-", node, self.parse_multiplicative())
            else:
                return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while True:
            if self.match_op("*"):
                node = BinaryNode("*", node, self.parse_unary())
            elif self.match_op("/"):
                node = BinaryNode("/", node, self.parse_unary())
            elif self.match_op("%"):
                node = BinaryNode("%", node, self.parse_unary())
            else:
                return node

    def parse_unary(self):
        if self.match_op("-"):
            return UnaryNode("-", self.parse_unary())
        return self.parse_power()

    def parse_power(self):
        node = self.parse_primary()
        if self.match_op("^"):
            return BinaryNode("^", node, self.parse_unary())
        return node

    def parse_primary(self):
        token = self.current()
        if token is None:
            raise ParseError("unexpected end of input", None)

        if token.kind == "NUMBER":
            self.advance()
            return NumberNode(float(token.value))

        if token.kind == "STRING":
            self.advance()
            return StringNode(token.value)

        if token.kind == "KEYWORD":
            if token.value == "true":
                self.advance()
                return BoolNode(True)
            if token.value == "false":
                self.advance()
                return BoolNode(False)

        if token.kind == "IDENT":
            name = self.advance().value
            if self.match_op("("):
                args = []
                if not self.match_op(")"):
                    while True:
                        args.append(self.parse_expr())
                        if self.match_op(","):
                            continue
                        if not self.match_op(")"):
                            raise ParseError("expected ')'", self.current().position if self.current() else 0)
                        break
                return CallNode(name, args)
            return NameNode(name)

        if self.match_op("("):
            expr = self.parse_expr()
            if not self.match_op(")"):
                raise ParseError("expected ')'", self.current().position if self.current() else 0)
            return expr

        raise ParseError("unexpected token", token.position)


def parse(source: str):
    from .lexer import tokenize

    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse()

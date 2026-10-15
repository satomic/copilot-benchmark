from dataclasses import dataclass
from .errors import ParseError
from .lexer import Token, tokenize

COMPARISON_OPS = frozenset({"==", "!=", "<", "<=", ">", ">="})
ADDITIVE_OPS = frozenset({"+", "-"})
MULTIPLICATIVE_OPS = frozenset({"*", "/", "%"})


@dataclass(frozen=True)
class NumberLiteral:
    value: float
    position: int


@dataclass(frozen=True)
class StringLiteral:
    value: str
    position: int


@dataclass(frozen=True)
class BoolLiteral:
    value: bool
    position: int


@dataclass(frozen=True)
class Identifier:
    name: str
    position: int


@dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: object
    position: int


@dataclass(frozen=True)
class BinaryOp:
    op: str
    left: object
    right: object
    position: int


@dataclass(frozen=True)
class Call:
    name: str
    args: list[object]
    position: int


class _Parser:
    def __init__(self, tokens: list[Token], source_len: int) -> None:
        self.tokens = tokens
        self.source_len = source_len
        self.pos = 0

    def _current(self) -> Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _consume(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _match(self, kind: str, value: str | None = None) -> Token | None:
        tok = self._current()
        if tok is not None and tok.kind == kind and (value is None or tok.value == value):
            self.pos += 1
            return tok
        return None

    def _expect(self, kind: str, value: str) -> Token:
        tok = self._current()
        if tok is None:
            raise ParseError(f"expected {value!r}, got end of input", self.source_len)
        if tok.kind != kind or tok.value != value:
            raise ParseError(f"expected {value!r}, got {tok.value!r}", tok.position)
        self.pos += 1
        return tok

    def parse(self) -> object:
        if not self.tokens:
            raise ParseError("empty expression", self.source_len)
        node = self._parse_expr()
        extra = self._current()
        if extra is not None:
            raise ParseError(f"unexpected token: {extra.value!r}", extra.position)
        return node

    def _parse_expr(self) -> object:
        return self._parse_or()

    def _parse_or(self) -> object:
        node = self._parse_and()
        while (tok := self._match("KEYWORD", "or")) is not None:
            right = self._parse_and()
            node = BinaryOp("or", node, right, tok.position)
        return node

    def _parse_and(self) -> object:
        node = self._parse_not()
        while (tok := self._match("KEYWORD", "and")) is not None:
            right = self._parse_not()
            node = BinaryOp("and", node, right, tok.position)
        return node

    def _parse_not(self) -> object:
        if (tok := self._match("KEYWORD", "not")) is not None:
            operand = self._parse_not()
            return UnaryOp("not", operand, tok.position)
        return self._parse_comparison()

    def _parse_comparison(self) -> object:
        node = self._parse_additive()
        tok = self._current()
        if tok is not None and tok.kind == "OP" and tok.value in COMPARISON_OPS:
            self._consume()
            right = self._parse_additive()
            node = BinaryOp(str(tok.value), node, right, tok.position)
            next_tok = self._current()
            if next_tok is not None and next_tok.kind == "OP" and next_tok.value in COMPARISON_OPS:
                raise ParseError("comparison operators are non-associative", next_tok.position)
        return node

    def _parse_additive(self) -> object:
        node = self._parse_multiplicative()
        while True:
            tok = self._current()
            if tok is not None and tok.kind == "OP" and tok.value in ADDITIVE_OPS:
                self._consume()
                right = self._parse_multiplicative()
                node = BinaryOp(str(tok.value), node, right, tok.position)
            else:
                break
        return node

    def _parse_multiplicative(self) -> object:
        node = self._parse_unary()
        while True:
            tok = self._current()
            if tok is not None and tok.kind == "OP" and tok.value in MULTIPLICATIVE_OPS:
                self._consume()
                right = self._parse_unary()
                node = BinaryOp(str(tok.value), node, right, tok.position)
            else:
                break
        return node

    def _parse_unary(self) -> object:
        if (tok := self._match("OP", "-")) is not None:
            operand = self._parse_unary()
            return UnaryOp("-", operand, tok.position)
        return self._parse_power()

    def _parse_power(self) -> object:
        node = self._parse_primary()
        if (tok := self._match("OP", "^")) is not None:
            right = self._parse_unary()
            node = BinaryOp("^", node, right, tok.position)
        return node

    def _parse_primary(self) -> object:
        tok = self._current()
        if tok is None:
            raise ParseError("unexpected end of input", self.source_len)

        if tok.kind == "NUMBER":
            self._consume()
            return NumberLiteral(float(tok.value), tok.position)

        if tok.kind == "STRING":
            self._consume()
            return StringLiteral(str(tok.value), tok.position)

        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self._consume()
            return BoolLiteral(tok.value == "true", tok.position)

        if tok.kind == "IDENT":
            self._consume()
            name = str(tok.value)
            if self._match("OP", "(") is not None:
                args: list[object] = []
                if self._match("OP", ")") is None:
                    args.append(self._parse_expr())
                    while self._match("OP", ",") is not None:
                        args.append(self._parse_expr())
                    self._expect("OP", ")")
                return Call(name, args, tok.position)
            return Identifier(name, tok.position)

        if tok.kind == "OP" and tok.value == "(":
            self._consume()
            expr = self._parse_expr()
            self._expect("OP", ")")
            return expr

        raise ParseError(f"unexpected token: {tok.value!r}", tok.position)


def parse(source: str) -> object:
    tokens = tokenize(source)
    return _Parser(tokens, len(source)).parse()

from dataclasses import dataclass
from .lexer import tokenize
from .errors import ParseError


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
class IdentNode:
    name: str


@dataclass
class BinOpNode:
    op: str
    left: object
    right: object


@dataclass
class UnaryOpNode:
    op: str
    operand: object


@dataclass
class CallNode:
    name: str
    args: list


@dataclass
class IfNode:
    cond: object
    then_expr: object
    else_expr: object


class Parser:
    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0
    
    def parse(self) -> object:
        if not self.tokens:
            raise ParseError("empty or comment-only source", 0)
        
        expr = self.expr()
        if self.pos < len(self.tokens):
            raise ParseError("trailing input after expression", self.tokens[self.pos].position)
        return expr
    
    def expr(self) -> object:
        return self.or_expr()
    
    def or_expr(self) -> object:
        left = self.and_expr()
        while self._match("KEYWORD", "or"):
            right = self.and_expr()
            left = BinOpNode("or", left, right)
        return left
    
    def and_expr(self) -> object:
        left = self.not_expr()
        while self._match("KEYWORD", "and"):
            right = self.not_expr()
            left = BinOpNode("and", left, right)
        return left
    
    def not_expr(self) -> object:
        if self._match("KEYWORD", "not"):
            operand = self.not_expr()
            return UnaryOpNode("not", operand)
        return self.comparison()
    
    def comparison(self) -> object:
        left = self.additive()
        
        if self._peek() and self._peek().kind == "OP" and self._peek().value in ("==", "!=", "<", "<=", ">", ">="):
            op = self._advance().value
            right = self.additive()
            return BinOpNode(op, left, right)
        
        return left
    
    def additive(self) -> object:
        left = self.multiplicative()
        while self._peek() and self._peek().kind == "OP" and self._peek().value in ("+", "-"):
            op = self._advance().value
            right = self.multiplicative()
            left = BinOpNode(op, left, right)
        return left
    
    def multiplicative(self) -> object:
        left = self.unary()
        while self._peek() and self._peek().kind == "OP" and self._peek().value in ("*", "/", "%"):
            op = self._advance().value
            right = self.unary()
            left = BinOpNode(op, left, right)
        return left
    
    def unary(self) -> object:
        if self._peek() and self._peek().kind == "OP" and self._peek().value == "-":
            self._advance()
            operand = self.unary()
            return UnaryOpNode("-", operand)
        return self.power()
    
    def power(self) -> object:
        left = self.primary()
        if self._peek() and self._peek().kind == "OP" and self._peek().value == "^":
            self._advance()
            right = self.unary()
            return BinOpNode("^", left, right)
        return left
    
    def primary(self) -> object:
        token = self._peek()
        if not token:
            raise ParseError("unexpected end of input", len(self.tokens) > 0 and self.tokens[-1].position or 0)
        
        if token.kind == "NUMBER":
            self._advance()
            return NumberNode(token.value)
        
        if token.kind == "STRING":
            self._advance()
            return StringNode(token.value)
        
        if token.kind == "KEYWORD":
            self._advance()
            return BoolNode(token.value)
        
        if token.kind == "IDENT":
            name = token.value
            ident_pos = self.pos
            self._advance()
            
            if self._peek() and self._peek().kind == "OP" and self._peek().value == "(":
                self._advance()
                args = []
                if self._peek() and not (self._peek().kind == "OP" and self._peek().value == ")"):
                    args.append(self.expr())
                    while self._match("OP", ","):
                        args.append(self.expr())
                
                if not self._match("OP", ")"):
                    raise ParseError("expected ')'", self._peek().position if self._peek() else len(self.tokens))
                
                return CallNode(name, args)
            
            return IdentNode(name)
        
        if token.kind == "OP" and token.value == "(":
            self._advance()
            expr_result = self.expr()
            if not self._match("OP", ")"):
                raise ParseError("expected ')'", self._peek().position if self._peek() else len(self.tokens))
            return expr_result
        
        raise ParseError(f"unexpected token: {token.value}", token.position)
    
    def _peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None
    
    def _advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token
    
    def _match(self, kind: str, value: object = None) -> bool:
        token = self._peek()
        if token and token.kind == kind and (value is None or token.value == value):
            self._advance()
            return True
        return False


def parse(source: str) -> object:
    tokens = tokenize(source)
    parser = Parser(tokens)
    return parser.parse()

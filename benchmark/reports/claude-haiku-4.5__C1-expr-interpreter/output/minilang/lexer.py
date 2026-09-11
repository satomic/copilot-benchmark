import re
from dataclasses import dataclass
from .errors import LexError


@dataclass
class Token:
    kind: str
    value: object
    position: int


class Lexer:
    KEYWORDS = {"true", "false", "and", "or", "not"}
    OPERATORS = {"+", "-", "*", "/", "%", "^", "==", "!=", "<", "<=", ">", ">=", "(", ")", ","}
    
    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.tokens = []
    
    def tokenize(self) -> list:
        while self.pos < len(self.source):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break
            
            if self._try_number():
                continue
            if self._try_string():
                continue
            if self._try_operator():
                continue
            if self._try_ident():
                continue
            
            raise LexError(f"unexpected character: {self.source[self.pos]!r}", self.pos)
        
        return self.tokens
    
    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            if self.source[self.pos] in " \t\n\r":
                self.pos += 1
            elif self.source[self.pos] == "#":
                while self.pos < len(self.source) and self.source[self.pos] != "\n":
                    self.pos += 1
            else:
                break
    
    def _try_number(self) -> bool:
        start = self.pos
        
        if self.pos < len(self.source) and self.source[self.pos] == ".":
            if self.pos + 1 < len(self.source) and self.source[self.pos + 1].isdigit():
                self.pos += 1
                while self.pos < len(self.source) and self.source[self.pos].isdigit():
                    self.pos += 1
                self._finalize_number(start)
                return True
            return False
        
        if self.pos < len(self.source) and self.source[self.pos].isdigit():
            while self.pos < len(self.source) and self.source[self.pos].isdigit():
                self.pos += 1
            
            if self.pos < len(self.source) and self.source[self.pos] == ".":
                self.pos += 1
                if self.pos < len(self.source) and self.source[self.pos].isdigit():
                    while self.pos < len(self.source) and self.source[self.pos].isdigit():
                        self.pos += 1
                elif not (self.pos < len(self.source) and self.source[self.pos] in "eE"):
                    raise LexError("number cannot end with '.'; move to '.' or remove it", self.pos - 1)
            
            if self.pos < len(self.source) and self.source[self.pos] in "eE":
                self.pos += 1
                if self.pos < len(self.source) and self.source[self.pos] in "+-":
                    self.pos += 1
                if self.pos < len(self.source) and self.source[self.pos].isdigit():
                    while self.pos < len(self.source) and self.source[self.pos].isdigit():
                        self.pos += 1
                else:
                    raise LexError("invalid exponent in number", self.pos - 1)
            
            self._finalize_number(start)
            return True
        
        return False
    
    def _finalize_number(self, start: int):
        num_str = self.source[start:self.pos]
        value = float(num_str)
        self.tokens.append(Token("NUMBER", value, start))
    
    def _try_string(self) -> bool:
        if self.pos >= len(self.source) or self.source[self.pos] != '"':
            return False
        
        start = self.pos
        self.pos += 1
        result = []
        
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch == '"':
                self.pos += 1
                self.tokens.append(Token("STRING", "".join(result), start))
                return True
            elif ch == "\\":
                if self.pos + 1 >= len(self.source):
                    raise LexError("unterminated string", start)
                self.pos += 1
                esc = self.source[self.pos]
                if esc == "n":
                    result.append("\n")
                elif esc == "t":
                    result.append("\t")
                elif esc == "r":
                    result.append("\r")
                elif esc == '"':
                    result.append('"')
                elif esc == "\\":
                    result.append("\\")
                else:
                    raise LexError(f"invalid escape sequence: \\{esc}", self.pos - 1)
                self.pos += 1
            elif ch in "\n\r":
                raise LexError("unterminated string", start)
            else:
                result.append(ch)
                self.pos += 1
        
        raise LexError("unterminated string", start)
    
    def _try_operator(self) -> bool:
        if self.pos >= len(self.source):
            return False
        
        start = self.pos
        
        if self.pos + 1 < len(self.source):
            two_char = self.source[self.pos:self.pos + 2]
            if two_char in self.OPERATORS:
                self.pos += 2
                self.tokens.append(Token("OP", two_char, start))
                return True
        
        if self.source[self.pos] == "=":
            raise LexError("single '=' is not valid; use '==' for equality", self.pos)
        
        if self.source[self.pos] in self.OPERATORS:
            self.pos += 1
            self.tokens.append(Token("OP", self.source[start], start))
            return True
        
        return False
    
    def _try_ident(self) -> bool:
        if self.pos >= len(self.source):
            return False
        
        if not (self.source[self.pos].isalpha() or self.source[self.pos] == "_"):
            return False
        
        start = self.pos
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == "_"):
            self.pos += 1
        
        ident = self.source[start:self.pos]
        if ident in self.KEYWORDS:
            value = True if ident == "true" else False if ident == "false" else ident
            self.tokens.append(Token("KEYWORD", value, start))
        else:
            self.tokens.append(Token("IDENT", ident, start))
        
        return True


def tokenize(source: str) -> list:
    lexer = Lexer(source)
    return lexer.tokenize()

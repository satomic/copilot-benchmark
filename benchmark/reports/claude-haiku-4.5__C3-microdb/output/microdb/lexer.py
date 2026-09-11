from .errors import LexError


KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON", "WHERE",
    "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC", "LIMIT", "OFFSET", "AS",
    "AND", "OR", "NOT", "IS", "NULL", "TRUE", "FALSE"
}


class Token:
    def __init__(
        self, type: str, value: object, offset: int
    ) -> None:
        self.type = type
        self.value = value
        self.offset = offset

    def __repr__(self) -> str:
        return f"Token({self.type}, {self.value!r}, {self.offset})"


class Lexer:
    def __init__(self, query: str) -> None:
        self.query = query
        self.pos = 0
        self.tokens: list[Token] = []

    def lex(self) -> list[Token]:
        while self.pos < len(self.query):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.query):
                break
            ch = self.query[self.pos]
            if ch == "'":
                self._read_string()
            elif ch.isdigit() or (ch == "." and
                                   self.pos + 1 < len(self.query) and
                                   self.query[self.pos + 1].isdigit()):
                self._read_number()
            elif ch.isalpha() or ch == "_":
                self._read_ident()
            elif ch in "(),.":
                self.tokens.append(Token(ch, ch, self.pos))
                self.pos += 1
            elif ch == "=":
                self.tokens.append(Token("=", "=", self.pos))
                self.pos += 1
            elif ch == "<":
                if self.pos + 1 < len(self.query) and self.query[self.pos + 1] == ">":
                    self.tokens.append(Token("<>", "<>", self.pos))
                    self.pos += 2
                elif self.pos + 1 < len(self.query) and self.query[self.pos + 1] == "=":
                    self.tokens.append(Token("<=", "<=", self.pos))
                    self.pos += 2
                else:
                    self.tokens.append(Token("<", "<", self.pos))
                    self.pos += 1
            elif ch == ">":
                if self.pos + 1 < len(self.query) and self.query[self.pos + 1] == "=":
                    self.tokens.append(Token(">=", ">=", self.pos))
                    self.pos += 2
                else:
                    self.tokens.append(Token(">", ">", self.pos))
                    self.pos += 1
            elif ch in "+-*/%":
                self.tokens.append(Token(ch, ch, self.pos))
                self.pos += 1
            else:
                raise LexError(f"Unexpected character: {ch}", self.pos)
        return self.tokens

    def _skip_whitespace_and_comments(self) -> None:
        while self.pos < len(self.query):
            if self.query[self.pos].isspace():
                self.pos += 1
            elif self.pos + 1 < len(self.query) and self.query[self.pos:self.pos+2] == "--":
                while self.pos < len(self.query) and self.query[self.pos] != "\n":
                    self.pos += 1
            else:
                break

    def _read_string(self) -> None:
        start = self.pos
        self.pos += 1
        value = ""
        while self.pos < len(self.query):
            if self.query[self.pos] == "'":
                if self.pos + 1 < len(self.query) and self.query[self.pos + 1] == "'":
                    value += "'"
                    self.pos += 2
                else:
                    self.pos += 1
                    self.tokens.append(Token("TEXT", value, start))
                    return
            else:
                value += self.query[self.pos]
                self.pos += 1
        raise LexError("Unterminated string", start)

    def _read_number(self) -> None:
        start = self.pos
        value = ""
        has_dot = False
        while self.pos < len(self.query):
            ch = self.query[self.pos]
            if ch.isdigit():
                value += ch
                self.pos += 1
            elif ch == "." and not has_dot:
                has_dot = True
                value += ch
                self.pos += 1
            elif ch in "eE":
                value += ch
                self.pos += 1
                if self.pos < len(self.query) and self.query[self.pos] in "+-":
                    value += self.query[self.pos]
                    self.pos += 1
            else:
                break
        if has_dot or "e" in value.lower():
            self.tokens.append(Token("FLOAT", float(value), start))
        else:
            self.tokens.append(Token("INT", int(value), start))

    def _read_ident(self) -> None:
        start = self.pos
        value = ""
        while self.pos < len(self.query):
            ch = self.query[self.pos]
            if ch.isalnum() or ch == "_":
                value += ch
                self.pos += 1
            else:
                break
        upper_value = value.upper()
        if upper_value in KEYWORDS:
            self.tokens.append(Token(upper_value, value, start))
        else:
            self.tokens.append(Token("IDENT", value, start))

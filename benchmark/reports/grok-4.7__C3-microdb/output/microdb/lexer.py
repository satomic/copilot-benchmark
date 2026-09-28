"""Hand-written lexer for the microdb query language."""

from __future__ import annotations

import dataclasses

from microdb.errors import LexError

KEYWORDS = frozenset(
    {
        "SELECT",
        "DISTINCT",
        "FROM",
        "INNER",
        "LEFT",
        "JOIN",
        "ON",
        "WHERE",
        "GROUP",
        "BY",
        "HAVING",
        "ORDER",
        "ASC",
        "DESC",
        "LIMIT",
        "OFFSET",
        "AS",
        "AND",
        "OR",
        "NOT",
        "IS",
        "NULL",
        "TRUE",
        "FALSE",
    }
)

_TWO_CHAR = {"<>", "<=", ">="}
_ONE_CHAR = set("=<>+-*/%(),.")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    value: object
    start: int
    end: int


def tokenize(sql: str) -> list[Token]:
    """Tokenize *sql*. Keywords are case-insensitive; identifiers are not."""
    return _Lexer(sql).run()


class _Lexer:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.n = len(sql)
        self.i = 0
        self.tokens: list[Token] = []

    def run(self) -> list[Token]:
        while self.i < self.n:
            self._skip_gap()
            if self.i >= self.n:
                break
            self._scan_one()
        self.tokens.append(Token("EOF", None, self.n, self.n))
        return self.tokens

    def _skip_gap(self) -> None:
        while self.i < self.n:
            ch = self.sql[self.i]
            if ch.isspace():
                self.i += 1
                continue
            if ch == "-" and self.i + 1 < self.n and self.sql[self.i + 1] == "-":
                self.i += 2
                while self.i < self.n and self.sql[self.i] != "\n":
                    self.i += 1
                continue
            return

    def _scan_one(self) -> None:
        ch = self.sql[self.i]
        if _is_digit(ch) or (ch == "." and self.i + 1 < self.n and _is_digit(self.sql[self.i + 1])):
            self.tokens.append(self._number())
            return
        if ch == "'":
            self.tokens.append(self._string())
            return
        if _is_ident_start(ch):
            self.tokens.append(self._ident())
            return
        if ch in _ONE_CHAR:
            self.tokens.append(self._operator())
            return
        raise LexError(f"unexpected character {ch!r}", self.i)

    def _number(self) -> Token:
        start = self.i
        is_float = self._scan_number_body()
        lexeme = self.sql[start:self.i]
        if is_float:
            return Token("FLOAT", float(lexeme), start, self.i)
        return Token("INT", int(lexeme), start, self.i)

    def _scan_number_body(self) -> bool:
        is_float = False
        if self.sql[self.i] == ".":
            self.i += 1
            self._digits()
            is_float = True
        else:
            self._digits()
            is_float = self._scan_fraction()
        if _exponent_at(self.sql, self.i):
            self._exponent()
            is_float = True
        return is_float

    def _scan_fraction(self) -> bool:
        if self.i >= self.n or self.sql[self.i] != ".":
            return False
        nxt = self.i + 1
        if nxt < self.n and _is_digit(self.sql[nxt]):
            self.i += 1
            self._digits()
            return True
        if _exponent_at(self.sql, nxt):
            self.i += 1
            return True
        # `digits.` is a float, including `1.`.
        self.i += 1
        return True

    def _digits(self) -> None:
        if self.i >= self.n or not _is_digit(self.sql[self.i]):
            raise LexError("invalid number", self.i)
        while self.i < self.n and _is_digit(self.sql[self.i]):
            self.i += 1

    def _exponent(self) -> None:
        self.i += 1
        if self.i < self.n and self.sql[self.i] in "+-":
            self.i += 1
        self._digits()

    def _string(self) -> Token:
        start = self.i
        self.i += 1
        chars: list[str] = []
        while self.i < self.n:
            ch = self.sql[self.i]
            if ch == "'":
                if self.i + 1 < self.n and self.sql[self.i + 1] == "'":
                    chars.append("'")
                    self.i += 2
                    continue
                self.i += 1
                return Token("TEXT", "".join(chars), start, self.i)
            chars.append(ch)
            self.i += 1
        raise LexError("unterminated string", start)

    def _ident(self) -> Token:
        start = self.i
        self.i += 1
        while self.i < self.n and _is_ident_cont(self.sql[self.i]):
            self.i += 1
        text = self.sql[start:self.i]
        if text.upper() in KEYWORDS:
            return Token("KEYWORD", text.upper(), start, self.i)
        return Token("IDENT", text, start, self.i)

    def _operator(self) -> Token:
        start = self.i
        two = self.sql[start:start + 2]
        if two in _TWO_CHAR:
            self.i += 2
            return Token("OP", two, start, self.i)
        self.i += 1
        return Token("OP", self.sql[start], start, self.i)


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ch == "_" or ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def _is_ident_cont(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


def _exponent_at(text: str, index: int) -> bool:
    n = len(text)
    if index >= n or text[index] not in "eE":
        return False
    j = index + 1
    if j < n and text[j] in "+-":
        j += 1
    return j < n and _is_digit(text[j])

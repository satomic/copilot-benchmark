"""Tokenizer for minilang."""

from dataclasses import dataclass

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = frozenset("+-*/%^<>(),")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Token:
    kind: str  # NUMBER, STRING, IDENT, KEYWORD, OP
    value: object
    position: int


def _is_ident_start(c):
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_ident_char(c):
    return _is_ident_start(c) or c.isdigit() and c.isascii()


def _is_digit(c):
    return "0" <= c <= "9"


def _lex_number(source, i):
    start = i
    n = len(source)
    while i < n and _is_digit(source[i]):
        i += 1
    if i < n and source[i] == ".":
        i += 1
        # A digit is required after '.', so "1." (and "1.e3") is rejected.
        if i >= n or not _is_digit(source[i]):
            raise LexError("invalid number: digit expected after '.'", i)
        while i < n and _is_digit(source[i]):
            i += 1
    if i < n and source[i] in "eE":
        i += 1
        if i < n and source[i] in "+-":
            i += 1
        if i >= n or not _is_digit(source[i]):
            raise LexError("invalid number: digit expected in exponent", i)
        while i < n and _is_digit(source[i]):
            i += 1
    return Token("NUMBER", float(source[start:i]), start), i


def _lex_string(source, i):
    start = i
    i += 1
    n = len(source)
    chars = []
    while True:
        if i >= n:
            raise LexError("unterminated string", start)
        c = source[i]
        if c == '"':
            return Token("STRING", "".join(chars), start), i + 1
        if c == "\n":
            raise LexError("unterminated string", start)
        if c == "\\":
            if i + 1 >= n:
                raise LexError("unterminated string", start)
            esc = source[i + 1]
            if esc not in _ESCAPES:
                raise LexError(f"invalid escape sequence: \\{esc}", i)
            chars.append(_ESCAPES[esc])
            i += 2
            continue
        chars.append(c)
        i += 1


def tokenize(source: str) -> list:
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#":
            while i < n and source[i] != "\n":
                i += 1
        elif _is_digit(c) or (c == "." and i + 1 < n and _is_digit(source[i + 1])):
            tok, i = _lex_number(source, i)
            tokens.append(tok)
        elif c == '"':
            tok, i = _lex_string(source, i)
            tokens.append(tok)
        elif _is_ident_start(c):
            start = i
            while i < n and _is_ident_char(source[i]):
                i += 1
            word = source[start:i]
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, start))
        elif source.startswith(_TWO_CHAR_OPS, i):
            tokens.append(Token("OP", source[i:i + 2], i))
            i += 2
        elif c in _ONE_CHAR_OPS:
            tokens.append(Token("OP", c, i))
            i += 1
        elif c == "=":
            raise LexError("unexpected '=' (did you mean '=='?)", i)
        else:
            raise LexError(f"unexpected character: {c!r}", i)
    return tokens

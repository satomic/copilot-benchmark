"""Lexer for minilang."""

from dataclasses import dataclass

from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})

# Longest operators first so that "==" wins over "=".
_OPERATORS = ("==", "!=", "<=", ">=", "+", "-", "*", "/", "%", "^", "<", ">", "(", ")", ",")

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Token:
    kind: str  # one of NUMBER, STRING, IDENT, KEYWORD, OP
    value: object
    position: int


def _is_ident_start(ch: str) -> bool:
    return ch.isascii() and (ch.isalpha() or ch == "_")


def _is_ident_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "_")


def _lex_number(source: str, start: int) -> "tuple[Token, int]":
    i = start
    n = len(source)
    int_digits = 0
    while i < n and source[i].isdigit():
        i += 1
        int_digits += 1
    frac_digits = 0
    if i < n and source[i] == ".":
        i += 1
        while i < n and source[i].isdigit():
            i += 1
            frac_digits += 1
        if frac_digits == 0:
            # ".5" is fine, "1." is not.
            raise LexError("number may not end with '.'", start)
    if int_digits == 0 and frac_digits == 0:
        raise LexError("unexpected character '.'", start)
    if i < n and source[i] in "eE":
        j = i + 1
        if j < n and source[j] in "+-":
            j += 1
        exp_digits = 0
        while j < n and source[j].isdigit():
            j += 1
            exp_digits += 1
        if exp_digits == 0:
            raise LexError("malformed exponent in number", start)
        i = j
    return Token("NUMBER", float(source[start:i]), start), i


def _lex_string(source: str, start: int) -> "tuple[Token, int]":
    i = start + 1
    n = len(source)
    chars = []
    while True:
        if i >= n:
            raise LexError("unterminated string", start)
        ch = source[i]
        if ch == '"':
            return Token("STRING", "".join(chars), start), i + 1
        if ch == "\n":
            raise LexError("newline in string", i)
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("unterminated string", start)
            esc = source[i + 1]
            if esc not in _ESCAPES:
                raise LexError(f"invalid escape sequence '\\{esc}'", i)
            chars.append(_ESCAPES[esc])
            i += 2
            continue
        chars.append(ch)
        i += 1


def tokenize(source: str) -> "list[Token]":
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            i += 1
        elif ch == "#":
            while i < n and source[i] != "\n":
                i += 1
        elif ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            tok, i = _lex_number(source, i)
            tokens.append(tok)
        elif ch == '"':
            tok, i = _lex_string(source, i)
            tokens.append(tok)
        elif _is_ident_start(ch):
            j = i + 1
            while j < n and _is_ident_char(source[j]):
                j += 1
            word = source[i:j]
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, i))
            i = j
        else:
            for op in _OPERATORS:
                if source.startswith(op, i):
                    tokens.append(Token("OP", op, i))
                    i += len(op)
                    break
            else:
                if ch == "=":
                    raise LexError("unexpected '=' (did you mean '==')?", i)
                raise LexError(f"unexpected character {ch!r}", i)
    return tokens

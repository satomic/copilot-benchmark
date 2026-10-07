"""Tokenizer."""

import dataclasses

from .errors import LexError

KEYWORDS = frozenset(
    {"let", "print", "if", "else", "while", "true", "false", "and", "or", "not"}
)
_TWO_CHAR_OPS = ("==", "!=", "<=", ">=")
_ONE_CHAR_OPS = "+-*/%(){};=<>"
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
_DIGITS = "0123456789"


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _is_ident_start(ch: str) -> bool:
    return ch == "_" or ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _digits_end(src: str, pos: int) -> int:
    while pos < len(src) and src[pos] in _DIGITS:
        pos += 1
    return pos


def _lex_number(src: str, start: int) -> tuple[Token, int]:
    pos = _digits_end(src, start)
    if pos < len(src) and src[pos] == ".":
        frac = pos + 1
        end = _digits_end(src, frac)
        if end == frac:
            raise LexError("malformed float", start)
        pos = end
        if pos < len(src) and src[pos] in "eE":
            exp = pos + 1
            if exp < len(src) and src[exp] in "+-":
                exp += 1
            end = _digits_end(src, exp)
            if end == exp:
                raise LexError("malformed exponent", start)
            pos = end
        text = src[start:pos]
        return Token("FLOAT", text, float(text), start), pos
    text = src[start:pos]
    return Token("INT", text, int(text), start), pos


def _lex_string(src: str, start: int) -> tuple[Token, int]:
    pos = start + 1
    out: list[str] = []
    while True:
        if pos >= len(src):
            raise LexError("unterminated string", start)
        ch = src[pos]
        if ch == '"':
            text = "".join(out)
            return Token("STRING", text, text, start), pos + 1
        if ch == "\n":
            raise LexError("newline in string", pos)
        if ch == "\\":
            if pos + 1 >= len(src) or src[pos + 1] not in _ESCAPES:
                raise LexError("invalid escape", pos)
            out.append(_ESCAPES[src[pos + 1]])
            pos += 2
        else:
            out.append(ch)
            pos += 1


def _lex_word(src: str, start: int) -> tuple[Token, int]:
    pos = start + 1
    while pos < len(src) and (_is_ident_start(src[pos]) or src[pos] in _DIGITS):
        pos += 1
    text = src[start:pos]
    kind = "KEYWORD" if text in KEYWORDS else "IDENT"
    return Token(kind, text, text, start), pos


def _skip_trivia(src: str, pos: int) -> int:
    while pos < len(src):
        if src[pos] in " \t\r\n\f\v":
            pos += 1
        elif src.startswith("//", pos):
            while pos < len(src) and src[pos] != "\n":
                pos += 1
        else:
            break
    return pos


def _lex_one(src: str, pos: int) -> tuple[Token, int]:
    ch = src[pos]
    if ch in _DIGITS:
        return _lex_number(src, pos)
    if ch == '"':
        return _lex_string(src, pos)
    if _is_ident_start(ch):
        return _lex_word(src, pos)
    if src[pos:pos + 2] in _TWO_CHAR_OPS:
        return Token("OP", src[pos:pos + 2], src[pos:pos + 2], pos), pos + 2
    if ch in _ONE_CHAR_OPS:
        return Token("OP", ch, ch, pos), pos + 1
    raise LexError(f"unexpected character {ch!r}", pos)


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    pos = _skip_trivia(src, 0)
    while pos < len(src):
        token, pos = _lex_one(src, pos)
        tokens.append(token)
        pos = _skip_trivia(src, pos)
    return tokens

"""Lexer for microvm."""

import dataclasses
from microvm.errors import LexError

KEYWORDS: frozenset[str] = frozenset({
    "let", "print", "if", "else", "while", "true", "false", "and", "or", "not"
})

TWO_CHAR_OPS: tuple[str, ...] = ("==", "!=", "<=", ">=")
ONE_CHAR_OPS: tuple[str, ...] = ("+", "-", "*", "/", "%", "(", ")", "{", "}", ";", "=", "<", ">")


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str      # "INT" | "FLOAT" | "STRING" | "IDENT" | "KEYWORD" | "OP"
    text: str      # the source lexeme (for STRING: the decoded value)
    value: object  # INT -> int, FLOAT -> float, STRING -> decoded str, else same as text
    offset: int    # zero-based character offset of the first character


def _lex_string(src: str, start: int) -> tuple[Token, int]:
    i = start + 1
    chars: list[str] = []
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':
            decoded = "".join(chars)
            return Token("STRING", decoded, decoded, start), i + 1
        if c in "\r\n":
            raise LexError("Literal newline in string literal", i)
        if c == "\\":
            i += 1
            if i >= n:
                raise LexError("Unterminated escape sequence", i - 1)
            esc = src[i]
            if esc == "n":
                chars.append("\n")
            elif esc == "t":
                chars.append("\t")
            elif esc == '"':
                chars.append('"')
            elif esc == "\\":
                chars.append("\\")
            else:
                raise LexError(f"Invalid escape sequence '\\{esc}'", i - 1)
            i += 1
        else:
            chars.append(c)
            i += 1
    raise LexError("Unterminated string literal", start)


def _lex_float_exponent(src: str, i: int, n: int) -> int:
    if i < n and src[i] in "eE":
        exp_start = i
        i += 1
        if i < n and src[i] in "+-":
            i += 1
        if i >= n or not src[i].isdigit():
            raise LexError("Invalid float exponent", exp_start)
        while i < n and src[i].isdigit():
            i += 1
    return i


def _lex_number(src: str, start: int) -> tuple[Token, int]:
    i = start
    n = len(src)
    while i < n and src[i].isdigit():
        i += 1
    if i < n and src[i] == ".":
        dot_pos = i
        i += 1
        if i >= n or not src[i].isdigit():
            raise LexError("Float requires digits after decimal point", dot_pos)
        while i < n and src[i].isdigit():
            i += 1
        i = _lex_float_exponent(src, i, n)
        if i < n and (src[i].isalpha() or src[i] == "_"):
            raise LexError("Invalid character after number", i)
        lexeme = src[start:i]
        return Token("FLOAT", lexeme, float(lexeme), start), i
    if i < n and (src[i].isalpha() or src[i] == "_"):
        raise LexError("Invalid character after number", i)
    lexeme = src[start:i]
    return Token("INT", lexeme, int(lexeme), start), i


def _lex_ident(src: str, start: int) -> tuple[Token, int]:
    i = start
    n = len(src)
    while i < n and (src[i].isalnum() or src[i] == "_"):
        i += 1
    lexeme = src[start:i]
    kind = "KEYWORD" if lexeme in KEYWORDS else "IDENT"
    return Token(kind, lexeme, lexeme, start), i


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            i += 2
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == '"':
            tok, i = _lex_string(src, i)
            tokens.append(tok)
            continue
        if c.isdigit():
            tok, i = _lex_number(src, i)
            tokens.append(tok)
            continue
        if c.isalpha() or c == "_":
            tok, i = _lex_ident(src, i)
            tokens.append(tok)
            continue
        matched_op = False
        if i + 1 < n and src[i : i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("OP", src[i : i + 2], src[i : i + 2], i))
            i += 2
            matched_op = True
        elif c in ONE_CHAR_OPS:
            tokens.append(Token("OP", c, c, i))
            i += 1
            matched_op = True
        if not matched_op:
            raise LexError(f"Unexpected character {c!r}", i)
    return tokens

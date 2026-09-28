from dataclasses import dataclass
import re

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    position: int


_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_IDENT_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_IDENT_PART = _IDENT_START + "0123456789"
_KEYWORDS = {"true", "false", "and", "or", "not"}
_TWO_CHAR_OPS = {"==", "!=", "<=", ">="}
_ONE_CHAR_OPS = set("+-*/%^<>() ,")


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(source):
        char = source[i]
        if char in " \t\r\n":
            i += 1
            continue
        if char == "#":
            newline = source.find("\n", i)
            i = len(source) if newline == -1 else newline + 1
            continue
        if char == '"':
            start = i
            i += 1
            chars: list[str] = []
            while i < len(source) and source[i] != '"':
                current = source[i]
                if current in "\r\n":
                    raise LexError("newline in string", i)
                if current == "\\":
                    if i + 1 >= len(source):
                        raise LexError("unterminated string", start)
                    escaped = source[i + 1]
                    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                    if escaped not in escapes:
                        raise LexError(f"invalid escape: \\{escaped}", i)
                    chars.append(escapes[escaped])
                    i += 2
                    continue
                chars.append(current)
                i += 1
            if i >= len(source):
                raise LexError("unterminated string", start)
            i += 1
            tokens.append(Token("STRING", "".join(chars), start))
            continue
        is_digit = "0" <= char <= "9"
        next_is_digit = i + 1 < len(source) and "0" <= source[i + 1] <= "9"
        if is_digit or (char == "." and next_is_digit):
            start = i
            match = _NUMBER.match(source, i)
            assert match is not None
            text = match.group(0)
            i = match.end()
            if i < len(source) and source[i] == ".":
                raise LexError("number may not end with a decimal point", i)
            if i < len(source) and source[i] in "eE":
                raise LexError("invalid exponent", i)
            try:
                value = float(text)
            except ValueError as error:
                raise LexError("invalid number", start) from error
            tokens.append(Token("NUMBER", value, start))
            continue
        if char in _IDENT_START:
            start = i
            i += 1
            while i < len(source) and source[i] in _IDENT_PART:
                i += 1
            value = source[start:i]
            kind = "KEYWORD" if value in _KEYWORDS else "IDENT"
            tokens.append(Token(kind, value, start))
            continue
        two = source[i:i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        if char == "=":
            raise LexError("unexpected '='; use '==' for equality", i)
        if char in _ONE_CHAR_OPS and char != " ":
            if char == ",":
                tokens.append(Token("OP", char, i))
            else:
                tokens.append(Token("OP", char, i))
            i += 1
            continue
        if char == "!":
            raise LexError("unexpected '!'", i)
        raise LexError(f"unexpected character: {char}", i)
    return tokens

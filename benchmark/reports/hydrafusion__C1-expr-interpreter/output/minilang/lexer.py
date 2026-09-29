from dataclasses import dataclass

from .errors import LexError


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: object
    position: int


_KEYWORDS = {"true", "false", "and", "or", "not"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
_TWO_CHAR_OPS = {"==", "!=", "<=", ">="}
_ONE_CHAR_OPS = set("+-*/%^<>() ,".replace(" ", ""))


def _number(source: str, start: int) -> tuple[Token, int]:
    length = len(source)
    index = start

    if source[index] == ".":
        index += 1
        while index < length and source[index].isdigit():
            index += 1
    else:
        while index < length and source[index].isdigit():
            index += 1
        if index < length and source[index] == ".":
            dot = index
            index += 1
            if index >= length or not source[index].isdigit():
                raise LexError("number may not end with '.'", dot)
            while index < length and source[index].isdigit():
                index += 1

    if index < length and source[index] in "eE":
        exponent = index
        index += 1
        if index < length and source[index] in "+-":
            index += 1
        if index >= length or not source[index].isdigit():
            raise LexError("invalid number", exponent)
        while index < length and source[index].isdigit():
            index += 1

    text = source[start:index]
    return Token("NUMBER", float(text), start), index


def _string(source: str, start: int) -> tuple[Token, int]:
    chars: list[str] = []
    index = start + 1
    while index < len(source):
        char = source[index]
        if char == '"':
            return Token("STRING", "".join(chars), start), index + 1
        if char in "\r\n":
            raise LexError("newline in string", index)
        if char == "\\":
            escape_position = index
            index += 1
            if index >= len(source):
                raise LexError("unterminated string", start)
            escaped = source[index]
            if escaped not in _ESCAPES:
                raise LexError(f"invalid escape: \\{escaped}", escape_position)
            chars.append(_ESCAPES[escaped])
        else:
            chars.append(char)
        index += 1
    raise LexError("unterminated string", start)


def tokenize(source: str) -> list[Token]:
    if not isinstance(source, str):
        raise TypeError("source must be a string")

    tokens: list[Token] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == "#":
            newline = source.find("\n", index)
            index = len(source) if newline == -1 else newline + 1
            continue
        if char.isdigit() or (
            char == "." and index + 1 < len(source) and source[index + 1].isdigit()
        ):
            token, index = _number(source, index)
            tokens.append(token)
            continue
        if char == '"':
            token, index = _string(source, index)
            tokens.append(token)
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < len(source) and (
                source[end].isalnum() or source[end] == "_"
            ):
                end += 1
            value = source[index:end]
            kind = "KEYWORD" if value in _KEYWORDS else "IDENT"
            tokens.append(Token(kind, value, index))
            index = end
            continue

        pair = source[index : index + 2]
        if pair in _TWO_CHAR_OPS:
            tokens.append(Token("OP", pair, index))
            index += 2
            continue
        if char == "=":
            raise LexError("unexpected '='", index)
        if char == "!":
            raise LexError("unexpected '!'", index)
        if char in _ONE_CHAR_OPS:
            tokens.append(Token("OP", char, index))
            index += 1
            continue
        raise LexError(f"unexpected character: {char}", index)

    return tokens

from dataclasses import dataclass

from .errors import LexError


KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


@dataclass(frozen=True)
class Token:
    kind: str
    value: float | str
    position: int


def _digit(char: str) -> bool:
    return "0" <= char <= "9"


def _identifier_start(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z" or char == "_"


def tokenize(source: str) -> list[Token]:
    tokens = []
    i = 0
    size = len(source)
    while i < size:
        char = source[i]
        if char in " \t\r\n":
            i += 1
            continue
        if char == "#":
            while i < size and source[i] not in "\r\n":
                i += 1
            continue
        start = i
        if _digit(char) or char == ".":
            if char == ".":
                i += 1
                if i == size or not _digit(source[i]):
                    raise LexError("expected a digit after decimal point", start)
            else:
                while i < size and _digit(source[i]):
                    i += 1
                if i < size and source[i] == ".":
                    dot = i
                    i += 1
                    if i == size or not _digit(source[i]):
                        raise LexError("expected a digit after decimal point", dot)
            while i < size and _digit(source[i]):
                i += 1
            if i < size and source[i] in "eE":
                i += 1
                if i < size and source[i] in "+-":
                    i += 1
                if i == size or not _digit(source[i]):
                    raise LexError("expected a digit in exponent", i)
                while i < size and _digit(source[i]):
                    i += 1
            tokens.append(Token("NUMBER", float(source[start:i]), start))
            continue
        if char == '"':
            i += 1
            contents = []
            while i < size and source[i] != '"':
                char = source[i]
                if char in "\r\n":
                    raise LexError("literal newline in string", i)
                if char == "\\":
                    escape_position = i
                    i += 1
                    if i == size:
                        raise LexError("unterminated string", start)
                    if source[i] not in ESCAPES:
                        raise LexError("unsupported escape", escape_position)
                    char = ESCAPES[source[i]]
                contents.append(char)
                i += 1
            if i == size:
                raise LexError("unterminated string", start)
            i += 1
            tokens.append(Token("STRING", "".join(contents), start))
            continue
        if _identifier_start(char):
            i += 1
            while i < size and (_identifier_start(source[i]) or _digit(source[i])):
                i += 1
            name = source[start:i]
            kind = "KEYWORD" if name in KEYWORDS else "IDENT"
            tokens.append(Token(kind, name, start))
            continue
        pair = source[i:i + 2]
        if pair in {"==", "!=", "<=", ">="}:
            tokens.append(Token("OP", pair, start))
            i += 2
            continue
        if char in "+-*/%^<>() ,":
            tokens.append(Token("OP", char, start))
            i += 1
            continue
        raise LexError(f"unexpected character: {char!r}", i)
    return tokens

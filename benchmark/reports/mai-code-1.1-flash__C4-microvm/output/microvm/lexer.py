import dataclasses

from .errors import LexError

KEYWORDS: set[str] = {
    "let",
    "print",
    "if",
    "else",
    "while",
    "true",
    "false",
    "and",
    "or",
    "not",
}

OPERATORS: tuple[str, ...] = (
    "==",
    "!=",
    "<=",
    ">=",
    "=",
    "+",
    "-",
    "*",
    "/",
    "%",
    "(",
    ")",
    "{",
    "}",
    ";",
    "<",
    ">",
)


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def _read_number(src: str, index: int) -> tuple[Token, int]:
    start = index
    while index < len(src) and src[index].isdigit():
        index += 1
    if index < len(src) and src[index] == ".":
        if index + 1 >= len(src) or not src[index + 1].isdigit():
            raise LexError("Invalid float literal", start)
        index += 1
        while index < len(src) and src[index].isdigit():
            index += 1
        if index < len(src) and src[index] in "eE":
            exp_index = index + 1
            if exp_index >= len(src):
                raise LexError("Invalid float literal", start)
            if src[exp_index] in "+-":
                exp_index += 1
            if exp_index >= len(src) or not src[exp_index].isdigit():
                raise LexError("Invalid float literal", start)
            index = exp_index
            while index < len(src) and src[index].isdigit():
                index += 1
        return Token("FLOAT", src[start:index], float(src[start:index]), start), index
    if index < len(src) and src[index] in "eE":
        raise LexError("Invalid float literal", start)
    return Token("INT", src[start:index], int(src[start:index]), start), index


def _read_string(src: str, index: int) -> tuple[Token, int]:
    start = index
    index += 1
    chars: list[str] = []
    while index < len(src):
        ch = src[index]
        if ch == '"':
            index += 1
            return Token("STRING", "".join(chars), "".join(chars), start), index
        if ch in "\r\n":
            raise LexError("Unterminated string literal", start)
        if ch == "\\":
            index += 1
            if index >= len(src):
                raise LexError("Unterminated string literal", start)
            esc = src[index]
            if esc == "n":
                chars.append("\n")
            elif esc == "t":
                chars.append("\t")
            elif esc == '"':
                chars.append('"')
            elif esc == "\\":
                chars.append("\\")
            else:
                raise LexError("Unsupported escape sequence", start)
            index += 1
            continue
        chars.append(ch)
        index += 1
    raise LexError("Unterminated string literal", start)


def _read_identifier(src: str, index: int) -> tuple[Token, int]:
    start = index
    index += 1
    while index < len(src) and (src[index].isalnum() or src[index] == "_"):
        index += 1
    text = src[start:index]
    if text in KEYWORDS:
        return Token("KEYWORD", text, text, start), index
    return Token("IDENT", text, text, start), index


def tokenize(src: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(src):
        ch = src[index]
        if ch.isspace():
            index += 1
            continue
        if ch == "/" and index + 1 < len(src) and src[index + 1] == "/":
            index += 2
            while index < len(src) and src[index] != "\n":
                index += 1
            continue
        if ch.isdigit():
            token, index = _read_number(src, index)
            tokens.append(token)
            continue
        if ch == '"':
            token, index = _read_string(src, index)
            tokens.append(token)
            continue
        if ch.isalpha() or ch == "_":
            token, index = _read_identifier(src, index)
            tokens.append(token)
            continue
        matched = False
        for op in OPERATORS:
            if src.startswith(op, index):
                tokens.append(Token("OP", op, op, index))
                index += len(op)
                matched = True
                break
        if matched:
            continue
        raise LexError(f"Unexpected character: {ch!r}", index)
    return tokens

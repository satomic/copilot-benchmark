from dataclasses import dataclass
from .errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})
TWO_CHAR_OPS = frozenset({"==", "!=", "<=", ">="})
ONE_CHAR_OPS = frozenset({"+", "-", "*", "/", "%", "^", "<", ">", "(", ")", ","})
ESCAPE_MAP = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_ident_part(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


@dataclass(frozen=True)
class Token:
    kind: str
    value: float | str
    position: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        if ch in (" ", "\t", "\n", "\r"):
            i += 1
            continue

        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if _is_digit(ch) or ch == ".":
            start = i
            if ch == ".":
                if i + 1 >= n or not _is_digit(source[i + 1]):
                    raise LexError("invalid character: '.'", start)
                i += 1
                while i < n and _is_digit(source[i]):
                    i += 1
            else:
                while i < n and _is_digit(source[i]):
                    i += 1
                if i < n and source[i] == ".":
                    i += 1
                    if i >= n or not _is_digit(source[i]):
                        raise LexError("number may not end with '.'", start)
                    while i < n and _is_digit(source[i]):
                        i += 1

            if i < n and source[i] == ".":
                raise LexError("invalid number literal", start)

            if i < n and source[i] in ("e", "E"):
                i += 1
                if i < n and source[i] in ("+", "-"):
                    i += 1
                if i >= n or not _is_digit(source[i]):
                    raise LexError("invalid exponent in number literal", start)
                while i < n and _is_digit(source[i]):
                    i += 1

            tokens.append(Token("NUMBER", float(source[start:i]), start))
            continue

        if ch == '"':
            start = i
            i += 1
            chars: list[str] = []
            while i < n:
                c = source[i]
                if c == '"':
                    i += 1
                    tokens.append(Token("STRING", "".join(chars), start))
                    break
                if c in ("\n", "\r"):
                    raise LexError("unterminated string literal", start)
                if c == "\\":
                    esc_pos = i
                    i += 1
                    if i >= n:
                        raise LexError("unterminated string literal", start)
                    esc = source[i]
                    if esc not in ESCAPE_MAP:
                        raise LexError(f"invalid escape sequence: \\{esc}", esc_pos)
                    chars.append(ESCAPE_MAP[esc])
                    i += 1
                else:
                    chars.append(c)
                    i += 1
            else:
                raise LexError("unterminated string literal", start)
            continue

        if _is_ident_start(ch):
            start = i
            i += 1
            while i < n and _is_ident_part(source[i]):
                i += 1
            word = source[start:i]
            kind = "KEYWORD" if word in KEYWORDS else "IDENT"
            tokens.append(Token(kind, word, start))
            continue

        if i + 1 < n and source[i : i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("OP", source[i : i + 2], i))
            i += 2
            continue

        if ch in ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, i))
            i += 1
            continue

        raise LexError(f"unexpected character: {ch!r}", i)

    return tokens

from dataclasses import dataclass

from .errors import LexError


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    position: int


KEYWORDS = {"true", "false", "and", "or", "not"}
ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        if ch.isspace():
            i += 1
            continue

        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            start = i
            j = i
            if ch == ".":
                j += 1
            while j < n and source[j].isdigit():
                j += 1
            if j < n and source[j] == ".":
                if j + 1 >= n or not source[j + 1].isdigit():
                    raise LexError("invalid number", start)
                j += 1
                while j < n and source[j].isdigit():
                    j += 1
            if j < n and source[j] in "eE":
                j += 1
                if j < n and source[j] in "+-":
                    j += 1
                if j >= n or not source[j].isdigit():
                    raise LexError("invalid number", start)
                while j < n and source[j].isdigit():
                    j += 1
            number_text = source[start:j]
            if number_text.endswith("."):
                raise LexError("invalid number", start)
            try:
                value = float(number_text)
            except ValueError as exc:  # pragma: no cover - defensive guard
                raise LexError("invalid number", start) from exc
            tokens.append(Token("NUMBER", value, start))
            i = j
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
                if c == "\\":
                    if i + 1 >= n:
                        raise LexError("unterminated string", start)
                    esc = source[i + 1]
                    if esc not in ESCAPES:
                        raise LexError(f"invalid escape: \\{esc}", i)
                    chars.append(ESCAPES[esc])
                    i += 2
                    continue
                if c in "\r\n":
                    raise LexError("unterminated string", start)
                chars.append(c)
                i += 1
            else:
                raise LexError("unterminated string", start)
            continue

        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            value = source[start:i]
            kind = "KEYWORD" if value in KEYWORDS else "IDENT"
            tokens.append(Token(kind, value, start))
            continue

        if ch in "+-*/% ^(),":
            value = ch
            if ch == "^":
                tokens.append(Token("OP", value, i))
                i += 1
                continue
            if ch in "+-*/%":
                tokens.append(Token("OP", value, i))
                i += 1
                continue
            if ch == "(":
                tokens.append(Token("OP", "(", i))
                i += 1
                continue
            if ch == ")":
                tokens.append(Token("OP", ")", i))
                i += 1
                continue
            if ch == ",":
                tokens.append(Token("OP", ",", i))
                i += 1
                continue

        if ch in "<>!=":
            if ch == "!":
                if i + 1 < n and source[i + 1] == "=":
                    tokens.append(Token("OP", "!=", i))
                    i += 2
                    continue
                raise LexError("unexpected character", i)
            if ch == "=":
                if i + 1 < n and source[i + 1] == "=":
                    tokens.append(Token("OP", "==", i))
                    i += 2
                    continue
                raise LexError("unexpected character", i)
            if ch in "<>":
                if i + 1 < n and source[i + 1] == "=":
                    tokens.append(Token("OP", ch + "=", i))
                    i += 2
                    continue
                tokens.append(Token("OP", ch, i))
                i += 1
                continue

        raise LexError(f"unexpected character: {ch}", i)

    return tokens

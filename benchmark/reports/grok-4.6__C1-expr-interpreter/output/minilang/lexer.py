from minilang.errors import LexError

KEYWORDS = frozenset({"true", "false", "and", "or", "not"})

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    '"': '"',
    "\\": "\\",
}

_TWO_CHAR_OPS = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS = frozenset(list("+-*/%^(),<>"))


class Token:
    def __init__(self, kind: str, value, position: int):
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.position})"

    def __eq__(self, other):
        return (
            isinstance(other, Token)
            and self.kind == other.kind
            and self.value == other.value
            and self.position == other.position
        )


def tokenize(source: str) -> list:
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            tok, i = _lex_number(source, i)
            tokens.append(tok)
            continue
        if ch == '"':
            tok, i = _lex_string(source, i)
            tokens.append(tok)
            continue
        if ch.isalpha() or ch == "_":
            tok, i = _lex_ident(source, i)
            tokens.append(tok)
            continue
        if ch == "=":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(Token("OP", "==", i))
                i += 2
                continue
            raise LexError("unexpected '='", i)
        if ch == "!" :
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(Token("OP", "!=", i))
                i += 2
                continue
            raise LexError(f"unexpected character: {ch!r}", i)
        if ch in "<>":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(Token("OP", ch + "=", i))
                i += 2
            else:
                tokens.append(Token("OP", ch, i))
                i += 1
            continue
        if ch in _ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, i))
            i += 1
            continue
        raise LexError(f"unexpected character: {ch!r}", i)
    return tokens


def _lex_number(source: str, i: int):
    start = i
    n = len(source)
    while i < n and source[i].isdigit():
        i += 1
    if i < n and source[i] == ".":
        if i + 1 >= n or not source[i + 1].isdigit():
            raise LexError("number may not end with '.'", i)
        i += 1
        while i < n and source[i].isdigit():
            i += 1
    if i < n and source[i] in "eE":
        exp_pos = i
        i += 1
        if i < n and source[i] in "+-":
            i += 1
        if i >= n or not source[i].isdigit():
            raise LexError("invalid exponent", exp_pos)
        while i < n and source[i].isdigit():
            i += 1
    text = source[start:i]
    return Token("NUMBER", float(text), start), i


def _lex_string(source: str, i: int):
    start = i
    i += 1
    n = len(source)
    chars = []
    while i < n:
        ch = source[i]
        if ch == "\n":
            raise LexError("newline in string", i)
        if ch == '"':
            return Token("STRING", "".join(chars), start), i + 1
        if ch == "\\":
            if i + 1 >= n:
                raise LexError("unterminated string", start)
            esc = source[i + 1]
            if esc not in _ESCAPES:
                raise LexError(f"invalid escape sequence: \\{esc}", i)
            chars.append(_ESCAPES[esc])
            i += 2
            continue
        chars.append(ch)
        i += 1
    raise LexError("unterminated string", start)


def _lex_ident(source: str, i: int):
    start = i
    n = len(source)
    i += 1
    while i < n and (source[i].isalnum() or source[i] == "_"):
        i += 1
    text = source[start:i]
    if text in KEYWORDS:
        return Token("KEYWORD", text, start), i
    return Token("IDENT", text, start), i

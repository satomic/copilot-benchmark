"""MiniLang lexical analyzer."""

from .errors import LexError


class Token:
    """A lexical token."""
    __slots__ = ("kind", "value", "position")

    def __init__(self, kind: str, value: object, position: int) -> None:
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r}, {self.position})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Token):
            return (self.kind, self.value, self.position) == (other.kind, other.value, other.position)
        return False


KEYWORDS = {"true", "false", "and", "or", "not"}


def tokenize(source: str) -> list[Token]:
    """Tokenize the input source code into a list of tokens."""
    tokens: list[Token] = []
    i = 0
    n = len(source)

    while i < n:
        ch = source[i]

        # 1. Whitespace
        if ch in " \t\r\n":
            i += 1
            continue

        # 2. Comments
        if ch == "#":
            i += 1
            while i < n and source[i] != "\n":
                i += 1
            continue

        # 4. Strings
        if ch == '"':
            start = i
            i += 1
            chars: list[str] = []
            terminated = False
            while i < n:
                c = source[i]
                if c in "\r\n":
                    raise LexError("literal newline in string", position=i)
                elif c == '"':
                    i += 1
                    terminated = True
                    break
                elif c == "\\":
                    esc_pos = i
                    i += 1
                    if i >= n:
                        raise LexError("unterminated string escape", position=esc_pos)
                    esc_char = source[i]
                    if esc_char == "n":
                        chars.append("\n")
                    elif esc_char == "t":
                        chars.append("\t")
                    elif esc_char == "r":
                        chars.append("\r")
                    elif esc_char == '"':
                        chars.append('"')
                    elif esc_char == "\\":
                        chars.append("\\")
                    else:
                        raise LexError(f"invalid escape sequence: \\{esc_char}", position=esc_pos)
                    i += 1
                else:
                    chars.append(c)
                    i += 1

            if not terminated:
                raise LexError("unterminated string", position=start)

            tokens.append(Token("STRING", "".join(chars), start))
            continue

        # 5 & 6. Identifiers and Keywords
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (source[i].isalnum() or source[i] == "_"):
                i += 1
            word = source[start:i]
            if word in KEYWORDS:
                tokens.append(Token("KEYWORD", word, start))
            else:
                tokens.append(Token("IDENT", word, start))
            continue

        # 3. Numbers: 123, 1.5, .5, 1e3, 1.2e-4, 2E+8. A number may not end with '.'
        if ch.isdigit() or (ch == "." and i + 1 < n and source[i + 1].isdigit()):
            start = i
            if ch == ".":
                i += 1
                while i < n and source[i].isdigit():
                    i += 1
            else:
                while i < n and source[i].isdigit():
                    i += 1
                if i < n and source[i] == ".":
                    dot_pos = i
                    if i + 1 < n and source[i + 1].isdigit():
                        i += 1
                        while i < n and source[i].isdigit():
                            i += 1
                    else:
                        raise LexError("number may not end with '.'", position=dot_pos)

            # Optional exponent
            if i < n and source[i] in "eE":
                exp_pos = i
                exp_i = i + 1
                if exp_i < n and source[exp_i] in "+-":
                    exp_i += 1
                if exp_i >= n or not source[exp_i].isdigit():
                    raise LexError("invalid exponent in number literal", position=exp_pos)
                while exp_i < n and source[exp_i].isdigit():
                    exp_i += 1
                i = exp_i

            # Check trailing identifier chars
            if i < n and (source[i].isalpha() or source[i] == "_"):
                raise LexError(f"invalid character in number literal: {source[i]!r}", position=i)

            num_str = source[start:i]
            try:
                num_val = float(num_str)
            except ValueError:
                raise LexError(f"invalid number: {num_str!r}", position=start)
            tokens.append(Token("NUMBER", num_val, start))
            continue

        # 7. Operators and punctuation
        if source[i : i + 2] in ("==", "!=", "<=", ">="):
            tokens.append(Token("OP", source[i : i + 2], i))
            i += 2
            continue

        if ch == "=":
            raise LexError("unexpected '='", position=i)

        if ch == "!":
            raise LexError("unexpected '!'", position=i)

        if ch in "+-*/%^<>()" or ch == ",":
            tokens.append(Token("OP", ch, i))
            i += 1
            continue

        # 8. Any other character
        raise LexError(f"unexpected character: {ch!r}", position=i)

    return tokens

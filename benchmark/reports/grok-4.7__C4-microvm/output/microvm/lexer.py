import dataclasses

from microvm.errors import LexError

_KEYWORDS = frozenset({
    "let", "print", "if", "else", "while", "true", "false", "and", "or", "not",
})
_TWO_CHAR_OPS = frozenset({"==", "!=", "<=", ">="})
_ONE_CHAR_OPS = frozenset("+-*/%(){};=<>")
_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


@dataclasses.dataclass(frozen=True)
class Token:
    kind: str
    text: str
    value: object
    offset: int


def tokenize(src: str) -> list[Token]:
    return _Lexer(src).tokens()


def _is_digit(ch: str) -> bool:
    return len(ch) == 1 and "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ch == "_" or ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def _is_ident_continue(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


class _Lexer:
    def __init__(self, src: str) -> None:
        self.src = src
        self.pos = 0
        self._out: list[Token] = []

    def tokens(self) -> list[Token]:
        while self.pos < len(self.src):
            self._skip()
            if self.pos >= len(self.src):
                break
            self._out.append(self._scan())
        return self._out

    def _skip(self) -> None:
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch in " \t\r\n\f\v":
                self.pos += 1
                continue
            if self.src.startswith("//", self.pos):
                self._skip_comment()
                continue
            return

    def _skip_comment(self) -> None:
        self.pos += 2
        while self.pos < len(self.src) and self.src[self.pos] != "\n":
            self.pos += 1

    def _scan(self) -> Token:
        ch = self.src[self.pos]
        if _is_digit(ch):
            return self._number()
        if ch == '"':
            return self._string()
        if _is_ident_start(ch):
            return self._ident()
        if ch == ".":
            raise LexError("invalid number", self.pos)
        return self._operator()

    def _number(self) -> Token:
        start = self.pos
        self._digits()
        if self._peek() != ".":
            text = self.src[start:self.pos]
            return Token("INT", text, int(text), start)
        return self._float(start)

    def _float(self, start: int) -> Token:
        # `1.` is illegal. Offset points at the dot that makes the lexeme invalid.
        if not _is_digit(self._peek(1)):
            raise LexError("invalid float", self.pos)
        self.pos += 1
        self._digits()
        self._exponent()
        text = self.src[start:self.pos]
        return Token("FLOAT", text, float(text), start)

    def _exponent(self) -> None:
        # `1.5e` without exponent digits is a float plus a later identifier, not an error.
        if self._peek() not in "eE":
            return
        index = self.pos + 1
        if self._at(index) in "+-":
            index += 1
        if not _is_digit(self._at(index)):
            return
        self.pos = index
        self._digits()

    def _string(self) -> Token:
        start = self.pos
        self.pos += 1
        chars: list[str] = []
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            if ch == '"':
                self.pos += 1
                value = "".join(chars)
                return Token("STRING", value, value, start)
            if ch in "\n\r":
                raise LexError("newline in string", self.pos)
            if ch == "\\":
                chars.append(self._escape())
                continue
            chars.append(ch)
            self.pos += 1
        raise LexError("unterminated string", start)

    def _escape(self) -> str:
        slash = self.pos
        self.pos += 1
        if self.pos >= len(self.src):
            raise LexError("unterminated string", slash)
        ch = self.src[self.pos]
        self.pos += 1
        if ch not in _ESCAPES:
            raise LexError("invalid escape", slash)
        return _ESCAPES[ch]

    def _ident(self) -> Token:
        start = self.pos
        self.pos += 1
        while _is_ident_continue(self._peek()):
            self.pos += 1
        text = self.src[start:self.pos]
        if text in _KEYWORDS:
            return Token("KEYWORD", text, text, start)
        return Token("IDENT", text, text, start)

    def _operator(self) -> Token:
        start = self.pos
        two = self.src[start:start + 2]
        if two in _TWO_CHAR_OPS:
            self.pos += 2
            return Token("OP", two, two, start)
        ch = self.src[start]
        if ch in _ONE_CHAR_OPS:
            self.pos += 1
            return Token("OP", ch, ch, start)
        raise LexError("unexpected character", start)

    def _digits(self) -> None:
        while _is_digit(self._peek()):
            self.pos += 1

    def _peek(self, ahead: int = 0) -> str:
        return self._at(self.pos + ahead)

    def _at(self, index: int) -> str:
        if index < 0 or index >= len(self.src):
            return ""
        return self.src[index]

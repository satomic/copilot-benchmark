"""Read text from stdin and print the most frequent words."""

import re as _re
import sys as _sys
from collections import Counter as _Counter

__all__ = ["tokenize", "top_words", "main"]

# Maximal runs of ASCII letters, digits, and apostrophes (after lowercasing).
_TOKEN_RE = _re.compile(r"[a-z0-9']+")


class _UsageError(Exception):
    """Invalid CLI arguments. Message is written to stderr by main."""


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = _Counter(tokenize(text))
    # Count descending, then word ascending (plain string comparison).
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def _parse_n(argv: list[str]) -> int:
    """Parse [-n N] / [--top N].

    argv does not include the program name. The last -n/--top wins.
    Attached forms -nN and --top=N are accepted. Anything else is a usage error.
    """
    n_text: str | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-n", "--top"):
            if index + 1 >= len(argv):
                raise _UsageError(f"option requires an argument: {arg}")
            n_text = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--top="):
            n_text = arg[len("--top=") :]
            index += 1
            continue
        if arg.startswith("-n") and len(arg) > 2:
            n_text = arg[2:]
            index += 1
            continue
        raise _UsageError(f"unrecognized argument: {arg}")
    if n_text is None:
        return 10
    try:
        n = int(n_text)
    except ValueError:
        raise _UsageError("N must be an integer >= 1") from None
    if n < 1:
        raise _UsageError("N must be an integer >= 1")
    return n


def _emit(text: str) -> None:
    """Write text to stdout with LF line endings (no CRLF translation)."""
    stdout = _sys.stdout
    buffer = getattr(stdout, "buffer", None)
    if buffer is not None and not hasattr(stdout, "getvalue"):
        stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()
        return
    stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = _sys.argv[1:]
    try:
        n = _parse_n(argv)
    except _UsageError as exc:
        _sys.stderr.write(f"usage: wordfreq.py [-n N]\nerror: {exc}\n")
        return 2
    text = _sys.stdin.read()
    lines = "".join(f"{word}\t{count}\n" for word, count in top_words(text, n))
    if lines:
        _emit(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Word frequency CLI: reads text from stdin and prints the most frequent words."""

# Imports are aliased with a leading underscore so the only public names are the API.
import argparse as _argparse
import re as _re
import sys as _sys
from collections import Counter as _Counter

__all__ = ["tokenize", "top_words", "main"]

_TOKEN_RE = _re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = _Counter(tokenize(text))
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if n < 1:
        raise _argparse.ArgumentTypeError(f"N must be >= 1, got {n}")
    return n


def _read_stdin() -> str:
    # Read raw bytes and decode as UTF-8 so behaviour doesn't depend on the locale.
    buffer = getattr(_sys.stdin, "buffer", None)
    if buffer is None:
        return _sys.stdin.read()
    return buffer.read().decode("utf-8", errors="replace")


def _write_stdout(text: str) -> None:
    # Write bytes to avoid "\r\n" newline translation on Windows.
    buffer = getattr(_sys.stdout, "buffer", None)
    if buffer is None:
        _sys.stdout.write(text)
    else:
        _sys.stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def main(argv: list[str] | None = None) -> int:
    parser = _argparse.ArgumentParser(
        prog="wordfreq.py",
        description="Print the most frequent words read from stdin.",
    )
    parser.add_argument(
        "-n", "--top", dest="n", type=_positive_int, default=10, metavar="N",
        help="number of words to print (default: 10)",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with 2 on usage errors (message already on stderr).
        return exc.code if isinstance(exc.code, int) else 2

    output = "".join(f"{word}\t{count}\n" for word, count in top_words(_read_stdin(), args.n))
    if output:
        _write_stdout(output)
    return 0


if __name__ == "__main__":
    _sys.exit(main())

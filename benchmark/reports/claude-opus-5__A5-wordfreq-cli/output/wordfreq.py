"""Word frequency counter reading text from standard input."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

__all__ = ["tokenize", "top_words", "main"]

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Split ``text`` into lowercased word tokens."""
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower()):
        word = raw.strip("'")
        if word:
            tokens.append(word)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return up to ``n`` (word, count) pairs, most frequent first."""
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


class _UsageError(Exception):
    pass


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {number}")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wordfreq",
        description="Print the most frequent words read from standard input.",
    )
    parser.add_argument(
        "-n",
        "--top",
        dest="n",
        type=_positive_int,
        default=10,
        metavar="N",
        help="number of words to print (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # argparse exits with code 2 on usage errors, which matches the spec; catching
    # SystemExit keeps main() returning the code instead of terminating callers.
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0

    text = sys.stdin.read()
    out = "".join(f"{word}\t{count}\n" for word, count in top_words(text, args.n))
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Word frequency CLI: reads text from stdin and prints the most frequent words."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

__all__ = ["tokenize", "top_words", "main"]

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be at least 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"N must be at least 1, got {number}")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wordfreq",
        description="Read text from stdin and print the most frequent words.",
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
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already wrote the usage error to stderr; exit code 2 for errors.
        return int(exc.code) if exc.code is not None else 0
    text = sys.stdin.read()
    out = sys.stdout
    for word, count in top_words(text, args.n):
        out.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

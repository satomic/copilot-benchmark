"""Print the most frequent words from standard input."""

import argparse as _argparse
import re as _re
import sys as _sys


_TOKEN_PATTERN = _re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Return normalized word tokens from *text*."""
    tokens = (
        match.group().strip("'")
        for match in _TOKEN_PATTERN.finditer(text.lower())
    )
    return [token for token in tokens if token]


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return up to *n* words ranked by frequency and then alphabetically."""
    if n < 1:
        raise ValueError("n must be at least 1")

    counts: dict[str, int] = {}
    for token in tokenize(text):
        counts[token] = counts.get(token, 0) + 1

    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise _argparse.ArgumentTypeError("N must be an integer") from error
    if number < 1:
        raise _argparse.ArgumentTypeError("N must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    """Run the command-line interface and return its process exit code."""
    parser = _argparse.ArgumentParser()
    parser.add_argument("-n", "--top", type=_positive_int, default=10, metavar="N")

    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    for word, count in top_words(_sys.stdin.read(), arguments.top):
        _sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

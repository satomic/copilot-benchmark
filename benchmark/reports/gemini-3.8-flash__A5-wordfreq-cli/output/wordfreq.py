"""Word frequency CLI tool."""

import argparse as _argparse
import re as _re
import sys as _sys
from collections import Counter as _Counter

__all__ = ["tokenize", "top_words", "main"]


def tokenize(text: str) -> list[str]:
    """Tokenize input text according to assignment rules."""
    lowered = text.lower()
    raw_tokens = _re.findall(r"[a-z0-9']+", lowered)
    tokens: list[str] = []
    for raw in raw_tokens:
        stripped = raw.strip("'")
        if stripped:
            tokens.append(stripped)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return at most n most frequent words sorted by count desc, then word asc."""
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be an integer >= 1")
    tokens = tokenize(text)
    counts = _Counter(tokens)
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return sorted_items[:n]


class _ArgumentParser(_argparse.ArgumentParser):
    """Custom parser that raises ValueError on usage error without exiting."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def _parse_n(argv: list[str]) -> int:
    """Parse and validate command line arguments, returning n."""
    parser = _ArgumentParser(prog="wordfreq", add_help=False)
    parser.add_argument("-n", "--top", dest="n", default=10)
    args = parser.parse_args(argv)

    raw_n = args.n
    try:
        if isinstance(raw_n, int):
            n = raw_n
        elif isinstance(raw_n, str):
            n = int(raw_n)
        else:
            raise ValueError(f"Invalid integer: {raw_n}")
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid -n/--top value: {raw_n}") from exc

    return n


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    if argv is None:
        argv = _sys.argv[1:]

    try:
        n = _parse_n(argv)
    except ValueError as err:
        _sys.stderr.write(f"Usage error: {err}\n")
        return 2

    text = _sys.stdin.read()
    results = top_words(text, n)
    for word, count in results:
        _sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    _sys.exit(main())

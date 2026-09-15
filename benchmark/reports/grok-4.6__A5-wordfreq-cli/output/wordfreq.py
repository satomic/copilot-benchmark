"""Word-frequency CLI: tokenize stdin and print the most common words."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")


class _UsageError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be an integer >= 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def _parse_n(argv: list[str]) -> int:
    parser = _ArgumentParser(prog="wordfreq.py", add_help=False)
    parser.add_argument("-n", "--top", dest="n", default="10", metavar="N")
    args, extra = parser.parse_known_args(argv)
    if extra:
        raise _UsageError("unexpected arguments")
    try:
        n = int(args.n)
    except (TypeError, ValueError) as exc:
        raise _UsageError("N must be an integer >= 1") from exc
    if n < 1:
        raise _UsageError("N must be an integer >= 1")
    return n


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        n = _parse_n(argv)
    except _UsageError as exc:
        print(f"wordfreq.py: error: {exc}", file=sys.stderr)
        return 2
    text = sys.stdin.read()
    for word, count in top_words(text, n):
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

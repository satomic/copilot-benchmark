"""Word frequency CLI: reads stdin and prints the most frequent words."""

import argparse
import re
import sys
from collections import Counter

_RAW_TOKEN = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split into [a-z0-9'] runs, strip edge apostrophes, drop empties."""
    tokens = []
    for raw in _RAW_TOKEN.findall(text.lower()):
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return up to n (word, count) pairs sorted by count desc, then word asc."""
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # type: ignore[override]
        raise _UsageError(message)


def _parse_n(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError(f"N must be >= 1, got {n}")
    return n


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="wordfreq.py", description="Print the most frequent words from stdin.")
    parser.add_argument("-n", "--top", dest="n", type=_parse_n, default=10,
                        help="number of words to print (default: 10)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        sys.stderr.write(f"wordfreq.py: error: {exc}\n")
        return 2
    except SystemExit as exc:  # --help exits 0 via argparse
        return exc.code if isinstance(exc.code, int) else 2

    text = sys.stdin.read()
    for word, count in top_words(text, args.n):
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Word frequency CLI: reads text from stdin, prints the most frequent words."""

import argparse
import re
import sys
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Split text into normalized word tokens per the tokenization rules."""
    return [tok for raw in _TOKEN_RE.findall(text.lower()) if (tok := raw.strip("'"))]


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return the at most `n` most frequent (word, count) pairs.

    Sorted by count descending, then word ascending.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wordfreq.py",
        description="Print the most frequent words read from stdin.",
    )
    parser.add_argument(
        "-n",
        "--top",
        dest="n",
        type=int,
        default=10,
        help="number of top words to print (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = _build_parser()
    # argparse exits with code 2 and prints usage to stderr for non-integer N.
    args = parser.parse_args(argv)
    if args.n < 1:
        print(f"wordfreq.py: error: n must be >= 1 (got {args.n})", file=sys.stderr)
        return 2
    text = sys.stdin.read()
    for word, count in top_words(text, args.n):
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

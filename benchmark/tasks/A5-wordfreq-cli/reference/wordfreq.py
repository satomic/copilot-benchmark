"""Print the most frequent words read from standard input."""

import argparse
import re
import sys
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_DEFAULT_TOP = 10


def tokenize(text: str) -> list[str]:
    """Split `text` into lowercase word tokens."""
    tokens = (raw.strip("'") for raw in _TOKEN_RE.findall(text.lower()))
    return [token for token in tokens if token]


def top_words(text: str, n: int = _DEFAULT_TOP) -> list[tuple[str, int]]:
    """Return up to `n` (word, count) pairs, most frequent first."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]


def main(argv: list[str] | None = None) -> int:
    """Read stdin, print the ranking, return the exit code."""
    parser = argparse.ArgumentParser(
        prog="wordfreq", description="Count word frequencies read from stdin."
    )
    parser.add_argument("-n", "--top", type=_positive_int, default=_DEFAULT_TOP)
    args = parser.parse_args(argv)

    for word, count in top_words(sys.stdin.read(), args.top):
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return value


if __name__ == "__main__":
    raise SystemExit(main())

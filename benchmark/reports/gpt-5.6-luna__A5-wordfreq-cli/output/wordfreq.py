import argparse as _argparse
import collections as _collections
import re as _re
import sys as _sys


def tokenize(text: str) -> list[str]:
    """Return normalized word tokens from text."""
    return [
        token.strip("'")
        for token in _re.findall(r"[a-z0-9']+", text.lower())
        if token.strip("'")
    ]


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return the most frequent words in ranking order."""
    if n < 1:
        raise ValueError("n must be at least 1")

    counts = _collections.Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def main(argv: list[str] | None = None) -> int:
    parser = _argparse.ArgumentParser()
    parser.add_argument("-n", "--top", dest="n", default="10")
    try:
        args = parser.parse_args(argv)
        try:
            n = int(args.n)
        except (TypeError, ValueError):
            parser.error("N must be an integer")
        if n < 1:
            parser.error("N must be at least 1")
    except SystemExit as error:
        return int(error.code)

    output = "".join(f"{word}\t{count}\n" for word, count in top_words(_sys.stdin.read(), n))
    _sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

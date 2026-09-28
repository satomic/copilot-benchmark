import argparse as _argparse
import re as _re
import sys as _sys
from collections import Counter as _Counter


def tokenize(text: str) -> list[str]:
    words = _re.findall(r"[a-z0-9']+", text.lower())
    return [word.strip("'") for word in words if word.strip("'")]


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be at least 1")

    counts = _Counter(tokenize(text))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]


def main(argv: list[str] | None = None) -> int:
    parser = _argparse.ArgumentParser()
    parser.add_argument("-n", "--top", type=int, default=10, metavar="N")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("N must be at least 1")

    text = _sys.stdin.read()
    for word, count in top_words(text, args.top):
        print(f"{word}\t{count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

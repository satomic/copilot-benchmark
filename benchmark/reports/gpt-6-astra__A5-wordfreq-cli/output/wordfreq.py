import argparse as _argparse
import collections as _collections
import io as _io
import re as _re
import sys as _sys


def tokenize(text: str) -> list[str]:
    return [
        word
        for raw in _re.findall(r"[a-z0-9']+", text.lower())
        if (word := raw.strip("'"))
    ]


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be at least 1")
    counts = _collections.Counter(tokenize(text))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise _argparse.ArgumentTypeError("N must be an integer") from None
    if number < 1:
        raise _argparse.ArgumentTypeError("N must be at least 1")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = _argparse.ArgumentParser(
        description="Print the most frequent words from standard input.",
        allow_abbrev=False,
    )
    parser.add_argument("-n", "--top", type=_positive_int, default=10, metavar="N")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        # Keep main callable: argparse's usage/help exits become return codes.
        return int(error.code)

    words = top_words(_sys.stdin.read(), args.top)
    if isinstance(_sys.stdout, _io.TextIOWrapper):
        # Emit literal LF line endings even on Windows.
        _sys.stdout.reconfigure(newline="\n")
    for word, count in words:
        _sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

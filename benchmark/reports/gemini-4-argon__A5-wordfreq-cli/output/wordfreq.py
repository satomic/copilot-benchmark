from __future__ import annotations as _annotations

import argparse as _argparse
import collections as _collections
import re as _re
import sys as _sys

__all__ = ["tokenize", "top_words", "main"]

_TOKEN_RE = _re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        cleaned = raw.strip("'")
        if cleaned:
            tokens.append(cleaned)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("n must be an integer >= 1")
    counts = _collections.Counter(tokenize(text))
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return sorted_items[:n]


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise _argparse.ArgumentTypeError(f"invalid int value: {value!r}") from exc
    if parsed < 1:
        raise _argparse.ArgumentTypeError("N must be >= 1")
    return parsed


def _build_parser() -> _argparse.ArgumentParser:
    parser = _argparse.ArgumentParser(prog="wordfreq.py", add_help=True)
    parser.add_argument(
        "-n",
        "--top",
        dest="n",
        type=_positive_int,
        default=10,
        metavar="N",
        help="number of most frequent words to output (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return code

    text = _sys.stdin.read()
    for word, count in top_words(text, args.n):
        _sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    _sys.exit(main())

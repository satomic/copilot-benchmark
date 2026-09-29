"""Command-line tool that reads text from stdin and prints the most frequent words."""

import re
import sys


def tokenize(text: str) -> list[str]:
    """Split text into words according to the tokenization rules.

    - Lowercase the entire input.
    - Raw tokens are maximal runs of [a-z0-9'].
    - Strip leading/trailing ' from each raw token.
    - Discard empty tokens.
    """
    text = text.lower()
    raw_tokens = re.findall(r"[a-z0-9']+", text)
    result = []
    for token in raw_tokens:
        t = token.strip("'")
        if t:
            result.append(t)
    return result


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """Return at most n (word, count) pairs sorted by count desc, then word asc.

    Raises ValueError when n < 1.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    tokens = tokenize(text)
    if not tokens:
        return []
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    sorted_words = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted_words[:n]


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, read stdin, and print top word frequencies.

    Exit codes:
        0 on success
        2 on usage error (invalid N)
    """
    if argv is None:
        argv = sys.argv[1:]

    n = 10
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-n", "--top"):
            i += 1
            if i >= len(argv):
                print("error: -n/--top requires an argument", file=sys.stderr)
                return 2
            try:
                n = int(argv[i])
            except ValueError:
                print(
                    f"error: invalid value for -n/--top: {argv[i]}",
                    file=sys.stderr,
                )
                return 2
            if n < 1:
                print(
                    "error: -n/--top must be >= 1",
                    file=sys.stderr,
                )
                return 2
        else:
            print(f"error: unknown argument: {arg}", file=sys.stderr)
            return 2
        i += 1

    text = sys.stdin.read()
    pairs = top_words(text, n)
    for word, count in pairs:
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
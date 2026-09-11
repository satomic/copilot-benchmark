"""Word frequency CLI: reads text from stdin and prints the most frequent words."""

import re
import sys

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    raw_tokens = _TOKEN_RE.findall(text)
    tokens = []
    for raw in raw_tokens:
        stripped = raw.strip("'")
        if stripped:
            tokens.append(stripped)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be >= 1")
    counts: dict[str, int] = {}
    for word in tokenize(text):
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]


def _parse_args(argv: list[str]) -> int:
    n = 10
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-n", "--top"):
            if i + 1 >= len(argv):
                raise ValueError(f"missing value for {arg}")
            value = argv[i + 1]
            try:
                n = int(value)
            except ValueError:
                raise ValueError(f"invalid int value: {value!r}")
            i += 2
        else:
            raise ValueError(f"unrecognized argument: {arg}")
    if n < 1:
        raise ValueError("N must be >= 1")
    return n


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        n = _parse_args(argv)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = sys.stdin.read()
    results = top_words(text, n)
    lines = [f"{word}\t{count}" for word, count in results]
    if lines:
        sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import re
import sys

__all__ = ["tokenize", "top_words", "main"]


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    raw_tokens = re.findall(r"[a-z0-9']+", lowered)
    tokens: list[str] = []
    for raw in raw_tokens:
        token = raw.strip("'")
        if token:
            tokens.append(token)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be at least 1")

    counts: dict[str, int] = {}
    for word in tokenize(text):
        counts[word] = counts.get(word, 0) + 1

    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:n]


def _parse_count(argv: list[str]) -> int:
    if not argv:
        return 10
    if len(argv) == 1:
        value = argv[0]
        if value.startswith("--top="):
            value = value.split("=", 1)[1]
        else:
            raise ValueError("invalid arguments")
        return _coerce_count(value)
    if len(argv) == 2 and argv[0] in {"-n", "--top"}:
        return _coerce_count(argv[1])
    raise ValueError("invalid arguments")


def _coerce_count(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("count must be an integer") from exc
    if value < 1:
        raise ValueError("count must be at least 1")
    return value


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        n = _parse_count(args)
    except ValueError:
        print(f"usage: {sys.argv[0]} [-n N]", file=sys.stderr)
        return 2

    text = sys.stdin.read()
    if not text:
        return 0

    results = top_words(text, n)
    for word, count in results:
        sys.stdout.write(f"{word}\t{count}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

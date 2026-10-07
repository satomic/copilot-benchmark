"""Word frequency CLI: reads stdin, prints the most frequent words."""
import argparse
import re
import sys
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN_RE.findall(text.lower()):
        word = raw.strip("'")
        if word:
            tokens.append(word)
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    if n < 1:
        raise ValueError("n must be >= 1")
    counts = Counter(tokenize(text))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:n]


def _read_stdin() -> str:
    # Read bytes when available so decoding is UTF-8 regardless of locale.
    buf = getattr(sys.stdin, "buffer", None)
    if buf is not None:
        return buf.read().decode("utf-8", errors="replace")
    return sys.stdin.read()


def _write_stdout(s: str) -> None:
    # Write bytes when available so newlines stay "\n" on Windows.
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        buf.write(s.encode("utf-8"))
        buf.flush()
    else:
        sys.stdout.write(s)
        sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wordfreq", add_help=True)
    parser.add_argument("-n", "--top", dest="n", default="10", metavar="N")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits with 0 for --help and 2 for usage errors.
        return exc.code if isinstance(exc.code, int) else 2
    try:
        n = int(args.n)
    except ValueError:
        n = 0
    if n < 1:
        print(f"wordfreq: N must be an integer >= 1, got {args.n!r}", file=sys.stderr)
        return 2
    out = "".join(f"{w}\t{c}\n" for w, c in top_words(_read_stdin(), n))
    if out:
        _write_stdout(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

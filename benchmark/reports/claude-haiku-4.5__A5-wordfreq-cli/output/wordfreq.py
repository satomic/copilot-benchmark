import sys
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    """
    Tokenize text according to specification:
    1. Lowercase the entire input first.
    2. A raw token is a maximal run of characters matching [a-z0-9'].
    3. Strip leading and trailing ' characters from each raw token.
    4. Discard tokens that are empty after stripping.
    5. Apostrophes inside a token are kept.
    """
    text = text.lower()
    raw_tokens = re.findall(r"[a-z0-9']+", text)
    
    tokens = []
    for token in raw_tokens:
        stripped = token.strip("'")
        if stripped:
            tokens.append(stripped)
    
    return tokens


def top_words(text: str, n: int = 10) -> list[tuple[str, int]]:
    """
    Return the top n most frequent words.
    Sort by count descending, then by word ascending.
    Raises ValueError when n < 1.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    
    tokens = tokenize(text)
    
    if not tokens:
        return []
    
    word_counts = Counter(tokens)
    sorted_words = sorted(word_counts.items(), key=lambda x: (-x[1], x[0]))
    
    return sorted_words[:n]


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.
    Usage: python wordfreq.py [-n N] or [--top N]
    Reads from stdin, outputs to stdout.
    Returns 0 on success, 2 on usage error.
    """
    if argv is None:
        argv = sys.argv[1:]
    
    n = 10
    i = 0
    
    while i < len(argv):
        arg = argv[i]
        if arg in ["-n", "--top"]:
            if i + 1 >= len(argv):
                print("Error: -n/--top requires an argument", file=sys.stderr)
                return 2
            try:
                n = int(argv[i + 1])
            except ValueError:
                print("Error: -n/--top argument must be an integer", file=sys.stderr)
                return 2
            if n < 1:
                print("Error: -n/--top argument must be at least 1", file=sys.stderr)
                return 2
            i += 2
        else:
            print(f"Error: unknown argument {arg}", file=sys.stderr)
            return 2
    
    try:
        text = sys.stdin.read()
    except Exception as e:
        print(f"Error reading from stdin: {e}", file=sys.stderr)
        return 2
    
    words = top_words(text, n)
    
    for word, count in words:
        print(f"{word}\t{count}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Task A2 — `.env` Line Parser

**Difficulty:** Atomic

## Working agreement (read this first)

- This folder is the project root. Do not read or write anything outside it.
- Python 3.11 is available. Use the **standard library only** — do not install any third-party
  package and do not access the network.
- Create **exactly** the files listed under *Deliverables*. Do not add extra files
  (no `README.md`, no `requirements.txt`, no scratch or notes files).
- Do not ask clarifying questions. If something is genuinely ambiguous, choose the most
  reasonable interpretation, implement it, and record the choice in a short code comment.
- When the deliverables satisfy the acceptance criteria, stop.

## Goal

Implement a parser for a small, precisely specified `.env`-style configuration format.

## Deliverables

- `envparse.py`

## Public API

```python
def parse_env(text: str) -> dict[str, str]:
    ...
```

## Format specification

Process the input **line by line**. Lines are separated by `\n`; a trailing `\r` on any line
is stripped before processing.

1. A line that is empty or contains only whitespace is **skipped**.
2. A line whose first non-whitespace character is `#` is a comment and is **skipped**.
3. Otherwise the line must contain at least one `=`. Split on the **first** `=` only:
   everything before it is the raw key, everything after it is the raw value.
4. The key is the raw key with leading and trailing whitespace stripped. An optional
   `export` prefix followed by at least one space is removed (e.g. `export FOO=1` → key `FOO`).
5. A key is valid if it matches `^[A-Za-z_][A-Za-z0-9_]*$`. An invalid or empty key is an error.
6. The value is the raw value with leading and trailing whitespace stripped, then:
   - If it starts and ends with `"` (and has length >= 2), the surrounding quotes are removed
     and these escape sequences are expanded inside: `\n` → newline, `\t` → tab,
     `\r` → carriage return, `\"` → `"`, `\\` → backslash. Any other `\x` sequence is left
     as-is (both characters).
   - Else if it starts and ends with `'` (and has length >= 2), the surrounding quotes are
     removed and the content is taken **literally** — no escape expansion.
   - Else the value is unquoted: it is taken as-is, except that an unquoted `#` that is
     preceded by at least one whitespace character starts a trailing comment; that `#` and
     everything after it are removed, and the remaining value is stripped again.
     A `#` not preceded by whitespace is part of the value (e.g. `C=a#b` → `a#b`).
7. If the same key appears more than once, the **last** occurrence wins.
8. Key order in the returned dict must follow first appearance of each key.

## Error handling

On a malformed line, raise `ValueError` whose message is exactly:

```
invalid line 7: <original line content without the trailing newline>
```

where `7` is the **1-based** line number. A line is malformed when it contains no `=`,
or when its key is empty or does not match the key pattern.

## Requirements

1. Implement exactly the behaviour above.
2. `envparse.py` must define no other public names. Helper names must start with `_`.
3. Importing `envparse` must have no side effects.

## Acceptance criteria

```python
parse_env("A=1\nB = 2 \n") == {"A": "1", "B": "2"}
parse_env("# c\n\n   \nA=1") == {"A": "1"}
parse_env('A="x\\ny"') == {"A": "x\ny"}
parse_env("A='x\\ny'") == {"A": "x\\ny"}
parse_env("A=hello  # trailing") == {"A": "hello"}
parse_env("A=a#b") == {"A": "a#b"}
parse_env("export FOO=bar") == {"FOO": "bar"}
parse_env("A=1\nA=2") == {"A": "2"}
parse_env("A=") == {"A": ""}
parse_env('A="  padded  "') == {"A": "  padded  "}
parse_env("URL=https://x/y?a=b") == {"URL": "https://x/y?a=b"}
```

`parse_env("A=1\nnope\n")` raises `ValueError("invalid line 2: nope")`.
`parse_env("1BAD=x")` raises `ValueError("invalid line 1: 1BAD=x")`.
`parse_env("=x")` raises `ValueError("invalid line 1: =x")`.

## Definition of done

`envparse.py` exists in this folder and every item under *Acceptance criteria* holds.

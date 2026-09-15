# Task A4 — Fix the Date-Range Splitter

**Difficulty:** Atomic

## Working agreement (read this first)

- This folder is the project root. Do not read or write anything outside it.
- Python 3.11 and `pytest` are available. Use the **standard library only** — do not install
  any third-party package and do not access the network.
- Do not create any new files. Modify only the file listed under *Deliverables*.
- Do not ask clarifying questions. If something is genuinely ambiguous, choose the most
  reasonable interpretation, implement it, and record the choice in a short code comment.
- When the deliverables satisfy the acceptance criteria, stop.

## Goal

`daterange.py` is supposed to split an inclusive date range into consecutive chunks.
It is buggy: `python -m pytest -q` currently fails. Fix the implementation so the whole
existing test suite passes.

## Deliverables

- `daterange.py` (modified in place)

## Existing files

- `daterange.py` — the buggy implementation. Its module docstring and the `split_range`
  docstring state the intended contract; treat them as the specification.
- `test_daterange.py` — the behavioural test suite. **Read-only.** You must not modify,
  delete, rename, skip, or weaken it in any way, and you must not add `conftest.py`,
  fixtures, markers, or `pytest.ini` to influence how it runs.

## The contract (restated)

`split_range(start: date, end: date, days: int) -> list[tuple[date, date]]`

1. The range `[start, end]` is **inclusive on both ends**.
2. The result is a list of `(chunk_start, chunk_end)` tuples, each inclusive on both ends.
3. Chunks are consecutive and non-overlapping: each chunk starts exactly one day after the
   previous chunk ends.
4. Together the chunks cover exactly `[start, end]` — the first chunk starts at `start` and
   the last chunk ends at `end`.
5. Every chunk spans **at most** `days` calendar days; only the last chunk may be shorter.
6. If `end` is before `start`, return `[]`.
7. If `days` is not a positive integer, raise `ValueError`.

## Constraints

1. Keep the public API exactly as it is: same module name, same function name, same parameter
   names and order, same return shape.
2. Do not change the intent of the docstrings. You may correct wording, but the contract
   must remain the one described above.
3. Do not add new public names to `daterange.py`. Helper names must start with `_`.
4. No new files at all — not even a scratch script you delete afterwards.

## Acceptance criteria

- `python -m pytest -q` reports **0 failed** and all tests passing, with `test_daterange.py`
  byte-identical to the version you were given.
- No file other than `daterange.py` has been added, modified, or removed.
- `split_range(date(2026, 1, 1), date(2026, 1, 10), 3)` returns
  `[(2026-01-01, 2026-01-03), (2026-01-04, 2026-01-06), (2026-01-07, 2026-01-09), (2026-01-10, 2026-01-10)]`.
- `split_range(date(2026, 5, 4), date(2026, 5, 4), 7)` returns `[(2026-05-04, 2026-05-04)]`.
- `split_range(date(2026, 1, 1), date(2026, 1, 10), 0)` raises `ValueError`.
- The function must terminate for every input, including `days` values that are zero or
  negative — no infinite loops.

## Definition of done

`python -m pytest -q` passes, `test_daterange.py` is unchanged, and no files were added.

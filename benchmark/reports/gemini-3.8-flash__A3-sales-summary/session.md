# Copilot CLI Session

> [!NOTE]
> - **Session ID:** `a17a24fa-7f52-4197-91de-17eb206f772d`  
> - **Started:** 2026/9/15 21:31:00  
> - **Duration:** 5m 16s  
> - **Exported:** 2026/9/15 21:36:16  

---

<sub>7s</sub>

### User

# Task A3 — Group-and-Aggregate

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

Aggregate a list of sales records by region.

## Deliverables

- `sales.py`

## Public API

```python
def summarize(rows: list[dict]) -> list[dict]:
    ...
```

## Specification

Each input row is a `dict` that may contain the keys `"region"` and `"amount"`.
Other keys are ignored.

### Region handling

1. The region value is `str(row["region"]).strip()`.
2. Rows are grouped **case-insensitively**: the group key is the region lowercased.
3. The `"region"` reported for a group is the **stripped value as it first appeared** in the
   input for that group. For example, rows with `" North "`, `"north"`, `"NORTH"` in that order
   form one group reported as `"North"`.
4. If `"region"` is missing, or is `None`, or is blank after stripping, raise `ValueError`
   with message exactly `row \<i>: missing region`, where `\<i>` is the **0-based** index of
   the offending row in the input list.

### Amount handling

5. The amount value is taken from `row.get("amount")`. It is treated as `0.0` when it is
   missing, `None`, or a string that is empty or whitespace-only.
6. Otherwise it is coerced with `float(value)`. Leading/trailing whitespace in strings is
   acceptable (`" 12.5 "` → `12.5`).
7. If coercion fails, raise `ValueError` with message exactly
   `row \<i>: invalid amount: \<repr>`, where `\<i>` is the 0-based row index and `\<repr>` is
   the Python `repr()` of the original value. Example: `row 3: invalid amount: 'abc'`.
8. `bool` amounts are not special-cased — `True` coerces to `1.0`.

### Output

9. Return a `list` of `dict`, one per group, each with exactly these four keys in this order:
   `"region"` (`str`), `"count"` (`int`), `"total"` (`float`), `"avg"` (`float`).
10. `count` is the number of rows in the group, including rows whose amount was `0.0`.
11. `total` is the sum of the group's amounts, rounded with `round(value, 2)`.
12. `avg` is `total_before_rounding / count`, rounded with `round(value, 2)`.
13. The result is sorted by `total` **descending**; ties are broken by `region` **ascending,
    case-insensitively**.
14. `summarize([])` returns `[]`.
15. The input list and its dicts must not be mutated.

## Requirements

1. `sales.py` must define no other public names. Helper names must start with `_`.
2. Importing `sales` must have no side effects.
3. Validation happens in input order: the first offending row raises, and a missing region
   is reported before an invalid amount on the same row.

## Acceptance criteria

```python
summarize([
    {"region": "North", "amount": "100"},
    {"region": "south", "amount": 50.5},
    {"region": " NORTH ", "amount": " 25 "},
    {"region": "South", "amount": None},
]) == [
    {"region": "North", "count": 2, "total": 125.0, "avg": 62.5},
    {"region": "south", "count": 2, "total": 50.5, "avg": 25.25},
]

summarize([]) == []
summarize([{"region": "a", "amount": 10}, {"region": "b", "amount": 10}]) == [
    {"region": "a", "count": 1, "total": 10.0, "avg": 10.0},
    {"region": "b", "count": 1, "total": 10.0, "avg": 10.0},
]
```

`summarize([{"amount": 1}])` raises `ValueError("row 0: missing region")`.
`summarize([{"region": "x", "amount": "abc"}])` raises `ValueError("row 0: invalid amount: 'abc'")`.

## Definition of done

`sales.py` exists in this folder and every item under *Acceptance criteria* holds.


---

<sub>12s</sub>

### Copilot

I am setting up the initial checkpoint and reviewing the requirements for Task A3.

---

<sub>46s</sub>

### `session_artifacts`

**checkpoint.md**

<details>
<summary>Arguments</summary>

```json
{
  "content": "# Task A3: Group-and-Aggregate\n\n## Goal\nAggregate a list of sales records by region.\n\n## Deliverables\n- `sales.py`\n\n## Acceptance Criteria\n- `summarize(rows)` groups by case-insensitive region, keeps first stripped representation.\n- Missing/None/blank region raises `ValueError(\"row <i>: missing region\")`.\n- Amount handled as 0.0 for None/missing/empty string; coerced via `float()` otherwise; failure raises `ValueError(\"row <i>: invalid amount: <repr>\")`.\n- Output: list of dicts with keys `\"region\"`, `\"count\"`, `\"total\"`, `\"avg\"` in that order.\n- `total` = `round(sum, 2)`, `avg` = `round(total_before_rounding / count, 2)`.\n- Sorted by `total` descending, ties broken by `region` ascending case-insensitively.\n- `summarize([]) == []`.\n- Input list and dicts not mutated.\n- Only public name is `summarize`. Helpers start with `_`.\n- No side effects on import. Standard library only. No extra files.\n\n## Initial Plan\n1. Check existing directory content.\n2. Implement `sales.py` carefully according to all rules.\n3. Test using python in powershell.\n4. Verify all acceptance criteria.\n5. Finish cleanly.\n\n## Next Action\nCheck files in the current working directory.\n",
  "operation": "write",
  "path": "checkpoint.md"
}
```

</details>

```
{"operation":"create"}
```


---

<sub>45s</sub>

### `session_artifacts` — Failed

**checkpoint.md**

<details>
<summary>Arguments</summary>

```json
{
  "operation": "read",
  "path": "checkpoint.md"
}
```

</details>

```
ENOENT: 系统找不到指定的文件。 (os error 2)
```


---

<sub>52s</sub>

### `session_artifacts`

**checkpoint.md**

<details>
<summary>Arguments</summary>

```json
{
  "operation": "read",
  "path": "checkpoint.md"
}
```

</details>

```
{"content":"# Task A3: Group-and-Aggregate\n\n## Goal\nAggregate a list of sales records by region.\n\n## Deliverables\n- `sales.py`\n\n## Acceptance Criteria\n- `summarize(rows)` groups by case-insensitive region, keeps first stripped representation.\n- Missing/None/blank region raises `ValueError(\"row <i>: missing region\")`.\n- Amount handled as 0.0 for None/missing/empty string; coerced via `float()` otherwise; failure raises `ValueError(\"row <i>: invalid amount: <repr>\")`.\n- Output: list of dicts with keys `\"region\"`, `\"count\"`, `\"total\"`, `\"avg\"` in that order.\n- `total` = `round(sum, 2)`, `avg` = `round(total_before_rounding / count, 2)`.\n- Sorted by `total` descending, ties broken by `region` ascending case-insensitively.\n- `summarize([]) == []`.\n- Input list and dicts not mutated.\n- Only public name is `summarize`. Helpers start with `_`.\n- No side effects on import. Standard library only. No extra files.\n\n## Initial Plan\n1. Check existing directory content.\n2. Implement `sales.py` carefully according to all rules.\n3. Test using python in powershell.\n4. Verify all acceptance criteria.\n5. Finish cleanly.\n\n## Next Action\nCheck files in the current working directory.\n"}
```


---

<sub>55s</sub>

### Copilot

I will check the current workspace directory for existing files.

---

<sub>57s</sub>

### `glob`

*****

"*"

```
.\task.md
```


---

<sub>1m 1s</sub>

### `view`

**view the file at C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\task.md.**

C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\task.md

<details>
<summary>77 lines</summary>

````
# Task A3 — Group-and-Aggregate

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

Aggregate a list of sales records by region.

## Deliverables

- `sales.py`

## Public API

```python
def summarize(rows: list[dict]) -> list[dict]:
    ...
```

## Specification

Each input row is a `dict` that may contain the keys `"region"` and `"amount"`.
Other keys are ignored.

### Region handling

1. The region value is `str(row["region"]).strip()`.
2. Rows are grouped **case-insensitively**: the group key is the region lowercased.
3. The `"region"` reported for a group is the **stripped value as it first appeared** in the
   input for that group. For example, rows with `" North "`, `"north"`, `"NORTH"` in that order
   form one group reported as `"North"`.
4. If `"region"` is missing, or is `None`, or is blank after stripping, raise `ValueError`
   with message exactly `row <i>: missing region`, where `<i>` is the **0-based** index of
   the offending row in the input list.

### Amount handling

5. The amount value is taken from `row.get("amount")`. It is treated as `0.0` when it is
   missing, `None`, or a string that is empty or whitespace-only.
6. Otherwise it is coerced with `float(value)`. Leading/trailing whitespace in strings is
   acceptable (`" 12.5 "` → `12.5`).
7. If coercion fails, raise `ValueError` with message exactly
   `row <i>: invalid amount: <repr>`, where `<i>` is the 0-based row index and `<repr>` is
   the Python `repr()` of the original value. Example: `row 3: invalid amount: 'abc'`.
8. `bool` amounts are not special-cased — `True` coerces to `1.0`.

### Output

9. Return a `list` of `dict`, one per group, each with exactly these four keys in this order:
   `"region"` (`str`), `"count"` (`int`), `"total"` (`float`), `"avg"` (`float`).
10. `count` is the number of rows in the group, including rows whose amount was `0.0`.
11. `total` is the sum of the group's amounts, rounded with `round(value, 2)`.
12. `avg` is `total_before_rounding / count`, rounded with `round(value, 2)`.
13. The result is sorted by `total` **descending**; ties are broken by `region` **ascending,
    case-insensitively**.
14. `summarize([])` returns `[]`.
15. The input list and its dicts must not be mutated.

## Requirements

1. `sales.py` must define no other public names. Helper names must start with `_`.
2. Importing `sales` must have no side effects.
3. Validation happens in input order: the first offending row raises, and a missing region
   is reported before an invalid amount on the same row.

## Acceptance criteria

```python
summarize([
    {"region": "North", "amount": "100"},
    {"region": "south", "amount": 50.5},
    {"region": " NORTH ", "amount": " 25 "},
    {"region": "South", "amount": None},
]) == [
    {"region": "North", "count": 2, "total": 125.0, "avg": 62.5},
    {"region": "south", "count": 2, "total": 50.5, "avg": 25.25},
]

summarize([]) == []
summarize([{"region": "a", "amount": 10}, {"region": "b", "amount": 10}]) == [
    {"region": "a", "count": 1, "total": 10.0, "avg": 10.0},
    {"region": "b", "count": 1, "total": 10.0, "avg": 10.0},
]
```

`summarize([{"amount": 1}])` raises `ValueError("row 0: missing region")`.
`summarize([{"region": "x", "amount": "abc"}])` raises `ValueError("row 0: invalid amount: 'abc'")`.

## Definition of done

`sales.py` exists in this folder and every item under *Acceptance criteria* holds.
````

</details>


---

<sub>2m 43s</sub>

### Copilot

I will now create `sales.py` implementing the `summarize` function according to the specifications.

---

<sub>2m 47s</sub>

### `create`

**create a new file at C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\sales.py.**

C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\sales.py

```
Created file C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\sales.py with 1513 characters
```


---

<sub>3m 5s</sub>

### `powershell`

**Run comprehensive test suite for sales.py**

<details>
<summary>Arguments</summary>

```json
{
  "command": "@'\nimport sys\nfrom sales import summarize\n\n# 1. Acceptance criteria test 1\nres1 = summarize([\n    {\"region\": \"North\", \"amount\": \"100\"},\n    {\"region\": \"south\", \"amount\": 50.5},\n    {\"region\": \" NORTH \", \"amount\": \" 25 \"},\n    {\"region\": \"South\", \"amount\": None},\n])\nexpected1 = [\n    {\"region\": \"North\", \"count\": 2, \"total\": 125.0, \"avg\": 62.5},\n    {\"region\": \"south\", \"count\": 2, \"total\": 50.5, \"avg\": 25.25},\n]\nassert res1 == expected1, f\"Expected {expected1}, got {res1}\"\n\n# 2. Acceptance criteria test 2: empty list\nassert summarize([]) == []\n\n# 3. Acceptance criteria test 3: ties broken ascending case-insensitively\nres3 = summarize([{\"region\": \"a\", \"amount\": 10}, {\"region\": \"b\", \"amount\": 10}])\nexpected3 = [\n    {\"region\": \"a\", \"count\": 1, \"total\": 10.0, \"avg\": 10.0},\n    {\"region\": \"b\", \"count\": 1, \"total\": 10.0, \"avg\": 10.0},\n]\nassert res3 == expected3, f\"Expected {expected3}, got {res3}\"\n\n# 4. Acceptance criteria test 4: missing region\ntry:\n    summarize([{\"amount\": 1}])\n    assert False, \"Should have raised ValueError\"\nexcept ValueError as e:\n    assert str(e) == \"row 0: missing region\", f\"Wrong message: {e}\"\n\n# 5. Acceptance criteria test 5: invalid amount\ntry:\n    summarize([{\"region\": \"x\", \"amount\": \"abc\"}])\n    assert False, \"Should have raised ValueError\"\nexcept ValueError as e:\n    assert str(e) == \"row 0: invalid amount: 'abc'\", f\"Wrong message: {e}\"\n\n# 6. Check non-mutation of input list and dicts\norig_row = {\"region\": \" East \", \"amount\": \"15\"}\ninput_list = [orig_row]\norig_row_copy = dict(orig_row)\nres6 = summarize(input_list)\nassert input_list == [orig_row], \"Input list was mutated!\"\nassert orig_row == orig_row_copy, \"Input dict was mutated!\"\n\n# 7. Check key order in output dicts\nassert list(res1[0].keys()) == [\"region\", \"count\", \"total\", \"avg\"]\n\n# 8. Check types of values in output dicts\nassert isinstance(res1[0][\"region\"], str)\nassert isinstance(res1[0][\"count\"], int)\nassert isinstance(res1[0][\"total\"], float)\nassert isinstance(res1[0][\"avg\"], float)\n\n# 9. Check public names in sales.py\nimport sales\npublic_names = [name for name in dir(sales) if not name.startswith(\"_\")]\nassert public_names == [\"summarize\"], f\"Unexpected public names: {public_names}\"\n\n# 10. Check region None and whitespace-only\nfor bad_region in [None, \"\", \"   \", \"\\t\\n\"]:\n    try:\n        summarize([{\"region\": bad_region, \"amount\": 10}])\n        assert False, f\"Should have failed on {bad_region!r}\"\n    except ValueError as e:\n        assert str(e) == \"row 0: missing region\", f\"Wrong message for {bad_region!r}: {e}\"\n\n# 11. Check amount None, missing, empty string, whitespace-only string -> treated as 0.0\nfor zero_amt in [None, \"\", \"   \", \"\\t\"]:\n    r = summarize([{\"region\": \"X\", \"amount\": zero_amt}])\n    assert r == [{\"region\": \"X\", \"count\": 1, \"total\": 0.0, \"avg\": 0.0}], f\"Failed for {zero_amt!r}: {r}\"\nr_missing = summarize([{\"region\": \"X\"}])\nassert r_missing == [{\"region\": \"X\", \"count\": 1, \"total\": 0.0, \"avg\": 0.0}]\n\n# 12. Check boolean amounts\nr_bool = summarize([{\"region\": \"X\", \"amount\": True}, {\"region\": \"X\", \"amount\": False}])\nassert r_bool == [{\"region\": \"X\", \"count\": 2, \"total\": 1.0, \"avg\": 0.5}], f\"Bool failed: {r_bool}\"\n\n# 13. Check validation order: missing region before invalid amount on same row\ntry:\n    summarize([{\"amount\": \"invalid\"}])\n    assert False, \"Should have failed\"\nexcept ValueError as e:\n    assert str(e) == \"row 0: missing region\", f\"Should report missing region first, got: {e}\"\n\n# 14. Check row index in error message on later rows\ntry:\n    summarize([{\"region\": \"A\", \"amount\": 10}, {\"region\": \"B\", \"amount\": \"invalid\"}])\n    assert False, \"Should have failed\"\nexcept ValueError as e:\n    assert str(e) == \"row 1: invalid amount: 'invalid'\", f\"Wrong message: {e}\"\n\ntry:\n    summarize([{\"region\": \"A\", \"amount\": 10}, {\"region\": \"   \"}])\n    assert False, \"Should have failed\"\nexcept ValueError as e:\n    assert str(e) == \"row 1: missing region\", f\"Wrong message: {e}\"\n\n# 15. Check tie-breaking case-insensitively\nres_tie = summarize([\n    {\"region\": \"beta\", \"amount\": 10},\n    {\"region\": \"Alpha\", \"amount\": 10},\n    {\"region\": \"GAMMA\", \"amount\": 20},\n])\nassert [r[\"region\"] for r in res_tie] == [\"GAMMA\", \"Alpha\", \"beta\"], f\"Tie breaking failed: {res_tie}\"\n\n# 16. Check rounding\nres_round = summarize([\n    {\"region\": \"R\", \"amount\": 1.006},\n    {\"region\": \"R\", \"amount\": 1.006},\n    {\"region\": \"R\", \"amount\": 1.006},\n])\n# sum = 3.018 -> total = 3.02\n# avg = 3.018 / 3 = 1.006 -> avg = 1.01\nassert res_round[0][\"total\"] == 3.02, f\"Total rounding: {res_round[0]['total']}\"\nassert res_round[0][\"avg\"] == 1.01, f\"Avg rounding: {res_round[0]['avg']}\"\n\n# 17. Check other keys are ignored\nres_ignored = summarize([{\"region\": \"Z\", \"amount\": 5, \"extra\": \"ignored\", \"id\": 123}])\nassert res_ignored == [{\"region\": \"Z\", \"count\": 1, \"total\": 5.0, \"avg\": 5.0}]\n\nprint(\"ALL TESTS PASSED SUCCESSFULLY!\")\n'@ | python -\n",
  "description": "Run comprehensive test suite for sales.py"
}
```

</details>

```
ALL TESTS PASSED SUCCESSFULLY!
<shellId: 0 completed with exit code 0>
```


---

<sub>3m 9s</sub>

### `glob`

****/***

"**/*"

```
.\task.md
.\sales.py
.\__pycache__\sales.cpython-311.pyc
```


---

<sub>3m 13s</sub>

### `powershell`

**Remove __pycache__ directory**

<details>
<summary>Arguments</summary>

```json
{
  "command": "Remove-Item -Recurse -Force __pycache__",
  "description": "Remove __pycache__ directory"
}
```

</details>

```

<shellId: 1 completed with exit code 0>
```


---

<sub>3m 34s</sub>

### `glob`

*****

"*"

```
.\task.md
.\sales.py
```


---

<sub>3m 39s</sub>

### `powershell`

**Check git status for uncommitted or untracked files**

<details>
<summary>Arguments</summary>

```json
{
  "command": "git status --short",
  "description": "Check git status for uncommitted or untracked files"
}
```

</details>

<details>
<summary>17 lines</summary>

```
M ../../../../.gitignore
 M ../../../models.txt
?? ../../../reports/gemini-3.8-flash__A1-roman-numeral/
?? ../../../reports/gemini-3.8-flash__A2-env-parser/
?? ../../../reports/gemini-3.8-flash__A3-sales-summary/
?? ../../../reports/kimi-k3__A1-roman-numeral/
?? ../../../reports/kimi-k3__A2-env-parser/
?? ../../../reports/kimi-k3__A3-sales-summary/
?? ../../../reports/kimi-k3__A4-fix-daterange/
?? ../../../reports/kimi-k3__A5-wordfreq-cli/
?? ../../../reports/kimi-k3__C1-expr-interpreter/
?? ../../../reports/kimi-k3__C2-kvstore/
?? ../../../reports/kimi-k3__C3-microdb/
?? ../../../reports/kimi-k3__C4-microvm/
?? ../../../reports/kimi-k3__M1-lru-ttl-cache/
?? ../../../reports/kimi-k3__M2-log-analyzer/
<shellId: 2 completed with exit code 0>
```

</details>


---

<sub>4m 19s</sub>

### `view`

**view the file at C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\sales.py.**

C:\workspace\13_benchmark\GPT-6 in Coding\benchmark\runs\gemini-3.8-flash\A3-sales-summary\sales.py

<details>
<summary>39 lines</summary>

```
def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}

    for i, row in enumerate(rows):
        if "region" not in row or row["region"] is None:
            raise ValueError(f"row {i}: missing region")

        stripped_region = str(row["region"]).strip()
        if not stripped_region:
            raise ValueError(f"row {i}: missing region")

        raw_amount = row.get("amount")
        if raw_amount is None:
            amount = 0.0
        elif isinstance(raw_amount, str) and not raw_amount.strip():
            amount = 0.0
        else:
            try:
                amount = float(raw_amount)
            except (ValueError, TypeError, OverflowError):
                raise ValueError(f"row {i}: invalid amount: {raw_amount!r}")

        group_key = stripped_region.lower()
        if group_key not in groups:
            groups[group_key] = {
                "region": stripped_region,
                "count": 0,
                "total": 0.0,
            }

        groups[group_key]["count"] += 1
        groups[group_key]["total"] += amount

    result = []
    for g in groups.values():
        count = g["count"]
        raw_total = g["total"]
        result.append({
            "region": g["region"],
            "count": count,
            "total": round(raw_total, 2),
            "avg": round(raw_total / count, 2),
        })

    result.sort(key=lambda x: (-x["total"], x["region"].lower()))
    return result
```

</details>


---

<sub>4m 26s</sub>

### `powershell`

**Run quick test with python -B to verify no pycache created**

<details>
<summary>Arguments</summary>

```json
{
  "command": "python -B -c \"import sales; print(sales.summarize([{'region': 'North', 'amount': '100'}]))\"",
  "description": "Run quick test with python -B to verify no pycache created"
}
```

</details>

```
[{'region': 'North', 'count': 1, 'total': 100.0, 'avg': 100.0}]
<shellId: 3 completed with exit code 0>
```


---

<sub>4m 41s</sub>

### `glob`

*****

"*"

```
.\task.md
.\sales.py
```


---

<sub>4m 45s</sub>

### `session_artifacts`

**checkpoint.md**

<details>
<summary>Arguments</summary>

```json
{
  "content": "# Task A3: Group-and-Aggregate\n\n## Goal\nAggregate a list of sales records by region.\n\n## Deliverables\n- `sales.py` (created and verified)\n\n## Status\nCompleted. All acceptance criteria met and verified with comprehensive tests.\nNo extra files created.\n",
  "operation": "write",
  "path": "checkpoint.md"
}
```

</details>

```
{"operation":"update"}
```


---

<sub>5m 3s</sub>

### Copilot

I have implemented the 

---

<sub>5m 14s</sub>

### Copilot

I have implemented `sales.py` with the `summarize` function according to the specifications:

- Groups rows case-insensitively by region while preserving the first-seen stripped region representation.
- Validates region presence and format before amount conversion, raising exact `ValueError` messages on invalid input.
- Handles empty/whitespace/missing amounts as `0.0`, coerces valid numbers to float, and aggregates totals and averages rounded to 2 decimal places.
- Sorts groups by total descending, breaking ties by region ascending case-insensitively.
- Confirms zero side effects, no mutation of inputs, and no additional public names or files.

---

<sub>Generated by [GitHub Copilot CLI](https://github.com/features/copilot/cli)</sub>

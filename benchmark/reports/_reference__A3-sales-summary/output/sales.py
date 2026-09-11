"""Aggregate sales rows by region."""

_BLANK = ("", None)


def summarize(rows: list[dict]) -> list[dict]:
    """Group `rows` by region (case-insensitively) and aggregate amounts."""
    groups: dict[str, dict] = {}

    for index, row in enumerate(rows):
        region = _region(row, index)
        amount = _amount(row, index)

        bucket = groups.setdefault(
            region.lower(), {"region": region, "count": 0, "total": 0.0}
        )
        bucket["count"] += 1
        bucket["total"] += amount

    summaries = [
        {
            "region": bucket["region"],
            "count": bucket["count"],
            "total": round(bucket["total"], 2),
            "avg": round(bucket["total"] / bucket["count"], 2),
        }
        for bucket in groups.values()
    ]
    summaries.sort(key=lambda item: (-item["total"], item["region"].lower()))
    return summaries


def _region(row: dict, index: int) -> str:
    raw = row.get("region")
    region = "" if raw is None else str(raw).strip()
    if not region:
        raise ValueError(f"row {index}: missing region")
    return region


def _amount(row: dict, index: int) -> float:
    raw = row.get("amount")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"row {index}: invalid amount: {raw!r}") from None

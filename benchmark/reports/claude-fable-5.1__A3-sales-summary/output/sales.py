"""Aggregate sales records by region."""

__all__ = ["summarize"]


def _region(row: dict, index: int) -> str:
    value = row.get("region")
    if value is None:
        raise ValueError(f"row {index}: missing region")
    region = str(value).strip()
    if not region:
        raise ValueError(f"row {index}: missing region")
    return region


def _amount(row: dict, index: int) -> float:
    value = row.get("amount")
    if value is None:
        return 0.0
    if isinstance(value, str) and not value.strip():
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"row {index}: invalid amount: {value!r}") from None


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for index, row in enumerate(rows):
        region = _region(row, index)
        amount = _amount(row, index)
        key = region.lower()
        group = groups.get(key)
        if group is None:
            group = {"region": region, "count": 0, "sum": 0.0}
            groups[key] = group
        group["count"] += 1
        group["sum"] += amount

    result = [
        {
            "region": g["region"],
            "count": g["count"],
            "total": round(g["sum"], 2),
            "avg": round(g["sum"] / g["count"], 2),
        }
        for g in groups.values()
    ]
    result.sort(key=lambda r: (-r["total"], r["region"].lower()))
    return result

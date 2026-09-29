"""Aggregate sales records by region."""

__all__ = ["summarize"]


def _region(row, i):
    value = row.get("region")
    if value is None:
        raise ValueError(f"row {i}: missing region")
    region = str(value).strip()
    if not region:
        raise ValueError(f"row {i}: missing region")
    return region


def _amount(row, i):
    value = row.get("amount")
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"row {i}: invalid amount: {value!r}") from None


def summarize(rows: list[dict]) -> list[dict]:
    groups = {}
    for i, row in enumerate(rows):
        region = _region(row, i)
        amount = _amount(row, i)
        key = region.lower()
        group = groups.get(key)
        if group is None:
            groups[key] = [region, 1, amount]
        else:
            group[1] += 1
            group[2] += amount

    result = [
        {
            "region": region,
            "count": count,
            "total": round(total, 2),
            "avg": round(total / count, 2),
        }
        for region, count, total in groups.values()
    ]
    # Ties compare the rounded (reported) totals.
    result.sort(key=lambda r: (-r["total"], r["region"].lower()))
    return result

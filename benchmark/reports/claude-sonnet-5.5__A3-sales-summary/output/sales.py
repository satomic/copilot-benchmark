def _amount(value, index):
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"row {index}: invalid amount: {value!r}") from None


def summarize(rows: list[dict]) -> list[dict]:
    groups = {}
    for i, row in enumerate(rows):
        raw = row.get("region")
        region = "" if raw is None else str(raw).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")
        amount = _amount(row.get("amount"), i)
        key = region.lower()
        if key not in groups:
            groups[key] = [region, 0, 0.0]
        g = groups[key]
        g[1] += 1
        g[2] += amount

    result = [
        {
            "region": region,
            "count": count,
            "total": round(total, 2),
            "avg": round(total / count, 2),
        }
        for region, count, total in groups.values()
    ]
    # Ties are compared on the rounded total, the value that is reported.
    result.sort(key=lambda r: (-r["total"], r["region"].lower()))
    return result

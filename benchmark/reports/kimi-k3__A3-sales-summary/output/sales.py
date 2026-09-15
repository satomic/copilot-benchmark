"""Aggregate sales records by region."""


def summarize(rows: list[dict]) -> list[dict]:
    groups = {}
    order = []
    for i, row in enumerate(rows):
        raw_region = row.get("region")
        if raw_region is None:
            raise ValueError(f"row {i}: missing region")
        region = str(raw_region).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")
        key = region.lower()

        value = row.get("amount")
        if value is None:
            amount = 0.0
        elif isinstance(value, str) and not value.strip():
            amount = 0.0
        else:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"row {i}: invalid amount: {value!r}") from None

        if key not in groups:
            groups[key] = {"region": region, "count": 0, "total": 0.0}
            order.append(key)
        g = groups[key]
        g["count"] += 1
        g["total"] += amount

    result = []
    for key in order:
        g = groups[key]
        total_before = g["total"]
        result.append({
            "region": g["region"],
            "count": g["count"],
            "total": round(total_before, 2),
            "avg": round(total_before / g["count"], 2),
        })

    result.sort(key=lambda d: (-d["total"], d["region"].lower()))
    return result

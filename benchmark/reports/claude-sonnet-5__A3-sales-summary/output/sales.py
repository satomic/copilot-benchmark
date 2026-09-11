def summarize(rows: list[dict]) -> list[dict]:
    groups = {}

    for i, row in enumerate(rows):
        region_raw = row.get("region")
        if region_raw is None:
            raise ValueError(f"row {i}: missing region")
        region = str(region_raw).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")
        key = region.lower()

        amount_raw = row.get("amount")
        if amount_raw is None:
            amount = 0.0
        elif isinstance(amount_raw, str) and amount_raw.strip() == "":
            amount = 0.0
        else:
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                raise ValueError(f"row {i}: invalid amount: {amount_raw!r}")

        if key not in groups:
            groups[key] = {"region": region, "count": 0, "total": 0.0}
        groups[key]["count"] += 1
        groups[key]["total"] += amount

    result = [
        {
            "region": g["region"],
            "count": g["count"],
            "total": round(g["total"], 2),
            "avg": round(g["total"] / g["count"], 2),
        }
        for g in groups.values()
    ]

    result.sort(key=lambda g: (-g["total"], g["region"].lower()))
    return result

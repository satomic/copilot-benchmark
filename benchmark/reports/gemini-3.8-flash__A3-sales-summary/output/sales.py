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

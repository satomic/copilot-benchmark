def summarize(rows: list[dict]) -> list[dict]:
    """Aggregate sales by stripped, case-insensitive region."""
    groups = {}
    for index, row in enumerate(rows):
        region_value = row.get("region")
        if region_value is None:
            raise ValueError(f"row {index}: missing region")
        region = str(region_value).strip()
        if not region:
            raise ValueError(f"row {index}: missing region")

        value = row.get("amount")
        if value is None or (isinstance(value, str) and not value.strip()):
            amount = 0.0
        else:
            try:
                amount = float(value)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError(
                    f"row {index}: invalid amount: {value!r}"
                ) from error

        key = region.lower()
        if key not in groups:
            groups[key] = {"region": region, "count": 0, "total": 0.0}
        group = groups[key]
        group["count"] += 1
        group["total"] += amount

    result = [
        {
            "region": group["region"],
            "count": group["count"],
            "total": round(group["total"], 2),
            "avg": round(group["total"] / group["count"], 2),
        }
        for group in groups.values()
    ]
    result.sort(key=lambda group: (-group["total"], group["region"].lower()))
    return result

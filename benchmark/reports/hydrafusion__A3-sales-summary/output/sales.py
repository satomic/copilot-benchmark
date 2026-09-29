def summarize(rows: list[dict]) -> list[dict]:
    groups = {}

    for index, row in enumerate(rows):
        if "region" not in row or row["region"] is None:
            raise ValueError(f"row {index}: missing region")

        region = str(row["region"]).strip()
        if not region:
            raise ValueError(f"row {index}: missing region")

        value = row.get("amount")
        if value is None or (isinstance(value, str) and not value.strip()):
            amount = 0.0
        else:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"row {index}: invalid amount: {value!r}"
                ) from None

        key = region.lower()
        if key not in groups:
            groups[key] = [region, 0, 0.0]
        groups[key][1] += 1
        groups[key][2] += amount

    result = [
        {
            "region": region,
            "count": count,
            "total": round(total, 2),
            "avg": round(total / count, 2),
        }
        for region, count, total in groups.values()
    ]
    result.sort(key=lambda group: (-group["total"], group["region"].lower()))
    return result

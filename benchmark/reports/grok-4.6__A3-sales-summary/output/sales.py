def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}
    for i, row in enumerate(rows):
        if "region" not in row or row["region"] is None:
            raise ValueError(f"row {i}: missing region")
        region = str(row["region"]).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")

        value = row.get("amount")
        if value is None or (isinstance(value, str) and not value.strip()):
            amount = 0.0
        else:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"row {i}: invalid amount: {value!r}") from None

        key = region.lower()
        if key not in groups:
            groups[key] = [region, 0, 0.0]
        groups[key][1] += 1
        groups[key][2] += amount

    result = []
    for display, count, total in groups.values():
        result.append(
            {
                "region": display,
                "count": count,
                "total": round(total, 2),
                "avg": round(total / count, 2),
            }
        )
    result.sort(key=lambda g: (-g["total"], g["region"].lower()))
    return result

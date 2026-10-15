def _parse_amount(index: int, value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str) and value.strip() == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"row {index}: invalid amount: {value!r}") from None


def summarize(rows: list[dict]) -> list[dict]:
    # Groups keyed by lowercased region; value is [first-seen region, count, total].
    groups: dict[str, list] = {}

    for i, row in enumerate(rows):
        region_raw = row.get("region")
        region = "" if region_raw is None else str(region_raw).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")

        amount = _parse_amount(i, row.get("amount"))

        key = region.lower()
        if key not in groups:
            groups[key] = [region, 0, 0.0]
        group = groups[key]
        group[1] += 1
        group[2] += amount

    result = []
    for region, count, total in groups.values():
        result.append({
            "region": region,
            "count": count,
            "total": round(total, 2),
            "avg": round(total / count, 2),
        })

    # Total descending; ties broken by region ascending (case-insensitive).
    result.sort(key=lambda g: (-g["total"], g["region"].lower()))
    return result

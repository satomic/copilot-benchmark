def _region_name(row: dict, index: int) -> str:
    raw = row.get("region")
    if raw is None:
        raise ValueError(f"row {index}: missing region")
    region = str(raw).strip()
    if region == "":
        raise ValueError(f"row {index}: missing region")
    return region


def _amount_value(row: dict, index: int) -> float:
    amount = row.get("amount")
    if amount is None or (isinstance(amount, str) and amount.strip() == ""):
        return 0.0
    try:
        return float(amount)
    except (TypeError, ValueError):
        raise ValueError(f"row {index}: invalid amount: {amount!r}") from None


def summarize(rows: list[dict]) -> list[dict]:
    # Sort by the reported (rounded) total. Ties use the case-insensitive region.
    groups: dict[str, dict] = {}
    for index, row in enumerate(rows):
        region = _region_name(row, index)
        amount = _amount_value(row, index)
        key = region.lower()
        group = groups.get(key)
        if group is None:
            group = {"region": region, "count": 0, "sum": 0.0}
            groups[key] = group
        group["count"] += 1
        group["sum"] += amount

    result = []
    for group in groups.values():
        raw_total = group["sum"]
        count = group["count"]
        result.append(
            {
                "region": group["region"],
                "count": count,
                "total": round(raw_total, 2),
                "avg": round(raw_total / count, 2),
            }
        )
    result.sort(key=lambda item: (-item["total"], item["region"].lower()))
    return result

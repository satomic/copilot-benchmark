def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}

    for i, row in enumerate(rows):
        raw_region = row.get("region")
        if raw_region is None:
            raise ValueError(f"row {i}: missing region")
        region = str(raw_region).strip()
        if not region:
            raise ValueError(f"row {i}: missing region")

        raw_amount = row.get("amount")
        if raw_amount is None or (isinstance(raw_amount, str) and not raw_amount.strip()):
            amount = 0.0
        else:
            try:
                amount = float(raw_amount)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"row {i}: invalid amount: {raw_amount!r}") from exc

        key = region.lower()
        if key not in groups:
            groups[key] = [region, 1, amount]
        else:
            entry = groups[key]
            entry[1] += 1
            entry[2] += amount

    result = [
        {
            "region": entry[0],
            "count": entry[1],
            "total": round(entry[2], 2),
            "avg": round(entry[2] / entry[1], 2),
        }
        for entry in groups.values()
    ]

    result.sort(key=lambda item: (-item["total"], item["region"].lower()))
    return result

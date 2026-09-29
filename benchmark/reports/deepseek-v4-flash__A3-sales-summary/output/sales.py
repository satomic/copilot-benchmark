def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[str, list] = {}
    first_region: dict[str, str] = {}
    region_order: list[str] = []

    for i, row in enumerate(rows):
        raw_region = row.get("region")
        if raw_region is None or (isinstance(raw_region, str) and raw_region.strip() == ""):
            raise ValueError(f"row {i}: missing region")
        region_str = str(raw_region).strip()
        if region_str == "":
            raise ValueError(f"row {i}: missing region")

        raw_amount = row.get("amount")
        if raw_amount is None:
            amount = 0.0
        elif isinstance(raw_amount, str) and raw_amount.strip() == "":
            amount = 0.0
        else:
            try:
                amount = float(raw_amount)
            except (ValueError, TypeError):
                raise ValueError(f"row {i}: invalid amount: {repr(raw_amount)}")

        key = region_str.lower()
        if key not in groups:
            groups[key] = []
            first_region[key] = region_str
            region_order.append(key)
        groups[key].append(amount)

    result = []
    for key in region_order:
        amounts = groups[key]
        count = len(amounts)
        total_before_round = sum(amounts)
        total = round(total_before_round, 2)
        avg = round(total_before_round / count, 2) if count > 0 else 0.0
        result.append({
            "region": first_region[key],
            "count": count,
            "total": total,
            "avg": avg,
        })

    result.sort(key=lambda r: (-r["total"], r["region"].lower()))
    return result
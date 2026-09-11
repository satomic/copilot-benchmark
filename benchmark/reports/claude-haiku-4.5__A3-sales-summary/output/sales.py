def summarize(rows: list[dict]) -> list[dict]:
    groups = {}  # lowercase_region -> (original_region, [amounts])

    for i, row in enumerate(rows):
        # Validate and get region (region validation before amount per spec)
        if "region" not in row or row["region"] is None:
            raise ValueError(f"row {i}: missing region")

        region_str = str(row["region"]).strip()

        if not region_str:
            raise ValueError(f"row {i}: missing region")

        region_lower = region_str.lower()

        # Validate and get amount
        amount_raw = row.get("amount")

        if amount_raw is None or (isinstance(amount_raw, str) and not amount_raw.strip()):
            amount = 0.0
        else:
            try:
                amount = float(amount_raw)
            except (ValueError, TypeError):
                raise ValueError(f"row {i}: invalid amount: {repr(amount_raw)}")

        # Add to group (keep original region for first occurrence)
        if region_lower not in groups:
            groups[region_lower] = (region_str, [])

        groups[region_lower][1].append(amount)

    # Build output
    result = []
    for region_lower, (region_original, amounts) in groups.items():
        count = len(amounts)
        total = sum(amounts)
        total_rounded = round(total, 2)
        avg = total / count
        avg_rounded = round(avg, 2)

        result.append({
            "region": region_original,
            "count": count,
            "total": total_rounded,
            "avg": avg_rounded,
        })

    # Sort by total descending, then by region ascending (case-insensitive)
    result.sort(key=lambda x: (-x["total"], x["region"].lower()))

    return result

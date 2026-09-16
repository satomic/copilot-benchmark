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
            except (TypeError, ValueError, OverflowError):
                raise ValueError(
                    f"row {index}: invalid amount: {value!r}"
                ) from None

        key = region.lower()
        if key not in groups:
            groups[key] = [region, 0, 0.0]
        group = groups[key]
        group[1] += 1
        group[2] += amount

    result = []
    for region, count, total_before_rounding in groups.values():
        total = round(total_before_rounding, 2)
        result.append(
            {
                "region": region,
                "count": count,
                "total": total,
                "avg": round(total_before_rounding / count, 2),
            }
        )

    result.sort(key=lambda item: (-item["total"], item["region"].lower()))
    return result

def summarize(rows: list[dict]) -> list[dict]:
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
            groups[key] = {
                "region": region,
                "count": 0,
                "total": 0.0,
                "avg": 0.0,
            }
        group = groups[key]
        group["count"] += 1
        group["total"] += amount

    result = list(groups.values())
    for group in result:
        group["avg"] = round(group["total"] / group["count"], 2)
        group["total"] = round(group["total"], 2)
    return sorted(result, key=lambda group: (-group["total"], group["region"].lower()))

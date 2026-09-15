def _normalize_region(value):
    return str(value).strip()


def _coerce_amount(value):
    if value is None:
        return 0.0
    if isinstance(value, str) and not value.strip():
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid amount: {value!r}")


def summarize(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    groups = {}

    for i, row in enumerate(rows):
        region_value = row.get("region") if isinstance(row, dict) else None
        if region_value is None:
            raise ValueError(f"row {i}: missing region")

        region_text = _normalize_region(region_value)
        if not region_text:
            raise ValueError(f"row {i}: missing region")

        key = region_text.lower()
        if key not in groups:
            groups[key] = {"region": region_text, "count": 0, "total": 0.0}

        amount_raw = row.get("amount")
        try:
            amount = _coerce_amount(amount_raw)
        except ValueError as exc:
            raise ValueError(f"row {i}: invalid amount: {amount_raw!r}") from exc

        group = groups[key]
        group["count"] += 1
        group["total"] += amount

    output = []
    for group in groups.values():
        total = round(group["total"], 2)
        avg = round(group["total"] / group["count"], 2)
        output.append(
            {
                "region": group["region"],
                "count": group["count"],
                "total": total,
                "avg": avg,
            }
        )

    output.sort(key=lambda item: (-item["total"], item["region"].lower()))
    return output

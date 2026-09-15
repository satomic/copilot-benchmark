from __future__ import annotations

from .errors import TypeMismatchError
from .value import compare_lt

AGGREGATE_NAMES = {"count", "sum", "avg", "min", "max"}


def aggregate_value(name: str, values: list[object], *, star_count: int | None = None) -> object:
    key = name.lower()
    if key == "count":
        if star_count is not None:
            return star_count
        return sum(1 for v in values if v is not None)
    if key == "sum":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        if any(isinstance(v, bool) for v in nums):
            raise TypeMismatchError("sum requires numeric input")
        if all(isinstance(v, int) for v in nums):
            return sum(nums)
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nums):
            return float(sum(float(v) for v in nums))
        raise TypeMismatchError("sum requires numeric input")
    if key == "avg":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        if any(isinstance(v, bool) for v in nums):
            raise TypeMismatchError("avg requires numeric input")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in nums):
            raise TypeMismatchError("avg requires numeric input")
        return sum(float(v) for v in nums) / len(nums)
    if key == "min":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        if any(isinstance(v, bool) and not isinstance(v, int) for v in nums):
            pass
        if not _compatible(nums):
            raise TypeMismatchError("min requires comparable values")
        current = nums[0]
        for v in nums[1:]:
            if compare_lt(v, current) is True:
                current = v
        return current
    if key == "max":
        nums = [v for v in values if v is not None]
        if not nums:
            return None
        if not _compatible(nums):
            raise TypeMismatchError("max requires comparable values")
        current = nums[0]
        for v in nums[1:]:
            if compare_lt(current, v) is True:
                current = v
        return current
    raise TypeMismatchError(f"unknown aggregate {name}")


def _compatible(values: list[object]) -> bool:
    kinds = {type(v) for v in values}
    if not values:
        return True
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return True
    if all(isinstance(v, str) for v in values):
        return True
    if all(isinstance(v, bool) for v in values):
        return True
    return False

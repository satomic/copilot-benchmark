from .parser import Expr
from .expr import evaluate, is_aggregate_expr
from .errors import ArityError, TypeMismatchError, AggregateError
from .value import type_of, is_numeric, compare_lt


class Aggregator:
    def __init__(self, expr: Expr, rows: list[dict[str, object]]) -> None:
        self.expr = expr
        self.rows = rows

    def compute(self) -> object:
        """Compute the aggregate value."""
        if self.expr.type != "call":
            raise AggregateError(f"Not an aggregate")
        func_name = self.expr.value.lower()
        args = self.expr.args or []
        
        if func_name == "count":
            if len(args) == 1 and args[0].type == "lit" and args[0].value == "*":
                return len(self.rows)
            if len(args) != 1:
                raise ArityError(f"count() takes 1 argument, got {len(args)}", "count", 1)
            count = 0
            for row in self.rows:
                val = evaluate(args[0], row)
                if val is not None:
                    count += 1
            return count
        
        if func_name == "sum":
            if len(args) != 1:
                raise ArityError(f"sum() takes 1 argument, got {len(args)}", "sum", 1)
            values = []
            for row in self.rows:
                val = evaluate(args[0], row)
                if val is not None:
                    if not is_numeric(val):
                        raise TypeMismatchError(f"sum() requires numeric values")
                    values.append(val)
            if not values:
                return None
            total = sum(values)
            has_float = any(isinstance(v, float) for v in values)
            return float(total) if has_float else total
        
        if func_name == "avg":
            if len(args) != 1:
                raise ArityError(f"avg() takes 1 argument, got {len(args)}", "avg", 1)
            values = []
            for row in self.rows:
                val = evaluate(args[0], row)
                if val is not None:
                    if not is_numeric(val):
                        raise TypeMismatchError(f"avg() requires numeric values")
                    values.append(val)
            if not values:
                return None
            return sum(values) / len(values)
        
        if func_name == "min":
            if len(args) != 1:
                raise ArityError(f"min() takes 1 argument, got {len(args)}", "min", 1)
            values = []
            for row in self.rows:
                val = evaluate(args[0], row)
                if val is not None:
                    values.append(val)
            if not values:
                return None
            if values and isinstance(values[0], bool):
                all_bool = all(isinstance(v, bool) for v in values)
                if not all_bool:
                    raise TypeMismatchError(f"Cannot mix BOOL with other types in min()")
                return min(values)
            first_type = type_of(values[0])
            for v in values[1:]:
                if type_of(v) != first_type and not (
                    first_type in ("INT", "FLOAT") and type_of(v) in ("INT", "FLOAT")
                ):
                    raise TypeMismatchError(f"Cannot mix types in min()")
            return min(values, key=lambda x: (x is None, x))
        
        if func_name == "max":
            if len(args) != 1:
                raise ArityError(f"max() takes 1 argument, got {len(args)}", "max", 1)
            values = []
            for row in self.rows:
                val = evaluate(args[0], row)
                if val is not None:
                    values.append(val)
            if not values:
                return None
            if values and isinstance(values[0], bool):
                all_bool = all(isinstance(v, bool) for v in values)
                if not all_bool:
                    raise TypeMismatchError(f"Cannot mix BOOL with other types in max()")
                return max(values)
            first_type = type_of(values[0])
            for v in values[1:]:
                if type_of(v) != first_type and not (
                    first_type in ("INT", "FLOAT") and type_of(v) in ("INT", "FLOAT")
                ):
                    raise TypeMismatchError(f"Cannot mix types in max()")
            return max(values, key=lambda x: (x is None, x))
        
        raise AggregateError(f"Unknown aggregate: {func_name}")

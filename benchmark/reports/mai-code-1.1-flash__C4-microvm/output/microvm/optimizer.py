from .parser import (
    AssignStmt,
    Binary,
    BlockStmt,
    IfStmt,
    LetStmt,
    Literal,
    Name,
    PrintStmt,
    Unary,
    WhileStmt,
)


_NO_RESULT = object()


def _is_bool(value: object) -> bool:
    return type(value) is bool


def _is_number(value: object) -> bool:
    return type(value) in (int, float) and not _is_bool(value)


def _eval_numeric(op: str, left: object, right: object) -> object:
    if op == "+":
        if type(left) is str and type(right) is str:
            return left + right
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) + float(right)
            return left + right
        return _NO_RESULT
    if op == "-":
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) - float(right)
            return left - right
        return _NO_RESULT
    if op == "*":
        if _is_number(left) and _is_number(right):
            if type(left) is float or type(right) is float:
                return float(left) * float(right)
            return left * right
        return _NO_RESULT
    if op == "/":
        if _is_number(left) and _is_number(right):
            if right == 0:
                return _NO_RESULT
            return float(left) / float(right)
        return _NO_RESULT
    if op == "%":
        if type(left) is int and type(right) is int:
            if right == 0:
                return _NO_RESULT
            return left % right
        return _NO_RESULT
    return _NO_RESULT


def _eval_compare(op: str, left: object, right: object) -> object:
    if op == "==":
        if type(left) is bool or type(right) is bool:
            if type(left) is bool and type(right) is bool:
                return left == right
            return False
        if _is_number(left) and _is_number(right):
            return float(left) == float(right)
        if type(left) is str and type(right) is str:
            return left == right
        return False
    if op == "!=":
        if type(left) is bool or type(right) is bool:
            if type(left) is bool and type(right) is bool:
                return left != right
            return True
        if _is_number(left) and _is_number(right):
            return float(left) != float(right)
        if type(left) is str and type(right) is str:
            return left != right
        return True
    if op in {"<", "<=", ">", ">="}:
        if _is_number(left) and _is_number(right):
            a = float(left)
            b = float(right)
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
            if op == ">":
                return a > b
            return a >= b
        if type(left) is str and type(right) is str:
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        return _NO_RESULT
    return _NO_RESULT


def _binary_ok(op: str, left: object, right: object) -> object:
    folded = _eval_numeric(op, left, right)
    if folded is not _NO_RESULT:
        return folded
    return _eval_compare(op, left, right)


def _unary_ok(op: str, value: object) -> object:
    if op == "neg":
        if _is_number(value):
            return -value
        return _NO_RESULT
    if op == "not":
        if _is_bool(value):
            return not value
        return _NO_RESULT
    return _NO_RESULT


def _fold_logic(op: str, left: object, right: object) -> object:
    if op == "and":
        if isinstance(left, Literal) and _is_bool(left.value):
            if left.value is False:
                return Literal(False)
        if isinstance(right, Literal) and _is_bool(right.value):
            if right.value is False:
                return Literal(False)
        if isinstance(left, Literal) and _is_bool(left.value) and isinstance(right, Literal) and _is_bool(right.value):
            return Literal(left.value and right.value)
    if op == "or":
        if isinstance(left, Literal) and _is_bool(left.value):
            if left.value is True:
                return Literal(True)
        if isinstance(right, Literal) and _is_bool(right.value):
            if right.value is True:
                return Literal(True)
        if isinstance(left, Literal) and _is_bool(left.value) and isinstance(right, Literal) and _is_bool(right.value):
            return Literal(left.value or right.value)
    return _NO_RESULT


def fold_constants(node: object) -> object:
    if isinstance(node, list):
        return [fold_constants(item) for item in node]
    if isinstance(node, Literal):
        return node
    if isinstance(node, Name):
        return node
    if isinstance(node, Unary):
        operand = fold_constants(node.operand)
        if isinstance(operand, Literal):
            folded = _unary_ok(node.op, operand.value)
            if folded is not _NO_RESULT:
                return Literal(folded)
        return Unary(node.op, operand)
    if isinstance(node, Binary):
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        if node.op in {"and", "or"}:
            folded = _fold_logic(node.op, left, right)
            if folded is not _NO_RESULT:
                return folded
        if isinstance(left, Literal) and isinstance(right, Literal):
            folded = _binary_ok(node.op, left.value, right.value)
            if folded is not _NO_RESULT:
                return Literal(folded)
        return Binary(node.op, left, right)
    if isinstance(node, LetStmt):
        return LetStmt(node.name, fold_constants(node.value))
    if isinstance(node, AssignStmt):
        return AssignStmt(node.name, fold_constants(node.value))
    if isinstance(node, PrintStmt):
        return PrintStmt(fold_constants(node.value))
    if isinstance(node, BlockStmt):
        return BlockStmt([fold_constants(item) for item in node.statements])
    if isinstance(node, IfStmt):
        return IfStmt(fold_constants(node.condition), fold_constants(node.then_branch), fold_constants(node.else_branch) if node.else_branch is not None else None)
    if isinstance(node, WhileStmt):
        return WhileStmt(fold_constants(node.condition), fold_constants(node.body))
    return node

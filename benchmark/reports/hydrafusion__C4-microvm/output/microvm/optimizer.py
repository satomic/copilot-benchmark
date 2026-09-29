from .parser import Assign, Binary, Block, If, Let, Literal, Print, Unary, Variable, While


def _is_number(value: object) -> bool:
    return type(value) in (int, float)


def _equal(left: object, right: object) -> bool:
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _binary_value(op: str, left: object, right: object) -> tuple[bool, object]:
    if op in ("==", "!="):
        result = _equal(left, right)
        return True, result if op == "==" else not result
    if op in ("<", "<=", ">", ">="):
        valid = (_is_number(left) and _is_number(right)) or (
            type(left) is str and type(right) is str
        )
        if not valid:
            return False, None
        operations = {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}
        return True, operations[op]
    if op == "+" and type(left) is str and type(right) is str:
        return True, left + right
    if op in ("+", "-", "*", "/") and _is_number(left) and _is_number(right):
        if op == "/" and right == 0:
            return False, None
        operations = {"+": left + right, "-": left - right, "*": left * right}
        return True, left / right if op == "/" else operations[op]
    if op == "%" and type(left) is int and type(right) is int and right != 0:
        return True, left % right
    return False, None


def _fold_unary(node: Unary) -> object:
    operand = fold_constants(node.operand)
    if not isinstance(operand, Literal):
        return Unary(node.op, operand)
    if node.op == "not" and type(operand.value) is bool:
        return Literal(not operand.value)
    if node.op == "-" and _is_number(operand.value):
        return Literal(-operand.value)
    return Unary(node.op, operand)


def _fold_binary(node: Binary) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if node.op in ("and", "or"):
        if isinstance(left, Literal) and type(left.value) is bool:
            if node.op == "and" and left.value is False:
                return Literal(False)
            if node.op == "or" and left.value is True:
                return Literal(True)
        if all(isinstance(value, Literal) and type(value.value) is bool for value in (left, right)):
            return Literal(left.value and right.value if node.op == "and" else left.value or right.value)
        return Binary(node.op, left, right)
    if isinstance(left, Literal) and isinstance(right, Literal):
        success, value = _binary_value(node.op, left.value, right.value)
        if success:
            return Literal(value)
    return Binary(node.op, left, right)


def fold_constants(node: object) -> object:
    if isinstance(node, (Literal, Variable)):
        return node
    if isinstance(node, Unary):
        return _fold_unary(node)
    if isinstance(node, Binary):
        return _fold_binary(node)
    if isinstance(node, Let):
        return Let(node.name, fold_constants(node.value))
    if isinstance(node, Assign):
        return Assign(node.name, fold_constants(node.value))
    if isinstance(node, Print):
        return Print(fold_constants(node.value))
    if isinstance(node, If):
        other = None if node.else_branch is None else fold_constants(node.else_branch)
        return If(fold_constants(node.condition), fold_constants(node.then_branch), other)
    if isinstance(node, While):
        return While(fold_constants(node.condition), fold_constants(node.body))
    if isinstance(node, Block):
        return Block(tuple(fold_constants(statement) for statement in node.statements))
    return node

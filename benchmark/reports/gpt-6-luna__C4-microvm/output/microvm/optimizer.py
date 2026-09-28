from dataclasses import replace

from .parser import Assign, Binary, Block, If, Let, Literal, Print, Unary, While


def fold_constants(node: object) -> object:
    if isinstance(node, Literal):
        return node
    if isinstance(node, Unary):
        operand = fold_constants(node.operand)
        result = _fold_unary(node.op, operand)
        return Literal(result) if result is not _NO_FOLD else replace(node, operand=operand)
    if isinstance(node, Binary):
        left = fold_constants(node.left)
        if node.op == "and" and _bool_literal(left, False):
            return Literal(False)
        if node.op == "or" and _bool_literal(left, True):
            return Literal(True)
        right = fold_constants(node.right)
        result = _fold_binary(node.op, left, right)
        return Literal(result) if result is not _NO_FOLD else replace(node, left=left, right=right)
    if isinstance(node, (Let, Assign)):
        return replace(node, value=fold_constants(node.value))
    if isinstance(node, Print):
        return replace(node, value=fold_constants(node.value))
    if isinstance(node, Block):
        return replace(node, statements=[fold_constants(stmt) for stmt in node.statements])
    if isinstance(node, If):
        return replace(node, condition=fold_constants(node.condition),
                       consequent=fold_constants(node.consequent),
                       alternative=None if node.alternative is None else fold_constants(node.alternative))
    if isinstance(node, While):
        return replace(node, condition=fold_constants(node.condition), body=fold_constants(node.body))
    return node


_NO_FOLD = object()


def _bool_literal(node: object, value: bool) -> bool:
    return isinstance(node, Literal) and type(node.value) is bool and node.value is value


def _fold_unary(op: str, operand: object) -> object:
    if not isinstance(operand, Literal):
        return _NO_FOLD
    value = operand.value
    if op == "not" and type(value) is bool:
        return not value
    if op == "-" and _number(value):
        return -value
    return _NO_FOLD


def _fold_binary(op: str, left: object, right: object) -> object:
    if not isinstance(left, Literal) or not isinstance(right, Literal):
        return _NO_FOLD
    a, b = left.value, right.value
    if op in {"and", "or"} and type(a) is bool and type(b) is bool:
        return a and b if op == "and" else a or b
    if op in {"==", "!="}:
        equal = _equal(a, b)
        return equal if op == "==" else not equal
    if op in {"<", "<=", ">", ">="} and _ordered(a, b):
        return {"<": lambda: a < b, "<=": lambda: a <= b,
                ">": lambda: a > b, ">=": lambda: a >= b}[op]()
    if op == "+" and type(a) is str and type(b) is str:
        return a + b
    if op in {"+", "-", "*", "/", "%"} and _number(a) and _number(b):
        if op == "%" and (type(a) is not int or type(b) is not int or b == 0):
            return _NO_FOLD
        if op == "/" and b == 0:
            return _NO_FOLD
        try:
            return {"+": lambda: a + b, "-": lambda: a - b,
                    "*": lambda: a * b, "/": lambda: a / b,
                    "%": lambda: a % b}[op]()
        except (ArithmeticError, OverflowError):
            return _NO_FOLD
    return _NO_FOLD


def _number(value: object) -> bool:
    return type(value) in {int, float}


def _equal(a: object, b: object) -> bool:
    if type(a) is type(b):
        return a == b
    return _number(a) and _number(b) and a == b


def _ordered(a: object, b: object) -> bool:
    return (_number(a) and _number(b)) or (type(a) is str and type(b) is str)

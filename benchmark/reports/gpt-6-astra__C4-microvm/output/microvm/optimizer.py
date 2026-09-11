import math

from .errors import VMRuntimeError
from .parser import _Node
from .vm import _BINARY_OPS, _Value, _binary, _unary


def _result(value: _Value, original: _Node) -> _Node:
    # Value-based pool dedup would merge -0.0 with 0.0, changing printed signs.
    if type(value) is float and value == 0.0 and math.copysign(1.0, value) < 0:
        return original
    return _Node("literal", value)


def _fold(node: _Node) -> _Node:
    children = tuple(_fold(child) for child in node.children)
    result = _Node(node.kind, node.value, children)
    if node.kind == "unary" and children[0].kind == "literal":
        value = children[0].value
        if value is not None:
            try:
                op = "NOT" if node.value == "not" else "NEG"
                return _result(_unary(op, value), result)
            except VMRuntimeError:
                return result
    if node.kind != "binary":
        return result
    left, right = children
    if node.value in ("and", "or"):
        if left.kind != "literal" or type(left.value) is not bool:
            return result
        if (node.value == "and" and not left.value) or (node.value == "or" and left.value):
            return left
        if right.kind == "literal" and type(right.value) is bool:
            return right
        return result
    if left.kind == right.kind == "literal":
        if left.value is not None and right.value is not None and isinstance(node.value, str):
            try:
                value = _binary(_BINARY_OPS[node.value], left.value, right.value)
                return _result(value, result)
            except VMRuntimeError:
                return result
    return result


def fold_constants(node: object) -> object:
    if not isinstance(node, _Node):
        raise TypeError("fold_constants expects an AST returned by parse")
    return _fold(node)

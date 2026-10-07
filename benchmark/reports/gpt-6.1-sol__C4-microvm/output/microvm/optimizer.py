from .errors import VMRuntimeError
from .parser import Node
from .vm import binary_operation, unary_operation


_BINARY = {
    "+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD",
    "==": "EQ", "!=": "NE", "<": "LT", "<=": "LE", ">": "GT", ">=": "GE",
}


def fold_constants(node: object) -> object:
    if not isinstance(node, Node):
        raise TypeError("Expected an AST node")
    children: list[Node] = []
    for child in node.children:
        folded = fold_constants(child)
        assert isinstance(folded, Node)
        children.append(folded)
    result = Node(node.kind, node.value, tuple(children))
    if node.kind not in ("unary", "binary"):
        return result
    if node.kind == "binary" and node.value in ("and", "or"):
        left, right = children
        if left.kind != "literal" or type(left.value) is not bool:
            return result
        if (node.value == "and" and left.value is False) or (
            node.value == "or" and left.value is True
        ):
            return left
        if right.kind == "literal" and type(right.value) is bool:
            return right
        return result
    if not all(child.kind == "literal" for child in children):
        return result
    try:
        assert children[0].value is not None
        if node.kind == "unary":
            value = unary_operation(
                "NOT" if node.value == "not" else "NEG", children[0].value
            )
        else:
            assert isinstance(node.value, str) and children[1].value is not None
            value = binary_operation(
                _BINARY[node.value], children[0].value, children[1].value
            )
    except VMRuntimeError:
        # Failed operations remain bytecode so errors occur only when executed.
        return result
    return Node("literal", value)

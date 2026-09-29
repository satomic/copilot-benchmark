from microvm.parser import (
    ProgramNode, LetNode, AssignNode, PrintNode, IfNode,
    WhileNode, BlockNode, BinaryOpNode, UnaryOpNode, LiteralNode, IdentNode,
)


def _is_bool_literal(node: object) -> bool:
    return isinstance(node, LiteralNode) and isinstance(node.value, bool)


def _fold_binary_andor(node: BinaryOpNode, left: object, right: object) -> object | None:
    if node.op == "and":
        if _is_bool_literal(left):
            if left.value is False:
                return LiteralNode(False)
            if _is_bool_literal(right):
                return LiteralNode(right.value)
            return None
        return None
    if node.op == "or":
        if _is_bool_literal(left):
            if left.value is True:
                return LiteralNode(True)
            if _is_bool_literal(right):
                return LiteralNode(right.value)
            return None
        return None
    return None


def _fold_binary_node(node: BinaryOpNode, left: object, right: object) -> object | None:
    left_lit = isinstance(left, LiteralNode)
    right_lit = isinstance(right, LiteralNode)
    result = _fold_binary_andor(node, left, right)
    if result is not None:
        return result
    if not left_lit or not right_lit:
        return None
    try:
        result = _fold_binary_values(node.op, left.value, right.value)
        if result is not None:
            return LiteralNode(result)
    except Exception:
        pass
    return None


def fold_constants(node: object) -> object:
    if isinstance(node, ProgramNode):
        return ProgramNode([fold_constants(s) for s in node.statements])
    elif isinstance(node, LetNode):
        return LetNode(node.name, fold_constants(node.value), node.offset)
    elif isinstance(node, AssignNode):
        return AssignNode(node.name, fold_constants(node.value), node.offset)
    elif isinstance(node, PrintNode):
        return PrintNode(fold_constants(node.value))
    elif isinstance(node, IfNode):
        cond = fold_constants(node.condition)
        then_branch = fold_constants(node.then_branch)
        else_branch = fold_constants(node.else_branch) if node.else_branch is not None else None
        return IfNode(cond, then_branch, else_branch)
    elif isinstance(node, WhileNode):
        return WhileNode(fold_constants(node.condition), fold_constants(node.body))
    elif isinstance(node, BlockNode):
        return BlockNode([fold_constants(s) for s in node.statements])
    elif isinstance(node, BinaryOpNode):
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        result = _fold_binary_node(node, left, right)
        if result is not None:
            return result
        return BinaryOpNode(node.op, left, right, node.offset)
    elif isinstance(node, UnaryOpNode):
        operand = fold_constants(node.operand)
        if isinstance(operand, LiteralNode):
            try:
                result = _fold_unary(node.op, operand.value)
                if result is not None:
                    return LiteralNode(result)
            except Exception:
                pass
        return UnaryOpNode(node.op, operand, node.offset)
    elif isinstance(node, (LiteralNode, IdentNode)):
        return node
    return node


def _fold_arith(op: str, lv: object, rv: object) -> object | None:
    if isinstance(lv, bool) or isinstance(rv, bool):
        return None
    if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        if op == "+":
            return lv + rv  # type: ignore
        elif op == "-":
            return lv - rv  # type: ignore
        elif op == "*":
            return lv * rv  # type: ignore
    if op == "+" and isinstance(lv, str) and isinstance(rv, str):
        return lv + rv
    return None


def _fold_equality(lv: object, rv: object) -> bool:
    if isinstance(lv, bool) and isinstance(rv, bool):
        return lv == rv
    if isinstance(lv, bool) or isinstance(rv, bool):
        return False
    if isinstance(lv, str) and isinstance(rv, str):
        return lv == rv
    if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        return lv == rv  # type: ignore
    return False


def _fold_cmp(op: str, lv: object, rv: object) -> object | None:
    if isinstance(lv, bool) or isinstance(rv, bool):
        return None
    if isinstance(lv, str) and isinstance(rv, str):
        if op == "<":
            return lv < rv
        elif op == "<=":
            return lv <= rv
        elif op == ">":
            return lv > rv
        elif op == ">=":
            return lv >= rv
    if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        if op == "<":
            return lv < rv  # type: ignore
        elif op == "<=":
            return lv <= rv  # type: ignore
        elif op == ">":
            return lv > rv  # type: ignore
        elif op == ">=":
            return lv >= rv  # type: ignore
    return None


def _fold_binary_values(op: str, lv: object, rv: object) -> object | None:
    if op in ("+", "-", "*"):
        return _fold_arith(op, lv, rv)
    elif op == "/":
        if isinstance(lv, bool) or isinstance(rv, bool):
            return None
        if isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
            return None if rv == 0 else lv / rv  # type: ignore
        return None
    elif op == "%":
        if isinstance(lv, bool) or isinstance(rv, bool):
            return None
        if isinstance(lv, int) and isinstance(rv, int):
            return None if rv == 0 else lv % rv
        return None
    elif op in ("==", "!="):
        eq = _fold_equality(lv, rv)
        return eq if op == "==" else not eq
    elif op in ("<", "<=", ">", ">="):
        return _fold_cmp(op, lv, rv)
    return None


def _fold_unary(op: str, v: object) -> object | None:
    if op == "not":
        if isinstance(v, bool):
            return not v
        return None
    elif op == "-":
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return -v
        return None
    return None
"""AST constant folder for microvm."""

from microvm.parser import (
    AssignStmt,
    BinaryOp,
    BlockStmt,
    IfStmt,
    LetStmt,
    Literal,
    PrintStmt,
    ProgramNode,
    UnaryOp,
    WhileStmt,
)


def is_num(v: object) -> bool:
    return (type(v) in (int, float)) and (type(v) is not bool)


def vm_equals(a: object, b: object) -> bool:
    if type(a) is bool or type(b) is bool:
        return (type(a) is bool and type(b) is bool) and (a is b)
    if (type(a) in (int, float)) and (type(b) in (int, float)):
        return a == b
    if type(a) is str and type(b) is str:
        return a == b
    return False


def _fold_arithmetic(op: str, lv: object, rv: object) -> tuple[bool, object]:
    if op == "+":
        if type(lv) is str and type(rv) is str:
            return True, lv + rv
        if is_num(lv) and is_num(rv):
            res = lv + rv  # type: ignore[operator]
            return True, int(res) if (type(lv) is int and type(rv) is int) else float(res)
    elif op in ("-", "*"):
        if is_num(lv) and is_num(rv):
            res = (lv - rv) if op == "-" else (lv * rv)  # type: ignore[operator]
            return True, int(res) if (type(lv) is int and type(rv) is int) else float(res)
    elif op == "/":
        if is_num(lv) and is_num(rv) and rv != 0:
            return True, float(lv) / float(rv)  # type: ignore[arg-type]
    elif op == "%":
        if type(lv) is int and type(rv) is int and type(lv) is not bool and type(rv) is not bool:
            if rv != 0:
                return True, lv % rv
    return False, None


def _fold_comparison(op: str, lv: object, rv: object) -> tuple[bool, object]:
    if op == "==":
        return True, vm_equals(lv, rv)
    if op == "!=":
        return True, not vm_equals(lv, rv)
    if is_num(lv) and is_num(rv):
        if op == "<":
            return True, lv < rv  # type: ignore[operator]
        if op == "<=":
            return True, lv <= rv  # type: ignore[operator]
        if op == ">":
            return True, lv > rv  # type: ignore[operator]
        if op == ">=":
            return True, lv >= rv  # type: ignore[operator]
    if type(lv) is str and type(rv) is str:
        if op == "<":
            return True, lv < rv
        if op == "<=":
            return True, lv <= rv
        if op == ">":
            return True, lv > rv
        if op == ">=":
            return True, lv >= rv
    return False, None


def _fold_binary_op(node: BinaryOp) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if node.op == "and":
        if isinstance(left, Literal) and type(left.value) is bool:
            if isinstance(right, Literal) and type(right.value) is bool:
                return Literal(left.value and right.value, node.offset)
            if left.value is False:
                return Literal(False, node.offset)
        return BinaryOp("and", left, right, node.offset)
    if node.op == "or":
        if isinstance(left, Literal) and type(left.value) is bool:
            if isinstance(right, Literal) and type(right.value) is bool:
                return Literal(left.value or right.value, node.offset)
            if left.value is True:
                return Literal(True, node.offset)
        return BinaryOp("or", left, right, node.offset)
    if isinstance(left, Literal) and isinstance(right, Literal):
        ok, val = _fold_arithmetic(node.op, left.value, right.value)
        if ok:
            return Literal(val, node.offset)  # type: ignore[arg-type]
        ok, val = _fold_comparison(node.op, left.value, right.value)
        if ok:
            return Literal(val, node.offset)  # type: ignore[arg-type]
    return BinaryOp(node.op, left, right, node.offset)


def _fold_unary_op(node: UnaryOp) -> object:
    operand = fold_constants(node.expr)
    if isinstance(operand, Literal):
        val = operand.value
        if node.op == "-" and is_num(val):
            return Literal(-val, node.offset)  # type: ignore[operator]
        if node.op == "not" and type(val) is bool:
            return Literal(not val, node.offset)
    return UnaryOp(node.op, operand, node.offset)


def fold_constants(node: object) -> object:
    if isinstance(node, ProgramNode):
        return ProgramNode(stmts=[fold_constants(s) for s in node.stmts])
    if isinstance(node, LetStmt):
        return LetStmt(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, AssignStmt):
        return AssignStmt(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, PrintStmt):
        return PrintStmt(fold_constants(node.expr), node.offset)
    if isinstance(node, IfStmt):
        tb = [fold_constants(s) for s in node.then_block]
        eb = fold_constants(node.else_branch) if node.else_branch is not None else None
        if isinstance(node.else_branch, list):
            eb = [fold_constants(s) for s in node.else_branch]
        return IfStmt(fold_constants(node.cond), tb, eb, node.offset)
    if isinstance(node, WhileStmt):
        return WhileStmt(fold_constants(node.cond), [fold_constants(s) for s in node.body], node.offset)
    if isinstance(node, BlockStmt):
        return BlockStmt([fold_constants(s) for s in node.stmts], node.offset)
    if isinstance(node, UnaryOp):
        return _fold_unary_op(node)
    if isinstance(node, BinaryOp):
        return _fold_binary_op(node)
    return node

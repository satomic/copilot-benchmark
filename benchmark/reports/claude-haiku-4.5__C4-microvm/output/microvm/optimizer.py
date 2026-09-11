from .parser import (Literal, BinOp, UnaryOp, Var, Let, Assign, Print, If, While,
                     Block, Program as ParserProgram)


def _fold_unary(op: str, operand) -> object:
    if isinstance(operand, Literal):
        if op == "-" and isinstance(operand.value, (int, float)):
            return Literal(-operand.value)
        elif op == "not" and isinstance(operand.value, bool):
            return Literal(not operand.value)
    return UnaryOp(op, operand)


def _fold_arithmetic(op: str, lv, rv) -> object | None:
    if op == "+" and isinstance(lv, str) and isinstance(rv, str):
        return Literal(lv + rv)
    if op == "+" and isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        return Literal(lv + rv)
    if op == "-" and isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        return Literal(lv - rv)
    if op == "*" and isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        return Literal(lv * rv)
    if op == "/" and isinstance(lv, (int, float)) and isinstance(rv, (int, float)):
        if rv == 0:
            return None
        return Literal(lv / rv)
    if op == "%" and isinstance(lv, int) and isinstance(rv, int):
        if rv == 0:
            return None
        return Literal(lv % rv)
    return None


def _fold_comparison(op: str, lv, rv) -> object | None:
    if op == "==":
        if type(lv) is bool and type(rv) is not bool:
            return Literal(False)
        if type(lv) is not bool and type(rv) is bool:
            return Literal(False)
        return Literal(lv == rv)
    if op == "!=":
        if type(lv) is bool and type(rv) is not bool:
            return Literal(True)
        if type(lv) is not bool and type(rv) is bool:
            return Literal(True)
        return Literal(lv != rv)
    if op in "<><=>=":
        is_num = isinstance(lv, (int, float)) and isinstance(rv, (int, float))
        is_str = isinstance(lv, str) and isinstance(rv, str)
        if not (is_num or is_str):
            return None
        if op == "<":
            return Literal(lv < rv)
        elif op == ">":
            return Literal(lv > rv)
        elif op == "<=":
            return Literal(lv <= rv)
        elif op == ">=":
            return Literal(lv >= rv)
    return None


def _fold_binary(op: str, left, right) -> object:
    if isinstance(left, Literal) and left.value is False and op == "and":
        return Literal(False)
    if isinstance(left, Literal) and left.value is True and op == "or":
        return Literal(True)
    if not (isinstance(left, Literal) and isinstance(right, Literal)):
        return BinOp(left, op, right)
    lv, rv = left.value, right.value
    result = _fold_arithmetic(op, lv, rv)
    if result is not None:
        return result
    result = _fold_comparison(op, lv, rv)
    if result is not None:
        return result
    if op == "and" and isinstance(lv, bool) and isinstance(rv, bool):
        return Literal(lv and rv)
    if op == "or" and isinstance(lv, bool) and isinstance(rv, bool):
        return Literal(lv or rv)
    return BinOp(left, op, right)


def fold_constants(node):
    if isinstance(node, ParserProgram):
        return ParserProgram([fold_constants(stmt) for stmt in node.statements])
    elif isinstance(node, Literal):
        return node
    elif isinstance(node, Var):
        return node
    elif isinstance(node, UnaryOp):
        return _fold_unary(node.op, fold_constants(node.operand))
    elif isinstance(node, BinOp):
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        return _fold_binary(node.op, left, right)
    elif isinstance(node, Let):
        return Let(node.name, fold_constants(node.value))
    elif isinstance(node, Assign):
        return Assign(node.name, fold_constants(node.value))
    elif isinstance(node, Print):
        return Print(fold_constants(node.expr))
    elif isinstance(node, If):
        return If(fold_constants(node.cond), fold_constants(node.then_branch),
                  fold_constants(node.else_branch) if node.else_branch else None)
    elif isinstance(node, While):
        return While(fold_constants(node.cond), fold_constants(node.body))
    elif isinstance(node, Block):
        return Block([fold_constants(stmt) for stmt in node.statements])
    else:
        return node

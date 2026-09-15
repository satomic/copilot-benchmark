from __future__ import annotations

from microvm.parser import (
    Assign,
    Binary,
    Block,
    If,
    Let,
    Literal,
    Name,
    Print,
    Script,
    Unary,
    While,
)


def fold_constants(node: object) -> object:
    if isinstance(node, Script):
        return Script([fold_constants(s) for s in node.statements])
    if isinstance(node, Block):
        return Block([fold_constants(s) for s in node.statements], node.offset)
    if isinstance(node, (Let, Assign, Print, If, While, Unary, Binary)):
        return _fold_compound(node)
    return node


def _fold_compound(node: object) -> object:
    if isinstance(node, Let):
        return Let(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, Assign):
        return Assign(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, Print):
        return Print(fold_constants(node.expr), node.offset)
    if isinstance(node, If):
        else_body = None if node.else_body is None else fold_constants(node.else_body)
        return If(fold_constants(node.cond), fold_constants(node.then_body), else_body, node.offset)
    if isinstance(node, While):
        return While(fold_constants(node.cond), fold_constants(node.body), node.offset)
    if isinstance(node, Unary):
        return _fold_unary(node)
    if isinstance(node, Binary):
        return _fold_binary(node)
    return node


def _fold_unary(node: Unary) -> object:
    expr = fold_constants(node.expr)
    if isinstance(expr, Literal):
        folded = _eval_unary(node.op, expr.value)
        if folded is not _FAIL:
            return Literal(folded, node.offset)
    return Unary(node.op, expr, node.offset)


def _fold_binary(node: Binary) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if node.op == "and":
        return _fold_and(left, right, node.offset)
    if node.op == "or":
        return _fold_or(left, right, node.offset)
    if isinstance(left, Literal) and isinstance(right, Literal):
        folded = _eval_binary(node.op, left.value, right.value)
        if folded is not _FAIL:
            return Literal(folded, node.offset)
    return Binary(node.op, left, right, node.offset)


def _fold_and(left: object, right: object, offset: int) -> object:
    if isinstance(left, Literal) and type(left.value) is bool and left.value is False:
        return Literal(False, offset)
    if _both_bool_lits(left, right):
        return Literal(left.value and right.value, offset)  # type: ignore[union-attr]
    return Binary("and", left, right, offset)


def _fold_or(left: object, right: object, offset: int) -> object:
    if isinstance(left, Literal) and type(left.value) is bool and left.value is True:
        return Literal(True, offset)
    if _both_bool_lits(left, right):
        return Literal(left.value or right.value, offset)  # type: ignore[union-attr]
    return Binary("or", left, right, offset)


def _both_bool_lits(left: object, right: object) -> bool:
    return (
        isinstance(left, Literal)
        and isinstance(right, Literal)
        and type(left.value) is bool
        and type(right.value) is bool
    )


_FAIL = object()


def _is_num(value: object) -> bool:
    return type(value) is int or type(value) is float


def _eval_unary(op: str, value: object) -> object:
    if op == "-" and _is_num(value):
        return -value  # type: ignore[operator]
    if op == "not" and type(value) is bool:
        return not value
    return _FAIL


def _eval_binary(op: str, left: object, right: object) -> object:
    if op in {"==", "!="}:
        eq = _eq(left, right)
        return eq if op == "==" else (not eq)
    if op in {"+", "-", "*", "/", "%"}:
        return _eval_arith(op, left, right)
    if op in {"<", "<=", ">", ">="}:
        return _eval_cmp(op, left, right)
    return _FAIL


def _eval_arith(op: str, left: object, right: object) -> object:
    if op == "+" and type(left) is str and type(right) is str:
        return left + right
    if op == "%" and type(left) is int and type(right) is int:
        if right == 0:
            return _FAIL
        return left % right
    if not (_is_num(left) and _is_num(right)):
        return _FAIL
    if op == "/":
        if right == 0:
            return _FAIL
        return float(left) / float(right)
    if op == "+":
        return left + right  # type: ignore[operator]
    if op == "-":
        return left - right  # type: ignore[operator]
    if op == "*":
        return left * right  # type: ignore[operator]
    return _FAIL


def _eval_cmp(op: str, left: object, right: object) -> object:
    ok_num = _is_num(left) and _is_num(right)
    ok_str = type(left) is str and type(right) is str
    if not (ok_num or ok_str):
        return _FAIL
    if op == "<":
        return left < right  # type: ignore[operator]
    if op == "<=":
        return left <= right  # type: ignore[operator]
    if op == ">":
        return left > right  # type: ignore[operator]
    return left >= right  # type: ignore[operator]


def _eq(left: object, right: object) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool and left is right
    if _is_num(left) and _is_num(right):
        return bool(left == right)
    return type(left) is type(right) and left == right

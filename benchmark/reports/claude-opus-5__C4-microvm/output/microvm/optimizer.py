"""Behaviour preserving constant folding over the AST.

Folding reuses the virtual machine's own operator implementations, so an
expression is folded only when evaluating it at run time would have produced
exactly the same value without raising.
"""

from __future__ import annotations

from typing import Callable

from . import parser as ast
from .errors import VMRuntimeError
from .vm import BINARY_OPS, UNARY_OPS

_BINARY_BY_SOURCE: dict[str, Callable[[object, object], object]] = {
    "+": BINARY_OPS["ADD"],
    "-": BINARY_OPS["SUB"],
    "*": BINARY_OPS["MUL"],
    "/": BINARY_OPS["DIV"],
    "%": BINARY_OPS["MOD"],
    "==": BINARY_OPS["EQ"],
    "!=": BINARY_OPS["NE"],
    "<": BINARY_OPS["LT"],
    "<=": BINARY_OPS["LE"],
    ">": BINARY_OPS["GT"],
    ">=": BINARY_OPS["GE"],
}

_UNARY_BY_SOURCE: dict[str, Callable[[object], object]] = {
    "-": UNARY_OPS["NEG"],
    "not": UNARY_OPS["NOT"],
}


def _fold_binary(node: ast.Binary) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if isinstance(left, ast.Literal) and isinstance(right, ast.Literal):
        try:
            value = _BINARY_BY_SOURCE[node.op](left.value, right.value)
        except VMRuntimeError:
            return ast.Binary(node.op, left, right, node.offset)
        return ast.Literal(value, node.offset)
    return ast.Binary(node.op, left, right, node.offset)


def _fold_unary(node: ast.Unary) -> object:
    operand = fold_constants(node.operand)
    if isinstance(operand, ast.Literal):
        try:
            return ast.Literal(_UNARY_BY_SOURCE[node.op](operand.value), node.offset)
        except VMRuntimeError:
            return ast.Unary(node.op, operand, node.offset)
    return ast.Unary(node.op, operand, node.offset)


def _fold_logical(node: ast.Logical) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    left_bool = isinstance(left, ast.Literal) and isinstance(left.value, bool)
    right_bool = isinstance(right, ast.Literal) and isinstance(right.value, bool)
    if left_bool and right_bool:
        result = (
            left.value and right.value  # type: ignore[union-attr]
            if node.op == "and"
            else left.value or right.value  # type: ignore[union-attr]
        )
        return ast.Literal(bool(result), node.offset)
    if left_bool:
        # The right operand is never evaluated in these two cases, so its
        # runtime BOOL check may safely disappear along with it.
        if node.op == "and" and left.value is False:  # type: ignore[union-attr]
            return ast.Literal(False, node.offset)
        if node.op == "or" and left.value is True:  # type: ignore[union-attr]
            return ast.Literal(True, node.offset)
    return ast.Logical(node.op, left, right, node.offset)


def _fold_statement(node: object) -> object:
    if isinstance(node, ast.Let):
        return ast.Let(node.identifier, fold_constants(node.expr), node.offset)
    if isinstance(node, ast.Assign):
        return ast.Assign(node.identifier, fold_constants(node.expr), node.offset)
    if isinstance(node, ast.Print):
        return ast.Print(fold_constants(node.expr), node.offset)
    if isinstance(node, ast.If):
        else_branch = None if node.else_branch is None else fold_constants(node.else_branch)
        return ast.If(
            fold_constants(node.condition),
            fold_constants(node.then_branch),
            else_branch,
            node.offset,
        )
    if isinstance(node, ast.While):
        return ast.While(
            fold_constants(node.condition), fold_constants(node.body), node.offset
        )
    if isinstance(node, ast.Block):
        return ast.Block(tuple(fold_constants(s) for s in node.statements), node.offset)
    if isinstance(node, ast.Module):
        return ast.Module(tuple(fold_constants(s) for s in node.statements), node.offset)
    return node


def fold_constants(node: object) -> object:
    """Return *node* with every safely computable sub-expression folded."""
    if isinstance(node, ast.Binary):
        return _fold_binary(node)
    if isinstance(node, ast.Unary):
        return _fold_unary(node)
    if isinstance(node, ast.Logical):
        return _fold_logical(node)
    return _fold_statement(node)

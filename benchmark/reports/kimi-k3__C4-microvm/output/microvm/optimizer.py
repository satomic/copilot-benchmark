"""Constant folding over the AST; never changes observable behaviour."""

import dataclasses

from .errors import VMRuntimeError
from .parser import Assign, BinOp, If, Let, Literal, Print, UnaryOp, While
from .vm import eval_binop, eval_neg, eval_not


def _fold_expr(node: object) -> object:
    """Fold an expression bottom-up; returns a (possibly new) node."""
    if isinstance(node, (Literal,)):
        return node
    if isinstance(node, UnaryOp):
        return _fold_unary(node)
    if isinstance(node, BinOp):
        return _fold_binary(node)
    return node


def _fold_unary(node: UnaryOp) -> object:
    operand = _fold_expr(node.operand)
    if isinstance(operand, Literal):
        try:
            fn = eval_neg if node.op == "-" else eval_not
            return Literal(fn(operand.value), node.offset)
        except VMRuntimeError:
            pass  # would fail at run time; leave unfolded
    return dataclasses.replace(node, operand=operand)


def _fold_binary(node: BinOp) -> object:
    left = _fold_expr(node.left)
    right = _fold_expr(node.right)
    if node.op in ("and", "or"):
        return _fold_logic(node, left, right)
    if isinstance(left, Literal) and isinstance(right, Literal):
        try:
            return Literal(eval_binop(node.op, left.value, right.value), node.offset)
        except VMRuntimeError:
            pass  # e.g. 1 / 0 or "a" + 1: must still fail at run time
    return dataclasses.replace(node, left=left, right=right)


def _fold_logic(node: BinOp, left: object, right: object) -> object:
    """Fold and/or only where the run-time BOOL checks are preserved."""
    if isinstance(left, Literal) and isinstance(right, Literal):
        if isinstance(left.value, bool) and isinstance(right.value, bool):
            value = (left.value and right.value) if node.op == "and" else (
                left.value or right.value
            )
            return Literal(bool(value), node.offset)
    if isinstance(left, Literal) and isinstance(left.value, bool):
        # The skipped side is never evaluated, so dropping it is safe; the
        # opposite direction (true and X / false or X) must keep X's check.
        if node.op == "and" and left.value is False:
            return Literal(False, node.offset)
        if node.op == "or" and left.value is True:
            return Literal(True, node.offset)
    return dataclasses.replace(node, left=left, right=right)


def _fold_stmt(node: object) -> object:
    """Fold every expression inside a statement, recursing into blocks."""
    if isinstance(node, (Let, Assign, Print)):
        return dataclasses.replace(node, value=_fold_expr(node.value))
    if isinstance(node, If):
        return dataclasses.replace(
            node,
            cond=_fold_expr(node.cond),
            then=[_fold_stmt(s) for s in node.then],
            otherwise=[_fold_stmt(s) for s in node.otherwise],
        )
    if isinstance(node, While):
        return dataclasses.replace(
            node, cond=_fold_expr(node.cond),
            body=[_fold_stmt(s) for s in node.body],
        )
    return node


def fold_constants(node: object) -> object:
    """Fold constants in an AST (a statement list); returns a new AST."""
    return [_fold_stmt(stmt) for stmt in node]

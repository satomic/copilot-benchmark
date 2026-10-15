"""Constant folding over the parser AST. Folding never changes observable behaviour."""

from __future__ import annotations

from .errors import VMRuntimeError
from .parser import Assign, Binary, Block, If, Let, Literal, Logical, Print, Unary, While
from .vm import binary_op, unary_op


def fold_constants(node: object) -> object:
    """Return a copy of ``node`` with literal sub-expressions folded where safe."""
    if isinstance(node, Block):
        return Block([fold_constants(stmt) for stmt in node.stmts])
    if isinstance(node, Let):
        return Let(node.name, node.offset, fold_constants(node.value))
    if isinstance(node, Assign):
        return Assign(node.name, node.offset, fold_constants(node.value))
    if isinstance(node, Print):
        return Print(fold_constants(node.value))
    if isinstance(node, If):
        return _fold_if(node)
    if isinstance(node, While):
        return While(fold_constants(node.cond), fold_constants(node.body))
    if isinstance(node, Unary):
        return _fold_unary(node)
    if isinstance(node, Binary):
        return _fold_binary(node)
    if isinstance(node, Logical):
        return _fold_logical(node)
    return node


def _fold_if(node: If) -> If:
    else_body = None if node.else_body is None else fold_constants(node.else_body)
    return If(fold_constants(node.cond), fold_constants(node.then_body), else_body)


def _fold_unary(node: Unary) -> object:
    operand = fold_constants(node.operand)
    if isinstance(operand, Literal):
        try:
            return Literal(unary_op(node.op, operand.value))
        except VMRuntimeError:
            pass  # would fail at run time; keep it so the error still happens
    return Unary(node.op, operand)


def _fold_binary(node: Binary) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if isinstance(left, Literal) and isinstance(right, Literal):
        try:
            return Literal(binary_op(node.op, left.value, right.value))
        except VMRuntimeError:
            pass  # would fail at run time; keep it so the error still happens
    return Binary(node.op, left, right)


def _fold_logical(node: Logical) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if isinstance(left, Literal) and type(left.value) is bool:
        # Short-circuit: the right side would never be evaluated, so it may be dropped.
        if node.op == "and" and left.value is False:
            return Literal(False)
        if node.op == "or" and left.value is True:
            return Literal(True)
        if isinstance(right, Literal) and type(right.value) is bool:
            folded = (left.value and right.value) if node.op == "and" else (left.value or right.value)
            return Literal(folded)
    return Logical(node.op, left, right)

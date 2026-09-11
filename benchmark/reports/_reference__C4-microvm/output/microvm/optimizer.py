"""AST constant folding.

Folding delegates the actual arithmetic to the same primitives the VM uses
(vm.binary_op / vm.unary_neg / vm.logical_not), so compile-time and run-time
semantics cannot drift apart. Anything those primitives reject stays unfolded
and fails at run time, exactly as it would have without the optimizer.
"""

from __future__ import annotations

from .errors import VMRuntimeError
from .parser import (
    Assign, Binary, Block, If, Let, Literal, Logical, Module, NotOp, Print,
    Unary, While,
)

__all__ = ["fold_constants"]


def _try(fn, *args):  # type: ignore[no-untyped-def]
    """Run a VM primitive; None means 'not foldable', wrapped means folded."""
    try:
        return (fn(*args),)
    except VMRuntimeError:
        return None


def fold_constants(node: object) -> object:
    """Return an equivalent AST with safely foldable subtrees replaced."""
    from . import vm  # deferred: vm imports nothing from here, but keep it lazy

    if isinstance(node, Module):
        return Module(tuple(fold_constants(s) for s in node.statements))
    if isinstance(node, Block):
        return Block(tuple(fold_constants(s) for s in node.statements))
    if isinstance(node, Let):
        return Let(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, Assign):
        return Assign(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, Print):
        return Print(fold_constants(node.expr))
    if isinstance(node, If):
        orelse = None if node.orelse is None else fold_constants(node.orelse)
        return If(fold_constants(node.cond), fold_constants(node.then), orelse)
    if isinstance(node, While):
        return While(fold_constants(node.cond), fold_constants(node.body))
    if isinstance(node, Unary):
        operand = fold_constants(node.operand)
        if isinstance(operand, Literal):
            folded = _try(vm.unary_neg, operand.value)
            if folded is not None:
                return Literal(folded[0])
        return Unary(operand)
    if isinstance(node, NotOp):
        operand = fold_constants(node.operand)
        if isinstance(operand, Literal):
            folded = _try(vm.logical_not, operand.value)
            if folded is not None:
                return Literal(folded[0])
        return NotOp(operand)
    if isinstance(node, Binary):
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        if isinstance(left, Literal) and isinstance(right, Literal):
            folded = _try(vm.binary_op, node.op, left.value, right.value)
            if folded is not None:
                return Literal(folded[0])
        return Binary(node.op, left, right)
    if isinstance(node, Logical):
        left = fold_constants(node.left)
        right = fold_constants(node.right)
        if isinstance(left, Literal) and left.value is False and node.op == "and":
            return Literal(False)  # right was never going to be evaluated
        if isinstance(left, Literal) and left.value is True and node.op == "or":
            return Literal(True)
        if (isinstance(left, Literal) and isinstance(right, Literal)
                and isinstance(left.value, bool) and isinstance(right.value, bool)):
            if node.op == "and":
                return Literal(left.value and right.value)
            return Literal(left.value or right.value)
        # `true and X` / `false or X` stay unfolded: X must still be
        # bool-checked when it is evaluated at run time.
        return Logical(node.op, left, right)
    return node

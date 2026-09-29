"""Behaviour-preserving constant folding over the AST."""

from __future__ import annotations

import dataclasses

from .errors import VMRuntimeError
from .opcodes import BINARY_OPCODES, UNARY_OPCODES
from .parser import Assign, Binary, Block, If, Let, Literal, Module, Print, Unary, While
from .vm import binary_op, unary_op

_I64_MIN = -(2 ** 63)
_I64_MAX = 2 ** 63 - 1


def _is_bool_literal(node: object) -> bool:
    return isinstance(node, Literal) and type(node.value) is bool


def _foldable_result(value: object) -> bool:
    # An INT that does not fit in i64 would make dumps() fail where the unfolded
    # program serializes fine, so such results are left unfolded.
    return type(value) is not int or _I64_MIN <= value <= _I64_MAX


def _fold_logical(node: Binary, left: object, right: object) -> object:
    short_value = node.op == "or"  # the left value that decides the result alone
    if _is_bool_literal(left) and left.value is short_value:
        return Literal(short_value, node.offset)
    if _is_bool_literal(left) and _is_bool_literal(right):
        result = (left.value and right.value) if node.op == "and" else (left.value or right.value)
        return Literal(result, node.offset)
    # "true and X" / "false or X" keep X's run-time BOOL check, so they stay.
    return Binary(node.op, left, right, node.offset)


def _fold_binary(node: Binary) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    if node.op in ("and", "or"):
        return _fold_logical(node, left, right)
    if isinstance(left, Literal) and isinstance(right, Literal):
        try:
            value = binary_op(BINARY_OPCODES[node.op], left.value, right.value)
        except VMRuntimeError:
            pass  # would fail at run time: keep it so it still fails there
        else:
            if _foldable_result(value):
                return Literal(value, node.offset)
    return Binary(node.op, left, right, node.offset)


def _fold_unary(node: Unary) -> object:
    operand = fold_constants(node.operand)
    if isinstance(operand, Literal):
        try:
            value = unary_op(UNARY_OPCODES[node.op], operand.value)
        except VMRuntimeError:
            pass
        else:
            if _foldable_result(value):
                return Literal(value, node.offset)
    return Unary(node.op, operand, node.offset)


def fold_constants(node: object) -> object:
    """Return a new AST with every safely foldable constant expression folded."""
    if isinstance(node, Binary):
        return _fold_binary(node)
    if isinstance(node, Unary):
        return _fold_unary(node)
    if isinstance(node, (Module, Block)):
        return dataclasses.replace(node, body=tuple(fold_constants(s) for s in node.body))
    if isinstance(node, (Let, Assign, Print)):
        return dataclasses.replace(node, value=fold_constants(node.value))
    if isinstance(node, If):
        orelse = None if node.orelse is None else fold_constants(node.orelse)
        return If(fold_constants(node.cond), fold_constants(node.then), orelse, node.offset)
    if isinstance(node, While):
        return While(fold_constants(node.cond), fold_constants(node.body), node.offset)
    return node

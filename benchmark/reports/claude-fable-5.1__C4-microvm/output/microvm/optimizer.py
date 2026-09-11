"""Behaviour-preserving constant folding over the AST."""

from __future__ import annotations

import dataclasses

from . import parser as ast
from .errors import VMRuntimeError
from .vm import binary_op, unary_op


def _is_literal(node: object) -> bool:
    return isinstance(node, ast.Literal)


def _is_bool_literal(node: object) -> bool:
    return isinstance(node, ast.Literal) and isinstance(node.value, bool)


def _fold_logical(node: ast.Binary) -> object:
    left, right = node.left, node.right
    if _is_bool_literal(left) and _is_bool_literal(right):
        result = (left.value and right.value) if node.op == "and" else (left.value or right.value)
        return ast.Literal(bool(result), node.offset)
    # The right operand is never evaluated in these two cases, so dropping it is safe.
    if node.op == "and" and _is_bool_literal(left) and left.value is False:
        return ast.Literal(False, node.offset)
    if node.op == "or" and _is_bool_literal(left) and left.value is True:
        return ast.Literal(True, node.offset)
    # `true and X` / `false or X` keep the runtime BOOL check on X: do not fold.
    return node


def _fold_binary(node: ast.Binary) -> object:
    if node.op in ("and", "or"):
        return _fold_logical(node)
    if not (_is_literal(node.left) and _is_literal(node.right)):
        return node
    try:
        value = binary_op(node.op, node.left.value, node.right.value)
    except VMRuntimeError:
        return node  # would fail at run time; keep it so it still fails there
    return ast.Literal(value, node.offset)


def _fold_unary(node: ast.Unary) -> object:
    if not _is_literal(node.operand):
        return node
    try:
        value = unary_op(node.op, node.operand.value)
    except VMRuntimeError:
        return node
    return ast.Literal(value, node.offset)


def fold_constants(node: object) -> object:
    """Return an equivalent AST with literal-only sub-expressions pre-evaluated."""
    if isinstance(node, ast.Binary):
        folded = ast.Binary(
            node.op, fold_constants(node.left), fold_constants(node.right), node.offset
        )
        return _fold_binary(folded)
    if isinstance(node, ast.Unary):
        return _fold_unary(ast.Unary(node.op, fold_constants(node.operand), node.offset))
    if isinstance(node, (ast.Literal, ast.Name)):
        return node
    if isinstance(node, (ast.Let, ast.Assign, ast.Print)):
        return dataclasses.replace(node, expr=fold_constants(node.expr))
    if isinstance(node, ast.If):
        orelse = None if node.orelse is None else fold_constants(node.orelse)
        return ast.If(
            fold_constants(node.cond), fold_constants(node.then), orelse, node.offset
        )
    if isinstance(node, ast.While):
        return ast.While(fold_constants(node.cond), fold_constants(node.body), node.offset)
    if isinstance(node, ast.Block):
        return ast.Block(tuple(fold_constants(s) for s in node.stmts), node.offset)
    if isinstance(node, ast.Module):
        return ast.Module(tuple(fold_constants(s) for s in node.stmts))
    return node

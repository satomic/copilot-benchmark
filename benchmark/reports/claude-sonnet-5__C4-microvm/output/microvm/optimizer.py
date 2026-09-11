"""Constant folding over the AST. Never changes observable behaviour."""

from .errors import VMRuntimeError
from .parser import (
    AssignStmt,
    BinOp,
    BoolLit,
    FloatLit,
    IfStmt,
    IntLit,
    LetStmt,
    LogicOp,
    Module,
    Neg,
    NotOp,
    PrintStmt,
    StrLit,
    VarRef,
    WhileStmt,
)
from .vm import apply_binary, apply_neg, apply_not

_LITERAL_TYPES = (IntLit, FloatLit, StrLit, BoolLit)


def _literal_value(node: object) -> tuple[bool, object]:
    if isinstance(node, _LITERAL_TYPES):
        return True, node.value
    return False, None


def _wrap_literal(value: object) -> object:
    if type(value) is bool:
        return BoolLit(value)
    if isinstance(value, int):
        return IntLit(value)
    if isinstance(value, float):
        return FloatLit(value)
    return StrLit(value)


def _fold_neg(node: Neg) -> object:
    expr = fold_constants(node.expr)
    is_lit, value = _literal_value(expr)
    if is_lit:
        try:
            return _wrap_literal(apply_neg(value))
        except VMRuntimeError:
            pass
    return Neg(expr)


def _fold_not(node: NotOp) -> object:
    expr = fold_constants(node.expr)
    is_lit, value = _literal_value(expr)
    if is_lit:
        try:
            return _wrap_literal(apply_not(value))
        except VMRuntimeError:
            pass
    return NotOp(expr)


def _fold_binop(node: BinOp) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    lok, lval = _literal_value(left)
    rok, rval = _literal_value(right)
    if lok and rok:
        try:
            return _wrap_literal(apply_binary(node.op, lval, rval))
        except VMRuntimeError:
            pass
    return BinOp(node.op, left, right, node.offset)


def _fold_logic(node: LogicOp) -> object:
    left = fold_constants(node.left)
    right = fold_constants(node.right)
    lok, lval = _literal_value(left)
    if lok and type(lval) is bool:
        if node.op == "and" and lval is False:
            return BoolLit(False)
        if node.op == "or" and lval is True:
            return BoolLit(True)
        rok, rval = _literal_value(right)
        if rok and type(rval) is bool:
            return BoolLit(lval and rval if node.op == "and" else lval or rval)
    return LogicOp(node.op, left, right)


def fold_constants(node: object) -> object:
    if isinstance(node, Module):
        return Module([fold_constants(s) for s in node.body])
    if isinstance(node, LetStmt):
        return LetStmt(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, AssignStmt):
        return AssignStmt(node.name, fold_constants(node.expr), node.offset)
    if isinstance(node, PrintStmt):
        return PrintStmt(fold_constants(node.expr))
    if isinstance(node, IfStmt):
        else_body = None if node.else_body is None else [fold_constants(s) for s in node.else_body]
        return IfStmt(
            fold_constants(node.cond),
            [fold_constants(s) for s in node.then_body],
            else_body,
        )
    if isinstance(node, WhileStmt):
        return WhileStmt(fold_constants(node.cond), [fold_constants(s) for s in node.body])
    if isinstance(node, Neg):
        return _fold_neg(node)
    if isinstance(node, NotOp):
        return _fold_not(node)
    if isinstance(node, BinOp):
        return _fold_binop(node)
    if isinstance(node, LogicOp):
        return _fold_logic(node)
    if isinstance(node, (_LITERAL_TYPES, VarRef)):
        return node
    return node

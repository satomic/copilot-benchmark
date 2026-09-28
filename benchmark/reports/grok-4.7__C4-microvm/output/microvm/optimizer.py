from typing import cast

from microvm.errors import VMRuntimeError
from microvm.parser import (
    AssignStmt,
    BinaryOp,
    Block,
    BoolLit,
    FloatLit,
    IfStmt,
    IntLit,
    LetStmt,
    PrintStmt,
    ProgramNode,
    StringLit,
    UnaryOp,
    WhileStmt,
)

_NO_FOLD = object()


def fold_constants(node: object) -> object:
    kind = type(node)
    if kind is ProgramNode:
        root = cast(ProgramNode, node)
        return ProgramNode([fold_constants(stmt) for stmt in root.statements])
    if kind is Block:
        block = cast(Block, node)
        return Block([fold_constants(stmt) for stmt in block.statements], block.offset)
    if kind is LetStmt:
        stmt = cast(LetStmt, node)
        return LetStmt(stmt.name, fold_constants(stmt.expr), stmt.offset)
    if kind is AssignStmt:
        stmt = cast(AssignStmt, node)
        return AssignStmt(stmt.name, fold_constants(stmt.expr), stmt.offset)
    if kind is PrintStmt:
        stmt = cast(PrintStmt, node)
        return PrintStmt(fold_constants(stmt.expr), stmt.offset)
    if kind is IfStmt:
        return _fold_if(cast(IfStmt, node))
    if kind is WhileStmt:
        return _fold_while(cast(WhileStmt, node))
    if kind is BinaryOp:
        return _fold_binary(cast(BinaryOp, node))
    if kind is UnaryOp:
        return _fold_unary(cast(UnaryOp, node))
    return node


def _fold_if(stmt: IfStmt) -> IfStmt:
    else_body = None if stmt.else_body is None else fold_constants(stmt.else_body)
    cond = fold_constants(stmt.cond)
    then_body = fold_constants(stmt.then_body)
    return IfStmt(cond, then_body, else_body, stmt.offset)


def _fold_while(stmt: WhileStmt) -> WhileStmt:
    return WhileStmt(fold_constants(stmt.cond), fold_constants(stmt.body), stmt.offset)


def _fold_binary(expr: BinaryOp) -> object:
    left = fold_constants(expr.left)
    right = fold_constants(expr.right)
    if expr.op == "and":
        return _fold_and(left, right, expr.offset)
    if expr.op == "or":
        return _fold_or(left, right, expr.offset)
    return _fold_eager(expr.op, left, right, expr.offset)


def _fold_and(left: object, right: object, offset: int) -> object:
    if type(left) is BoolLit and type(right) is BoolLit:
        value = cast(BoolLit, left).value and cast(BoolLit, right).value
        return BoolLit(value, offset)
    # false and X never evaluates X, so dropping X cannot hide a bool check.
    if type(left) is BoolLit and cast(BoolLit, left).value is False:
        return BoolLit(False, offset)
    # true and X must stay: the runtime still checks that X is BOOL.
    return BinaryOp("and", left, right, offset)


def _fold_or(left: object, right: object, offset: int) -> object:
    if type(left) is BoolLit and type(right) is BoolLit:
        value = cast(BoolLit, left).value or cast(BoolLit, right).value
        return BoolLit(value, offset)
    if type(left) is BoolLit and cast(BoolLit, left).value is True:
        return BoolLit(True, offset)
    return BinaryOp("or", left, right, offset)


def _fold_eager(op: str, left: object, right: object, offset: int) -> object:
    if not _is_literal(left) or not _is_literal(right):
        return BinaryOp(op, left, right, offset)
    folded = _try_binary(op, _literal_value(left), _literal_value(right))
    if folded is _NO_FOLD:
        return BinaryOp(op, left, right, offset)
    made = _make_lit(folded, offset)
    if made is _NO_FOLD:
        return BinaryOp(op, left, right, offset)
    return made


def _fold_unary(expr: UnaryOp) -> object:
    operand = fold_constants(expr.operand)
    if not _is_literal(operand):
        return UnaryOp(expr.op, operand, expr.offset)
    folded = _try_unary(expr.op, _literal_value(operand))
    if folded is _NO_FOLD:
        return UnaryOp(expr.op, operand, expr.offset)
    made = _make_lit(folded, expr.offset)
    if made is _NO_FOLD:
        return UnaryOp(expr.op, operand, expr.offset)
    return made


def _try_binary(op: str, left: object, right: object) -> object:
    from microvm.vm import _apply_binary

    try:
        return _apply_binary(op, left, right)
    except VMRuntimeError:
        return _NO_FOLD


def _try_unary(op: str, value: object) -> object:
    from microvm.vm import _apply_unary

    try:
        return _apply_unary(op, value)
    except VMRuntimeError:
        return _NO_FOLD


def _is_literal(node: object) -> bool:
    return type(node) in (IntLit, FloatLit, StringLit, BoolLit)


def _literal_value(node: object) -> object:
    if type(node) is IntLit:
        return cast(IntLit, node).value
    if type(node) is FloatLit:
        return cast(FloatLit, node).value
    if type(node) is StringLit:
        return cast(StringLit, node).value
    return cast(BoolLit, node).value


def _make_lit(value: object, offset: int) -> object:
    if type(value) is bool:
        return BoolLit(value, offset)
    if type(value) is int:
        return IntLit(value, offset)
    if type(value) is float:
        return FloatLit(value, offset)
    if type(value) is str:
        return StringLit(value, offset)
    return _NO_FOLD

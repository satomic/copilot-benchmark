from __future__ import annotations

from microvm.parser import (
    AssignStmt,
    BinOp,
    BlockStmt,
    Expr,
    IfStmt,
    LetStmt,
    Literal,
    LogicOp,
    PrintStmt,
    ProgramAST,
    Stmt,
    UnaryOp,
    WhileStmt,
)


def _is_number(val: object) -> bool:
    return type(val) in (int, float)


def _fold_unary(node: UnaryOp, operand: Expr) -> Expr:
    if not isinstance(operand, Literal):
        return UnaryOp(node.op, operand, node.offset)
    val = operand.value
    if node.op == "-" and _is_number(val):
        return Literal(-val, node.offset)  # type: ignore[operator]
    if node.op == "not" and type(val) is bool:
        return Literal(not val, node.offset)
    return UnaryOp(node.op, operand, node.offset)


def _fold_arith(op: str, lv: object, rv: object, offset: int) -> Literal | None:
    if op == "+" and type(lv) is str and type(rv) is str:
        return Literal(lv + rv, offset)
    if not (_is_number(lv) and _is_number(rv)):
        return None
    if op == "+":
        return Literal(lv + rv, offset)  # type: ignore[operator]
    if op == "-":
        return Literal(lv - rv, offset)  # type: ignore[operator]
    if op == "*":
        return Literal(lv * rv, offset)  # type: ignore[operator]
    if op == "/":
        if rv == 0:
            return None
        return Literal(float(lv) / float(rv), offset)  # type: ignore[arg-type]
    if op == "%":
        if type(lv) is int and type(rv) is int and rv != 0:
            return Literal(lv % rv, offset)
    return None


def _fold_compare(op: str, lv: object, rv: object, offset: int) -> Literal | None:
    if op in ("==", "!="):
        if _is_number(lv) and _is_number(rv):
            eq = lv == rv
        elif type(lv) is type(rv):
            eq = lv == rv
        else:
            eq = False
        return Literal(eq if op == "==" else not eq, offset)
    if (_is_number(lv) and _is_number(rv)) or (type(lv) is str and type(rv) is str):
        if op == "<":
            return Literal(lv < rv, offset)  # type: ignore[operator]
        if op == "<=":
            return Literal(lv <= rv, offset)  # type: ignore[operator]
        if op == ">":
            return Literal(lv > rv, offset)  # type: ignore[operator]
        if op == ">=":
            return Literal(lv >= rv, offset)  # type: ignore[operator]
    return None


def _fold_binop(node: BinOp, left: Expr, right: Expr) -> Expr:
    if isinstance(left, Literal) and isinstance(right, Literal):
        lv, rv = left.value, right.value
        res = (
            _fold_arith(node.op, lv, rv, node.offset)
            if node.op in ("+", "-", "*", "/", "%")
            else _fold_compare(node.op, lv, rv, node.offset)
        )
        if res is not None:
            return res
    return BinOp(node.op, left, right, node.offset)


def _fold_logic(node: LogicOp, left: Expr, right: Expr) -> Expr:
    if isinstance(left, Literal) and type(left.value) is bool:
        if node.op == "and" and left.value is False:
            return Literal(False, node.offset)
        if node.op == "or" and left.value is True:
            return Literal(True, node.offset)
        if isinstance(right, Literal) and type(right.value) is bool:
            if node.op == "and":
                return Literal(left.value and right.value, node.offset)
            return Literal(left.value or right.value, node.offset)
    return LogicOp(node.op, left, right, node.offset)


def _fold_expr(expr: Expr) -> Expr:
    if isinstance(expr, UnaryOp):
        return _fold_unary(expr, _fold_expr(expr.operand))
    if isinstance(expr, BinOp):
        return _fold_binop(expr, _fold_expr(expr.left), _fold_expr(expr.right))
    if isinstance(expr, LogicOp):
        return _fold_logic(expr, _fold_expr(expr.left), _fold_expr(expr.right))
    return expr


def _fold_stmt(stmt: Stmt) -> Stmt:
    if isinstance(stmt, LetStmt):
        return LetStmt(stmt.name, _fold_expr(stmt.expr), stmt.offset)
    if isinstance(stmt, AssignStmt):
        return AssignStmt(stmt.name, _fold_expr(stmt.expr), stmt.offset)
    if isinstance(stmt, PrintStmt):
        return PrintStmt(_fold_expr(stmt.expr), stmt.offset)
    if isinstance(stmt, BlockStmt):
        return BlockStmt([_fold_stmt(s) for s in stmt.stmts], stmt.offset)
    if isinstance(stmt, IfStmt):
        cond = _fold_expr(stmt.cond)
        then_b = _fold_stmt(stmt.then_block)
        assert isinstance(then_b, BlockStmt)
        else_b = _fold_stmt(stmt.else_branch) if stmt.else_branch is not None else None
        assert else_b is None or isinstance(else_b, (BlockStmt, IfStmt))
        return IfStmt(cond, then_b, else_b, stmt.offset)
    if isinstance(stmt, WhileStmt):
        cond = _fold_expr(stmt.cond)
        body = _fold_stmt(stmt.body)
        assert isinstance(body, BlockStmt)
        return WhileStmt(cond, body, stmt.offset)
    return stmt


def fold_constants(node: object) -> object:
    if isinstance(node, ProgramAST):
        return ProgramAST([_fold_stmt(s) for s in node.stmts])
    if isinstance(node, (LetStmt, AssignStmt, PrintStmt, BlockStmt, IfStmt, WhileStmt)):
        return _fold_stmt(node)
    if isinstance(node, (Literal, Var, UnaryOp, BinOp, LogicOp)):
        return _fold_expr(node)
    return node

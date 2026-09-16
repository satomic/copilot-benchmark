from .parser import Literal, Variable, Unary, Binary, Let, Assign, Print, Block, If, While, ProgramNode


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _eval(op: str, a: object, b: object = None) -> object:
    if op == "not": return not a if isinstance(a, bool) else None
    if op == "-" : return -a if _num(a) else None
    if op in ("+", "-", "*"):
        if op == "+" and isinstance(a, str) and isinstance(b, str): return a + b
        if not (_num(a) and _num(b)): return None
        return {"+": lambda: a+b, "-": lambda: a-b, "*": lambda: a*b}[op]()
    if op == "/": return a / b if _num(a) and _num(b) and b != 0 else None
    if op == "%": return a % b if type(a) is int and type(b) is int and b != 0 else None
    if op in ("==", "!="):
        eq = type(a) is type(b) and a == b or _num(a) and _num(b) and a == b
        return eq if op == "==" else not eq
    if op in ("<", "<=", ">", ">="):
        if not ((_num(a) and _num(b)) or (isinstance(a, str) and isinstance(b, str))): return None
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    return None


def fold_constants(node: object) -> object:
    if isinstance(node, ProgramNode): return ProgramNode([fold_constants(x) for x in node.statements])
    if isinstance(node, (Let, Assign, Print)): return type(node)(node.name, fold_constants(node.expr)) if not isinstance(node, Print) else Print(fold_constants(node.expr))
    if isinstance(node, Block): return Block([fold_constants(x) for x in node.statements])
    if isinstance(node, If): return If(fold_constants(node.cond), fold_constants(node.then), fold_constants(node.otherwise) if node.otherwise else None)
    if isinstance(node, While): return While(fold_constants(node.cond), fold_constants(node.body))
    if isinstance(node, Unary):
        e = fold_constants(node.expr)
        if isinstance(e, Literal):
            value = _eval(node.op, e.value)
            if value is not None: return Literal(value)
        return Unary(node.op, e)
    if isinstance(node, Binary):
        left, right = fold_constants(node.left), fold_constants(node.right)
        if node.op == "and" and isinstance(left, Literal) and isinstance(left.value, bool):
            if isinstance(right, Literal) and isinstance(right.value, bool): return Literal(right.value)
        if node.op == "or" and isinstance(left, Literal) and isinstance(left.value, bool):
            if isinstance(right, Literal) and isinstance(right.value, bool): return Literal(right.value)
        if isinstance(left, Literal) and isinstance(right, Literal):
            value = _eval(node.op, left.value, right.value)
            if value is not None: return Literal(value)
        return Binary(node.op, left, right)
    return node

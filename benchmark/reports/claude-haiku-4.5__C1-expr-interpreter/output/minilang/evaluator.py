from .parser import parse, NumberNode, StringNode, BoolNode, IdentNode, BinOpNode, UnaryOpNode, CallNode, IfNode
from .errors import EvalError
from .builtins import BUILTINS


def evaluate(source: str, env: dict | None = None) -> object:
    """Evaluate a minilang expression."""
    if env is None:
        env = {}
    env = dict(env)
    
    ast = parse(source)
    return _eval(ast, env)


def _eval(node: object, env: dict) -> object:
    """Recursively evaluate an AST node."""
    if isinstance(node, NumberNode):
        return node.value
    
    if isinstance(node, StringNode):
        return node.value
    
    if isinstance(node, BoolNode):
        return node.value
    
    if isinstance(node, IdentNode):
        name = node.name
        if name not in env:
            raise EvalError(f"undefined variable: {name}")
        value = env[name]
        if not isinstance(value, (float, str, bool)):
            raise EvalError(f"unsupported value for {name}: {value!r}")
        return value
    
    if isinstance(node, BinOpNode):
        return _eval_binop(node, env)
    
    if isinstance(node, UnaryOpNode):
        return _eval_unary(node, env)
    
    if isinstance(node, CallNode):
        return _eval_call(node, env)
    
    if isinstance(node, IfNode):
        return _eval_if(node, env)
    
    raise EvalError(f"unknown node type: {type(node)}")


def _eval_binop(node: BinOpNode, env: dict) -> object:
    """Evaluate a binary operation."""
    op = node.op
    
    if op == "or":
        left = _eval(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("'or' requires boolean operands")
        if left:
            return True
        right = _eval(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("'or' requires boolean operands")
        return right
    
    if op == "and":
        left = _eval(node.left, env)
        if not isinstance(left, bool):
            raise EvalError("'and' requires boolean operands")
        if not left:
            return False
        right = _eval(node.right, env)
        if not isinstance(right, bool):
            raise EvalError("'and' requires boolean operands")
        return right
    
    left = _eval(node.left, env)
    right = _eval(node.right, env)
    
    if op == "+":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        raise EvalError("'+' requires two numbers or two strings")
    
    if op == "-":
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise EvalError("'-' requires two numbers")
        return left - right
    
    if op == "*":
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise EvalError("'*' requires two numbers")
        return left * right
    
    if op == "/":
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise EvalError("'/' requires two numbers")
        if right == 0:
            raise EvalError("division by zero")
        return left / right
    
    if op == "%":
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise EvalError("'%' requires two numbers")
        if right == 0:
            raise EvalError("modulo by zero")
        return left % right
    
    if op == "^":
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise EvalError("'^' requires two numbers")
        result = left ** right
        if not isinstance(result, float) or (result != result):
            raise EvalError(f"invalid result from power operation")
        return result
    
    if op == "==":
        if type(left) != type(right):
            return False
        return left == right
    
    if op == "!=":
        if type(left) != type(right):
            return True
        return left != right
    
    if op == "<":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        if isinstance(left, str) and isinstance(right, str):
            return left < right
        raise EvalError("'<' requires two numbers or two strings")
    
    if op == "<=":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left <= right
        if isinstance(left, str) and isinstance(right, str):
            return left <= right
        raise EvalError("'<=' requires two numbers or two strings")
    
    if op == ">":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left > right
        if isinstance(left, str) and isinstance(right, str):
            return left > right
        raise EvalError("'>' requires two numbers or two strings")
    
    if op == ">=":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left >= right
        if isinstance(left, str) and isinstance(right, str):
            return left >= right
        raise EvalError("'>=' requires two numbers or two strings")
    
    raise EvalError(f"unknown binary operator: {op}")


def _eval_unary(node: UnaryOpNode, env: dict) -> object:
    """Evaluate a unary operation."""
    op = node.op
    
    if op == "-":
        operand = _eval(node.operand, env)
        if not isinstance(operand, (int, float)):
            raise EvalError("unary '-' requires a number")
        return -operand
    
    if op == "not":
        operand = _eval(node.operand, env)
        if not isinstance(operand, bool):
            raise EvalError("'not' requires a boolean")
        return not operand
    
    raise EvalError(f"unknown unary operator: {op}")


def _eval_call(node: CallNode, env: dict) -> object:
    """Evaluate a function call."""
    name = node.name
    
    if name == "if":
        if len(node.args) != 3:
            raise EvalError(f"if() takes 3 argument(s), got {len(node.args)}")
        cond = _eval(node.args[0], env)
        if not isinstance(cond, bool):
            raise EvalError("if() condition must be a boolean")
        if cond:
            return _eval(node.args[1], env)
        else:
            return _eval(node.args[2], env)
    
    if name not in BUILTINS:
        raise EvalError(f"undefined function: {name}")
    
    args = [_eval(arg, env) for arg in node.args]
    func = BUILTINS[name]
    try:
        if name in ("min", "max"):
            if len(args) == 0:
                raise EvalError(f"{name}() takes 1 argument(s), got 0")
            for arg in args:
                if not isinstance(arg, (int, float)):
                    raise EvalError(f"{name}() arguments must be numbers")
            return func(*args)
        elif name == "round":
            if len(args) not in (1, 2):
                raise EvalError(f"round() takes 1 or 2 argument(s), got {len(args)}")
            if not isinstance(args[0], (int, float)):
                raise EvalError("round() first argument must be a number")
            if len(args) == 2 and not isinstance(args[1], (int, float)):
                raise EvalError("round() second argument must be a number")
            return func(*args)
        elif name == "abs":
            if len(args) != 1:
                raise EvalError(f"abs() takes 1 argument(s), got {len(args)}")
            if not isinstance(args[0], (int, float)):
                raise EvalError("abs() argument must be a number")
            return func(args[0])
        elif name == "len":
            if len(args) != 1:
                raise EvalError(f"len() takes 1 argument(s), got {len(args)}")
            if not isinstance(args[0], str):
                raise EvalError("len() argument must be a string")
            return func(args[0])
        elif name in ("upper", "lower"):
            if len(args) != 1:
                raise EvalError(f"{name}() takes 1 argument(s), got {len(args)}")
            if not isinstance(args[0], str):
                raise EvalError(f"{name}() argument must be a string")
            return func(args[0])
        elif name == "str":
            if len(args) != 1:
                raise EvalError(f"str() takes 1 argument(s), got {len(args)}")
            return func(args[0])
        elif name == "num":
            if len(args) != 1:
                raise EvalError(f"num() takes 1 argument(s), got {len(args)}")
            if not isinstance(args[0], str):
                raise EvalError("num() argument must be a string")
            return func(args[0])
    except EvalError:
        raise
    
    raise EvalError(f"error calling {name}()")


def _eval_if(node: IfNode, env: dict) -> object:
    """Evaluate if expression."""
    cond = _eval(node.cond, env)
    if not isinstance(cond, bool):
        raise EvalError("if() condition must be a boolean")
    if cond:
        return _eval(node.then_expr, env)
    else:
        return _eval(node.else_expr, env)

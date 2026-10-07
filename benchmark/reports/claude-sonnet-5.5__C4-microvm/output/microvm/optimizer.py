"""AST constant folding that never changes observable behaviour."""

from .errors import VMRuntimeError
from .opcodes import BINARY_OPCODES
from .vm import apply_binary, apply_neg, apply_not

_INT_MIN = -(2 ** 63)
_INT_MAX = 2 ** 63 - 1


def _is_lit(node: tuple) -> bool:
    return node[0] == "lit"


def _is_bool_lit(node: tuple) -> bool:
    return node[0] == "lit" and type(node[1]) is bool


def _foldable(value: object) -> bool:
    # Huge ints stay unfolded so the constant pool remains serializable.
    return type(value) is not int or _INT_MIN <= value <= _INT_MAX


def _try(func, *args) -> tuple:
    try:
        result = func(*args)
    except VMRuntimeError:
        return ()
    return ("lit", result) if _foldable(result) else ()


def _fold_bin(node: tuple) -> tuple:
    left, right = fold_constants(node[2]), fold_constants(node[3])
    if _is_lit(left) and _is_lit(right):
        folded = _try(apply_binary, BINARY_OPCODES[node[1]], left[1], right[1])
        if folded:
            return folded
    return ("bin", node[1], left, right)


def _fold_un(node: tuple) -> tuple:
    inner = fold_constants(node[2])
    if _is_lit(inner):
        folded = _try(apply_neg, inner[1])
        if folded:
            return folded
    return ("un", "-", inner)


def _fold_not(node: tuple) -> tuple:
    inner = fold_constants(node[1])
    if _is_lit(inner):
        folded = _try(apply_not, inner[1])
        if folded:
            return folded
    return ("not", inner)


def _fold_logic(node: tuple) -> tuple:
    tag = node[0]
    left, right = fold_constants(node[1]), fold_constants(node[2])
    if _is_bool_lit(left):
        # `false and X` / `true or X` never evaluate X.
        if tag == "and" and left[1] is False:
            return ("lit", False)
        if tag == "or" and left[1] is True:
            return ("lit", True)
        if _is_bool_lit(right):
            return ("lit", left[1] and right[1] if tag == "and" else left[1] or right[1])
    return (tag, left, right)


def _fold_block(node: tuple) -> tuple:
    return (node[0], [fold_constants(s) for s in node[1]])


def _fold_opt(node: tuple | None) -> tuple | None:
    return None if node is None else fold_constants(node)


def fold_constants(node: object) -> object:
    tag = node[0]  # type: ignore[index]
    if tag in ("lit", "var"):
        return node
    if tag == "bin":
        return _fold_bin(node)  # type: ignore[arg-type]
    if tag == "un":
        return _fold_un(node)  # type: ignore[arg-type]
    if tag == "not":
        return _fold_not(node)  # type: ignore[arg-type]
    if tag in ("and", "or"):
        return _fold_logic(node)  # type: ignore[arg-type]
    if tag in ("program", "block"):
        return _fold_block(node)  # type: ignore[arg-type]
    if tag in ("let", "assign"):
        return (tag, node[1], fold_constants(node[2]))  # type: ignore[index]
    if tag == "print":
        return (tag, fold_constants(node[1]))  # type: ignore[index]
    if tag == "if":
        return (tag, fold_constants(node[1]), fold_constants(node[2]), _fold_opt(node[3]))  # type: ignore[index]
    if tag == "while":
        return (tag, fold_constants(node[1]), fold_constants(node[2]))  # type: ignore[index]
    raise ValueError(f"unknown AST node {tag!r}")

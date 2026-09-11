"""minilang: a small expression language (lexer, parser, evaluator)."""

from .errors import EvalError, LexError, MiniLangError, ParseError
from .evaluator import evaluate_ast as _evaluate_ast
from .lexer import tokenize as _tokenize
from .parser import parse as _parse

__all__ = [
    "tokenize",
    "parse",
    "evaluate",
    "MiniLangError",
    "LexError",
    "ParseError",
    "EvalError",
]


def tokenize(source: str) -> list:
    return _tokenize(source)


def parse(source: str):
    return _parse(source)


def evaluate(source: str, env: dict | None = None):
    ast = _parse(source)
    # Never mutate the caller's env: evaluate on a private copy.
    local_env = dict(env) if env else {}
    return _evaluate_ast(ast, local_env)

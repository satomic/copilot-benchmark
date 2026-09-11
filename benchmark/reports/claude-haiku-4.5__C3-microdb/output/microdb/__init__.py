from .schema import Table, Column
from .lexer import Lexer
from .parser import Parser
from .planner import plan
from .executor import execute_plan, Result


def execute(query: str, tables: dict[str, Table]) -> Result:
    """Execute a SQL query against tables."""
    lexer = Lexer(query)
    tokens = lexer.lex()
    parser = Parser(tokens)
    parsed_query = parser.parse()
    plan_stages = plan(parsed_query)
    result = execute_plan(plan_stages, tables)
    return result


__all__ = [
    "execute",
    "Table",
    "Column",
    "Result",
]

from .lexer import Lexer, Token
from .errors import ParseError
import dataclasses


@dataclasses.dataclass
class Query:
    distinct: bool
    select_items: list["SelectItem"]
    from_table: str | None
    join: "Join | None"
    where_expr: "Expr | None"
    group_by: list["Expr"]
    having_expr: "Expr | None"
    order_by: list[tuple["Expr", str]]
    limit: int | None
    offset: int | None


@dataclasses.dataclass
class SelectItem:
    expr: "Expr | None"
    alias: str | None
    star_table: str | None


@dataclasses.dataclass
class Join:
    type: str
    table: str
    on_expr: "Expr"


@dataclasses.dataclass
class Expr:
    type: str
    value: object = None
    left: "Expr | None" = None
    right: "Expr | None" = None
    args: list["Expr"] | None = None
    col_table: str | None = None
    col_name: str | None = None


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Query:
        distinct = False
        if self._match("SELECT"):
            if self._match("DISTINCT"):
                distinct = True
            select_items = self._parse_select_list()
        else:
            raise ParseError("Expected SELECT", self._offset())
        
        from_table, join = self._parse_from_and_join()
        where_expr = self._parse_where()
        group_by = self._parse_group_by()
        having_expr = self._parse_having()
        order_by = self._parse_order_by()
        limit = self._parse_limit()
        offset_val = self._parse_offset()
        
        return Query(
            distinct=distinct,
            select_items=select_items,
            from_table=from_table,
            join=join,
            where_expr=where_expr,
            group_by=group_by,
            having_expr=having_expr,
            order_by=order_by,
            limit=limit,
            offset=offset_val
        )
    
    def _parse_from_and_join(self) -> tuple[str | None, "Join | None"]:
        from_table = None
        join = None
        if self._match("FROM"):
            from_table = self._expect("IDENT").value
            join = self._parse_join_if_present()
        return from_table, join
    
    def _parse_join_if_present(self) -> "Join | None":
        if self._match("INNER"):
            self._expect("JOIN")
            join_table = self._expect("IDENT").value
            self._expect("ON")
            on_expr = self._parse_or_expr()
            return Join(type="INNER", table=join_table, on_expr=on_expr)
        elif self._match("LEFT"):
            self._expect("JOIN")
            join_table = self._expect("IDENT").value
            self._expect("ON")
            on_expr = self._parse_or_expr()
            return Join(type="LEFT", table=join_table, on_expr=on_expr)
        return None
    
    def _parse_where(self) -> "Expr | None":
        if self._match("WHERE"):
            return self._parse_or_expr()
        return None
    
    def _parse_group_by(self) -> list["Expr"]:
        group_by = []
        if self._match("GROUP"):
            self._expect("BY")
            group_by.append(self._parse_or_expr())
            while self._match(","):
                group_by.append(self._parse_or_expr())
        return group_by
    
    def _parse_having(self) -> "Expr | None":
        if self._match("HAVING"):
            return self._parse_or_expr()
        return None
    
    def _parse_order_by(self) -> list[tuple["Expr", str]]:
        order_by = []
        if self._match("ORDER"):
            self._expect("BY")
            order_by.append((self._parse_or_expr(), "ASC"))
            self._check_and_set_order_direction(order_by, 0)
            while self._match(","):
                order_by.append((self._parse_or_expr(), "ASC"))
                self._check_and_set_order_direction(order_by, len(order_by) - 1)
        return order_by
    
    def _check_and_set_order_direction(self, order_by: list, idx: int) -> None:
        if self._check("ASC"):
            self.pos += 1
        elif self._check("DESC"):
            self.pos += 1
            order_by[idx] = (order_by[idx][0], "DESC")
    
    def _parse_limit(self) -> int | None:
        if self._match("LIMIT"):
            return self._expect("INT").value
        return None
    
    def _parse_offset(self) -> int | None:
        if self._match("OFFSET"):
            return self._expect("INT").value
        return None

    def _parse_select_list(self) -> list[SelectItem]:
        items = []
        if self._check("*"):
            self.pos += 1
            items.append(SelectItem(expr=None, alias=None, star_table=None))
        else:
            items.append(self._parse_select_item())
            while self._match(","):
                items.append(self._parse_select_item())
        return items

    def _parse_select_item(self) -> SelectItem:
        if self._check("*"):
            self.pos += 1
            return SelectItem(expr=None, alias=None, star_table=None)
        
        if self._check("IDENT"):
            start_pos = self.pos
            ident_tok = self._expect("IDENT")
            if self._match("."):
                if self._check("*"):
                    self.pos += 1
                    return SelectItem(expr=None, alias=None, star_table=ident_tok.value)
                else:
                    col = self._expect("IDENT")
                    expr = Expr(
                        type="col",
                        col_table=ident_tok.value,
                        col_name=col.value
                    )
            elif self._check("("):
                self.pos = start_pos
                expr = self._parse_or_expr()
            else:
                expr = Expr(type="col", col_table=None, col_name=ident_tok.value)
        else:
            expr = self._parse_or_expr()
        
        alias = None
        if self._match("AS"):
            alias = self._expect("IDENT").value
        elif self._check("IDENT") and not self._is_keyword(self.tokens[self.pos].value.upper()):
            alias = self._expect("IDENT").value
        
        return SelectItem(expr=expr, alias=alias, star_table=None)

    def _parse_or_expr(self) -> Expr:
        left = self._parse_and_expr()
        while self._match("OR"):
            right = self._parse_and_expr()
            left = Expr(type="or", left=left, right=right)
        return left

    def _parse_and_expr(self) -> Expr:
        left = self._parse_not_expr()
        while self._match("AND"):
            right = self._parse_not_expr()
            left = Expr(type="and", left=left, right=right)
        return left

    def _parse_not_expr(self) -> Expr:
        if self._match("NOT"):
            expr = self._parse_not_expr()
            return Expr(type="not", left=expr)
        return self._parse_predicate()

    def _parse_predicate(self) -> Expr:
        left = self._parse_additive()
        if self._match("IS"):
            if self._match("NOT"):
                self._expect("NULL")
                return Expr(type="is_not_null", left=left)
            else:
                self._expect("NULL")
                return Expr(type="is_null", left=left)
        elif self._check("=") or self._check("<>") or self._check("<") or \
             self._check("<=") or self._check(">") or self._check(">="):
            op = self.tokens[self.pos].value
            self.pos += 1
            right = self._parse_additive()
            return Expr(type="cmp", value=op, left=left, right=right)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._check("+") or self._check("-"):
            op = self.tokens[self.pos].value
            self.pos += 1
            right = self._parse_multiplicative()
            left = Expr(type="arith", value=op, left=left, right=right)
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._check("*") or self._check("/") or self._check("%"):
            op = self.tokens[self.pos].value
            self.pos += 1
            right = self._parse_unary()
            left = Expr(type="arith", value=op, left=left, right=right)
        return left

    def _parse_unary(self) -> Expr:
        if self._match("-"):
            expr = self._parse_unary()
            return Expr(type="neg", left=expr)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        if self._check("INT"):
            tok = self._expect("INT")
            return Expr(type="lit", value=tok.value)
        if self._check("FLOAT"):
            tok = self._expect("FLOAT")
            return Expr(type="lit", value=tok.value)
        if self._check("TEXT"):
            tok = self._expect("TEXT")
            return Expr(type="lit", value=tok.value)
        if self._match("TRUE"):
            return Expr(type="lit", value=True)
        if self._match("FALSE"):
            return Expr(type="lit", value=False)
        if self._match("NULL"):
            return Expr(type="lit", value=None)
        if self._match("("):
            expr = self._parse_or_expr()
            self._expect(")")
            return expr
        if self._check("IDENT"):
            ident = self._expect("IDENT")
            if self._match("."):
                col = self._expect("IDENT")
                return Expr(type="col", col_table=ident.value, col_name=col.value)
            elif self._match("("):
                args = []
                if not self._check(")"):
                    if self._match("*"):
                        args.append(Expr(type="lit", value="*"))
                    else:
                        args.append(self._parse_or_expr())
                        while self._match(","):
                            args.append(self._parse_or_expr())
                self._expect(")")
                return Expr(type="call", value=ident.value, args=args)
            else:
                return Expr(type="col", col_table=None, col_name=ident.value)
        raise ParseError(f"Unexpected token", self._offset())

    def _match(self, *types: str) -> bool:
        for t in types:
            if self._check(t):
                self.pos += 1
                return True
        return False

    def _check(self, type: str) -> bool:
        if self.pos >= len(self.tokens):
            return False
        return self.tokens[self.pos].type == type

    def _expect(self, type: str) -> Token:
        if not self._check(type):
            raise ParseError(f"Expected {type}", self._offset())
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _offset(self) -> int:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos].offset
        return len(self.tokens) - 1 if self.tokens else 0

    def _is_keyword(self, word: str) -> bool:
        return word in {
            "SELECT", "DISTINCT", "FROM", "INNER", "LEFT", "JOIN", "ON",
            "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
            "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "IS", "NULL",
            "TRUE", "FALSE"
        }

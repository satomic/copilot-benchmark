from dataclasses import dataclass
from .errors import ParseError, AggregateError, ArityError
from .lexer import Token, tokenize
from .expr import Expr, Literal, ColumnRef, Unary, Binary, IsNull, Call


@dataclass
class SelectItem:
    expr: Expr | None
    alias: str | None
    star_table: str | None = None


@dataclass
class Query:
    items: list[SelectItem]
    table: str
    join_kind: str | None
    join_table: str | None
    join_on: Expr | None
    where: Expr | None
    group_by: list[Expr]
    having: Expr | None
    order_by: list[tuple[Expr, bool]]
    limit: int | None
    offset: int
    distinct: bool


class Parser:
    def __init__(self, source: str) -> None:
        self.ts = tokenize(source); self.i = 0
    def cur(self) -> Token:
        return self.ts[self.i]
    def take(self, kind: str) -> Token:
        if self.cur().kind != kind:
            raise ParseError(f"expected {kind}", self.cur().offset)
        t = self.cur(); self.i += 1; return t
    def parse(self) -> Query:
        self.take("SELECT"); distinct = bool(self._accept("DISTINCT"))
        items = self._items(); self.take("FROM"); table = self.take("IDENT").text
        jk = jt = None; jo = None
        if self.cur().kind in {"INNER", "LEFT"}:
            jk = self.cur().kind; self.i += 1; self.take("JOIN"); jt = self.take("IDENT").text
            self.take("ON"); jo = self.expr()
        where = self._clause("WHERE")
        group: list[Expr] = []
        if self._accept("GROUP"):
            self.take("BY"); group = self._expr_list()
        having = self._clause("HAVING")
        order: list[tuple[Expr, bool]] = []
        if self._accept("ORDER"):
            self.take("BY")
            while True:
                e = self.expr(); desc = bool(self._accept("DESC")); self._accept("ASC")
                order.append((e, desc))
                if not self._accept(","): break
        limit = offset = None
        if self._accept("LIMIT"): limit = self._integer()
        if self._accept("OFFSET"): offset = self._integer()
        if self.cur().kind != "EOF": raise ParseError("unexpected token", self.cur().offset)
        return Query(items, table, jk, jt, jo, where, group, having, order, limit, offset or 0, distinct)
    def _items(self) -> list[SelectItem]:
        out: list[SelectItem] = []
        while True:
            if self._accept("*"): item = SelectItem(None, None)
            elif self.cur().kind == "IDENT" and self.i + 2 < len(self.ts) and self.ts[self.i + 1].kind == "." and self.ts[self.i + 2].kind == "*":
                table = self.cur().text; self.i += 3; item = SelectItem(None, None, table)
            else:
                e = self.expr(); alias = self.take("IDENT").text if self._accept("AS") else None
                item = SelectItem(e, alias)
            out.append(item)
            if not self._accept(","): return out
    def _expr_list(self) -> list[Expr]:
        out = [self.expr()]
        while self._accept(","): out.append(self.expr())
        return out
    def _clause(self, key: str) -> Expr | None:
        return self.expr() if self._accept(key) else None
    def _integer(self) -> int:
        t = self.take("INT")
        return int(t.text)
    def _accept(self, kind: str) -> Token | None:
        if self.cur().kind == kind:
            t = self.cur(); self.i += 1; return t
        return None
    def expr(self) -> Expr:
        return self._or()
    def _or(self) -> Expr:
        e = self._and()
        while self._accept("OR"):
            old = e; right = self._and(); e = Binary("OR", old, right, f"{old.text} OR {right.text}")
        return e
    def _and(self) -> Expr:
        e = self._not()
        while self._accept("AND"):
            old = e; right = self._not(); e = Binary("AND", old, right, f"{old.text} AND {right.text}")
        return e
    def _not(self) -> Expr:
        if self._accept("NOT"):
            child = self._not(); return Unary("NOT", child, f"NOT {child.text}")
        return self._pred()
    def _pred(self) -> Expr:
        e = self._add()
        if self.cur().kind in {"=", "<>", "<", "<=", ">", ">="}:
            op = self.cur().kind; self.i += 1; right = self._add(); e = Binary(op, e, right, f"{e.text} {op} {right.text}")
            if self.cur().kind in {"=", "<>", "<", "<=", ">", ">="}: raise ParseError("chained comparison", self.cur().offset)
        elif self._accept("IS"):
            neg = bool(self._accept("NOT")); self.take("NULL"); e = IsNull(e, neg, f"{e.text} IS {'NOT ' if neg else ''}NULL")
        return e
    def _add(self) -> Expr:
        e = self._mul()
        while self.cur().kind in {"+", "-"}:
            op = self.cur().kind; self.i += 1; r = self._mul(); e = Binary(op, e, r, f"{e.text} {op} {r.text}")
        return e
    def _mul(self) -> Expr:
        e = self._unary()
        while self.cur().kind in {"*", "/", "%"}:
            op = self.cur().kind; self.i += 1; r = self._unary(); e = Binary(op, e, r, f"{e.text} {op} {r.text}")
        return e
    def _unary(self) -> Expr:
        if self._accept("-"):
            e = self._unary(); return Unary("-", e, f"-{e.text}")
        return self._primary()
    def _primary(self) -> Expr:
        t = self.cur()
        if t.kind in {"INT", "FLOAT", "TEXT", "TRUE", "FALSE", "NULL"}:
            self.i += 1; val: object = int(t.text) if t.kind == "INT" else float(t.text) if t.kind == "FLOAT" else {"TRUE": True, "FALSE": False, "NULL": None}.get(t.kind, t.text)
            return Literal(val, t.text if t.kind != "TEXT" else "'" + t.text + "'")
        if t.kind == "(":
            self.i += 1; e = self.expr(); self.take(")"); return e
        if t.kind == "IDENT":
            self.i += 1; name = t.text
            if self._accept("("):
                args: list[Expr] = []
                if not self._accept(")"):
                    if self._accept("*"): args = [Literal("*", "*")]
                    else: args = self._expr_list()
                    self.take(")")
                if name.lower() in {"count", "sum", "avg", "min", "max"} and any(a.aggregate for a in args):
                    raise ParseError("nested aggregate", t.offset)
                if name.lower() == "count" and len(args) != 1:
                    raise ArityError(f"count: expected 1, got {len(args)}")
                return Call(name, args, f"{name}({', '.join(a.text for a in args)})")
            table = None
            if self._accept("."): table, name = name, self.take("IDENT").text
            return ColumnRef(name, table, f"{table + '.' if table else ''}{name}")
        raise ParseError("expected expression", t.offset)


def parse(source: str) -> Query:
    return Parser(source).parse()

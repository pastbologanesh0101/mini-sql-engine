"""Recursive-descent parser for the Mini SQL Engine.

Grammar (informal EBNF; case-insensitive keywords, `|` = alternatives,
`[]` = optional, `{}` = zero or more):

    program        := statement (";" statement)* [";"]
    statement      := create_table | insert | select

    create_table   := "CREATE" "TABLE" IDENT "(" column_def {"," column_def} ")"
    column_def     := IDENT type
    type           := "INTEGER" | "INT" | "TEXT" | "REAL" | "FLOAT"

    insert         := "INSERT" "INTO" IDENT "VALUES" "(" literal {"," literal} ")"
    literal        := NUMBER | STRING | "TRUE" | "FALSE" | "NULL"

    select         := "SELECT" select_list
                       "FROM" IDENT
                       [join_clause]
                       ["WHERE" condition]
                       ["GROUP" "BY" IDENT]
                       ["ORDER" "BY" IDENT [("ASC" | "DESC")]]
                       ["LIMIT" NUMBER]

    select_list    := "*" | select_item {"," select_item}
    select_item    := agg_call | column_ref
    agg_call       := ("COUNT"|"SUM"|"AVG"|"MIN"|"MAX") "(" ("*" | column_ref) ")"
    column_ref     := IDENT ["." IDENT]

    join_clause    := "JOIN" IDENT "ON" column_ref "=" column_ref

    condition      := or_expr
    or_expr        := and_expr {"OR" and_expr}
    and_expr       := comparison {"AND" comparison}
    comparison     := operand cmp_op operand
    cmp_op         := "=" | "!=" | "<>" | "<" | ">" | "<=" | ">="
    operand        := column_ref | literal

`AND` binds tighter than `OR` (standard SQL precedence), enforced by having
`and_expr` nest inside `or_expr`.
"""

from __future__ import annotations

from mini_sql_engine.ast_nodes import (
    AggregateCall, BinaryOp, Column, ColumnDef, CreateTable, Insert,
    JoinClause, Literal, Select, SelectItem,
)
from mini_sql_engine.errors import ParseError
from mini_sql_engine.lexer import Token, tokenize

AGG_FUNCS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
TYPE_WORDS = {"INTEGER", "INT", "TEXT", "REAL", "FLOAT"}
CMP_OPS = {"=", "!=", "<>", "<", ">", "<=", ">="}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # -- low level helpers -------------------------------------------------

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def at_keyword(self, word: str) -> bool:
        tok = self.peek()
        return tok.kind == "KEYWORD" and tok.value == word

    def at_end_of_statement(self) -> bool:
        return self.peek().kind in ("SEMI", "EOF")

    def expect(self, kind: str, value: str | None = None) -> Token:
        tok = self.peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            expected = value if value else kind
            found = tok.value if tok.value else tok.kind
            raise ParseError(
                f"Parse error at position {tok.pos}: expected {expected!r}, "
                f"found {found!r}"
            )
        return self.advance()

    def expect_keyword(self, word: str) -> Token:
        return self.expect("KEYWORD", word)

    # -- top level -----------------------------------------------------

    def parse_program(self) -> list:
        statements = []
        while self.peek().kind != "EOF":
            if self.peek().kind == "SEMI":
                self.advance()
                continue
            statements.append(self.parse_statement())
            if self.peek().kind == "SEMI":
                self.advance()
        return statements

    def parse_statement(self):
        tok = self.peek()
        if tok.kind != "KEYWORD":
            raise ParseError(
                f"Parse error at position {tok.pos}: expected a statement "
                f"keyword (CREATE, INSERT, SELECT), found {tok.value!r}"
            )
        if tok.value == "CREATE":
            return self.parse_create_table()
        if tok.value == "INSERT":
            return self.parse_insert()
        if tok.value == "SELECT":
            return self.parse_select()
        raise ParseError(
            f"Parse error at position {tok.pos}: unsupported statement {tok.value!r}"
        )

    # -- CREATE TABLE ----------------------------------------------------

    def parse_create_table(self) -> CreateTable:
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        name = self.expect("IDENT").value
        self.expect("LPAREN")
        columns = [self.parse_column_def()]
        while self.peek().kind == "COMMA":
            self.advance()
            columns.append(self.parse_column_def())
        self.expect("RPAREN")
        return CreateTable(table_name=name, columns=columns)

    def parse_column_def(self) -> ColumnDef:
        name = self.expect("IDENT").value
        type_tok = self.peek()
        if type_tok.kind != "KEYWORD" or type_tok.value not in TYPE_WORDS:
            raise ParseError(
                f"Parse error at position {type_tok.pos}: expected a column type "
                f"(INTEGER, TEXT, REAL), found {type_tok.value!r}"
            )
        self.advance()
        normalized = "INTEGER" if type_tok.value == "INT" else (
            "REAL" if type_tok.value == "FLOAT" else type_tok.value
        )
        return ColumnDef(name=name, col_type=normalized)

    # -- INSERT ------------------------------------------------------------

    def parse_insert(self) -> Insert:
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        name = self.expect("IDENT").value
        self.expect_keyword("VALUES")
        self.expect("LPAREN")
        values = [self.parse_literal()]
        while self.peek().kind == "COMMA":
            self.advance()
            values.append(self.parse_literal())
        self.expect("RPAREN")
        return Insert(table_name=name, values=values)

    def parse_literal(self):
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            if "." in tok.value:
                return float(tok.value)
            return int(tok.value)
        if tok.kind == "STRING":
            self.advance()
            return tok.value
        if tok.kind == "KEYWORD" and tok.value == "TRUE":
            self.advance()
            return True
        if tok.kind == "KEYWORD" and tok.value == "FALSE":
            self.advance()
            return False
        if tok.kind == "KEYWORD" and tok.value == "NULL":
            self.advance()
            return None
        raise ParseError(
            f"Parse error at position {tok.pos}: expected a literal value, "
            f"found {tok.value!r}"
        )

    # -- SELECT --------------------------------------------------------

    def parse_select(self) -> Select:
        self.expect_keyword("SELECT")
        items = self.parse_select_list()
        self.expect_keyword("FROM")
        table_name = self.expect("IDENT").value

        join = None
        if self.at_keyword("JOIN") or self.at_keyword("INNER"):
            join = self.parse_join()

        where = None
        if self.at_keyword("WHERE"):
            self.advance()
            where = self.parse_or_expr()

        group_by = None
        if self.at_keyword("GROUP"):
            self.advance()
            self.expect_keyword("BY")
            group_by = self.expect("IDENT").value

        order_by = None
        order_dir = "ASC"
        if self.at_keyword("ORDER"):
            self.advance()
            self.expect_keyword("BY")
            order_by = self.expect("IDENT").value
            if self.at_keyword("ASC"):
                self.advance()
                order_dir = "ASC"
            elif self.at_keyword("DESC"):
                self.advance()
                order_dir = "DESC"

        limit = None
        if self.at_keyword("LIMIT"):
            self.advance()
            num_tok = self.expect("NUMBER")
            limit = int(num_tok.value)

        if not self.at_end_of_statement():
            tok = self.peek()
            raise ParseError(
                f"Parse error at position {tok.pos}: unexpected token {tok.value!r} "
                f"in SELECT statement"
            )

        return Select(
            items=items, table_name=table_name, join=join, where=where,
            group_by=group_by, order_by=order_by, order_dir=order_dir, limit=limit,
        )

    def parse_select_list(self):
        if self.peek().kind == "STAR":
            self.advance()
            return "*"
        items = [self.parse_select_item()]
        while self.peek().kind == "COMMA":
            self.advance()
            items.append(self.parse_select_item())
        return items

    def parse_select_item(self) -> SelectItem:
        tok = self.peek()
        if tok.kind == "KEYWORD" and tok.value in AGG_FUNCS:
            func = tok.value
            self.advance()
            self.expect("LPAREN")
            if self.peek().kind == "STAR":
                self.advance()
                column = None
            else:
                column = self.parse_column_ref()
            self.expect("RPAREN")
            alias = f"{func}({column if column else '*'})"
            return SelectItem(expr=AggregateCall(func=func, column=column), alias=alias)
        column = self.parse_column_ref()
        return SelectItem(expr=column, alias=str(column))

    def parse_column_ref(self) -> Column:
        first = self.expect("IDENT").value
        if self.peek().kind == "DOT":
            self.advance()
            second = self.expect("IDENT").value
            return Column(name=second, table=first)
        return Column(name=first)

    def parse_join(self) -> JoinClause:
        if self.at_keyword("INNER"):
            self.advance()
        self.expect_keyword("JOIN")
        table_name = self.expect("IDENT").value
        self.expect_keyword("ON")
        left = self.parse_column_ref()
        self.expect("OP", "=")
        right = self.parse_column_ref()
        return JoinClause(table_name=table_name, left_col=left, right_col=right)

    # -- WHERE condition (AND binds tighter than OR) -------------------

    def parse_or_expr(self):
        left = self.parse_and_expr()
        while self.at_keyword("OR"):
            self.advance()
            right = self.parse_and_expr()
            left = BinaryOp(op="OR", left=left, right=right)
        return left

    def parse_and_expr(self):
        left = self.parse_comparison()
        while self.at_keyword("AND"):
            self.advance()
            right = self.parse_comparison()
            left = BinaryOp(op="AND", left=left, right=right)
        return left

    def parse_comparison(self):
        left = self.parse_operand()
        tok = self.peek()
        if tok.kind == "OP" and tok.value in CMP_OPS:
            op = tok.value
            self.advance()
            right = self.parse_operand()
            return BinaryOp(op=op, left=left, right=right)
        raise ParseError(
            f"Parse error at position {tok.pos}: expected a comparison operator "
            f"(=, !=, <, >, <=, >=), found {tok.value!r}"
        )

    def parse_operand(self):
        tok = self.peek()
        if tok.kind == "IDENT":
            return self.parse_column_ref()
        if tok.kind in ("NUMBER", "STRING") or (
            tok.kind == "KEYWORD" and tok.value in ("TRUE", "FALSE", "NULL")
        ):
            return Literal(value=self.parse_literal())
        raise ParseError(
            f"Parse error at position {tok.pos}: expected a column name or literal, "
            f"found {tok.value!r}"
        )


def parse_sql(sql: str) -> list:
    """Tokenize and parse a (possibly multi-statement) SQL string."""
    tokens = tokenize(sql)
    return Parser(tokens).parse_program()

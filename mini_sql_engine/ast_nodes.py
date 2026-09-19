"""AST node definitions produced by the parser and consumed by the engine.

Plain dataclasses are used instead of a generic tree so the execution engine
can pattern-match on concrete Python types.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ColumnDef:
    name: str
    col_type: str  # "INTEGER", "TEXT", or "REAL"


@dataclass
class CreateTable:
    table_name: str
    columns: list[ColumnDef]


@dataclass
class Insert:
    table_name: str
    values: list


@dataclass
class Column:
    """A (possibly table-qualified) column reference, e.g. users.id or id."""
    name: str
    table: str | None = None

    def __str__(self) -> str:
        return f"{self.table}.{self.name}" if self.table else self.name


@dataclass
class Literal:
    value: object


@dataclass
class BinaryOp:
    op: str          # '=', '!=', '<', '>', '<=', '>=', 'AND', 'OR'
    left: object
    right: object


@dataclass
class AggregateCall:
    func: str        # COUNT, SUM, AVG, MIN, MAX
    column: Column | None   # None means COUNT(*)
    alias: str = ""


@dataclass
class SelectItem:
    expr: object      # Column or AggregateCall
    alias: str = ""


@dataclass
class JoinClause:
    table_name: str
    left_col: Column
    right_col: Column


@dataclass
class Select:
    items: list           # list[SelectItem] or the literal string "*"
    table_name: str
    join: JoinClause | None = None
    where: object = None
    group_by: str | None = None
    order_by: str | None = None
    order_dir: str = "ASC"
    limit: int | None = None

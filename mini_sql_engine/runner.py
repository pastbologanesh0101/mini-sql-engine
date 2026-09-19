"""Glue layer: parse SQL text and execute the resulting statements against a
``Database``. Shared by the interactive REPL, the script-file runner, and the
test suite so all three exercise exactly the same code path.
"""

from __future__ import annotations

from mini_sql_engine.ast_nodes import CreateTable, Insert, Select
from mini_sql_engine.engine import Database
from mini_sql_engine.parser import parse_sql


class StatementResult:
    """Wraps the outcome of executing a single statement."""

    def __init__(self, kind: str, columns=None, rows=None, message: str = ""):
        self.kind = kind          # "CREATE_TABLE", "INSERT", or "SELECT"
        self.columns = columns
        self.rows = rows
        self.message = message


def run_statement(db: Database, stmt) -> StatementResult:
    if isinstance(stmt, CreateTable):
        db.create_table(stmt)
        return StatementResult("CREATE_TABLE", message=f"Table '{stmt.table_name}' created.")
    if isinstance(stmt, Insert):
        db.insert(stmt)
        return StatementResult("INSERT", message="1 row inserted.")
    if isinstance(stmt, Select):
        columns, rows = db.select(stmt)
        return StatementResult("SELECT", columns=columns, rows=rows)
    raise TypeError(f"Unknown statement type: {stmt!r}")


def run_sql(db: Database, sql: str) -> list[StatementResult]:
    """Parse (possibly multiple, ';'-separated) statements and run them in order."""
    statements = parse_sql(sql)
    return [run_statement(db, stmt) for stmt in statements]

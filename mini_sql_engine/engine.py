"""In-memory execution engine for the Mini SQL Engine.

Tables are stored as a list of dict rows (``{column_name: value}``) plus the
declared column types used for basic type checking on ``INSERT``. The
``Database`` class holds a collection of named tables and is the object the
REPL/script runner executes statements against.

Execution of a ``SELECT`` proceeds in the classic relational order:
FROM -> JOIN -> WHERE -> GROUP BY (aggregates) -> ORDER BY -> LIMIT -> project.
"""

from __future__ import annotations

from mini_sql_engine.ast_nodes import (
    AggregateCall, BinaryOp, Column, CreateTable, Insert, Literal, Select,
)
from mini_sql_engine.errors import ExecutionError, TypeCheckError

NUMERIC_TYPES = (int, float)


def _type_ok(value, col_type: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        # bool is a subclass of int in Python; treat as its own (unsupported) type
        return False
    if col_type == "INTEGER":
        return isinstance(value, int)
    if col_type == "REAL":
        return isinstance(value, NUMERIC_TYPES)
    if col_type == "TEXT":
        return isinstance(value, str)
    return False


def _coerce(value, col_type: str):
    if value is None:
        return None
    if col_type == "REAL" and isinstance(value, int):
        return float(value)
    return value


class Table:
    def __init__(self, name: str, columns):
        self.name = name
        self.columns = columns  # list[ColumnDef]
        self.column_names = [c.name for c in columns]
        self.column_types = {c.name: c.col_type for c in columns}
        self.rows: list[dict] = []

    def insert(self, values: list):
        if len(values) != len(self.columns):
            raise ExecutionError(
                f"Table '{self.name}' has {len(self.columns)} column(s) but "
                f"{len(values)} value(s) were supplied"
            )
        row = {}
        for col_def, value in zip(self.columns, values):
            if not _type_ok(value, col_def.col_type):
                raise TypeCheckError(
                    f"Column '{col_def.name}' in table '{self.name}' expects "
                    f"{col_def.col_type}, got {type(value).__name__} ({value!r})"
                )
            row[col_def.name] = _coerce(value, col_def.col_type)
        self.rows.append(row)


class Database:
    def __init__(self):
        self.tables: dict[str, Table] = {}

    def create_table(self, stmt: CreateTable):
        if stmt.table_name in self.tables:
            raise ExecutionError(f"Table '{stmt.table_name}' already exists")
        seen = set()
        for col in stmt.columns:
            if col.name in seen:
                raise ExecutionError(
                    f"Duplicate column '{col.name}' in table '{stmt.table_name}'"
                )
            seen.add(col.name)
        self.tables[stmt.table_name] = Table(stmt.table_name, stmt.columns)

    def get_table(self, name: str) -> Table:
        if name not in self.tables:
            raise ExecutionError(f"Table '{name}' does not exist")
        return self.tables[name]

    def insert(self, stmt: Insert):
        table = self.get_table(stmt.table_name)
        table.insert(stmt.values)

    def select(self, stmt: Select):
        return execute_select(self, stmt)


# ---------------------------------------------------------------------------
# SELECT execution
# ---------------------------------------------------------------------------

def _assign_join_columns(col1: Column, col2: Column, t1: str, t2: str):
    """Work out which of col1/col2 belongs to table t1 and which to t2,
    honoring explicit table qualifiers and falling back to positional
    assignment (col1 -> t1, col2 -> t2) when unqualified."""
    slot = {t1: None, t2: None}
    unqualified = []
    for c in (col1, col2):
        if c.table is None:
            unqualified.append(c)
        elif c.table == t1:
            slot[t1] = c
        elif c.table == t2:
            slot[t2] = c
        else:
            raise ExecutionError(f"Unknown table '{c.table}' referenced in JOIN condition")
    for t in (t1, t2):
        if slot[t] is None and unqualified:
            slot[t] = unqualified.pop(0)
    return slot[t1], slot[t2]


def _resolve_column(context: dict, col: Column):
    """Look up a column's value in a {table_name: row_dict} context."""
    if col.table:
        if col.table not in context:
            raise ExecutionError(f"Unknown table '{col.table}'")
        row = context[col.table]
        if col.name not in row:
            raise ExecutionError(f"Unknown column '{col.name}' in table '{col.table}'")
        return row[col.name]

    matches = [row[col.name] for row in context.values() if col.name in row]
    if not matches:
        raise ExecutionError(f"Unknown column '{col.name}'")
    if len(matches) > 1:
        raise ExecutionError(
            f"Ambiguous column '{col.name}' - qualify it with a table name"
        )
    return matches[0]


def _eval_operand(context: dict, node):
    if isinstance(node, Column):
        return _resolve_column(context, node)
    if isinstance(node, Literal):
        return node.value
    raise ExecutionError(f"Cannot evaluate expression: {node!r}")


def _compare(op: str, left, right) -> bool:
    try:
        if op == "=":
            return left == right
        if op in ("!=", "<>"):
            return left != right
        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right
    except TypeError:
        return False
    raise ExecutionError(f"Unsupported comparison operator '{op}'")


def _eval_condition(context: dict, node) -> bool:
    if isinstance(node, BinaryOp):
        if node.op == "AND":
            return _eval_condition(context, node.left) and _eval_condition(context, node.right)
        if node.op == "OR":
            return _eval_condition(context, node.left) or _eval_condition(context, node.right)
        left = _eval_operand(context, node.left)
        right = _eval_operand(context, node.right)
        return _compare(node.op, left, right)
    raise ExecutionError(f"Cannot evaluate condition: {node!r}")


def _load_contexts(db: Database, stmt: Select):
    from_table = db.get_table(stmt.table_name)
    contexts = [{stmt.table_name: row} for row in from_table.rows]

    if stmt.join is None:
        return contexts

    join_table = db.get_table(stmt.join.table_name)
    left_col, right_col = _assign_join_columns(
        stmt.join.left_col, stmt.join.right_col, stmt.table_name, stmt.join.table_name
    )
    if left_col.name not in from_table.column_names:
        raise ExecutionError(
            f"Unknown column '{left_col.name}' in table '{stmt.table_name}'"
        )
    if right_col.name not in join_table.column_names:
        raise ExecutionError(
            f"Unknown column '{right_col.name}' in table '{stmt.join.table_name}'"
        )

    joined = []
    for left_row in from_table.rows:
        for right_row in join_table.rows:
            if left_row[left_col.name] == right_row[right_col.name]:
                joined.append({
                    stmt.table_name: left_row,
                    stmt.join.table_name: right_row,
                })
    return joined


def _order_key(value):
    # Allow sorting mixed None values without raising.
    return (value is None, value)


def _apply_order_and_limit_on_contexts(contexts, stmt: Select):
    if stmt.order_by:
        col = Column(name=stmt.order_by)
        try:
            contexts = sorted(
                contexts, key=lambda c: _order_key(_resolve_column(c, col))
            )
        except ExecutionError:
            raise
        if stmt.order_dir == "DESC":
            contexts = list(reversed(contexts))
    if stmt.limit is not None:
        contexts = contexts[: stmt.limit]
    return contexts


def _project(db: Database, contexts, stmt: Select):
    tables_involved = [stmt.table_name] + ([stmt.join.table_name] if stmt.join else [])
    multi_table = len(tables_involved) > 1

    if stmt.items == "*":
        if multi_table:
            columns = [
                f"{t}.{name}"
                for t in tables_involved
                for name in db.get_table(t).column_names
            ]
            rows = []
            for ctx in contexts:
                row = []
                for t in tables_involved:
                    row.extend(ctx[t].values())
                rows.append(row)
            return columns, rows
        else:
            table_name = tables_involved[0]
            columns = list(db.get_table(table_name).column_names)
            rows = [list(ctx[table_name].values()) for ctx in contexts]
            return columns, rows

    columns = [item.alias for item in stmt.items]
    rows = []
    for ctx in contexts:
        row = []
        for item in stmt.items:
            if isinstance(item.expr, Column):
                row.append(_resolve_column(ctx, item.expr))
            else:
                raise ExecutionError("Aggregate function used without GROUP BY context")
        rows.append(row)
    return columns, rows


# -- aggregates --------------------------------------------------------

def _aggregate_values(func: str, values: list):
    non_null = [v for v in values if v is not None]
    if func == "COUNT":
        return len(non_null)
    if func == "SUM":
        return sum(non_null) if non_null else 0
    if func == "AVG":
        return (sum(non_null) / len(non_null)) if non_null else None
    if func == "MIN":
        return min(non_null) if non_null else None
    if func == "MAX":
        return max(non_null) if non_null else None
    raise ExecutionError(f"Unsupported aggregate function '{func}'")


def _compute_aggregate(item: AggregateCall, group_contexts: list):
    if item.column is None:
        if item.func != "COUNT":
            raise ExecutionError(f"{item.func}(*) is not supported, use COUNT(*)")
        return len(group_contexts)
    values = [_resolve_column(ctx, item.column) for ctx in group_contexts]
    return _aggregate_values(item.func, values)


def _execute_grouped(contexts, stmt: Select):
    if stmt.items == "*":
        raise ExecutionError("SELECT * cannot be combined with aggregate functions")

    if stmt.group_by:
        group_col = Column(name=stmt.group_by)
        groups: dict = {}
        order = []
        for ctx in contexts:
            key = _resolve_column(ctx, group_col)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(ctx)
        group_items = [(k, groups[k]) for k in order]
    else:
        group_items = [(None, contexts)]

    columns = [item.alias for item in stmt.items]
    output_rows = []
    for key, group_contexts in group_items:
        row = []
        for item in stmt.items:
            if isinstance(item.expr, AggregateCall):
                row.append(_compute_aggregate(item.expr, group_contexts))
            elif isinstance(item.expr, Column):
                if stmt.group_by and item.expr.name == stmt.group_by:
                    row.append(key)
                elif group_contexts:
                    row.append(_resolve_column(group_contexts[0], item.expr))
                else:
                    row.append(None)
            else:
                raise ExecutionError(f"Cannot select expression {item.expr!r}")
        output_rows.append(row)

    if stmt.order_by:
        try:
            idx = columns.index(stmt.order_by)
        except ValueError:
            idx = None
        if idx is not None:
            output_rows.sort(key=lambda r: _order_key(r[idx]))
            if stmt.order_dir == "DESC":
                output_rows.reverse()

    if stmt.limit is not None:
        output_rows = output_rows[: stmt.limit]

    return columns, output_rows


def execute_select(db: Database, stmt: Select):
    contexts = _load_contexts(db, stmt)

    if stmt.where is not None:
        contexts = [ctx for ctx in contexts if _eval_condition(ctx, stmt.where)]

    has_aggregate = isinstance(stmt.items, list) and any(
        isinstance(item.expr, AggregateCall) for item in stmt.items
    )

    if stmt.group_by or has_aggregate:
        return _execute_grouped(contexts, stmt)

    contexts = _apply_order_and_limit_on_contexts(contexts, stmt)
    return _project(db, contexts, stmt)

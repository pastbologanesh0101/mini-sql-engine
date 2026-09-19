# Mini SQL Engine

[![Tests](https://github.com/pastbologanesh0101/mini-sql-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/pastbologanesh0101/mini-sql-engine/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A small in-memory SQL query engine written from scratch in pure Python
(standard library only — no `sqlite3`, no third-party DB drivers). It
implements its own tokenizer, recursive-descent parser, and execution engine
over Python data structures, plus an interactive REPL and a `.sql` script
runner.

The point of this project is the implementation, not the coverage: it
supports a deliberately small, precisely-defined subset of SQL (documented
below), not a general-purpose database.

## Architecture

```
SQL text
   |
   v
mini_sql_engine/lexer.py    - tokenizer: chars -> Token stream
   |
   v
mini_sql_engine/parser.py   - recursive-descent parser: tokens -> AST
   |                          (mini_sql_engine/ast_nodes.py)
   v
mini_sql_engine/engine.py   - execution engine: AST -> results
   |                          (Database / Table hold rows as list[dict])
   v
mini_sql_engine/formatter.py - renders (columns, rows) as an ASCII table
   |
   v
mini_sql_engine/runner.py   - glue: parse_sql() + run each statement
   |
   v
mini_sql.py                 - CLI: REPL and script-file entry point
```

- **Lexer** (`lexer.py`): a single-pass scanner that turns SQL text into
  `Token(kind, value, pos)` objects — keywords, identifiers, numbers, string
  literals (`'...'`, with `''` as an escaped quote), operators (`= != <> < >
  <= >=`), punctuation, and `-- comment` handling.
- **Parser** (`parser.py`): hand-written recursive descent, one function per
  grammar rule (see the full grammar below). Produces plain dataclass AST
  nodes from `ast_nodes.py`. `AND` is parsed as nesting inside `OR`
  (`or_expr := and_expr {OR and_expr}`, `and_expr := comparison {AND
  comparison}`), which gives `AND` higher precedence than `OR`, matching
  standard SQL.
- **Engine** (`engine.py`): tables are `Table` objects holding `rows: list[dict]`
  plus declared column types. A `SELECT` executes in this order: load base
  rows -> apply `JOIN` (nested-loop equi-join) -> apply `WHERE` -> apply
  `GROUP BY`/aggregates (or nothing) -> apply `ORDER BY` -> apply `LIMIT` ->
  project the requested columns.
- **Formatter** (`formatter.py`): renders `(columns, rows)` as an aligned
  ASCII table with a row count footer.
- **Runner** (`runner.py`): the only place that ties parsing to execution;
  both the REPL and the script mode (and the tests) call `run_sql(db, text)`.

## Supported SQL subset

Keywords are case-insensitive. Every statement must end with `;` when there
is more than one statement in the input (a trailing `;` is always accepted).

### `CREATE TABLE`

```
CREATE TABLE table_name (col1 TYPE, col2 TYPE, ...);
```

Types: `INTEGER` (alias `INT`), `TEXT`, `REAL` (alias `FLOAT`).

### `INSERT`

```
INSERT INTO table_name VALUES (val1, val2, ...);
```

One row per statement, values positional (matching the declared column
order). String literals use single quotes: `'like this'`.

**Type checking:** values are checked against the column's declared type at
insert time. `INTEGER` requires a Python `int` literal, `TEXT` requires a
string literal, `REAL` accepts an `int` or a `float` literal (an `int` is
coerced to `float`). Mismatches raise a `TypeCheckError` with a clear message,
e.g. inserting `'thirty'` into an `INTEGER` column — the engine does **not**
silently coerce strings to numbers or vice versa.

### `SELECT`

```
SELECT column1, column2 FROM table
SELECT * FROM table
SELECT col, AGG(col) FROM table
  [JOIN other_table ON table.col = other_table.col]
  [WHERE condition]
  [GROUP BY column]
  [ORDER BY column [ASC|DESC]]
  [LIMIT n]
```

- **Columns**: `*` for all columns, or a comma-separated list. Columns can be
  qualified as `table.column` (required to disambiguate a `JOIN`'s shared
  column names, optional otherwise).
- **`WHERE`**: comparisons `= != <> < > <= >=` between a column and a column
  or literal, combined with `AND` / `OR`. **`AND` binds tighter than `OR`**,
  exactly like standard SQL — `WHERE a OR b AND c` is `a OR (b AND c)`, not
  `(a OR b) AND c`.
- **`JOIN`**: a single inner (equi-)join: `JOIN other ON t1.col = t2.col`
  (`INNER JOIN` also accepted). Implemented as a nested-loop join keeping
  only rows where the two columns are equal.
- **`GROUP BY`**: single-column grouping with aggregate functions `COUNT(*)`,
  `COUNT(col)`, `SUM(col)`, `AVG(col)`, `MIN(col)`, `MAX(col)` in the select
  list. Aggregates without `GROUP BY` compute a single summary row over the
  whole (post-`WHERE`) result set. `NULL` values are excluded from aggregate
  computations (`SUM`/`COUNT` treat them as absent, `AVG`/`MIN`/`MAX` of an
  all-`NULL` group is `NULL`).
- **`ORDER BY`**: single column, `ASC` (default) or `DESC`.
- **`LIMIT`**: integer row cap, applied last.

### Not supported (by design, to keep the engine small)

`UPDATE`, `DELETE`, `ALTER TABLE`, multi-table `JOIN` chains, subqueries,
`HAVING`, multi-column `GROUP BY`/`ORDER BY`, `LIKE`, `IN`, `NULL`-specific
operators (`IS NULL`), and transactions.

## Full grammar

```
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

join_clause    := ["INNER"] "JOIN" IDENT "ON" column_ref "=" column_ref

condition      := or_expr
or_expr        := and_expr {"OR" and_expr}
and_expr       := comparison {"AND" comparison}
comparison     := operand cmp_op operand
cmp_op         := "=" | "!=" | "<>" | "<" | ">" | "<=" | ">="
operand        := column_ref | literal
```

## Running it

Requires only Python 3.11+ (standard library only; `pytest` is used for
tests but the engine itself has zero dependencies).

### Interactive REPL

```bash
python mini_sql.py
```

```
Mini SQL Engine - type SQL statements ending in ';', or 'exit' / 'quit' to leave.
Example: CREATE TABLE users (id INTEGER, name TEXT);
sql> CREATE TABLE users (id INTEGER, name TEXT, age INTEGER);
Table 'users' created.
sql> INSERT INTO users VALUES (1, 'Alice', 30);
1 row inserted.
sql> INSERT INTO users VALUES (2, 'Bob', 25);
1 row inserted.
sql> SELECT * FROM users WHERE age > 26 ORDER BY age DESC;
+----+-------+-----+
| id | name  | age |
+----+-------+-----+
| 1  | Alice | 30  |
+----+-------+-----+
(1 row)
sql> exit
```

### Script mode (non-interactive)

Put any sequence of statements in a `.sql` file and run:

```bash
python mini_sql.py path/to/script.sql
```

Each statement's result (a table for `SELECT`, or a short confirmation for
`CREATE TABLE` / `INSERT`) is printed in order. This is what the test suite
uses to verify end-to-end behavior without a live REPL — see
`tests/fixtures/sample.sql` and `tests/test_engine.py::ScriptModeTests`.

## Example session (JOIN + GROUP BY)

```sql
CREATE TABLE users (id INTEGER, name TEXT);
INSERT INTO users VALUES (1, 'Alice');
INSERT INTO users VALUES (2, 'Bob');

CREATE TABLE orders (order_id INTEGER, user_id INTEGER, amount INTEGER);
INSERT INTO orders VALUES (100, 1, 50);
INSERT INTO orders VALUES (101, 1, 20);
INSERT INTO orders VALUES (102, 2, 75);

SELECT users.name, orders.amount
FROM users JOIN orders ON users.id = orders.user_id;
-- Alice | 50, Alice | 20, Bob | 75

SELECT user_id, SUM(amount) FROM orders GROUP BY user_id;
-- 1 | 70, 2 | 75
```

## Tests

```bash
python -m pytest tests/ -v
```

22 tests cover: create/insert/select round-trips, column projection vs
`SELECT *`, `WHERE` filtering including an `AND`/`OR` precedence case crafted
to give the wrong answer under left-to-right evaluation, comparison
operators, `ORDER BY` (both directions), `LIMIT`, `INNER JOIN` correctness
(including a row with no match being correctly excluded), `GROUP BY` with
every aggregate function against hand-computed expected values, type
checking on `INSERT`, parse errors on malformed SQL, execution errors on
unknown tables/columns, and full script-mode execution through the actual
CLI entry point.

CI (`.github/workflows/tests.yml`) runs the same suite on Python 3.11 and
3.12 on every push and pull request.

## Project layout

```
mini_sql.py                  # CLI entry point (REPL + script mode)
mini_sql_engine/
  lexer.py                   # tokenizer
  parser.py                  # recursive-descent parser -> AST
  ast_nodes.py                # AST dataclasses
  engine.py                  # Database/Table + SELECT execution
  formatter.py                # ASCII table rendering
  runner.py                  # parse + execute glue
  errors.py                   # SQLError and subclasses
tests/
  test_engine.py
  fixtures/sample.sql
.github/workflows/tests.yml
```

## License

MIT - see [LICENSE](LICENSE).

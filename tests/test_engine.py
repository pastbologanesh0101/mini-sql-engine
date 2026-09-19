"""Unit tests for the Mini SQL Engine.

Run with:
    python -m pytest tests/ -v
or:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mini_sql_engine.engine import Database
from mini_sql_engine.errors import ExecutionError, ParseError, TypeCheckError
from mini_sql_engine.runner import run_sql

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def run(db, sql):
    return run_sql(db, sql)


def last_select(db, sql):
    """Run possibly-multiple statements, return (columns, rows) of the final SELECT."""
    results = run_sql(db, sql)
    select_results = [r for r in results if r.kind == "SELECT"]
    result = select_results[-1]
    return result.columns, result.rows


class CreateInsertSelectTests(unittest.TestCase):
    def test_create_insert_select_roundtrip(self):
        db = Database()
        columns, rows = last_select(db, """
            CREATE TABLE users (id INTEGER, name TEXT, age INTEGER);
            INSERT INTO users VALUES (1, 'Alice', 30);
            INSERT INTO users VALUES (2, 'Bob', 25);
            SELECT * FROM users;
        """)
        self.assertEqual(columns, ["id", "name", "age"])
        self.assertEqual(rows, [[1, "Alice", 30], [2, "Bob", 25]])

    def test_select_specific_columns_vs_star(self):
        db = Database()
        run(db, "CREATE TABLE t (a INTEGER, b TEXT, c INTEGER);")
        run(db, "INSERT INTO t VALUES (1, 'x', 100);")

        cols_star, rows_star = last_select(db, "SELECT * FROM t;")
        self.assertEqual(cols_star, ["a", "b", "c"])
        self.assertEqual(rows_star, [[1, "x", 100]])

        cols_specific, rows_specific = last_select(db, "SELECT a, c FROM t;")
        self.assertEqual(cols_specific, ["a", "c"])
        self.assertEqual(rows_specific, [[1, 100]])

    def test_insert_wrong_arity_raises(self):
        db = Database()
        run(db, "CREATE TABLE t (a INTEGER, b TEXT);")
        with self.assertRaises(ExecutionError):
            run(db, "INSERT INTO t VALUES (1);")


class TypeCheckingTests(unittest.TestCase):
    def test_string_into_integer_column_rejected(self):
        db = Database()
        run(db, "CREATE TABLE t (id INTEGER, name TEXT);")
        with self.assertRaises(TypeCheckError):
            run(db, "INSERT INTO t VALUES ('not-a-number', 'Alice');")

    def test_integer_into_real_column_is_coerced_to_float(self):
        db = Database()
        run(db, "CREATE TABLE t (score REAL);")
        run(db, "INSERT INTO t VALUES (5);")
        _, rows = last_select(db, "SELECT score FROM t;")
        self.assertEqual(rows, [[5.0]])
        self.assertIsInstance(rows[0][0], float)


class WhereClauseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        run(self.db, "CREATE TABLE emp (id INTEGER, dept TEXT, salary INTEGER);")
        run(self.db, "INSERT INTO emp VALUES (1, 'eng', 100);")
        run(self.db, "INSERT INTO emp VALUES (2, 'eng', 50);")
        run(self.db, "INSERT INTO emp VALUES (3, 'sales', 100);")
        run(self.db, "INSERT INTO emp VALUES (4, 'sales', 40);")

    def test_simple_equality_filter(self):
        _, rows = last_select(self.db, "SELECT id FROM emp WHERE dept = 'eng';")
        self.assertEqual([r[0] for r in rows], [1, 2])

    def test_comparison_operators(self):
        _, rows = last_select(self.db, "SELECT id FROM emp WHERE salary >= 100;")
        self.assertEqual([r[0] for r in rows], [1, 3])
        _, rows = last_select(self.db, "SELECT id FROM emp WHERE salary < 50;")
        self.assertEqual([r[0] for r in rows], [4])
        _, rows = last_select(self.db, "SELECT id FROM emp WHERE dept != 'eng';")
        self.assertEqual([r[0] for r in rows], [3, 4])

    def test_and_or_precedence(self):
        # AND must bind tighter than OR: dept='sales' AND salary=100 gives {3}.
        # A wrong-precedence implementation that evaluates left-to-right as
        # ((dept='eng' OR dept='sales') AND salary=100) would still get this
        # one right, so we also test a case that breaks it:
        #   dept='eng' OR dept='sales' AND salary=40
        # Correct (AND first): dept='eng' (1,2) OR (dept='sales' AND salary=40) (4)
        #   => {1, 2, 4}
        # Wrong (OR first, left-to-right): (dept='eng' OR dept='sales') AND salary=40
        #   => {4} only
        _, rows = last_select(
            self.db,
            "SELECT id FROM emp WHERE dept = 'eng' OR dept = 'sales' AND salary = 40;",
        )
        self.assertEqual(sorted(r[0] for r in rows), [1, 2, 4])

    def test_and_only(self):
        _, rows = last_select(
            self.db, "SELECT id FROM emp WHERE dept = 'sales' AND salary = 100;"
        )
        self.assertEqual([r[0] for r in rows], [3])


class OrderByLimitTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        run(self.db, "CREATE TABLE t (id INTEGER, score INTEGER);")
        for i, score in [(1, 30), (2, 10), (3, 20)]:
            run(self.db, f"INSERT INTO t VALUES ({i}, {score});")

    def test_order_by_asc(self):
        _, rows = last_select(self.db, "SELECT id FROM t ORDER BY score ASC;")
        self.assertEqual([r[0] for r in rows], [2, 3, 1])

    def test_order_by_desc(self):
        _, rows = last_select(self.db, "SELECT id FROM t ORDER BY score DESC;")
        self.assertEqual([r[0] for r in rows], [1, 3, 2])

    def test_limit_truncates(self):
        _, rows = last_select(self.db, "SELECT id FROM t ORDER BY score DESC LIMIT 2;")
        self.assertEqual([r[0] for r in rows], [1, 3])


class JoinTests(unittest.TestCase):
    def test_inner_join_matches_correctly(self):
        db = Database()
        run(db, "CREATE TABLE users (id INTEGER, name TEXT);")
        run(db, "INSERT INTO users VALUES (1, 'Alice');")
        run(db, "INSERT INTO users VALUES (2, 'Bob');")
        run(db, "INSERT INTO users VALUES (3, 'Carol');")  # no orders -> excluded

        run(db, "CREATE TABLE orders (order_id INTEGER, user_id INTEGER, amount INTEGER);")
        run(db, "INSERT INTO orders VALUES (100, 1, 50);")
        run(db, "INSERT INTO orders VALUES (101, 1, 20);")
        run(db, "INSERT INTO orders VALUES (102, 2, 75);")

        _, rows = last_select(
            db,
            "SELECT users.name, orders.amount FROM users "
            "JOIN orders ON users.id = orders.user_id;",
        )
        pairs = sorted((r[0], r[1]) for r in rows)
        self.assertEqual(pairs, [("Alice", 20), ("Alice", 50), ("Bob", 75)])
        self.assertEqual(len(rows), 3)  # Carol has no matching orders


class GroupByAggregateTests(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        run(self.db, "CREATE TABLE sales (dept TEXT, amount INTEGER);")
        data = [("eng", 10), ("eng", 20), ("eng", 30), ("sales", 5), ("sales", 15)]
        for dept, amount in data:
            run(self.db, f"INSERT INTO sales VALUES ('{dept}', {amount});")

    def test_group_by_count(self):
        _, rows = last_select(
            self.db, "SELECT dept, COUNT(*) FROM sales GROUP BY dept ORDER BY dept ASC;"
        )
        self.assertEqual(rows, [["eng", 3], ["sales", 2]])

    def test_group_by_sum(self):
        _, rows = last_select(
            self.db, "SELECT dept, SUM(amount) FROM sales GROUP BY dept ORDER BY dept ASC;"
        )
        self.assertEqual(rows, [["eng", 60], ["sales", 20]])

    def test_group_by_avg(self):
        _, rows = last_select(
            self.db, "SELECT dept, AVG(amount) FROM sales GROUP BY dept ORDER BY dept ASC;"
        )
        self.assertAlmostEqual(rows[0][1], 20.0)
        self.assertAlmostEqual(rows[1][1], 10.0)

    def test_group_by_min_max(self):
        _, rows = last_select(
            self.db,
            "SELECT dept, MIN(amount), MAX(amount) FROM sales GROUP BY dept ORDER BY dept ASC;",
        )
        self.assertEqual(rows, [["eng", 10, 30], ["sales", 5, 15]])


class ErrorHandlingTests(unittest.TestCase):
    def test_malformed_sql_raises_parse_error(self):
        db = Database()
        with self.assertRaises(ParseError):
            run(db, "SELEC * FORM t")

    def test_malformed_create_table_raises_parse_error(self):
        db = Database()
        with self.assertRaises(ParseError):
            run(db, "CREATE TABLE t (id)")  # missing column type

    def test_query_nonexistent_table_raises_clear_error(self):
        db = Database()
        with self.assertRaises(ExecutionError) as ctx:
            run(db, "SELECT * FROM ghost;")
        self.assertIn("ghost", str(ctx.exception))

    def test_query_nonexistent_column_raises_clear_error(self):
        db = Database()
        run(db, "CREATE TABLE t (id INTEGER);")
        run(db, "INSERT INTO t VALUES (1);")
        with self.assertRaises(ExecutionError) as ctx:
            run(db, "SELECT missing_col FROM t;")
        self.assertIn("missing_col", str(ctx.exception))


class ScriptModeTests(unittest.TestCase):
    def test_script_file_runs_end_to_end(self):
        script_path = os.path.join(FIXTURES_DIR, "sample.sql")
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "mini_sql.py"), script_path],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Bob", result.stdout)
        self.assertIn("Alice", result.stdout)
        self.assertIn("row", result.stdout)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Mini SQL Engine - CLI entry point.

Usage:
    python mini_sql.py                 # interactive REPL
    python mini_sql.py path/to/file.sql # run a script non-interactively

The REPL reads one statement at a time (terminated by ';'), executes it
against an in-memory database that lives for the duration of the process,
and prints the result as a formatted ASCII table (for SELECT) or a short
confirmation message (for CREATE TABLE / INSERT). Errors are caught and
printed as a single clear line instead of a Python traceback.
"""

from __future__ import annotations

import sys

from mini_sql_engine.engine import Database
from mini_sql_engine.errors import SQLError
from mini_sql_engine.formatter import format_table
from mini_sql_engine.runner import run_sql

BANNER = (
    "Mini SQL Engine - type SQL statements ending in ';', or 'exit' / 'quit' to leave.\n"
    "Example: CREATE TABLE users (id INTEGER, name TEXT);"
)


def print_result(result) -> None:
    if result.kind == "SELECT":
        print(format_table(result.columns, result.rows))
    else:
        print(result.message)


def run_script(db: Database, path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            sql_text = f.read()
    except OSError as exc:
        print(f"Error: could not read script '{path}': {exc}", file=sys.stderr)
        return 1

    try:
        results = run_sql(db, sql_text)
    except SQLError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for result in results:
        print_result(result)
    return 0


def run_repl(db: Database) -> None:
    print(BANNER)
    buffer = ""
    while True:
        prompt = "sql> " if not buffer else "...> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break

        stripped = line.strip()
        if not buffer and stripped.lower() in ("exit", "quit", "exit;", "quit;"):
            break
        if not stripped:
            continue

        buffer += (" " if buffer else "") + line
        if ";" not in line:
            continue

        statement_text = buffer
        buffer = ""
        try:
            for result in run_sql(db, statement_text):
                print_result(result)
        except SQLError as exc:
            print(f"Error: {exc}")


def main(argv: list[str]) -> int:
    db = Database()
    if len(argv) > 1:
        return run_script(db, argv[1])
    run_repl(db)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

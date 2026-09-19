"""Render (columns, rows) query results as an ASCII table for the CLI."""

from __future__ import annotations


def _cell(value) -> str:
    if value is None:
        return "NULL"
    return str(value)


def format_table(columns: list[str], rows: list[list]) -> str:
    if not columns:
        return "(no columns)"

    str_rows = [[_cell(v) for v in row] for row in rows]
    widths = [len(c) for c in columns]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)) + " |"

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    lines = [sep, fmt_row(columns), sep]
    for row in str_rows:
        lines.append(fmt_row(row))
    lines.append(sep)
    if not rows:
        lines.append("(0 rows)")
    else:
        lines.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)

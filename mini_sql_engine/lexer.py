"""Hand-written tokenizer (lexer) for the Mini SQL Engine.

Converts a raw SQL string into a flat list of ``Token`` objects that the
recursive-descent parser (see ``mini_sql/parser.py``) consumes. Nothing here
knows about SQL grammar/statement structure - it only recognizes the small
set of lexical categories: keywords, identifiers, numbers, strings and
punctuation/operators.
"""

from __future__ import annotations

from dataclasses import dataclass

from mini_sql_engine.errors import LexError

KEYWORDS = {
    "CREATE", "TABLE", "INSERT", "INTO", "VALUES", "SELECT", "FROM", "WHERE",
    "AND", "OR", "NOT", "ORDER", "BY", "ASC", "DESC", "LIMIT", "JOIN",
    "INNER", "ON", "GROUP", "AS",
    "INTEGER", "INT", "TEXT", "REAL", "FLOAT",
    "COUNT", "SUM", "AVG", "MIN", "MAX",
    "TRUE", "FALSE", "NULL",
}

# Multi-character operators must be listed before their single-char prefixes.
OPERATORS = ["<=", ">=", "!=", "<>", "=", "<", ">"]

SINGLE_PUNCT = {
    "(": "LPAREN",
    ")": "RPAREN",
    ",": "COMMA",
    ";": "SEMI",
    ".": "DOT",
    "*": "STAR",
}


@dataclass
class Token:
    kind: str      # KEYWORD, IDENT, NUMBER, STRING, OP, or one of SINGLE_PUNCT values / EOF
    value: str     # normalized text (keywords upper-cased); literal text otherwise
    pos: int       # character offset in the source, for error messages

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Token({self.kind}, {self.value!r})"


def tokenize(sql: str) -> list[Token]:
    """Turn a SQL string into a list of tokens, ending with an EOF token."""
    tokens: list[Token] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # Whitespace
        if ch.isspace():
            i += 1
            continue

        # Line comments: -- to end of line
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        # String literals: 'text' (doubled '' is an escaped quote)
        if ch == "'":
            start = i
            i += 1
            buf = []
            closed = False
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                buf.append(sql[i])
                i += 1
            if not closed:
                raise LexError(f"Unterminated string literal starting at position {start}")
            tokens.append(Token("STRING", "".join(buf), start))
            continue

        # Numbers: integers and decimals, optional leading '-'
        if ch.isdigit() or (ch == "-" and i + 1 < n and sql[i + 1].isdigit()):
            start = i
            if ch == "-":
                i += 1
            while i < n and sql[i].isdigit():
                i += 1
            if i < n and sql[i] == "." and i + 1 < n and sql[i + 1].isdigit():
                i += 1
                while i < n and sql[i].isdigit():
                    i += 1
            tokens.append(Token("NUMBER", sql[start:i], start))
            continue

        # Identifiers and keywords
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (sql[i].isalnum() or sql[i] == "_"):
                i += 1
            word = sql[start:i]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token("KEYWORD", upper, start))
            else:
                tokens.append(Token("IDENT", word, start))
            continue

        # Multi/single char operators
        matched_op = None
        for op in OPERATORS:
            if sql.startswith(op, i):
                matched_op = op
                break
        if matched_op:
            tokens.append(Token("OP", matched_op, i))
            i += len(matched_op)
            continue

        if ch in SINGLE_PUNCT:
            tokens.append(Token(SINGLE_PUNCT[ch], ch, i))
            i += 1
            continue

        raise LexError(f"Unexpected character {ch!r} at position {i}")

    tokens.append(Token("EOF", "", n))
    return tokens

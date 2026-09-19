"""Exception types raised by the Mini SQL Engine.

All errors raised anywhere in the engine (lexing, parsing, execution)
are subclasses of ``SQLError`` so callers (the REPL, script runner, or
tests) can catch a single type and print a clean message instead of a
raw Python traceback.
"""


class SQLError(Exception):
    """Base class for every error the engine can raise."""


class LexError(SQLError):
    """Raised when the tokenizer encounters an unrecognized character."""


class ParseError(SQLError):
    """Raised when the token stream does not match the grammar."""


class ExecutionError(SQLError):
    """Raised while executing a valid AST (e.g. unknown table/column)."""


class TypeCheckError(SQLError):
    """Raised when a value's type does not match its column's declared type."""

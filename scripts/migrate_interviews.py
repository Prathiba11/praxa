"""Add columns to the interview tables without losing what is in them.

`Base.metadata.create_all` creates missing *tables*. It does not touch a table
that already exists, so a column added to a model after the first run is simply
never created and every query against it fails. That is the whole reason this
script exists.

It is deliberately not a migration framework. Alembic is the right answer for a
schema that changes often against data someone depends on; this is one additive
column on a two-week-old table, and a twelve-line idempotent script is a smaller
thing to understand than a migrations directory. If the schema starts moving
regularly, that is the signal to switch.

Safe to run repeatedly: every change is checked before it is applied, and
`ADD COLUMN` with a default never rewrites existing rows.

    python scripts/migrate_interviews.py
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from career_copilot.core.logging import configure_logging
from career_copilot.storage.db import get_engine, init_db

# (table, column, the full DDL fragment to add it with)
_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "interview_sessions",
        "planned_questions",
        "planned_questions INTEGER NOT NULL DEFAULT 5",
    ),
)


def _columns(connection: Connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table})")).all()
    return {str(row[1]) for row in rows}


def _tables(connection: Connection) -> set[str]:
    rows = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'")).all()
    return {str(row[0]) for row in rows}


def main() -> None:
    configure_logging()
    init_db()  # creates anything missing entirely, which is the common case

    applied = 0
    skipped = 0
    with get_engine().begin() as connection:
        existing_tables = _tables(connection)
        for table, column, ddl in _ADDITIONS:
            if table not in existing_tables:
                print(f"  {table}: created fresh, nothing to migrate")
                continue
            if column in _columns(connection, table):
                skipped += 1
                print(f"  {table}.{column}: already present")
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
            applied += 1
            print(f"  {table}.{column}: added")

    print(f"\n{applied} column(s) added, {skipped} already up to date.")
    if applied:
        print("Existing sessions default to 5 planned questions.")


if __name__ == "__main__":
    main()

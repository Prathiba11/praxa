"""Database engine and sessions.

SQLite behind SQLAlchemy, deliberately. Single user, local, PII-heavy - a file
on disk is the right answer, and going through SQLAlchemy with a repository
layer means moving to Postgres later is a connection string plus a migration
rather than a rewrite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from career_copilot.core.config import get_settings
from career_copilot.core.errors import CopilotError
from career_copilot.core.logging import get_logger
from career_copilot.storage.models import Base

__all__ = ["StorageError", "get_engine", "init_db", "reset_engine", "session_scope"]

log = get_logger(__name__)


class StorageError(CopilotError):
    user_message = "Your saved data could not be read or updated."


#: How long a statement waits for a lock before giving up, in milliseconds.
#: Five seconds is the sqlite3 default and it is not enough: a job sync writes
#: a hundred rows one transaction at a time.
_BUSY_TIMEOUT_MS = 15_000


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{settings.db_path}",
        future=True,
        # The API serves requests on a thread pool and runs job syncs through
        # `asyncio.to_thread`, so connections legitimately cross threads.
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()

        # SQLite ignores foreign keys unless told otherwise, per connection.
        # Without this, an application row can point at a job that does not
        # exist and nothing complains - the funnel counts drift and no error is
        # ever raised. An integration test caught exactly that.
        cursor.execute("PRAGMA foreign_keys=ON")

        # Write-ahead logging, so a reader is not blocked by a writer.
        #
        # This is a scar. In the default rollback-journal mode a write holds an
        # exclusive lock on the whole file, and a job sync writes one posting
        # per transaction in a background thread. The Jobs page polls the list
        # endpoint while that runs, the read collided with a write, SQLite
        # raised "database is locked", `session_scope` wrapped it as
        # StorageError, and StorageError is not in the API error mapping - so it
        # fell through to a bare HTTP 500. The page said "Could not load
        # postings" every time a fetch was in flight. WAL lets the read proceed
        # against the last committed snapshot instead.
        cursor.execute("PRAGMA journal_mode=WAL")

        # And when a lock genuinely must be waited for, wait rather than fail.
        cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")

        cursor.close()

    Base.metadata.create_all(engine)
    log.info("database ready", extra={"path": str(settings.db_path)})
    return engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def init_db() -> None:
    """Create tables if they do not exist. Safe to call repeatedly."""
    get_engine()


def reset_engine() -> None:
    """Forget the cached engine and session factory.

    Both are lru_cached, which is right in the app and wrong in tests: without
    this, the second test in a run would quietly reuse the first one's database
    file. Public rather than a private reach-in, because tests are a real caller.
    """
    get_engine.cache_clear()
    _session_factory.cache_clear()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any failure."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise StorageError(f"database error: {type(exc).__name__}: {exc}") from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

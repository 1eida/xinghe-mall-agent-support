"""SQLite checkpoints for conversation history and pending confirmations."""

from contextlib import AbstractAsyncContextManager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from core.settings import settings


def initialize_database() -> AbstractAsyncContextManager[AsyncSqliteSaver]:
    Path(settings.SQLITE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(settings.SQLITE_DB_PATH)


__all__ = ["initialize_database"]

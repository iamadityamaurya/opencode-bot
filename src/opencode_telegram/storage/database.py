import asyncio
import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()
        await self._migrate()

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database connection is not initialized")
        return self._conn

    async def _create_tables(self):
        async with self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_states (
                telegram_user_id INTEGER PRIMARY KEY,
                telegram_chat_id INTEGER,
                selected_project TEXT,
                selected_session_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                telegram_chat_id INTEGER,
                ack_message_id INTEGER,
                state TEXT NOT NULL CHECK(state IN ('queued', 'running', 'awaiting_permission', 'completed', 'failed', 'cancelled')),
                prompt TEXT,
                response_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pinned_status (
                chat_id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """):
            await self._conn.commit()

    async def _migrate(self):
        """Additive migrations for databases created by earlier versions."""
        await self._ensure_column("user_states", "telegram_chat_id", "INTEGER")
        await self._ensure_column("tasks", "telegram_chat_id", "INTEGER")
        await self._ensure_column("tasks", "ack_message_id", "INTEGER")

    async def _ensure_column(self, table: str, column: str, decl: str):
        async with self._conn.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
        existing = {row["name"] for row in rows}
        if column in existing:
            return
        logger.info(f"Migrating: adding {table}.{column}")
        await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        await self._conn.commit()

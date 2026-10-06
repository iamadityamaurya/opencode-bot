import aiosqlite
from dataclasses import dataclass
from typing import Any
from opencode_telegram.storage.database import Database

@dataclass
class UserState:
    telegram_user_id: int
    selected_project: str | None = None
    selected_session_id: str | None = None
    telegram_chat_id: int | None = None

@dataclass
class TaskRecord:
    task_id: str
    session_id: str
    telegram_user_id: int
    state: str
    prompt: str
    response_text: str = ""
    telegram_chat_id: int | None = None
    ack_message_id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

@dataclass
class PinnedStatus:
    chat_id: int
    message_id: int

class Repository:
    def __init__(self, db: Database):
        self.db = db

    # -- user state --------------------------------------------------------
    async def get_user_state(self, user_id: int) -> UserState | None:
        async with self.db.conn.execute(
            "SELECT telegram_user_id, telegram_chat_id, selected_project, selected_session_id FROM user_states WHERE telegram_user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return UserState(
                    telegram_user_id=row["telegram_user_id"],
                    selected_project=row["selected_project"],
                    selected_session_id=row["selected_session_id"],
                    telegram_chat_id=row["telegram_chat_id"],
                )
            return None

    async def set_user_project(self, user_id: int, project_name: str):
        async with self.db.conn.execute("""
            INSERT INTO user_states (telegram_user_id, selected_project, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                selected_project = excluded.selected_project,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, project_name)):
            await self.db.conn.commit()

    async def set_user_session(self, user_id: int, session_id: str | None):
        async with self.db.conn.execute("""
            INSERT INTO user_states (telegram_user_id, selected_session_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                selected_session_id = excluded.selected_session_id,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, session_id)):
            await self.db.conn.commit()

    async def set_user_chat(self, user_id: int, chat_id: int):
        async with self.db.conn.execute("""
            INSERT INTO user_states (telegram_user_id, telegram_chat_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                telegram_chat_id = excluded.telegram_chat_id,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, chat_id)):
            await self.db.conn.commit()

    async def list_chat_ids(self) -> list[int]:
        async with self.db.conn.execute(
            "SELECT DISTINCT telegram_chat_id FROM user_states WHERE telegram_chat_id IS NOT NULL"
        ) as cursor:
            rows = await cursor.fetchall()
            return [int(r["telegram_chat_id"]) for r in rows]

    async def get_chat_id_for_session(self, session_id: str) -> int | None:
        async with self.db.conn.execute(
            """
            SELECT us.telegram_chat_id AS chat_id
            FROM sessions s
            JOIN user_states us ON us.telegram_user_id = s.telegram_user_id
            WHERE s.session_id = ? AND us.telegram_chat_id IS NOT NULL
            """,
            (session_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row["chat_id"]) if row else None

    # -- sessions ----------------------------------------------------------
    async def save_session(self, session_id: str, project_name: str, user_id: int, title: str | None):
        async with self.db.conn.execute("""
            INSERT INTO sessions (session_id, project_name, telegram_user_id, title)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                title = excluded.title
        """, (session_id, project_name, user_id, title)):
            await self.db.conn.commit()

    async def list_user_sessions(self, user_id: int, project_name: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT session_id, project_name, title, created_at FROM sessions WHERE telegram_user_id = ?"
        params: list[Any] = [user_id]
        if project_name:
            query += " AND project_name = ?"
            params.append(project_name)
        query += " ORDER BY created_at DESC"

        async with self.db.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # -- tasks -------------------------------------------------------------
    async def create_task(
        self,
        task_id: str,
        session_id: str,
        user_id: int,
        prompt: str,
        chat_id: int | None = None,
        ack_message_id: int | None = None,
    ) -> TaskRecord:
        active = await self.get_active_task_for_session(session_id)
        if active:
            raise RuntimeError(f"Active task {active.task_id} already exists for session {session_id}")

        async with self.db.conn.execute("""
            INSERT INTO tasks (task_id, session_id, telegram_user_id, telegram_chat_id, ack_message_id, state, prompt)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)
        """, (task_id, session_id, user_id, chat_id, ack_message_id, prompt)):
            await self.db.conn.commit()

        return TaskRecord(
            task_id=task_id,
            session_id=session_id,
            telegram_user_id=user_id,
            state="queued",
            prompt=prompt,
            telegram_chat_id=chat_id,
            ack_message_id=ack_message_id,
        )

    async def update_task_state(self, task_id: str, state: str, response_text: str = ""):
        async with self.db.conn.execute("""
            UPDATE tasks
            SET state = ?, response_text = CASE WHEN ? != '' THEN ? ELSE response_text END, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
        """, (state, response_text, response_text, task_id)):
            await self.db.conn.commit()

    @staticmethod
    def _task_from_row(row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            telegram_user_id=row["telegram_user_id"],
            state=row["state"],
            prompt=row["prompt"],
            response_text=row["response_text"],
            telegram_chat_id=row["telegram_chat_id"],
            ack_message_id=row["ack_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_active_task_for_session(self, session_id: str) -> TaskRecord | None:
        async with self.db.conn.execute("""
            SELECT task_id, session_id, telegram_user_id, telegram_chat_id, ack_message_id, state, prompt, response_text, created_at, updated_at
            FROM tasks
            WHERE session_id = ? AND state IN ('queued', 'running', 'awaiting_permission')
            ORDER BY created_at DESC LIMIT 1
        """, (session_id,)) as cursor:
            row = await cursor.fetchone()
            return self._task_from_row(row) if row else None

    async def list_all_active_tasks(self) -> list[TaskRecord]:
        async with self.db.conn.execute("""
            SELECT task_id, session_id, telegram_user_id, telegram_chat_id, ack_message_id, state, prompt, response_text, created_at, updated_at
            FROM tasks
            WHERE state IN ('queued', 'running', 'awaiting_permission')
            ORDER BY updated_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [self._task_from_row(r) for r in rows]

    # -- pinned status -----------------------------------------------------
    async def save_pinned_status(self, chat_id: int, message_id: int):
        async with self.db.conn.execute("""
            INSERT INTO pinned_status (chat_id, message_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                message_id = excluded.message_id,
                updated_at = CURRENT_TIMESTAMP
        """, (chat_id, message_id)):
            await self.db.conn.commit()

    async def get_pinned_status(self, chat_id: int) -> PinnedStatus | None:
        async with self.db.conn.execute(
            "SELECT chat_id, message_id FROM pinned_status WHERE chat_id = ?",
            (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return PinnedStatus(chat_id=row["chat_id"], message_id=row["message_id"]) if row else None

    async def delete_pinned_status(self, chat_id: int):
        async with self.db.conn.execute(
            "DELETE FROM pinned_status WHERE chat_id = ?", (chat_id,)
        ):
            await self.db.conn.commit()

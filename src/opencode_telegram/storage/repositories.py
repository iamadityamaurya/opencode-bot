import aiosqlite
from dataclasses import dataclass
from typing import Any
from opencode_telegram.storage.database import Database

@dataclass
class UserState:
    telegram_user_id: int
    selected_project: str | None = None
    selected_session_id: str | None = None

@dataclass
class TaskRecord:
    task_id: str
    session_id: str
    telegram_user_id: int
    state: str
    prompt: str
    response_text: str = ""
    created_at: str | None = None
    updated_at: str | None = None

class Repository:
    def __init__(self, db: Database):
        self.db = db

    async def get_user_state(self, user_id: int) -> UserState | None:
        async with self.db.conn.execute(
            "SELECT telegram_user_id, selected_project, selected_session_id FROM user_states WHERE telegram_user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return UserState(
                    telegram_user_id=row["telegram_user_id"],
                    selected_project=row["selected_project"],
                    selected_session_id=row["selected_session_id"],
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

    async def create_task(self, task_id: str, session_id: str, user_id: int, prompt: str) -> TaskRecord:
        async with self.db.conn.execute("""
            INSERT INTO tasks (task_id, session_id, telegram_user_id, state, prompt)
            VALUES (?, ?, ?, 'queued', ?)
        """, (task_id, session_id, user_id, prompt)):
            await self.db.conn.commit()

        return TaskRecord(
            task_id=task_id,
            session_id=session_id,
            telegram_user_id=user_id,
            state="queued",
            prompt=prompt
        )

    async def update_task_state(self, task_id: str, state: str, response_text: str = ""):
        async with self.db.conn.execute("""
            UPDATE tasks
            SET state = ?, response_text = CASE WHEN ? != '' THEN ? ELSE response_text END, updated_at = CURRENT_TIMESTAMP
            WHERE task_id = ?
        """, (state, response_text, response_text, task_id)):
            await self.db.conn.commit()

    async def get_active_task_for_session(self, session_id: str) -> TaskRecord | None:
        async with self.db.conn.execute("""
            SELECT task_id, session_id, telegram_user_id, state, prompt, response_text, created_at, updated_at
            FROM tasks
            WHERE session_id = ? AND state IN ('queued', 'running', 'awaiting_permission')
            ORDER BY created_at DESC LIMIT 1
        """, (session_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return TaskRecord(
                    task_id=row["task_id"],
                    session_id=row["session_id"],
                    telegram_user_id=row["telegram_user_id"],
                    state=row["state"],
                    prompt=row["prompt"],
                    response_text=row["response_text"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return None

    async def list_all_active_tasks(self) -> list[TaskRecord]:
        async with self.db.conn.execute("""
            SELECT task_id, session_id, telegram_user_id, state, prompt, response_text, created_at, updated_at
            FROM tasks
            WHERE state IN ('queued', 'running', 'awaiting_permission')
            ORDER BY updated_at DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [
                TaskRecord(
                    task_id=r["task_id"],
                    session_id=r["session_id"],
                    telegram_user_id=r["telegram_user_id"],
                    state=r["state"],
                    prompt=r["prompt"],
                    response_text=r["response_text"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in rows
            ]

import logging
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.opencode.models import SessionInfo
from opencode_telegram.storage.repositories import Repository

logger = logging.getLogger(__name__)

class SessionService:
    def __init__(self, client: OpenCodeClient, repo: Repository):
        self.client = client
        self.repo = repo

    async def create_session_for_user(
        self,
        user_id: int,
        project_name: str,
        title: str | None = None,
        directory: str | None = None
    ) -> SessionInfo:
        session = await self.client.create_session(title=title or f"Telegram session ({project_name})")
        if directory:
            await self.client.move_session_directory(session.id, directory)
            session.directory = directory

        await self.repo.save_session(
            session_id=session.id,
            project_name=project_name,
            user_id=user_id,
            title=title or f"Telegram session ({project_name})"
        )
        await self.repo.set_user_session(user_id, session.id)
        return session

    async def get_active_session_for_user(self, user_id: int) -> str | None:
        state = await self.repo.get_user_state(user_id)
        return state.selected_session_id if state else None

    async def list_user_sessions(self, user_id: int, project_name: str | None = None) -> list[dict]:
        return await self.repo.list_user_sessions(user_id, project_name=project_name)

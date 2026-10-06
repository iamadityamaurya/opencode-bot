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
        # V2 is location-scoped: bind the project directory when creating the
        # session so it never defaults to the server's working directory.
        session = await self.client.create_session(
            title=title or f"Telegram session ({project_name})",
            directory=directory,
        )

        await self.repo.save_session(
            session_id=session.id,
            project_name=project_name,
            user_id=user_id,
            title=title or f"Telegram session ({project_name})"
        )
        await self.repo.set_user_session(user_id, session.id)
        return session

    async def list_user_sessions(self, user_id: int, project_name: str | None = None) -> list[dict]:
        return await self.repo.list_user_sessions(user_id, project_name=project_name)

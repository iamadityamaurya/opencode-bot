import logging
import httpx
from typing import Any
from opencode_telegram.opencode.errors import (
    OpenCodeError,
    OpenCodeConnectionError,
    OpenCodeAuthError,
    OpenCodeResponseError,
    OpenCodeSessionNotFoundError,
)
from opencode_telegram.opencode.models import SessionInfo, SessionMessage

logger = logging.getLogger(__name__)

class OpenCodeClient:
    def __init__(self, base_url: str, password: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.timeout = timeout
        auth = ("opencode", password) if password else None
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=auth,
            timeout=httpx.Timeout(timeout),
            headers={"Accept": "application/json"}
        )

    async def close(self):
        await self.client.aclose()

    async def check_health(self) -> bool:
        try:
            resp = await self.client.get("/api/global/health")
            if resp.status_code == 200:
                return True
            resp = await self.client.get("/global/health")
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning(f"Health check failed: {e}")
            return False

    async def get_projects(self) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get("/api/project")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Invalid OpenCode password / unauthorized")
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except httpx.HTTPError as e:
            raise OpenCodeConnectionError(f"Failed to fetch projects: {e}") from e

    async def create_session(self, title: str | None = None) -> SessionInfo:
        payload = {}
        if title:
            payload["title"] = title
        try:
            resp = await self.client.post("/api/session", json=payload)
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized session creation")
            resp.raise_for_status()
            res_json = resp.json()
            session_data = res_json.get("data", res_json)
            return SessionInfo.from_dict(session_data)
        except httpx.HTTPError as e:
            raise OpenCodeResponseError(getattr(e.response, "status_code", 500), str(e)) from e

    async def list_sessions(self) -> list[SessionInfo]:
        try:
            resp = await self.client.get("/api/session")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized session listing")
            resp.raise_for_status()
            res_json = resp.json()
            items = res_json if isinstance(res_json, list) else res_json.get("data", [])
            return [SessionInfo.from_dict(item) for item in items if isinstance(item, dict)]
        except httpx.HTTPError as e:
            raise OpenCodeConnectionError(f"Failed to list sessions: {e}") from e

    async def get_session(self, session_id: str) -> SessionInfo:
        try:
            resp = await self.client.get(f"/api/session/{session_id}")
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            resp.raise_for_status()
            res_json = resp.json()
            session_data = res_json.get("data", res_json)
            return SessionInfo.from_dict(session_data)
        except httpx.HTTPError as e:
            raise OpenCodeResponseError(getattr(e.response, "status_code", 500), str(e)) from e

    async def send_prompt(self, session_id: str, prompt_text: str) -> dict[str, Any]:
        """Submit a prompt to OpenCode asynchronously or synchronously."""
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/prompt",
                json={"text": prompt_text}
            )
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            raise OpenCodeResponseError(getattr(e.response, "status_code", 500), str(e)) from e

    async def get_messages(self, session_id: str) -> list[SessionMessage]:
        try:
            resp = await self.client.get(f"/api/session/{session_id}/message")
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            resp.raise_for_status()
            res_json = resp.json()
            items = res_json.get("data", []) if isinstance(res_json, dict) else res_json
            return [SessionMessage.from_dict(item, default_session_id=session_id) for item in items if isinstance(item, dict)]
        except httpx.HTTPError as e:
            raise OpenCodeResponseError(getattr(e.response, "status_code", 500), str(e)) from e

    async def interrupt_session(self, session_id: str) -> bool:
        """Interrupt / abort the current task in session."""
        try:
            resp = await self.client.post(f"/api/session/{session_id}/interrupt")
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to interrupt session {session_id}: {e}")
            return False

    async def get_diff(self, session_id: str) -> list[dict[str, Any]]:
        """Get file changes for a session."""
        try:
            resp = await self.client.get(f"/api/session/{session_id}/diff")
            if resp.status_code != 200:
                return []
            res_json = resp.json()
            return res_json.get("data", []) if isinstance(res_json, dict) else res_json
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch diff for session {session_id}: {e}")
            return []

    async def set_session_agent(self, session_id: str, agent_name: str) -> bool:
        """Switch agent mode (e.g. 'build' or 'plan') for a session."""
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/agent",
                json={"agent": agent_name}
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to set agent to {agent_name} for session {session_id}: {e}")
            return False

    async def move_session_directory(self, session_id: str, directory_path: str) -> bool:
        """Change working directory for a session."""
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/move",
                json={"directory": directory_path}
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to move session {session_id} to {directory_path}: {e}")
            return False



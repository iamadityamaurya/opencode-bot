import logging
from typing import Any

import httpx

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
    """Async client for the OpenCode V2 HTTP API (``/api/*``).

    OpenCode V2 exposes its API from the shared background service under the
    ``/api`` prefix and requires authentication. When ``OPENCODE_SERVER_PASSWORD``
    is configured the server uses HTTP basic auth (username defaults to
    ``opencode``, override with ``OPENCODE_SERVER_USERNAME``).

    See https://opencode.ai/v2/docs/api/ for the authoritative contract.
    """

    def __init__(
        self,
        base_url: str,
        password: str = "",
        username: str = "opencode",
        timeout: float = 30.0,
        connect_timeout: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.username = username or "opencode"
        self.timeout = timeout
        auth = (self.username, password) if password else None
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            auth=auth,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            headers={"Accept": "application/json"},
        )

    async def close(self):
        await self.client.aclose()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _data(payload: Any) -> Any:
        """Unwrap the V2 ``{"data": ...}`` envelope when present."""
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    @staticmethod
    def _as_list(payload: Any) -> list:
        data = OpenCodeClient._data(payload)
        return data if isinstance(data, list) else []

    def _error_from_http(self, exc: httpx.HTTPError) -> OpenCodeError:
        response = getattr(exc, "response", None)
        status = response.status_code if response is not None else 0
        if status == 401:
            return OpenCodeAuthError("Invalid OpenCode server password / unauthorized")
        if isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout | httpx.ReadTimeout):
            return OpenCodeConnectionError(f"OpenCode server unreachable: {exc}")
        return OpenCodeResponseError(status or 500, str(exc))

    # -- server ------------------------------------------------------------
    async def get_server_info(self) -> dict[str, Any] | None:
        """Return ``GET /api/info`` payload, or ``None`` when unreachable.

        Raises :class:`OpenCodeAuthError` when the server rejects credentials.
        """
        try:
            resp = await self.client.get("/api/info")
        except httpx.HTTPError as e:
            logger.warning(f"OpenCode health check failed: {e}")
            return None

        if resp.status_code == 401:
            raise OpenCodeAuthError("Invalid OpenCode server password / unauthorized")
        if resp.status_code != 200:
            logger.warning(f"OpenCode health check returned HTTP {resp.status_code}")
            return None

        try:
            info = resp.json()
        except ValueError:
            logger.warning("OpenCode health check returned non-JSON payload")
            return None

        if isinstance(info, dict) and "version" in info:
            return info
        return None

    async def check_health(self) -> bool:
        try:
            return await self.get_server_info() is not None
        except OpenCodeAuthError:
            logger.warning("OpenCode server rejected credentials during health check")
            return False

    # -- projects ----------------------------------------------------------
    async def get_projects(self) -> list[dict[str, Any]]:
        try:
            resp = await self.client.get("/api/project")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Invalid OpenCode server password / unauthorized")
            resp.raise_for_status()
            return self._as_list(resp.json())
        except httpx.HTTPError as e:
            raise OpenCodeConnectionError(f"Failed to fetch projects: {e}") from e

    # -- sessions ----------------------------------------------------------
    async def create_session(
        self,
        title: str | None = None,
        directory: str | None = None,
        agent: str | None = None,
    ) -> SessionInfo:
        """Create a session, optionally bound to a project directory (location)."""
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = title
        if agent:
            payload["agent"] = agent
        # V2 is location-scoped: the session runs inside this directory.
        if directory:
            payload["location"] = {"directory": str(directory)}

        try:
            resp = await self.client.post("/api/session", json=payload)
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized session creation")
            resp.raise_for_status()
            data = self._data(resp.json())
            return SessionInfo.from_dict(data if isinstance(data, dict) else {})
        except httpx.HTTPError as e:
            raise self._error_from_http(e) from e

    async def list_sessions(
        self,
        directory: str | None = None,
        limit: int | None = None,
    ) -> list[SessionInfo]:
        params: dict[str, Any] = {}
        if directory:
            params["directory"] = str(directory)
        if limit:
            params["limit"] = int(limit)
        try:
            resp = await self.client.get("/api/session", params=params)
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized session listing")
            resp.raise_for_status()
            return [SessionInfo.from_dict(item) for item in self._as_list(resp.json())]
        except httpx.HTTPError as e:
            raise self._error_from_http(e) from e

    async def get_session(self, session_id: str) -> SessionInfo:
        try:
            resp = await self.client.get(f"/api/session/{session_id}")
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized session lookup")
            resp.raise_for_status()
            data = self._data(resp.json())
            return SessionInfo.from_dict(data if isinstance(data, dict) else {})
        except httpx.HTTPError as e:
            raise self._error_from_http(e) from e

    async def send_prompt(
        self,
        session_id: str,
        prompt_text: str,
        delivery: str | None = None,
    ) -> dict[str, Any]:
        """Enqueue a prompt for a session and return the accepted inbox item.

        V2's ``POST /api/session/{id}/prompt`` accepts the message and returns
        immediately; completion is observed through messages or the event stream.
        """
        payload: dict[str, Any] = {"text": prompt_text}
        if delivery:
            payload["delivery"] = delivery
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/prompt",
                json=payload,
            )
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized prompt submission")
            if resp.status_code == 409:
                raise OpenCodeResponseError(409, f"Session {session_id} is busy")
            resp.raise_for_status()
            data = self._data(resp.json())
            return data if isinstance(data, dict) else {}
        except httpx.HTTPError as e:
            raise self._error_from_http(e) from e

    async def get_messages(
        self,
        session_id: str,
        order: str = "desc",
        limit: int | None = 30,
    ) -> list[SessionMessage]:
        params: dict[str, Any] = {"order": order}
        if limit is not None:
            params["limit"] = str(limit)
        try:
            resp = await self.client.get(
                f"/api/session/{session_id}/message",
                params=params,
            )
            if resp.status_code == 404:
                raise OpenCodeSessionNotFoundError(f"Session {session_id} not found")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized message listing")
            resp.raise_for_status()
            return [
                SessionMessage.from_dict(item, default_session_id=session_id)
                for item in self._as_list(resp.json())
                if isinstance(item, dict)
            ]
        except httpx.HTTPError as e:
            raise self._error_from_http(e) from e

    async def interrupt_session(self, session_id: str) -> bool:
        """Request cancellation of the active execution in a session."""
        try:
            resp = await self.client.post(f"/api/session/{session_id}/interrupt")
            if resp.status_code == 401:
                raise OpenCodeAuthError("Unauthorized interrupt")
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
            return self._as_list(resp.json())
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch diff for session {session_id}: {e}")
            return []

    async def set_session_agent(self, session_id: str, agent_name: str) -> bool:
        """Switch agent mode (e.g. 'build' or 'plan') for a session."""
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/agent",
                json={"agent": agent_name},
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to set agent to {agent_name} for session {session_id}: {e}")
            return False

    async def get_models(self, directory: str | None = None) -> list[dict[str, Any]]:
        """Fetch available LLM models from the OpenCode server."""
        params: dict[str, Any] = {}
        if directory:
            params["location"] = str(directory)
        try:
            resp = await self.client.get("/api/model", params=params)
            if resp.status_code != 200:
                return []
            return self._as_list(resp.json())
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch models: {e}")
            return []

    async def set_session_model(
        self,
        session_id: str,
        model_id: str,
        provider_id: str,
        variant: str | None = None,
    ) -> bool:
        """Set or switch the AI model for a session.

        V2 expects a ``Model.Ref`` object: ``{"model": {"id", "providerID"}}``.
        """
        if not provider_id:
            logger.error("Cannot set model without a provider ID")
            return False
        model_ref: dict[str, Any] = {"id": model_id, "providerID": provider_id}
        if variant:
            model_ref["variant"] = variant
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/model",
                json={"model": model_ref},
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to set model {provider_id}/{model_id} for session {session_id}: {e}")
            return False

    async def respond_to_permission(
        self,
        session_id: str,
        permission_id: str,
        approved: bool,
        remember: bool = False,
    ) -> bool:
        """Reply to an OpenCode permission request.

        V2 uses ``POST /api/session/{id}/permission/{requestID}/reply`` with a
        ``decision`` of ``once``, ``always`` or ``reject``.
        """
        if approved:
            decision = "always" if remember else "once"
        else:
            decision = "reject"
        try:
            resp = await self.client.post(
                f"/api/session/{session_id}/permission/{permission_id}/reply",
                json={"decision": decision},
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to reply to permission {permission_id}: {e}")
            return False

    async def rename_session(self, session_id: str, title: str) -> bool:
        """Rename a session title on the OpenCode server."""
        try:
            resp = await self.client.patch(
                f"/api/session/{session_id}",
                json={"title": title},
            )
            return resp.status_code in (200, 204)
        except httpx.HTTPError as e:
            logger.error(f"Failed to rename session {session_id}: {e}")
            return False

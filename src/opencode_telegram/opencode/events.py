import asyncio
import json
import logging
from typing import Awaitable, Callable

import httpx

from opencode_telegram.opencode.models import ServerEvent

logger = logging.getLogger(__name__)


class SSEEventListener:
    """Resilient listener for the OpenCode V2 ``GET /api/event`` SSE stream."""

    def __init__(self, base_url: str, password: str = "", username: str = "opencode"):
        self.base_url = base_url.rstrip("/")
        self.password = password
        self.username = username or "opencode"
        self._running = False
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[ServerEvent], Awaitable[None]]] = []

    def add_callback(self, callback: Callable[[ServerEvent], Awaitable[None]]):
        self._callbacks.append(callback)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self):
        auth = (self.username, self.password) if self.password else None
        backoff = 1.0
        while self._running:
            try:
                async with httpx.AsyncClient(
                    auth=auth, timeout=httpx.Timeout(60.0, connect=5.0)
                ) as client:
                    async with client.stream("GET", f"{self.base_url}/api/event") as response:
                        if response.status_code != 200:
                            logger.warning(
                                f"SSE connection failed with status {response.status_code}"
                            )
                            await asyncio.sleep(backoff)
                            backoff = min(backoff * 2, 30.0)
                            continue

                        backoff = 1.0  # Reset backoff on successful connect
                        logger.info("Connected to OpenCode SSE stream")

                        data_lines: list[str] = []
                        async for line in response.aiter_lines():
                            if not self._running:
                                break
                            if line == "":
                                if data_lines:
                                    await self._process_frame("\n".join(data_lines))
                                    data_lines = []
                            elif line.startswith(":"):
                                continue  # comment / heartbeat
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].lstrip())

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"SSE stream disconnected: {e}. Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _process_frame(self, data_str: str):
        try:
            payload = json.loads(data_str)
            event = ServerEvent.from_dict(payload)
            for cb in self._callbacks:
                try:
                    await cb(event)
                except Exception as err:
                    logger.error(f"Error in SSE callback: {err}", exc_info=True)
        except Exception as e:
            logger.debug(f"Failed to parse SSE payload '{data_str[:50]}': {e}")

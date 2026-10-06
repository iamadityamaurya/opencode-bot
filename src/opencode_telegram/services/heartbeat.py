import asyncio
import logging

from opencode_telegram.config import Config
from opencode_telegram.opencode.models import ServerEvent
from opencode_telegram.opencode.router import (
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    SESSION_EXECUTION_STARTED,
    SESSION_IDLE,
    SESSION_USAGE_UPDATED,
    EventRouter,
)
from opencode_telegram.storage.repositories import Repository

logger = logging.getLogger(__name__)

_TERMINAL_EVENTS = {
    SESSION_IDLE,
    "session.execution.succeeded",
    "session.execution.failed",
    "session.execution.interrupted",
}


class HeartbeatService:
    """Keeps one pinned "current status" message up to date per chat.

    Tracks which sessions are active and how much they have cost from the SSE
    stream, then periodically edits a pinned message. Disabled when
    ``heartbeat_interval_seconds`` is 0.
    """

    def __init__(
        self,
        repo: Repository,
        router: EventRouter,
        config: Config,
    ):
        self.repo = repo
        self.router = router
        self.config = config
        self._bot = None
        self._active_sessions: set[str] = set()
        self._awaiting_permission: set[str] = set()
        self._session_cost: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    def bind(self, bot):
        self._bot = bot

    async def handle_event(self, event: ServerEvent):
        session_id = event.session_id
        if not session_id:
            return
        if event.event_type == SESSION_EXECUTION_STARTED:
            self._active_sessions.add(session_id)
        elif event.event_type in _TERMINAL_EVENTS:
            self._active_sessions.discard(session_id)
            self._awaiting_permission.discard(session_id)
        elif event.event_type == PERMISSION_ASKED:
            self._awaiting_permission.add(session_id)
        elif event.event_type == PERMISSION_REPLIED:
            self._awaiting_permission.discard(session_id)
        elif event.event_type == SESSION_USAGE_UPDATED:
            cost = event.data.get("cost")
            if isinstance(cost, (int, float)):
                self._session_cost[session_id] = float(cost)

    def _compose(self) -> str:
        active = len(self._active_sessions)
        waiting = len(self._awaiting_permission)
        total_cost = sum(self._session_cost.values())
        lines = ["📡 OpenCode Status"]
        lines.append(f"• Active sessions: {active}")
        if waiting:
            lines.append(f"• Awaiting permission: {waiting}")
        lines.append(f"• Session cost: ${total_cost:.4f}")
        if active == 0:
            lines.append("• State: idle 💤")
        return "\n".join(lines)

    async def _update_chat(self, chat_id: int):
        text = self._compose()
        pinned = await self.repo.get_pinned_status(chat_id)
        if pinned is None:
            try:
                message = await self._bot.send_message(chat_id=chat_id, text=text)
                await self._bot.pin_chat_message(
                    chat_id=chat_id, message_id=message.message_id, disable_notification=True
                )
                await self.repo.save_pinned_status(chat_id, message.message_id)
            except Exception as err:
                logger.warning(f"Heartbeat could not send/pin status for chat {chat_id}: {err}")
            return
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id, message_id=pinned.message_id, text=text
            )
        except Exception as err:
            # "not modified" just means the status has not changed; anything else
            # (deleted message, lost pin) means we should repin on the next tick.
            if "not modified" in str(err).lower():
                return
            logger.debug(f"Heartbeat edit failed for chat {chat_id}: {err}")
            await self.repo.delete_pinned_status(chat_id)

    async def run(self):
        interval = float(self.config.heartbeat_interval_seconds)
        if interval <= 0:
            logger.info("Heartbeat disabled (heartbeat_interval_seconds=0)")
            return
        logger.info(f"Heartbeat started (every {interval:.0f}s)")
        while True:
            await asyncio.sleep(interval)
            if self._bot is None:
                continue
            try:
                for chat_id in await self.repo.list_chat_ids():
                    await self._update_chat(chat_id)
            except Exception as err:
                logger.error(f"Heartbeat tick failed: {err}", exc_info=True)

    def start(self):
        if self.config.heartbeat_interval_seconds <= 0:
            return None
        self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

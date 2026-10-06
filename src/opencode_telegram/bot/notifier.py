import logging
import time

from opencode_telegram.bot.callbacks import CallbackRegistry
from opencode_telegram.bot.keyboards import get_permission_keyboard
from opencode_telegram.config import Config
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.opencode.models import ServerEvent
from opencode_telegram.opencode.router import (
    COMPLETION_EVENTS,
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    SESSION_EXECUTION_FAILED,
    SESSION_EXECUTION_INTERRUPTED,
    SESSION_EXECUTION_STARTED,
    SESSION_IDLE,
    SESSION_STEP_STARTED,
    SESSION_TOOL_INPUT_STARTED,
    EventRouter,
)
from opencode_telegram.storage.repositories import Repository

try:  # PTB >= 20.8
    from telegram import ReactionTypeEmoji
except ImportError:  # pragma: no cover - older PTB
    ReactionTypeEmoji = None

logger = logging.getLogger(__name__)

_REACTION_STARTED = "👀"
_REACTION_SUCCEEDED = "✅"
_REACTION_FAILED = "❌"
_REACTION_INTERRUPTED = "🛑"


class TelegramNotifier:
    """Turns OpenCode events into Telegram side effects.

    Owns the long-lived bot handle so it can act on events that arrive with no
    active update: reactions on a task's acknowledgement message, live progress
    edits, and permission prompts. Handlers call :meth:`register_task_message`
    when a task starts so the notifier knows which message belongs to a session.
    """

    def __init__(
        self,
        client: OpenCodeClient,
        repo: Repository,
        router: EventRouter,
        callbacks: CallbackRegistry,
        config: Config,
    ):
        self.client = client
        self.repo = repo
        self.router = router
        self.callbacks = callbacks
        self.config = config
        self._bot = None
        # session_id -> (chat_id, ack_message_id)
        self._task_messages: dict[str, tuple[int, int]] = {}
        self._last_progress_edit: dict[str, float] = {}
        # permission_id -> (chat_id, message_id)
        self._permission_messages: dict[str, tuple[int, int]] = {}
        self._last_reaction: dict[int, str] = {}

    def bind(self, bot):
        self._bot = bot

    # -- registration from handlers ---------------------------------------
    def register_task_message(self, session_id: str, chat_id: int, message_id: int):
        self._task_messages[session_id] = (chat_id, message_id)
        self._last_progress_edit.pop(session_id, None)
        self._last_reaction.pop(message_id, None)

    def clear_task_message(self, session_id: str):
        self._task_messages.pop(session_id, None)
        self._last_progress_edit.pop(session_id, None)

    # -- event entrypoint --------------------------------------------------
    async def handle_event(self, event: ServerEvent):
        if self._bot is None:
            return
        try:
            if event.event_type == SESSION_EXECUTION_STARTED:
                await self._on_started(event)
            elif event.event_type in (SESSION_STEP_STARTED, SESSION_TOOL_INPUT_STARTED):
                await self._on_progress(event)
            elif event.event_type in COMPLETION_EVENTS:
                await self._on_finished(event)
            elif event.event_type == PERMISSION_ASKED:
                await self._on_permission_asked(event)
            elif event.event_type == PERMISSION_REPLIED:
                await self._on_permission_replied(event)
        except Exception as err:
            logger.error(f"Notifier failed handling {event.event_type}: {err}", exc_info=True)

    # -- handlers ----------------------------------------------------------
    async def _on_started(self, event: ServerEvent):
        target = self._task_messages.get(event.session_id or "")
        if target:
            await self._react(target[0], target[1], _REACTION_STARTED)

    async def _on_progress(self, event: ServerEvent):
        session_id = event.session_id or ""
        target = self._task_messages.get(session_id)
        if not target:
            return

        now = time.monotonic()
        last = self._last_progress_edit.get(session_id, 0.0)
        if now - last < float(self.config.progress_edit_interval_seconds):
            return
        self._last_progress_edit[session_id] = now

        if event.event_type == SESSION_TOOL_INPUT_STARTED:
            detail = event.data.get("name") or "tool"
            text = f"⚙️ Working… running `{detail}`"
        else:
            agent = event.data.get("agent") or "agent"
            model = event.data.get("model") or {}
            model_id = model.get("id") if isinstance(model, dict) else None
            text = f"⚙️ Working… {agent}" + (f" · {model_id}" if model_id else "")

        await self._edit(target[0], target[1], text)

    async def _on_finished(self, event: ServerEvent):
        session_id = event.session_id or ""
        target = self._task_messages.get(session_id)
        if not target:
            return

        if event.event_type == SESSION_EXECUTION_FAILED:
            emoji = _REACTION_FAILED
        elif event.event_type == SESSION_EXECUTION_INTERRUPTED:
            emoji = _REACTION_INTERRUPTED
        else:
            # session.idle / session.execution.succeeded
            emoji = _REACTION_SUCCEEDED

        await self._react(target[0], target[1], emoji)
        # Keep the mapping until the TaskService completion callback clears it,
        # so a trailing idle does not lose the message. Idle is terminal here.
        if event.event_type != SESSION_IDLE:
            self.clear_task_message(session_id)

    async def _on_permission_asked(self, event: ServerEvent):
        session_id = event.session_id or ""
        permission_id = event.data.get("id")
        if not permission_id:
            return

        chat_id = await self._resolve_chat(session_id)
        if chat_id is None:
            logger.warning(f"No chat found for permission request in session {session_id}")
            return

        action = event.data.get("action") or "unknown action"
        resources = event.data.get("resources") or []
        lines = ["🛡️ Permission Required", f"Action: {action}"]
        for res in resources[:5]:
            lines.append(f"• {res}")
        if event.data.get("message"):
            lines.append(str(event.data["message"]))
        lines.append(f"Session: {session_id[:12]}…")

        token = self.callbacks.add(
            "permission",
            {"session_id": session_id, "permission_id": permission_id},
        )
        keyboard = get_permission_keyboard(token)
        message = await self._send(chat_id, "\n".join(lines), keyboard)
        if message is not None:
            self._permission_messages[permission_id] = (chat_id, message.message_id)

    async def _on_permission_replied(self, event: ServerEvent):
        request_id = event.data.get("requestID")
        target = self._permission_messages.pop(request_id, None) if request_id else None
        if not target:
            return
        reply = event.data.get("reply")
        decision = reply.get("decision") if isinstance(reply, dict) else reply
        await self._edit(target[0], target[1], f"🛡️ Permission resolved ({decision}).")

    # -- low level helpers -------------------------------------------------
    async def _resolve_chat(self, session_id: str) -> int | None:
        target = self._task_messages.get(session_id)
        if target:
            return target[0]
        chat_id = await self.repo.get_chat_id_for_session(session_id)
        if chat_id is not None:
            return chat_id
        chats = await self.repo.list_chat_ids()
        return chats[0] if chats else None

    async def _react(self, chat_id: int, message_id: int, emoji: str):
        if ReactionTypeEmoji is None or not self.config.enable_reactions:
            return
        if self._last_reaction.get(message_id) == emoji:
            return
        try:
            await self._bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            self._last_reaction[message_id] = emoji
        except Exception as err:
            logger.debug(f"Failed to set reaction {emoji}: {err}")

    async def _edit(self, chat_id: int, message_id: int, text: str):
        try:
            await self._bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception as err:
            logger.debug(f"Failed to edit progress message: {err}")

    async def _send(self, chat_id: int, text: str, keyboard=None):
        try:
            return await self._bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
        except Exception as err:
            logger.error(f"Failed to send permission prompt: {err}")
            return None

import asyncio
import logging
from typing import Awaitable, Callable, Iterable

from opencode_telegram.opencode.models import ServerEvent

logger = logging.getLogger(__name__)

# Event type constants for the OpenCode V2 SSE stream. These are the raw
# ``type`` strings emitted on ``GET /api/event``.
SESSION_IDLE = "session.idle"
SESSION_EXECUTION_STARTED = "session.execution.started"
SESSION_EXECUTION_SUCCEEDED = "session.execution.succeeded"
SESSION_EXECUTION_FAILED = "session.execution.failed"
SESSION_EXECUTION_INTERRUPTED = "session.execution.interrupted"
SESSION_STEP_STARTED = "session.step.started"
SESSION_TOOL_INPUT_STARTED = "session.tool.input.started"
SESSION_USAGE_UPDATED = "session.usage.updated"
PERMISSION_ASKED = "permission.asked"
PERMISSION_REPLIED = "permission.replied"

# Events that (taken together) mean a turn is over.
COMPLETION_EVENTS = frozenset(
    {
        SESSION_IDLE,
        SESSION_EXECUTION_SUCCEEDED,
        SESSION_EXECUTION_FAILED,
        SESSION_EXECUTION_INTERRUPTED,
    }
)

EventCallback = Callable[[ServerEvent], Awaitable[None]]


class EventRouter:
    """Single fan-out point for the OpenCode SSE stream.

    ``SSEEventListener`` hands every parsed :class:`ServerEvent` to
    :meth:`handle`. Subscribers get every event; callers can also block on a
    specific session/type with :meth:`wait_for`, which is what makes task
    completion event-driven instead of poll-driven.

    The stream is live-only (no replay), so ``wait_for`` must never be treated
    as the source of truth — it only wakes up the caller early. Always re-read
    authoritative state over HTTP afterwards.
    """

    def __init__(self):
        self._subscribers: list[EventCallback] = []
        self._waiters: list[tuple[str | None, frozenset[str] | None, asyncio.Future]] = []

    def subscribe(self, callback: EventCallback):
        """Register a callback invoked for every event (errors are swallowed)."""
        self._subscribers.append(callback)

    async def handle(self, event: ServerEvent):
        # Wake any matching waiter first so latency stays minimal.
        for session_id, types, future in list(self._waiters):
            if future.done():
                continue
            if session_id and event.session_id != session_id:
                continue
            if types and event.event_type not in types:
                continue
            future.set_result(event)

        for callback in list(self._subscribers):
            try:
                await callback(event)
            except Exception as err:  # never let one subscriber kill the stream
                logger.error(f"Error in event subscriber: {err}", exc_info=True)

    async def wait_for(
        self,
        session_id: str | None,
        types: Iterable[str] | None,
        timeout: float,
    ) -> ServerEvent | None:
        """Wait for a matching event, returning ``None`` on timeout."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        entry = (session_id, frozenset(types) if types else None, future)
        self._waiters.append(entry)
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            try:
                self._waiters.remove(entry)
            except ValueError:
                pass

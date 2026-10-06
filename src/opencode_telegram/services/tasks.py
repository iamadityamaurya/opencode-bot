import asyncio
import logging
import time
import uuid
from typing import Awaitable, Callable

from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.opencode.models import SessionMessage
from opencode_telegram.opencode.router import COMPLETION_EVENTS, EventRouter
from opencode_telegram.storage.repositories import Repository, TaskRecord

logger = logging.getLogger(__name__)


def _message_time_ms(message: SessionMessage) -> int | None:
    """Return a message's creation time in epoch milliseconds, if present."""
    created = message.created_at
    if created is None:
        return None
    return int(created)


def evaluate_completion(
    messages: list[SessionMessage],
    baseline_ms: int | None,
) -> tuple[bool, str | None, str]:
    """Decide whether a session turn has finished.

    ``messages`` must be newest-first. Only messages created at or after
    ``baseline_ms`` (the accepted prompt) are considered, so an idle message
    from a previous turn is never mistaken for the current one.

    Returns ``(done, outcome, response_text)`` where ``outcome`` is the idle
    message's outcome (``succeeded``/``failed``/``interrupted``) when done.
    """
    fresh = [
        m for m in messages
        if baseline_ms is None
        or _message_time_ms(m) is None
        or _message_time_ms(m) >= baseline_ms
    ]

    idle = next((m for m in fresh if m.msg_type == "idle"), None)
    if idle is None:
        return (False, None, "")

    # Pick the latest assistant text produced during this turn.
    response_text = ""
    for m in sorted(
        (m for m in fresh if m.msg_type == "assistant" and m.text and m.text.strip()),
        key=lambda m: _message_time_ms(m) or 0,
        reverse=True,
    ):
        response_text = m.text
        break

    return (True, idle.outcome or "succeeded", response_text)


def _baseline_from_inbox(inbox: dict) -> int | None:
    """Extract the accepted user message's creation time from a prompt response."""
    if not isinstance(inbox, dict):
        return None
    time_info = inbox.get("time")
    if isinstance(time_info, dict) and isinstance(time_info.get("created"), (int, float)):
        return int(time_info["created"])
    return None


class TaskService:
    def __init__(
        self,
        client: OpenCodeClient,
        repo: Repository,
        poll_interval_seconds: float = 5.0,
        task_timeout_seconds: float = 600.0,
        router: EventRouter | None = None,
    ):
        self.client = client
        self.repo = repo
        self.poll_interval_seconds = poll_interval_seconds
        self.task_timeout_seconds = task_timeout_seconds
        self.router = router
        self._session_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    async def submit_task(
        self,
        user_id: int,
        session_id: str,
        prompt: str,
        on_completion: Callable[[TaskRecord], Awaitable[None]] | None = None,
        chat_id: int | None = None,
        ack_message_id: int | None = None,
    ) -> TaskRecord:
        # Check if there is already a running task
        active_task = await self.repo.get_active_task_for_session(session_id)
        if active_task:
            raise RuntimeError(
                f"Task {active_task.task_id} is already running for session {session_id}"
            )

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        record = await self.repo.create_task(
            task_id,
            session_id,
            user_id,
            prompt,
            chat_id=chat_id,
            ack_message_id=ack_message_id,
        )

        # Launch execution in background task
        asyncio.create_task(self._run_task_worker(record, on_completion))
        return record

    async def _run_task_worker(
        self,
        task: TaskRecord,
        on_completion: Callable[[TaskRecord], Awaitable[None]] | None,
    ):
        lock = self._get_lock(task.session_id)
        async with lock:
            await self.repo.update_task_state(task.task_id, "running")
            task.state = "running"

            try:
                # V2 accepts the prompt and returns the inbox item immediately.
                inbox = await self.client.send_prompt(task.session_id, task.prompt)
                baseline_ms = _baseline_from_inbox(inbox) or int(time.time() * 1000)

                # Prefer the event stream: it wakes us the instant a turn ends.
                # We still re-read messages on every wake (and on the poll
                # fallback interval) because the stream is live-only and
                # evaluate_completion remains the source of truth.
                deadline = time.monotonic() + self.task_timeout_seconds
                completed = False
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    wait_slice = min(self.poll_interval_seconds, remaining)
                    if self.router is not None:
                        await self.router.wait_for(
                            task.session_id, COMPLETION_EVENTS, timeout=wait_slice
                        )
                    else:
                        await asyncio.sleep(wait_slice)

                    msgs = await self.client.get_messages(task.session_id, order="desc", limit=30)
                    done, outcome, response_text = evaluate_completion(msgs, baseline_ms)
                    if not done:
                        continue

                    completed = True
                    if outcome == "failed":
                        await self.repo.update_task_state(
                            task.task_id, "failed", response_text or "Task failed in OpenCode"
                        )
                        task.state = "failed"
                        task.response_text = response_text
                    elif outcome == "interrupted":
                        await self.repo.update_task_state(
                            task.task_id, "cancelled", "Task was interrupted"
                        )
                        task.state = "cancelled"
                        task.response_text = response_text
                    else:
                        await self.repo.update_task_state(
                            task.task_id, "completed", response_text or "Task completed."
                        )
                        task.state = "completed"
                        task.response_text = response_text
                    break

                if not completed:
                    await self.repo.update_task_state(
                        task.task_id, "failed", "Task timed out waiting for OpenCode"
                    )
                    task.state = "failed"

            except Exception as e:
                logger.error(f"Error running task {task.task_id}: {e}", exc_info=True)
                await self.repo.update_task_state(task.task_id, "failed", str(e))
                task.state = "failed"
                task.response_text = str(e)

            if on_completion:
                try:
                    await on_completion(task)
                except Exception as cb_err:
                    logger.error(f"Error in task completion callback: {cb_err}")

    async def cancel_task(self, session_id: str) -> bool:
        active_task = await self.repo.get_active_task_for_session(session_id)
        if not active_task:
            return False

        # Request abort from OpenCode API
        success = await self.client.interrupt_session(session_id)
        if success:
            await self.repo.update_task_state(active_task.task_id, "cancelled", "Cancelled by user")
        return success

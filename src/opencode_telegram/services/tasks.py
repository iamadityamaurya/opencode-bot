import asyncio
import logging
import uuid
from typing import Callable, Awaitable
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.storage.repositories import Repository, TaskRecord

logger = logging.getLogger(__name__)

class TaskService:
    def __init__(self, client: OpenCodeClient, repo: Repository):
        self.client = client
        self.repo = repo
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
        on_completion: Callable[[TaskRecord], Awaitable[None]] | None = None
    ) -> TaskRecord:
        # Check if there is already a running task
        active_task = await self.repo.get_active_task_for_session(session_id)
        if active_task:
            raise RuntimeError(f"Task {active_task.task_id} is already running for session {session_id}")

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        record = await self.repo.create_task(task_id, session_id, user_id, prompt)

        # Launch execution in background task
        asyncio.create_task(self._run_task_worker(record, on_completion))
        return record

    async def _run_task_worker(
        self,
        task: TaskRecord,
        on_completion: Callable[[TaskRecord], Awaitable[None]] | None
    ):
        lock = self._get_lock(task.session_id)
        async with lock:
            await self.repo.update_task_state(task.task_id, "running")
            task.state = "running"

            try:
                # Send prompt to OpenCode
                await self.client.send_prompt(task.session_id, task.prompt)

                # Poll for completion by checking message history
                completed = False
                final_response = ""
                for _ in range(120):  # Poll up to 10 minutes (120 * 5s)
                    await asyncio.sleep(5)
                    msgs = await self.client.get_messages(task.session_id)
                    if not msgs:
                        continue

                    last_msg = msgs[0]  # Most recent message is first
                    if last_msg.msg_type == "idle":
                        if last_msg.outcome == "failed":
                            await self.repo.update_task_state(task.task_id, "failed", "Task failed in OpenCode")
                            task.state = "failed"
                        else:
                            # Extract assistant response text
                            for m in msgs:
                                if m.msg_type == "assistant" and m.text:
                                    final_response = m.text
                                    break
                            await self.repo.update_task_state(task.task_id, "completed", final_response)
                            task.state = "completed"
                            task.response_text = final_response
                        completed = True
                        break

                if not completed:
                    await self.repo.update_task_state(task.task_id, "failed", "Task timed out waiting for OpenCode")
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

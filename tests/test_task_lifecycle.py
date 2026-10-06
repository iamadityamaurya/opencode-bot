import asyncio

import pytest
from opencode_telegram.opencode.models import ServerEvent, SessionMessage
from opencode_telegram.opencode.router import EventRouter
from opencode_telegram.services.tasks import TaskService, evaluate_completion
from opencode_telegram.storage.database import Database
from opencode_telegram.storage.repositories import Repository


def _msg(msg_type, created_at, text="", outcome=None):
    return SessionMessage(
        id=f"msg_{created_at}",
        session_id="ses_1",
        msg_type=msg_type,
        text=text,
        outcome=outcome,
        created_at=created_at,
    )


def test_evaluate_completion_ignores_stale_idle():
    # An idle from a previous turn (created before the prompt baseline) must not
    # be mistaken for completion of the current turn.
    messages = [_msg("idle", 1000, outcome="succeeded"), _msg("assistant", 900, text="old")]
    done, outcome, text = evaluate_completion(messages, baseline_ms=2000)
    assert done is False


def test_evaluate_completion_detects_fresh_turn():
    messages = [
        _msg("idle", 2500, outcome="succeeded"),
        _msg("assistant", 2400, text="final answer"),
        _msg("assistant", 2300, text="intermediate"),
        _msg("user", 2100, text="hi"),
    ]
    done, outcome, text = evaluate_completion(messages, baseline_ms=2000)
    assert done is True
    assert outcome == "succeeded"
    assert text == "final answer"


def test_evaluate_completion_reports_failure_and_interrupt():
    failed = evaluate_completion([_msg("idle", 3000, outcome="failed")], baseline_ms=2000)
    assert failed == (True, "failed", "")

    interrupted = evaluate_completion([_msg("idle", 3000, outcome="interrupted")], baseline_ms=2000)
    assert interrupted == (True, "interrupted", "")

@pytest.mark.asyncio
async def test_task_state_transitions(tmp_path):
    db_file = tmp_path / "test_bot.sqlite3"
    db = Database(db_file)
    await db.connect()
    repo = Repository(db)

    # Create task
    task = await repo.create_task("task_001", "ses_001", 12345, "Write hello world")
    assert task.task_id == "task_001"
    assert task.state == "queued"

    # Fetch active task
    active = await repo.get_active_task_for_session("ses_001")
    assert active is not None
    assert active.task_id == "task_001"

    # Transition to running
    await repo.update_task_state("task_001", "running")
    active = await repo.get_active_task_for_session("ses_001")
    assert active.state == "running"

    # Transition to completed
    await repo.update_task_state("task_001", "completed", "Done!")
    active = await repo.get_active_task_for_session("ses_001")
    assert active is None  # No longer active

    await db.close()


class _FakeClient:
    """Minimal stand-in that returns canned messages on demand."""

    def __init__(self):
        self.messages: list[SessionMessage] = []
        self.prompted = False

    async def send_prompt(self, session_id, prompt_text, delivery=None):
        self.prompted = True
        return {"time": {"created": 1000}}

    async def get_messages(self, session_id, order="desc", limit=30):
        return self.messages

    async def interrupt_session(self, session_id):
        return True


@pytest.mark.asyncio
async def test_task_completes_on_event_without_waiting_for_poll(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    await db.connect()
    repo = Repository(db)
    router = EventRouter()
    fake = _FakeClient()

    # Poll interval is much longer than the test: completion can only come from
    # the event stream.
    service = TaskService(
        fake,
        repo,
        poll_interval_seconds=30.0,
        task_timeout_seconds=5.0,
        router=router,
    )

    finished = asyncio.Event()
    seen: list = []

    async def on_completion(task):
        seen.append(task)
        finished.set()

    await service.submit_task(
        1, "ses_evt", "hello", on_completion=on_completion, chat_id=42, ack_message_id=7
    )

    # Let the worker send the prompt and start waiting on the router.
    for _ in range(50):
        if fake.prompted:
            break
        await asyncio.sleep(0.01)

    fake.messages = [_msg("idle", 2500, outcome="succeeded"), _msg("assistant", 2400, text="done")]
    await router.handle(
        ServerEvent(
            id="evt_1",
            event_type="session.idle",
            data={"sessionID": "ses_evt"},
            session_id="ses_evt",
        )
    )

    await asyncio.wait_for(finished.wait(), timeout=2.0)
    assert seen[0].state == "completed"
    assert seen[0].response_text == "done"

    await db.close()

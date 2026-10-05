import pytest
from opencode_telegram.storage.database import Database
from opencode_telegram.storage.repositories import Repository

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

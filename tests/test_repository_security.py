import pytest

from opencode_telegram.storage.database import Database
from opencode_telegram.storage.repositories import Repository


@pytest.mark.asyncio
async def test_sessions_are_scoped_to_their_owner(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    await db.connect()
    repo = Repository(db)

    await repo.save_session("ses_owner", "project", 100, "Owned")

    assert await repo.get_session_for_user("ses_owner", 100) is not None
    assert await repo.get_session_for_user("ses_owner", 200) is None

    await db.close()


@pytest.mark.asyncio
async def test_only_one_active_task_can_exist_per_session(tmp_path):
    db = Database(tmp_path / "bot.sqlite3")
    await db.connect()
    repo = Repository(db)

    await repo.create_task("task_one", "ses_one", 100, "first")
    with pytest.raises(Exception):
        await repo.create_task("task_two", "ses_one", 100, "second")

    await db.close()
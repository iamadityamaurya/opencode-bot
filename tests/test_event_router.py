import asyncio

import pytest

from opencode_telegram.opencode.models import ServerEvent
from opencode_telegram.opencode.router import COMPLETION_EVENTS, EventRouter


def _event(event_type: str, session_id: str) -> ServerEvent:
    return ServerEvent(
        id="evt_1",
        event_type=event_type,
        data={"sessionID": session_id},
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_wait_for_resolves_on_matching_event():
    router = EventRouter()

    async def fire_soon():
        await asyncio.sleep(0.02)
        await router.handle(_event("session.idle", "ses_a"))

    asyncio.create_task(fire_soon())
    result = await router.wait_for("ses_a", COMPLETION_EVENTS, timeout=2.0)
    assert result is not None
    assert result.event_type == "session.idle"


@pytest.mark.asyncio
async def test_wait_for_ignores_other_sessions_and_types():
    router = EventRouter()

    async def fire_wrong_then_right():
        await asyncio.sleep(0.02)
        await router.handle(_event("session.step.started", "ses_a"))
        await router.handle(_event("session.idle", "ses_b"))
        await asyncio.sleep(0.02)
        await router.handle(_event("session.idle", "ses_a"))

    asyncio.create_task(fire_wrong_then_right())
    result = await router.wait_for("ses_a", COMPLETION_EVENTS, timeout=2.0)
    assert result is not None
    assert result.session_id == "ses_a"


@pytest.mark.asyncio
async def test_wait_for_times_out_without_event():
    router = EventRouter()
    result = await router.wait_for("ses_a", COMPLETION_EVENTS, timeout=0.05)
    assert result is None


@pytest.mark.asyncio
async def test_subscriber_exception_does_not_break_others():
    router = EventRouter()
    seen = []

    async def bad(_event):
        raise RuntimeError("boom")

    async def good(event):
        seen.append(event.event_type)

    router.subscribe(bad)
    router.subscribe(good)
    await router.handle(_event("session.idle", "ses_a"))
    assert seen == ["session.idle"]

import pytest
import httpx
from unittest.mock import AsyncMock, patch
from opencode_telegram.opencode.client import OpenCodeClient
from opencode_telegram.opencode.models import SessionInfo

@pytest.mark.asyncio
async def test_client_create_session():
    client = OpenCodeClient("http://127.0.0.1:4096")
    req = httpx.Request("POST", "http://127.0.0.1:4096/api/session")
    mock_resp = httpx.Response(
        200,
        json={"data": {"id": "ses_test123", "title": "Test Session", "location": {"directory": "/tmp"}}},
        request=req
    )

    with patch.object(client.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        session = await client.create_session("Test Session")
        assert session.id == "ses_test123"
        assert session.title == "Test Session"
        assert session.directory == "/tmp"

    await client.close()

@pytest.mark.asyncio
async def test_client_health():
    client = OpenCodeClient("http://127.0.0.1:4096")
    req = httpx.Request("GET", "http://127.0.0.1:4096/api/global/health")
    mock_resp = httpx.Response(200, json={"status": "ok"}, request=req)

    with patch.object(client.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        health = await client.check_health()
        assert health is True

    await client.close()


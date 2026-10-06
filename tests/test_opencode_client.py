import pytest
import httpx
from unittest.mock import AsyncMock, patch
from opencode_telegram.opencode.client import OpenCodeClient


def _response(method: str, path: str, status: int = 200, **kwargs) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request(method, f"http://127.0.0.1:4096{path}"), **kwargs)


@pytest.mark.asyncio
async def test_client_create_session_sends_location():
    client = OpenCodeClient("http://127.0.0.1:4096")
    mock_resp = _response(
        "POST",
        "/api/session",
        json={"data": {"id": "ses_test123", "title": "Test Session", "location": {"directory": "/tmp"}}},
    )

    with patch.object(client.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        session = await client.create_session("Test Session", directory="/tmp")

        assert session.id == "ses_test123"
        assert session.title == "Test Session"
        assert session.directory == "/tmp"

        # V2 is location-scoped: the directory must be sent on creation.
        assert mock_post.call_args.kwargs["json"]["location"] == {"directory": "/tmp"}

    await client.close()


@pytest.mark.asyncio
async def test_client_health_uses_api_info_and_rejects_html():
    client = OpenCodeClient("http://127.0.0.1:4096")

    with patch.object(client.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = _response("GET", "/api/info", json={"version": "2.0.19", "pid": 1, "urls": [], "paths": {"tmp": "/tmp"}})
        assert await client.check_health() is True
        assert mock_get.call_args.args[0] == "/api/info"

        # A SPA fallback returns 200 text/html; it must not be treated as healthy.
        mock_get.return_value = _response("GET", "/api/info", text="<!doctype html>")
        assert await client.check_health() is False

    await client.close()


@pytest.mark.asyncio
async def test_client_get_models_and_switch_model():
    client = OpenCodeClient("http://127.0.0.1:4096")
    mock_resp = _response(
        "GET",
        "/api/model",
        json={"location": {"directory": "/tmp"}, "data": [{"id": "claude-3-5-sonnet", "name": "Claude 3.5 Sonnet", "providerID": "anthropic"}]},
    )

    with patch.object(client.client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        models = await client.get_models()
        assert len(models) == 1
        assert models[0]["id"] == "claude-3-5-sonnet"

    with patch.object(client.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _response("POST", "/api/session/ses_123/model", json={"data": {}})
        success = await client.set_session_model("ses_123", "claude-3-5-sonnet", "anthropic")
        assert success is True
        # V2 expects a Model.Ref object, not flat modelID/providerID fields.
        assert mock_post.call_args.kwargs["json"] == {
            "model": {"id": "claude-3-5-sonnet", "providerID": "anthropic"}
        }

    await client.close()


@pytest.mark.asyncio
async def test_client_respond_to_permission_uses_reply_route_and_decision():
    client = OpenCodeClient("http://127.0.0.1:4096")

    with patch.object(client.client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _response("POST", "/api/session/ses_123/permission/perm_456/reply", json={})
        success = await client.respond_to_permission("ses_123", "perm_456", approved=True)
        assert success is True
        assert mock_post.call_args.args[0] == "/api/session/ses_123/permission/perm_456/reply"
        assert mock_post.call_args.kwargs["json"] == {"decision": "once"}

        await client.respond_to_permission("ses_123", "perm_456", approved=False)
        assert mock_post.call_args.kwargs["json"] == {"decision": "reject"}

    await client.close()


@pytest.mark.asyncio
async def test_client_rename_uses_patch():
    client = OpenCodeClient("http://127.0.0.1:4096")

    with patch.object(client.client, "patch", new_callable=AsyncMock) as mock_patch:
        mock_patch.return_value = _response("PATCH", "/api/session/ses_123", json={"data": {}})
        rename_success = await client.rename_session("ses_123", "New Title")
        assert rename_success is True
        assert mock_patch.call_args.args[0] == "/api/session/ses_123"
        assert mock_patch.call_args.kwargs["json"] == {"title": "New Title"}

    await client.close()

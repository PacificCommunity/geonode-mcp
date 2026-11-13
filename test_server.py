#!/usr/bin/env python3
"""
Tests for the MCP GeoNode Server.

These tests exercise configuration wiring and tool registration without making
any network calls to a GeoNode instance.
"""

import asyncio

import httpx

from mcp_geonode import server
from mcp_geonode.server import mcp


def _run(coro):
    return asyncio.run(coro)


def test_configure_geonode_updates_status():
    previous_client = server.geonode_client
    try:
        result = _run(server.configure_geonode("https://example.org"))

        assert result["configured"] is True
        assert result["configuration_source"] == "manual"
        assert result["base_url"].startswith("https://example.org")

        status = server.get_configuration_status()
        assert status["configured"] is True
        assert status["configuration_source"] == "manual"
        assert status["base_url"].startswith("https://example.org")
    finally:
        new_client = server.geonode_client
        if new_client is not None and new_client is not previous_client:
            _run(new_client.aclose())
        # configure_geonode() closed the previous client, so rebuild the
        # process-wide client from the environment to leave a clean state.
        server.geonode_client = None
        server._configuration_source = None
        server._auto_configure_from_env()


def test_configure_geonode_rejects_invalid_url():
    result = _run(server.configure_geonode("not-a-url"))
    assert "error" in result


def test_version_comes_from_single_source():
    """The package version must match the server's reported version."""
    from mcp_geonode._version import __version__ as source_version

    assert server.__version__ == source_version
    assert mcp.version == source_version


def test_cli_entry_point_is_importable():
    """The mcp-geonode-cli console script must resolve to a packaged module."""
    from mcp_geonode.cli import main_cli

    assert callable(main_cli)


def test_registered_tools_include_expected():
    tools = _run(mcp.list_tools())
    names = {tool.name for tool in tools}
    for expected in (
        "configure_geonode",
        "get_configuration_status",
        "list_resources",
        "download_resource",
        "download_asset",
    ):
        assert expected in names


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def request(self, method, endpoint, **kwargs):
        return self._payload


def test_download_resource_uses_download_urls(monkeypatch):
    payload = {
        "resource": {"download_urls": [{"url": "https://x/api/v2/assets/9/download"}]}
    }
    monkeypatch.setattr(server, "get_client", lambda: _FakeClient(payload))

    result = _run(server.download_resource(2071))
    assert result["download_url"] == "https://x/api/v2/assets/9/download"


def test_download_resource_without_urls(monkeypatch):
    monkeypatch.setattr(server, "get_client", lambda: _FakeClient({"resource": {}}))

    result = _run(server.download_resource(2071))
    assert "error" in result


class _ScriptedClient:
    """Returns or raises each scripted response in order, recording calls."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    async def request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _http_error(status_code=400, text=""):
    request = httpx.Request("PUT", "https://x/api/v2/resources/7/permissions")
    response = httpx.Response(status_code, text=text, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_set_resource_permissions_sends_all_buckets(monkeypatch):
    fake = _ScriptedClient(
        {"status": "ready", "execution_id": "exec-1", "status_url": "https://x/status"}
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(
        server.set_resource_permissions(
            7, users=[{"id": 1, "permissions": "view"}]
        )
    )

    assert result["execution_id"] == "exec-1"
    method, endpoint, kwargs = fake.calls[0]
    assert (method, endpoint) == ("PUT", "resources/7/permissions")
    assert kwargs["data"] == {
        "users": [{"id": 1, "permissions": "view"}],
        "groups": [],
        "organizations": [],
    }


def test_set_resource_permissions_returns_synchronous_response_unchanged(monkeypatch):
    payload = {"message": "Permissions updated"}
    fake = _ScriptedClient(payload)
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_resource_permissions(7, groups=[{"id": 2, "permissions": "view"}]))

    assert result == payload


def test_set_resource_permissions_retries_once_on_empty_400(monkeypatch):
    fake = _ScriptedClient(
        _http_error(400, ""),
        {"status": "ready", "execution_id": "exec-2"},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)
    monkeypatch.setattr(server, "PERMISSION_RETRY_DELAY_SECONDS", 0)

    result = _run(server.set_resource_permissions(7, users=[{"id": 1, "permissions": "view"}]))

    assert result["execution_id"] == "exec-2"
    assert len(fake.calls) == 2


def test_set_resource_permissions_reports_second_empty_400(monkeypatch):
    fake = _ScriptedClient(_http_error(400, ""), _http_error(400, ""))
    monkeypatch.setattr(server, "get_client", lambda: fake)
    monkeypatch.setattr(server, "PERMISSION_RETRY_DELAY_SECONDS", 0)

    result = _run(server.set_resource_permissions(7, users=[{"id": 1, "permissions": "view"}]))

    assert len(fake.calls) == 2
    assert "after one retry" in result["error"]
    assert "<empty body>" in result["error"]
    assert "may still be running" in result["error"]


def test_set_resource_permissions_does_not_retry_when_400_has_body(monkeypatch):
    fake = _ScriptedClient(_http_error(400, '{"detail": "invalid permission id"}'))
    monkeypatch.setattr(server, "get_client", lambda: fake)
    monkeypatch.setattr(server, "PERMISSION_RETRY_DELAY_SECONDS", 0)

    result = _run(server.set_resource_permissions(7, users=[{"id": 1, "permissions": "view"}]))

    assert len(fake.calls) == 1
    assert "invalid permission id" in result["error"]
    assert "HTTP 400" in result["error"]


def test_check_execution_status_uses_resource_service_endpoint(monkeypatch):
    fake = _ScriptedClient({"status": "finished", "log": ""})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.check_execution_status("exec-1"))

    assert fake.calls == [
        ("GET", "resource-service/execution-status/exec-1", {})
    ]
    assert result == {"status": "finished", "log": ""}
    assert "error" not in result


def test_check_execution_status_marks_failed_execution(monkeypatch):
    fake = _ScriptedClient({"status": "failed", "log": "permission id 99 missing"})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.check_execution_status("exec-1"))

    assert result["status"] == "failed"
    assert result["log"] == "permission id 99 missing"
    assert "permission id 99 missing" in result["error"]


def test_check_execution_status_is_registered_in_cli():
    from mcp_geonode.cli import TOOL_NAMES

    assert "check_execution_status" in TOOL_NAMES

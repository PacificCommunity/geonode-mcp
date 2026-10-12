#!/usr/bin/env python3
"""
Tests for the MCP GeoNode Server.

These tests exercise configuration wiring and tool registration without making
any network calls to a GeoNode instance.
"""

import asyncio

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

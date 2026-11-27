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


def test_upload_document_posts_to_importer(monkeypatch, tmp_path):
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fake = _ScriptedClient({"execution_id": "exec-1"})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.upload_document(file_path=str(pdf), title="National Policy"))

    method, endpoint, kwargs = fake.calls[0]
    assert (method, endpoint) == ("POST", "uploads/upload")
    assert kwargs["data"] == {"action": "document_upload", "title": "National Policy"}
    assert kwargs["files"]["base_file"][0] == "policy.pdf"
    assert result == {"execution_id": "exec-1"}


def test_upload_document_remote_url_uses_json_payload(monkeypatch):
    fake = _ScriptedClient({"execution_id": "exec-2"})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(
        server.upload_document(
            doc_url="https://example.org/report.pdf", extension=".pdf"
        )
    )

    method, endpoint, kwargs = fake.calls[0]
    assert (method, endpoint) == ("POST", "uploads/upload")
    assert kwargs["data"] == {
        "action": "document_upload",
        "title": "Uploaded Document",
        "extension": "pdf",
        "url": "https://example.org/report.pdf",
    }
    assert kwargs["files"] is None
    assert result == {"execution_id": "exec-2"}


def test_upload_document_patches_abstract_and_publish_after_import(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "plan.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fake = _ScriptedClient(
        {"execution_id": "exec-3"},
        {"status": "finished", "output_params": {"resources": [{"id": 42}]}},
        {},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(
        server.upload_document(file_path=str(pdf), abstract="Summary", publish=True)
    )

    assert fake.calls[1] == ("GET", "executionrequest/exec-3", {})
    assert fake.calls[2] == (
        "PATCH",
        "documents/42",
        {
            "data": {
                "abstract": "Summary",
                "is_published": True,
                "is_approved": True,
            }
        },
    )
    assert result["execution_id"] == "exec-3"
    assert result["document_id"] == 42
    assert result["applied"] == {
        "abstract": "Summary",
        "is_published": True,
        "is_approved": True,
    }


def test_upload_document_reports_failed_import(monkeypatch, tmp_path):
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fake = _ScriptedClient(
        {"execution_id": "exec-4"},
        {"status": "failed", "log": "boom"},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.upload_document(file_path=str(pdf), publish=True))

    assert result["error"] == "Document import failed"
    assert result["execution"]["status"] == "failed"
    assert all(call[0] != "PATCH" for call in fake.calls)


def test_upload_document_warns_when_import_does_not_finish(monkeypatch, tmp_path):
    pdf = tmp_path / "slow.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    fake = _ScriptedClient(
        {"execution_id": "exec-5"},
        {"status": "running"},
        {"status": "running"},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)
    monkeypatch.setattr(server, "DOCUMENT_IMPORT_MAX_POLLS", 2)
    monkeypatch.setattr(server, "DOCUMENT_IMPORT_POLL_INTERVAL_SECONDS", 0)

    result = _run(server.upload_document(file_path=str(pdf), publish=True))

    assert "warnings" in result
    assert "did not finish" in result["warnings"][0]
    assert all(call[0] != "PATCH" for call in fake.calls)


def test_upload_document_rejects_missing_and_conflicting_inputs(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    assert "error" in _run(server.upload_document())
    assert "error" in _run(
        server.upload_document(file_path="/nope.pdf", doc_url="https://x/y.pdf")
    )
    assert "error" in _run(server.upload_document(file_path="/does/not/exist.pdf"))
    assert fake.calls == []


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


def test_set_dataset_thumbnail_with_bbox(monkeypatch):
    payload = {
        "message": "Thumbnail correctly created.",
        "success": True,
        "thumbnail_url": "https://x/new.jpg",
    }
    fake = _ScriptedClient(payload)
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(
        server.set_dataset_thumbnail(
            42, [168.1685, 168.4698, -17.8268, -17.6403], zoom=10
        )
    )

    assert result == payload
    method, endpoint, kwargs = fake.calls[0]
    assert (method, endpoint) == ("POST", "resources/42/set_thumbnail_from_bbox")
    assert kwargs["data"] == {
        "bbox": [168.1685, 168.4698, -17.8268, -17.6403],
        "srid": "EPSG:4326",
        "zoom": 10,
    }


def test_set_dataset_thumbnail_uses_dataset_extent(monkeypatch):
    fake = _ScriptedClient(
        {
            "resource": {
                "extent": {
                    "coords": [168.1685, -17.8268, 168.4698, -17.6403],
                    "srid": "EPSG:4326",
                }
            }
        },
        {
            "message": "Thumbnail correctly created.",
            "success": True,
            "thumbnail_url": "https://x/new.jpg",
        },
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42))

    assert result["success"] is True
    assert fake.calls[0][0:2] == ("GET", "resources/42")
    method, endpoint, kwargs = fake.calls[1]
    assert (method, endpoint) == ("POST", "resources/42/set_thumbnail_from_bbox")
    assert kwargs["data"] == {
        "bbox": [168.1685, 168.4698, -17.8268, -17.6403],
        "srid": "EPSG:4326",
    }


def test_set_dataset_thumbnail_reports_http_body(monkeypatch):
    fake = _ScriptedClient(
        _http_error(403, '{"message": "You do not have permission to set this thumbnail."}')
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42, [1, 2, 3, 4]))

    assert "HTTP 403" in result["error"]
    assert "do not have permission" in result["error"]


def test_set_dataset_thumbnail_reports_missing_dataset_on_extent_lookup(monkeypatch):
    fake = _ScriptedClient(_http_error(404, '{"message": "Resource not found."}'))
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42))

    assert len(fake.calls) == 1
    assert "HTTP 404" in result["error"]


def test_set_dataset_thumbnail_rejects_invalid_bbox(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    for bbox in (
        [1, 2, 3],
        [1, 2, 3, float("nan")],
        [1, 2, 3, float("inf")],
        [1, 2, "4", 5],
        [True, 2, 3, 4],
    ):
        result = _run(server.set_dataset_thumbnail(42, bbox))
        assert "bbox" in result["error"].lower()

    assert fake.calls == []


def test_set_dataset_thumbnail_rejects_invalid_srid_and_zoom(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    assert "srid" in _run(server.set_dataset_thumbnail(42, [1, 2, 3, 4], srid=""))["error"]
    assert "zoom" in _run(server.set_dataset_thumbnail(42, [1, 2, 3, 4], zoom=-1))["error"]
    assert fake.calls == []


def test_set_dataset_thumbnail_reports_missing_extent(monkeypatch):
    fake = _ScriptedClient({"resource": {}})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42))

    assert "extent" in result["error"].lower()
    assert len(fake.calls) == 1


def test_set_dataset_thumbnail_timeout_verifies_new_thumbnail(monkeypatch):
    fake = _ScriptedClient(
        TimeoutError("timed out"),
        {"resource": {"thumbnail_url": "https://x/new.jpg"}},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42, [1, 2, 3, 4]))

    assert result["success"] is True
    assert result["thumbnail_url"] == "https://x/new.jpg"
    assert "timed out" in result["message"].lower()


def test_set_dataset_thumbnail_timeout_without_thumbnail(monkeypatch):
    fake = _ScriptedClient(
        TimeoutError("timed out"),
        {"resource": {"thumbnail_url": None}},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.set_dataset_thumbnail(42, [1, 2, 3, 4]))

    assert "error" in result
    assert "may still" in result["error"].lower()


def test_set_dataset_thumbnail_is_registered_in_cli():
    from mcp_geonode.cli import TOOL_NAMES

    assert "set_dataset_thumbnail" in TOOL_NAMES


def test_create_group_sends_expected_payload(monkeypatch):
    fake = _ScriptedClient({"group_profile": {"pk": 3, "title": "Pacific Data Hub"}})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("Pacific Data Hub", "Regional data", group_id=1))

    assert result["group_profile"]["pk"] == 3
    assert fake.calls == [
        (
            "POST",
            "groups",
            {
                "data": {
                    "title": "Pacific Data Hub",
                    "slug": "pacific-data-hub",
                    "description": "Regional data",
                    "access": "public",
                    "group": 1,
                }
            },
        )
    ]


def test_create_group_accepts_explicit_slug_email_and_categories(monkeypatch):
    fake = _ScriptedClient({"group_profile": {"pk": 4}})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    _run(
        server.create_group(
            "Coastal",
            "Coastal data",
            slug="coastal-data",
            email="team@example.org",
            access="private",
            categories=["climate"],
            group_id=2,
        )
    )

    data = fake.calls[0][2]["data"]
    assert data["slug"] == "coastal-data"
    assert data["email"] == "team@example.org"
    assert data["access"] == "private"
    assert data["categories"] == ["climate"]
    assert data["group"] == 2


def test_create_group_rejects_blank_title(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("   ", "desc", group_id=1))

    assert "error" in result
    assert "title" in result["error"]
    assert fake.calls == []


def test_create_group_rejects_blank_description(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("Title", "  ", group_id=1))

    assert "error" in result
    assert "description" in result["error"]
    assert fake.calls == []


def test_create_group_rejects_unknown_access(monkeypatch):
    fake = _ScriptedClient()
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("Title", "desc", access="secret", group_id=1))

    assert "error" in result
    assert "access" in result["error"]
    assert fake.calls == []


def test_create_group_reuses_existing_group_id_when_omitted(monkeypatch):
    fake = _ScriptedClient(
        {
            "group_profiles": [
                {"title": "Existing", "group": {"pk": 9, "name": "existing"}}
            ]
        },
        {"group_profile": {"pk": 5}},
    )
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("New Group", "desc"))

    assert result["group_profile"]["pk"] == 5
    assert fake.calls[0] == ("GET", "groups", {"params": {"page_size": 1}})
    assert fake.calls[1][2]["data"]["group"] == 9


def test_create_group_errors_when_no_placeholder_group_exists(monkeypatch):
    fake = _ScriptedClient({"group_profiles": []})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("New Group", "desc"))

    assert "error" in result
    assert "group_id" in result["error"]
    assert len(fake.calls) == 1


def test_create_group_returns_error_on_api_failure(monkeypatch):
    fake = _ScriptedClient(RuntimeError("HTTP 403"))
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(server.create_group("New Group", "desc", group_id=1))

    assert "error" in result
    assert "Failed to create group" in result["error"]


def test_create_group_is_registered_in_cli():
    from mcp_geonode.cli import TOOL_NAMES

    assert "create_group" in TOOL_NAMES

#!/usr/bin/env python3
"""Unit tests for the download_asset tool and its helpers."""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mcp_geonode import server
from mcp_geonode.server import (
    _asset_descriptors_from_links,
    _filename_from_content_disposition,
    _load_asset_download_dir,
    _safe_filename,
    _unwrap_resource,
    download_asset,
)


class _FakeClient:
    """Minimal stand-in for GeoNodeClient, recording calls."""

    def __init__(self, resource, download_error=None):
        self.base_url = "https://geonode.example.org"
        self._resource = resource
        self._download_error = download_error or {}
        self.calls = []

    async def request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint))
        return self._resource

    async def download_to_file(self, url, dest_dir, fallback_name):
        self.calls.append(("download", url))
        asset_id = int(url.rstrip("/").split("/")[-2])
        if asset_id in self._download_error:
            raise RuntimeError(self._download_error[asset_id])
        path = Path(dest_dir) / fallback_name
        path.write_bytes(b"zip-bytes")
        return {
            "file_path": str(path),
            "filename": fallback_name,
            "size_bytes": 9,
            "content_type": "application/zip",
            "content_disposition": "",
        }


def _asset_link(url, name="myfile.shp", title="Original", asset_type="original"):
    return {
        "extension": "shp",
        "link_type": "data",
        "name": name,
        "mime": "application/octet-stream",
        "url": url,
        "extras": {
            "type": "asset",
            "deletable": False,
            "content": {"title": title, "type": asset_type, "created": "2024-01-01"},
        },
    }


def _run(coro):
    return asyncio.run(coro)


def test_safe_filename_strips_paths_and_unsafe_chars():
    assert _safe_filename("../../etc/passwd", "fb") == "passwd"
    assert _safe_filename("..\\..\\windows\\evil.zip", "fb") == "evil.zip"
    assert _safe_filename("we<ird:name.zip", "fb") == "we_ird_name.zip"
    assert _safe_filename(None, "fb") == "fb"
    assert _safe_filename("", "fb") == "fb"
    assert _safe_filename("...", "fb") == "fb"


def test_filename_from_content_disposition():
    assert (
        _filename_from_content_disposition("attachment; filename=myfile.zip")
        == "myfile.zip"
    )
    assert (
        _filename_from_content_disposition('attachment; filename="a b.zip"')
        == "a b.zip"
    )
    assert (
        _filename_from_content_disposition("filename*=UTF-8''caf%C3%A9.zip")
        == "café.zip"
    )
    assert _filename_from_content_disposition(None) is None
    assert _filename_from_content_disposition("attachment") is None


def test_asset_descriptors_extract_asset_pks():
    links = [
        {"url": "https://x/api/v2/resources/1", "extras": {"type": "metadata"}},
        _asset_link("https://x/api/v2/assets/45/link"),
        {
            "url": "https://x/api/v2/assets/46/link",
            "extras": {
                "type": "asset",
                "content": {
                    "title": "extra",
                    "type": "original",
                    "download_url": "https://x/api/v2/assets/46/download",
                },
            },
        },
        {"extras": {"type": "asset", "content": {}}},
    ]
    descriptors = _asset_descriptors_from_links(links)
    assert [d["asset_id"] for d in descriptors] == [45, 46, None]
    assert descriptors[0]["name"] == "myfile.shp"
    assert descriptors[0]["type"] == "original"


def test_asset_descriptors_handles_non_list():
    assert _asset_descriptors_from_links(None) == []
    assert _asset_descriptors_from_links("nope") == []


def test_unwrap_resource_handles_both_shapes():
    links = [{"extras": {"type": "asset"}}]
    assert _unwrap_resource({"links": links}) == {"links": links}
    assert _unwrap_resource({"resource": {"links": links}}) == {"links": links}
    assert _unwrap_resource(None) == {}


def test_load_asset_download_dir(monkeypatch):
    monkeypatch.delenv("GEONODE_ASSET_DOWNLOAD_DIR", raising=False)
    assert _load_asset_download_dir() is None

    monkeypatch.setenv("GEONODE_ASSET_DOWNLOAD_DIR", "   ")
    assert _load_asset_download_dir() is None

    monkeypatch.setenv("GEONODE_ASSET_DOWNLOAD_DIR", "~/assets")
    assert _load_asset_download_dir() == str(Path("~/assets").expanduser())


def test_download_asset_downloads_all(tmp_path, monkeypatch):
    resource = {
        "links": [
            _asset_link("https://x/api/v2/assets/45/link"),
            _asset_link("https://x/api/v2/assets/46/link", name="two.tif"),
        ]
    }
    fake = _FakeClient(resource)
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(download_asset(resource_id=123, dest_dir=str(tmp_path)))

    assert result["resource_id"] == 123
    assert result["errors"] == []
    assert {d["asset_id"] for d in result["downloaded"]} == {45, 46}
    assert all(Path(d["file_path"]).exists() for d in result["downloaded"])
    assert (
        "download",
        "https://geonode.example.org/api/v2/assets/45/download",
    ) in fake.calls


def test_download_asset_single_and_unknown(tmp_path, monkeypatch):
    resource = {
        "links": [
            _asset_link("https://x/api/v2/assets/45/link"),
            _asset_link("https://x/api/v2/assets/46/link"),
        ]
    }
    fake = _FakeClient(resource)
    monkeypatch.setattr(server, "get_client", lambda: fake)

    single = _run(download_asset(resource_id=123, asset_id=46, dest_dir=str(tmp_path)))
    assert [d["asset_id"] for d in single["downloaded"]] == [46]

    missing = _run(download_asset(resource_id=123, asset_id=99, dest_dir=str(tmp_path)))
    assert "error" in missing
    assert missing["assets"]


def test_download_asset_no_assets(tmp_path, monkeypatch):
    fake = _FakeClient({"links": [{"extras": {"type": "metadata"}}]})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(download_asset(resource_id=123, dest_dir=str(tmp_path)))
    assert result["assets"] == []
    assert result["downloaded"] == []
    assert "no assets" in result["message"]


def test_download_asset_handles_nested_resource(tmp_path, monkeypatch):
    resource = {"resource": {"links": [_asset_link("https://x/api/v2/assets/45/link")]}}
    fake = _FakeClient(resource)
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(download_asset(resource_id=123, dest_dir=str(tmp_path)))
    assert [d["asset_id"] for d in result["downloaded"]] == [45]


def test_download_asset_reports_per_asset_errors(tmp_path, monkeypatch):
    resource = {
        "links": [
            _asset_link("https://x/api/v2/assets/45/link"),
            _asset_link("https://x/api/v2/assets/46/link"),
        ]
    }
    fake = _FakeClient(resource, download_error={46: "boom"})
    monkeypatch.setattr(server, "get_client", lambda: fake)

    result = _run(download_asset(resource_id=123, dest_dir=str(tmp_path)))
    assert [d["asset_id"] for d in result["downloaded"]] == [45]
    assert result["errors"] == [{"asset_id": 46, "error": "boom"}]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

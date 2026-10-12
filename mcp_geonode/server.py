#!/usr/bin/env python3
"""
MCP Server for GeoNode API

This server provides access to GeoNode functionality through the Model Context Protocol.
It supports resource listing, searching, uploading, downloading, user management, and more.
"""

import asyncio
import base64
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, HttpUrl

# Try to import python-dotenv for .env file support
try:
    from dotenv import load_dotenv

    load_dotenv()  # Load .env file if it exists
except ImportError:
    # python-dotenv not installed, continue without .env support
    pass


def _resolve_log_file_path() -> Path:
    """Resolve the server log file path from the environment or default location."""
    raw_path = os.getenv("GEONODE_LOG_FILE", "geonode-mcp.log")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _configure_logging() -> Path:
    """Configure stderr logging plus a persistent file log for MCP hosts that hide stderr."""
    logging.basicConfig(level=logging.INFO)

    log_file_path = _resolve_log_file_path()
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    package_logger = logging.getLogger("mcp_geonode")
    existing_handler = next(
        (
            handler
            for handler in package_logger.handlers
            if isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename) == log_file_path
        ),
        None,
    )
    if existing_handler is None:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        package_logger.addHandler(file_handler)

    return log_file_path


LOG_FILE_PATH = _configure_logging()
logger = logging.getLogger(__name__)


def _sanitize_for_logging(value: Any) -> Any:
    """Sanitize request data for debug logging."""
    if isinstance(value, dict):
        return {key: _sanitize_for_logging(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_logging(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


def _summarize_files(files: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Summarize uploaded files without logging raw binary content."""
    if not files:
        return None

    summary: Dict[str, Any] = {}
    for field_name, file_value in files.items():
        if isinstance(file_value, tuple):
            filename = file_value[0] if len(file_value) > 0 else None
            content = file_value[1] if len(file_value) > 1 else None
            content_type = file_value[2] if len(file_value) > 2 else None
            size = len(content) if isinstance(content, (bytes, bytearray)) else None
            summary[field_name] = {
                "filename": filename,
                "content_type": content_type,
                "size": size,
            }
        else:
            summary[field_name] = _sanitize_for_logging(file_value)
    return summary


def _load_max_concurrent_uploads() -> int:
    """Load and validate upload concurrency limit from environment."""
    raw_value = os.getenv("GEONODE_MAX_CONCURRENT_UPLOADS", "5")
    try:
        parsed_value = int(raw_value)
    except ValueError:
        logger.warning(
            "Invalid GEONODE_MAX_CONCURRENT_UPLOADS=%r, using default value 5",
            raw_value,
        )
        return 5

    if parsed_value < 1:
        logger.warning(
            "GEONODE_MAX_CONCURRENT_UPLOADS must be >= 1 (got %d), using 1",
            parsed_value,
        )
        return 1

    return parsed_value


def _load_http_timeout() -> float:
    """Load and validate the HTTP request timeout (seconds) from environment.

    httpx's default is 5 seconds for connect/read/write/pool combined, which is
    too tight for a GeoNode instance under concurrent load: a request can fully
    succeed server-side and still time out client-side while waiting on the
    response, leaving the caller unable to tell success from failure.
    """
    raw_value = os.getenv("GEONODE_HTTP_TIMEOUT", "30")
    try:
        parsed_value = float(raw_value)
    except ValueError:
        logger.warning(
            "Invalid GEONODE_HTTP_TIMEOUT=%r, using default value 30", raw_value
        )
        return 30.0

    if parsed_value <= 0:
        logger.warning(
            "GEONODE_HTTP_TIMEOUT must be > 0 (got %s), using 30", parsed_value
        )
        return 30.0

    return parsed_value


def _load_asset_download_dir() -> Optional[str]:
    """Load the default directory for downloaded dataset assets from environment.

    Returns None when unset, in which case callers fall back to the current
    working directory.
    """
    raw_value = os.getenv("GEONODE_ASSET_DOWNLOAD_DIR")
    if raw_value is None or not raw_value.strip():
        return None
    return os.path.expanduser(raw_value.strip())


_ASSET_URL_PATTERN = re.compile(r"/assets/(\d+)(?:/|$)")
_CONTENT_DISPOSITION_FILENAME_PATTERN = re.compile(
    r'filename\*?=(?:"([^"]*)"|([^;]+))', flags=re.IGNORECASE
)


def _safe_filename(name: Optional[str], fallback: str) -> str:
    """Reduce an untrusted name to a safe basename.

    Strips any directory components (defeating traversal such as ``../../x``)
    and characters that are awkward or unsafe in filenames, then falls back to
    ``fallback`` when nothing usable remains.
    """
    if not name:
        return fallback
    base = os.path.basename(str(name).replace("\\", "/"))
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    base = base.strip().strip(".")
    return base or fallback


def _filename_from_content_disposition(value: Optional[str]) -> Optional[str]:
    """Extract the filename from a Content-Disposition header value, if any."""
    if not value:
        return None
    match = _CONTENT_DISPOSITION_FILENAME_PATTERN.search(value)
    if not match:
        return None
    if match.group(1) is not None:
        filename = match.group(1)
    else:
        filename = match.group(2)
        # RFC 5987 extended form: filename*=UTF-8''percent-encoded
        if "''" in filename:
            filename = filename.split("''", 1)[1]
    return unquote(filename.strip()) or None


def _unwrap_resource(payload: Any) -> Dict[str, Any]:
    """Return the resource object from a resource-detail payload.

    Some GeoNode deployments return the resource fields at the top level,
    others nest them under a ``resource`` key.
    """
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("resource")
    if isinstance(nested, dict):
        return nested
    return payload


def _asset_descriptors_from_links(links: Any) -> List[Dict[str, Any]]:
    """Extract asset descriptors from a resource's ``links`` payload.

    Assets are attached to a resource through Link entries flagged with
    ``extras.type == "asset"``. The asset primary key is not serialized
    directly, but both the link URL and the download URL embed it as
    ``/assets/{pk}/...``.
    """
    descriptors: List[Dict[str, Any]] = []
    if not isinstance(links, list):
        return descriptors

    for link in links:
        if not isinstance(link, dict):
            continue
        extras = link.get("extras") or {}
        if extras.get("type") != "asset":
            continue

        content = extras.get("content") or {}
        asset_id = None
        for candidate in (link.get("url"), content.get("download_url")):
            if not candidate:
                continue
            match = _ASSET_URL_PATTERN.search(str(candidate))
            if match:
                asset_id = int(match.group(1))
                break

        descriptors.append(
            {
                "asset_id": asset_id,
                "name": link.get("name"),
                "title": content.get("title"),
                "type": content.get("type"),
                "extension": link.get("extension"),
                "mime": link.get("mime"),
            }
        )
    return descriptors


class GeoNodeConfig(BaseModel):
    """Configuration for GeoNode connection."""

    base_url: HttpUrl
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    verify_ssl: bool = True
    http_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> Optional["GeoNodeConfig"]:
        """Create GeoNodeConfig from environment variables.

        Environment variables:
        - GEONODE_BASE_URL: Base URL of the GeoNode instance
        - GEONODE_USERNAME: Username for authentication (optional)
        - GEONODE_PASSWORD: Password for authentication (optional)
        - GEONODE_TOKEN: Bearer token for authentication (optional)
        - GEONODE_VERIFY_SSL: Whether to verify SSL certificates (default: true)
        - GEONODE_HTTP_TIMEOUT: HTTP request timeout in seconds (default: 30)
        - GEONODE_MAX_CONCURRENT_UPLOADS: Upload concurrency limit (default: 5)
        - GEONODE_LOG_FILE: File path for persistent server logs (default: ./geonode-mcp.log)

        Returns:
            GeoNodeConfig instance if GEONODE_BASE_URL is set, None otherwise
        """
        base_url = os.getenv("GEONODE_BASE_URL")
        if not base_url:
            return None

        username = os.getenv("GEONODE_USERNAME")
        password = os.getenv("GEONODE_PASSWORD")
        token = os.getenv("GEONODE_TOKEN")
        verify_ssl = os.getenv("GEONODE_VERIFY_SSL", "true").lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        http_timeout = _load_http_timeout()

        try:
            return cls(
                base_url=base_url,
                username=username,
                password=password,
                token=token,
                verify_ssl=verify_ssl,
                http_timeout=http_timeout,
            )
        except Exception as e:
            logger.error(f"Failed to create GeoNodeConfig from environment: {e}")
            return None


class GeoNodeClient:
    """HTTP client for GeoNode API interactions."""

    def __init__(self, config: GeoNodeConfig):
        self.config = config
        self.base_url = str(config.base_url).rstrip("/")
        self.api_base = f"{self.base_url}/api/v2"

        # Setup authentication headers
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if config.token:
            self.headers["Authorization"] = f"Bearer {config.token}"
        elif config.username and config.password:
            credentials = base64.b64encode(
                f"{config.username}:{config.password}".encode()
            ).decode()
            self.headers["Authorization"] = f"Basic {credentials}"

        # A single, shared, pooled client for the lifetime of this GeoNodeClient
        # (which is itself a process-wide singleton, see get_client()). Opening a
        # brand-new httpx.AsyncClient per request meant every concurrent call paid
        # its own TCP/TLS handshake, which made timeouts far more likely under any
        # concurrency (parallel tool calls, batch scripts, etc.).
        self._http_client = httpx.AsyncClient(
            verify=self.config.verify_ssl,
            follow_redirects=True,
            timeout=httpx.Timeout(self.config.http_timeout),
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call multiple times."""
        await self._http_client.aclose()

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request to GeoNode API."""
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        request_context = {
            "method": method,
            "url": url,
            "params": _sanitize_for_logging(params),
            "payload": _sanitize_for_logging(data),
            "files": _summarize_files(files),
        }

        logger.debug("GeoNode API request: %s", request_context)

        client = self._http_client
        try:
            if files:
                # Remove Content-Type for file uploads to let httpx set it
                headers = {
                    k: v for k, v in self.headers.items() if k != "Content-Type"
                }
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    files=files,
                )
            else:
                response = await client.request(
                    method, url, headers=self.headers, params=params, json=data
                )

            logger.debug(
                "GeoNode API response: %s",
                {
                    "method": method,
                    "url": url,
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type", ""),
                },
            )

            response.raise_for_status()

            # Handle different content types
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json()
            else:
                return {"content": response.text, "content_type": content_type}

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error %s for %s %s with request=%s: %s",
                e.response.status_code,
                method,
                url,
                request_context,
                e.response.text,
            )
            raise
        except httpx.TimeoutException as e:
            # Distinct from other errors: a timeout means we never confirmed the
            # outcome. The request may well have completed on the GeoNode side
            # (the connection/response just wasn't seen in time), so callers
            # must not treat this the same as a confirmed server-side failure.
            detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            msg = (
                f"No response from GeoNode within {self.config.http_timeout}s for "
                f"{method} {url} ({detail}). The request may have still completed "
                "server-side despite this client-side timeout; verify the "
                "resource's actual state before retrying or reporting failure."
            )
            logger.error(msg)
            raise TimeoutError(msg) from e
        except Exception as e:
            # Wrap so the exception message is never blank downstream: many
            # transport-level exceptions (e.g. httpx.ConnectError) stringify to
            # "" on their own, and every tool function does `f"...: {e}"` when
            # reporting failure to the caller.
            detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            logger.error(
                "Request failed for %s %s with request=%s: %s",
                method,
                url,
                request_context,
                detail,
            )
            raise RuntimeError(detail) from e

    async def download_to_file(
        self, url: str, dest_dir: Path, fallback_name: str
    ) -> Dict[str, Any]:
        """Stream a response body to a file inside ``dest_dir``.

        Unlike :meth:`request`, the body is written to disk as raw bytes
        (assets are served as ZIP archives) rather than decoded as JSON/text.
        The output filename is taken from the response's ``Content-Disposition``
        header when present, sanitized to a safe basename, and otherwise falls
        back to ``fallback_name``. Existing files are overwritten.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        headers = {k: v for k, v in self.headers.items() if k != "Content-Type"}
        headers["Accept"] = "*/*"

        logger.debug("GeoNode download: %s -> %s", url, dest_dir)
        try:
            async with self._http_client.stream(
                "GET", url, headers=headers
            ) as response:
                response.raise_for_status()
                content_disposition = response.headers.get("content-disposition", "")
                filename = _safe_filename(
                    _filename_from_content_disposition(content_disposition),
                    fallback_name,
                )
                dest = dest_dir / filename
                total = 0
                with dest.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
                        total += len(chunk)

            return {
                "file_path": str(dest),
                "filename": filename,
                "size_bytes": total,
                "content_type": response.headers.get("content-type", ""),
                "content_disposition": content_disposition,
            }
        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error %s downloading %s: %s",
                e.response.status_code,
                url,
                e.response.text,
            )
            raise
        except httpx.TimeoutException as e:
            detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            msg = (
                f"No response from GeoNode within {self.config.http_timeout}s "
                f"while downloading {url} ({detail})."
            )
            logger.error(msg)
            raise TimeoutError(msg) from e
        except Exception as e:
            detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            logger.error("Download failed for %s: %s", url, detail)
            raise RuntimeError(detail) from e


# Create the MCP server
mcp = FastMCP("GeoNode MCP Server")

# Global client instance (will be set based on configuration)
geonode_client: Optional[GeoNodeClient] = None
# How the active client was configured: "environment" or "manual".
_configuration_source: Optional[str] = None
MAX_CONCURRENT_UPLOADS = _load_max_concurrent_uploads()
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)


# Try to auto-configure from environment on startup
def _auto_configure_from_env():
    """Automatically configure GeoNode client from environment variables if available."""
    global geonode_client, _configuration_source

    if geonode_client is None:
        env_config = GeoNodeConfig.from_env()
        if env_config:
            geonode_client = GeoNodeClient(env_config)
            _configuration_source = "environment"
            logger.info(
                f"Auto-configured GeoNode client from environment for {env_config.base_url}"
            )
            return True
    return False


# Attempt auto-configuration on module load
_auto_configure_from_env()


def get_client() -> GeoNodeClient:
    """Get the configured GeoNode client."""
    global geonode_client

    # Try auto-configuration if no client is set
    if geonode_client is None:
        _auto_configure_from_env()

    if geonode_client is None:
        raise RuntimeError(
            "GeoNode client not configured. Please set environment variables:\n"
            "- GEONODE_BASE_URL (required)\n"
            "- GEONODE_USERNAME (optional)\n"
            "- GEONODE_PASSWORD (optional)\n"
            "- GEONODE_TOKEN (optional)\n"
            "- GEONODE_VERIFY_SSL (optional, default: true)\n"
            "- GEONODE_HTTP_TIMEOUT (optional, default: 30)\n"
            "- GEONODE_MAX_CONCURRENT_UPLOADS (optional, default: 5)\n"
            "\nOr create a .env file with these variables."
        )
    return geonode_client


@mcp.tool()
async def configure_geonode(
    base_url: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    token: Optional[str] = None,
    verify_ssl: bool = True,
) -> Dict[str, Any]:
    """
    Configure the connection to a GeoNode instance.

    This overrides any configuration loaded from the environment.

    Args:
        base_url: GeoNode instance URL
        username: Username for basic authentication (optional)
        password: Password for basic authentication (optional)
        token: API token for bearer authentication (optional)
        verify_ssl: Verify SSL certificates (default: True)

    Returns:
        Dictionary describing the applied configuration
    """
    global geonode_client, _configuration_source

    try:
        config = GeoNodeConfig(
            base_url=base_url,
            username=username,
            password=password,
            token=token,
            verify_ssl=verify_ssl,
            http_timeout=_load_http_timeout(),
        )
    except Exception as e:
        return {"error": f"Invalid GeoNode configuration: {e}"}

    previous = geonode_client
    geonode_client = GeoNodeClient(config)
    _configuration_source = "manual"

    if previous is not None and previous is not geonode_client:
        try:
            await previous.aclose()
        except Exception:
            logger.warning("Failed to close previous GeoNode client", exc_info=True)

    logger.info("GeoNode client configured manually for %s", config.base_url)
    return {
        "configured": True,
        "configuration_source": "manual",
        "base_url": str(config.base_url),
        "has_username": username is not None,
        "has_token": token is not None,
        "verify_ssl": verify_ssl,
        "message": f"Successfully configured GeoNode client for {config.base_url}",
    }


@mcp.tool()
def get_configuration_status() -> Dict[str, Any]:
    """
    Get current GeoNode configuration status.

    Returns:
        Dictionary containing configuration information
    """
    global geonode_client

    status = {
        "configured": geonode_client is not None,
        "configuration_source": _configuration_source,
        "base_url": None,
        "has_username": False,
        "has_token": False,
        "verify_ssl": True,
        "http_timeout": 30.0,
        "max_concurrent_uploads": MAX_CONCURRENT_UPLOADS,
        "log_file": str(LOG_FILE_PATH),
        "env_vars_available": {},
    }

    # Check environment variables
    env_vars = {
        "GEONODE_BASE_URL": os.getenv("GEONODE_BASE_URL"),
        "GEONODE_USERNAME": os.getenv("GEONODE_USERNAME"),
        "GEONODE_PASSWORD": "***" if os.getenv("GEONODE_PASSWORD") else None,
        "GEONODE_TOKEN": "***" if os.getenv("GEONODE_TOKEN") else None,
        "GEONODE_VERIFY_SSL": os.getenv("GEONODE_VERIFY_SSL", "true"),
        "GEONODE_HTTP_TIMEOUT": os.getenv("GEONODE_HTTP_TIMEOUT", "30"),
        "GEONODE_MAX_CONCURRENT_UPLOADS": os.getenv("GEONODE_MAX_CONCURRENT_UPLOADS"),
        "GEONODE_LOG_FILE": os.getenv("GEONODE_LOG_FILE"),
    }

    status["env_vars_available"] = {k: v is not None for k, v in env_vars.items()}

    if geonode_client:
        config = geonode_client.config
        status.update(
            {
                "base_url": str(config.base_url),
                "has_username": config.username is not None,
                "has_token": config.token is not None,
                "verify_ssl": config.verify_ssl,
                "http_timeout": config.http_timeout,
            }
        )
    else:
        # Check if environment configuration is available
        env_config = GeoNodeConfig.from_env()
        if env_config:
            status["configuration_source"] = "environment_available"
            status["base_url"] = str(env_config.base_url)

    return status


@mcp.tool()
async def list_resources(
    resource_type: Optional[str] = None,
    search: Optional[str] = None,
    query: Optional[str] = None,
    search_fields: Optional[List[str]] = None,
    group: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    featured: Optional[bool] = None,
    published: Optional[bool] = None,
    approved: Optional[bool] = None,
    category: Optional[str] = None,
    keywords: Optional[str] = None,
    thesaurus_keywords: Optional[str] = None,
    region: Optional[str] = None,
    owner: Optional[str] = None,
    extent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List and search GeoNode resources with filtering options.

    Args:
        resource_type: Type of resource (dataset, map, document, service, geostory, dashboard)
        search: Free text search in title and abstract
        query: Alias for search
        search_fields: Fields used for text search
        page: Page number for pagination (default: 1)
        page_size: Number of items per page (default: 20)
        featured: Filter by featured status
        published: Filter by published status
        approved: Filter by approved status
        category: Filter by category identifier
        keywords: Filter by keyword name
        thesaurus_keywords: Filter by thesaurus keyword term
        region: Filter by region name
        group: Filter by group name
        owner: Filter by owner username
        extent: Bounding box extent as "minx,miny,maxx,maxy"

    Returns:
        Dictionary containing resources list and metadata
    """
    client = get_client()

    params = {"page": page, "page_size": page_size}

    search_term = search or query
    if search_term:
        params["search"] = search_term
        params["search_fields"] = search_fields or ["title", "abstract"]
    elif search_fields:
        params["search_fields"] = search_fields

    if resource_type:
        params["filter{resource_type}"] = resource_type
    if featured is not None:
        params["filter{featured}"] = str(featured).lower()
    if published is not None:
        params["filter{is_published}"] = str(published).lower()
    if approved is not None:
        params["filter{is_approved}"] = str(approved).lower()
    if category:
        params["filter{category.identifier}"] = category
    if keywords:
        params["filter{keywords.name}"] = keywords
    if group:
        params["filter{group.name}"] = group
    if region:
        params["filter{region.name}"] = region
    if owner:
        params["filter{owner.username}"] = owner
    if extent:
        params["extent"] = extent

    try:
        if thesaurus_keywords:
            server_filtered_params = dict(params)
            server_filtered_params["filter{tkeywords}"] = thesaurus_keywords
            try:
                result = await client.request(
                    "GET", "resources", params=server_filtered_params
                )
                return result
            except httpx.HTTPStatusError:
                logger.warning(
                    "GeoNode tkeywords filter failed, falling back to page-level client filtering"
                )

        result = await client.request("GET", "resources", params=params)

        if thesaurus_keywords:
            needle = thesaurus_keywords.strip().lower()
            resources = result.get("resources", [])
            filtered_resources = []

            for resource in resources:
                tkeywords = resource.get("tkeywords") or []
                if not isinstance(tkeywords, list):
                    continue
                for tkeyword in tkeywords:
                    candidates = [
                        str(tkeyword.get("name", "")).strip().lower(),
                        str(tkeyword.get("slug", "")).strip().lower(),
                        str(tkeyword.get("uri", "")).strip().lower(),
                    ]
                    if needle in candidates:
                        filtered_resources.append(resource)
                        break

            result["resources"] = filtered_resources
            result["filtered_count"] = len(filtered_resources)

        return result
    except Exception as e:
        detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        raise RuntimeError(
            f"Failed to list resources with params={_sanitize_for_logging(params)}: {detail}"
        ) from e


@mcp.tool()
async def list_groups(
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    List GeoNode groups, optionally filtered by a text search query.

    Args:
        search: Free text search for group names and metadata
        page: Page number for pagination (default: 1)
        page_size: Number of items per page (default: 20)

    Returns:
        Dictionary containing groups list and metadata
    """
    client = get_client()

    params = {
        "page": page,
        "page_size": page_size,
    }
    if search:
        params["search"] = search

    try:
        result = await client.request("GET", "groups", params=params)
        if search:
            needle = search.strip().lower()
            group_items = result.get("group_profiles") or result.get("groups") or []
            if isinstance(group_items, list):
                filtered_groups = []
                for group_item in group_items:
                    title = str(group_item.get("title", "")).strip().lower()
                    group_name = str(group_item.get("name", "")).strip().lower()
                    if needle in title or needle in group_name:
                        filtered_groups.append(group_item)

                if "group_profiles" in result:
                    result["group_profiles"] = filtered_groups
                elif "groups" in result:
                    result["groups"] = filtered_groups
                result["filtered_count"] = len(filtered_groups)
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list groups: {e}") from e


@mcp.tool()
async def list_regions(
    page: int = 1, page_size: int = 20, filters: Optional[dict] = None
) -> Dict[str, Any]:
    """
    List available GeoNode regions.

    Args:
        page: Page number for pagination
        page_size: Number of items per page
        filters: Optional dictionary of additional filters to apply (e.g., {"filter{code}": "NA"})

    Returns:
        Dictionary containing regions list and metadata
    """
    client = get_client()

    params = {
        "page": page,
        "page_size": page_size,
    }
    if filters:
        params.update(filters)

    try:
        result = await client.request("GET", "regions", params=params)
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list regions: {e}") from e


@mcp.tool()
async def list_categories(page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """
    List available GeoNode categories.

    Args:
        page: Page number for pagination
        page_size: Number of items per page

    Returns:
        Dictionary containing categories list and metadata
    """
    client = get_client()

    params = {
        "page": page,
        "page_size": page_size,
    }

    try:
        result = await client.request("GET", "categories", params=params)
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list categories: {e}") from e


@mcp.tool()
async def list_tkeywords(page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """
    List GeoNode thesaurus keywords (tkeywords).

    Args:
        page: Page number for pagination
        page_size: Number of items per page

    Returns:
        Dictionary containing tkeywords and metadata
    """
    client = get_client()

    params = {
        "page": page,
        "page_size": page_size,
    }

    try:
        result = await client.request("GET", "tkeywords", params=params)
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list tkeywords: {e}") from e


@mcp.tool()
async def get_resource_details(resource_id: int) -> Dict[str, Any]:
    """
    Get detailed information about a specific resource.

    Args:
        resource_id: ID of the resource to retrieve

    Returns:
        Dictionary containing detailed resource information
    """
    client = get_client()

    try:
        result = await client.request("GET", f"resources/{resource_id}")
        return result
    except Exception as e:
        return {"error": f"Failed to get resource details: {e}"}


@mcp.tool()
async def get_dataset_details(dataset_id: int) -> Dict[str, Any]:
    """
    Get detailed information about a specific dataset (includes additional metadata).

    Args:
        dataset_id: ID of the dataset to retrieve

    Returns:
        Dictionary containing detailed dataset information
    """
    client = get_client()

    try:
        result = await client.request("GET", f"datasets/{dataset_id}")
        return result
    except Exception as e:
        return {"error": f"Failed to get dataset details: {e}"}


@mcp.tool()
async def download_resource(
    resource_id: int, resource_type: str = "dataset"
) -> Dict[str, Any]:
    """
    Get download information for a resource.

    Args:
        resource_id: ID of the resource to download
        resource_type: Type of resource (dataset, document)

    Returns:
        Dictionary containing download information
    """
    client = get_client()

    try:
        if resource_type == "dataset":
            # Use the download_urls exposed on the resource detail; constructing
            # a /datasets/{alternate}/dataset_download URL 404s for datasets that
            # have no uploaded files (e.g. GeoServer-backed layers).
            payload = await client.request("GET", f"resources/{resource_id}")
            resource = _unwrap_resource(payload)
            urls = resource.get("download_urls") or []
            if urls:
                download_url = urls[0]["url"]
            else:
                return {"error": "No download URL found for this dataset"}
        elif resource_type == "document":
            download_url = f"{client.base_url}/documents/{resource_id}/download"
        else:
            return {
                "error": f"Download not supported for resource type: {resource_type}"
            }

        return {
            "download_url": download_url,
            "message": f"Resource can be downloaded from: {download_url}",
        }
    except Exception as e:
        return {"error": f"Failed to get download information: {e}"}


@mcp.tool()
async def download_asset(
    resource_id: int,
    asset_id: Optional[int] = None,
    dest_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download the assets attached to a dataset (resource) to local files.

    Assets are the files attached to a resource: the original uploaded files
    plus any supplementary files. GeoNode serves each asset as a ZIP archive,
    which is saved as-is. If asset_id is omitted, every asset of the resource
    is downloaded.

    Args:
        resource_id: ID of the resource (dataset) whose assets to download
        asset_id: Optional ID of a single asset to download
        dest_dir: Directory to write files into. Defaults to the
            GEONODE_ASSET_DOWNLOAD_DIR environment variable, then the current
            working directory. Created if it does not exist.

    Returns:
        Dictionary listing the resource's assets and the files written
    """
    client = get_client()

    resolved_dir = dest_dir or _load_asset_download_dir() or os.getcwd()
    dest_path = Path(resolved_dir).expanduser()
    try:
        dest_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"error": f"Invalid destination directory '{resolved_dir}': {e}"}

    try:
        payload = await client.request("GET", f"resources/{resource_id}")
    except Exception as e:
        return {"error": f"Failed to load resource {resource_id}: {e}"}

    assets = _asset_descriptors_from_links(_unwrap_resource(payload).get("links"))
    if not assets:
        return {
            "resource_id": resource_id,
            "dest_dir": str(dest_path),
            "assets": [],
            "downloaded": [],
            "errors": [],
            "message": f"Resource {resource_id} has no assets to download.",
        }

    if asset_id is not None:
        selected = [asset for asset in assets if asset["asset_id"] == asset_id]
        if not selected:
            return {
                "error": (
                    f"Asset {asset_id} is not attached to resource {resource_id}."
                ),
                "assets": assets,
            }
    else:
        selected = assets

    downloaded: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for asset in selected:
        current_id = asset["asset_id"]
        if current_id is None:
            errors.append(
                {
                    "asset": asset,
                    "error": "Could not determine asset id from resource links.",
                }
            )
            continue

        url = f"{client.base_url}/api/v2/assets/{current_id}/download"
        try:
            result = await client.download_to_file(
                url, dest_path, f"asset_{current_id}.zip"
            )
            downloaded.append(
                {
                    "asset_id": current_id,
                    "name": asset.get("name") or asset.get("title"),
                    "file_path": result["file_path"],
                    "size_bytes": result["size_bytes"],
                }
            )
        except Exception as e:
            errors.append({"asset_id": current_id, "error": str(e)})

    return {
        "resource_id": resource_id,
        "dest_dir": str(dest_path),
        "assets": assets,
        "downloaded": downloaded,
        "errors": errors,
    }


@mcp.tool()
async def upload_dataset(
    base_file_path: str,
    title: Optional[str] = None,
    abstract: Optional[str] = None,
    overwrite_existing: bool = False,
    skip_existing: bool = False,
) -> Dict[str, Any]:
    """
    Upload a dataset to GeoNode.

    Args:
        base_file_path: Path to the main dataset file (e.g., .shp, .tif)
        title: Title for the dataset (optional)
        abstract: Abstract/description for the dataset (optional)
        overwrite_existing: Whether to overwrite existing datasets with same name
        skip_existing: Whether to skip upload if dataset already exists

    Returns:
        Dictionary containing upload status and execution information
    """
    client = get_client()

    try:
        # Check if file exists
        if not os.path.exists(base_file_path):
            return {"error": f"File not found: {base_file_path}"}

        # Prepare files for upload
        files = {}
        base_name = os.path.splitext(base_file_path)[0]
        file_ext = os.path.splitext(base_file_path)[1].lower()

        # Main file
        with open(base_file_path, "rb") as f:
            files["base_file"] = (
                os.path.basename(base_file_path),
                f.read(),
                "application/octet-stream",
            )

        # For shapefiles, include supporting files
        if file_ext == ".shp":
            for ext in [".dbf", ".shx", ".prj", ".sld"]:
                support_file = base_name + ext
                if os.path.exists(support_file):
                    with open(support_file, "rb") as f:
                        field_name = ext[1:] + "_file"  # .dbf -> dbf_file
                        files[field_name] = (
                            os.path.basename(support_file),
                            f.read(),
                            "application/octet-stream",
                        )

        # Prepare form data
        data = {}
        if title:
            data["title"] = title
        if abstract:
            data["abstract"] = abstract
        if overwrite_existing:
            data["overwrite_existing_layer"] = "True"
        if skip_existing:
            data["skip_existing_layers"] = "True"

        async with upload_semaphore:
            result = await client.request(
                "POST", "uploads/upload", data=data, files=files
            )
        return result
    except Exception as e:
        return {"error": f"Failed to upload dataset: {e}"}


@mcp.tool()
async def upload_document(
    file_path: Optional[str] = None,
    doc_url: Optional[str] = None,
    title: str = "Uploaded Document",
    abstract: Optional[str] = None,
    extension: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload a document to GeoNode or reference a remote document.

    Args:
        file_path: Path to local file to upload (optional)
        doc_url: URL of remote document (optional)
        title: Title for the document
        abstract: Abstract/description for the document (optional)
        extension: File extension for remote documents (required if URL doesn't have extension)

    Returns:
        Dictionary containing upload status
    """
    client = get_client()

    if not file_path and not doc_url:
        return {"error": "Either file_path or doc_url must be provided"}

    try:
        data = {"title": title}
        if abstract:
            data["abstract"] = abstract

        files = None
        if file_path:
            # Local file upload
            if not os.path.exists(file_path):
                return {"error": f"File not found: {file_path}"}

            with open(file_path, "rb") as f:
                files = {
                    "doc_file": (
                        os.path.basename(file_path),
                        f.read(),
                        "application/octet-stream",
                    )
                }
        else:
            # Remote document reference
            data["doc_url"] = doc_url
            if extension:
                data["extension"] = extension

        async with upload_semaphore:
            result = await client.request("POST", "documents", data=data, files=files)
        return result
    except Exception as e:
        return {"error": f"Failed to upload document: {e}"}


@mcp.tool()
async def upload_dataset_metadata_xml(
    dataset_id: int,
    xml_file_path: str,
) -> Dict[str, Any]:
    """
    Upload an ISO 19139 metadata XML file to an existing dataset.

    Args:
        dataset_id: ID of the dataset to update
        xml_file_path: Local path to the ISO metadata XML file

    Returns:
        Dictionary containing upload status
    """
    client = get_client()

    if not os.path.exists(xml_file_path):
        return {"error": f"File not found: {xml_file_path}"}

    url = f"{client.base_url}/api/v2/uploads/upload"
    headers = {k: v for k, v in client.headers.items() if k != "Content-Type"}

    try:
        with open(xml_file_path, "rb") as f:
            xml_content = f.read()

        filename = os.path.basename(xml_file_path)
        files = [
            ("base_file", (filename, xml_content, "text/xml")),
            ("xml_file", (filename, xml_content, "text/xml")),
        ]
        data = {
            "action": "resource_metadata_upload",
            "resource_pk": str(dataset_id),
        }

        logger.debug(
            "upload_dataset_metadata_xml: POST %s resource_pk=%s (%d bytes)",
            url,
            dataset_id,
            len(xml_content),
        )

        async with httpx.AsyncClient(verify=client.config.verify_ssl, follow_redirects=True) as http:
            response = await http.post(url, headers=headers, files=files, data=data)

        logger.debug(
            "upload_dataset_metadata_xml response: status=%s content_type=%s",
            response.status_code,
            response.headers.get("content-type", ""),
        )

        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {
            "status": "ok",
            "http_status": response.status_code,
            "content": response.text,
        }

    except httpx.HTTPStatusError as e:
        return {
            "error": f"HTTP {e.response.status_code} uploading metadata XML: {e.response.text}"
        }
    except Exception as e:
        return {"error": f"Failed to upload metadata XML: {e}"}


@mcp.tool()
async def delete_resource(resource_id: int) -> Dict[str, Any]:
    """
    Delete a resource from GeoNode.

    Args:
        resource_id: ID of the resource to delete

    Returns:
        Dictionary containing deletion status
    """
    client = get_client()

    try:
        await client.request("DELETE", f"resources/{resource_id}")
        return {"message": f"Resource {resource_id} deleted successfully"}
    except TimeoutError:
        # The DELETE itself timed out client-side, so we don't actually know
        # whether GeoNode processed it. Rather than reporting a bare failure
        # (which invites an unnecessary and potentially confusing retry),
        # check the resource's real state before answering.
        logger.warning(
            "Delete request for resource %s timed out; verifying actual state "
            "with a follow-up GET before reporting an outcome",
            resource_id,
        )
        try:
            await client.request("GET", f"resources/{resource_id}")
        except httpx.HTTPStatusError as verify_err:
            if verify_err.response.status_code == 404:
                return {
                    "message": f"Resource {resource_id} deleted successfully",
                    "note": (
                        "The initial delete request timed out waiting for a "
                        "response, but a follow-up check confirmed the resource "
                        "no longer exists."
                    ),
                }
            return {
                "error": (
                    f"Delete request for resource {resource_id} timed out, and "
                    "the follow-up verification check itself failed "
                    f"(HTTP {verify_err.response.status_code}). Resource status "
                    "is unknown; please check manually before retrying."
                )
            }
        except Exception:
            return {
                "error": (
                    f"Delete request for resource {resource_id} timed out, and "
                    "the follow-up verification check also failed. Resource "
                    "status is unknown; please check manually before retrying."
                )
            }
        else:
            # GET succeeded, meaning the resource still exists: the delete
            # genuinely did not take effect.
            return {
                "error": (
                    f"Delete request for resource {resource_id} timed out, and "
                    "the resource still exists on GeoNode. The delete did not "
                    "take effect; it is safe to retry."
                )
            }
    except Exception as e:
        return {"error": f"Failed to delete resource: {e}"}


@mcp.tool()
async def update_dataset_metadata(
    dataset_id: int,
    title: Optional[str] = None,
    abstract: Optional[str] = None,
    edition: Optional[str] = None,
    license_id: Optional[str] = None,
    category: Optional[str] = None,
    owner: Optional[Dict[str, Any]] = None,
    point_of_contact: Optional[Dict[str, Any]] = None,
    hkeywords: Optional[List[str]] = None,
    regions: Optional[List[str]] = None,
    temporal_extent_start: Optional[str] = None,
    temporal_extent_end: Optional[str] = None,
    attribution: Optional[str] = None,
    maintenance_frequency: Optional[str] = None,
    supplemental_information: Optional[str] = None,
    purpose: Optional[str] = None,
    tkeywords: Optional[List[Dict[str, List[str]]]] = None,
) -> Dict[str, Any]:
    """
    Update metadata for a dataset.

    Args:
        dataset_id: ID of the metadata instance to update
        title: New title (optional)
        abstract: New abstract/description (optional)
        edition: Edition/version label for the dataset metadata (optional)
        license_id: New license ID (optional)
        category: Category name to resolve via gn_description filter
        owner: Owner contact object, e.g. {"id": 1, "label": "John"}
        point_of_contact: POC contact object, e.g. {"id": 2, "label": "Jane"}
        hkeywords: Pre-split keywords list (from CSV `Keywords` column)
        regions: Region labels or code to associate with the metadata record
        temporal_extent_start: Temporal extent start date/time
        temporal_extent_end: Temporal extent end date/time
        attribution: Attribution statement
        maintenance_frequency: Maintenance frequency value
        supplemental_information: Supplemental information text
        purpose: Purpose of the dataset (optional)
        tkeywords: List of dictionaries mapping thesaurus name to keyword IDs.
            Example: [{"themes": ["id1", "id2"]}, {"place": ["id3"]}]

    Returns:
        Dictionary containing update status
    """
    client = get_client()

    # maintenace frequencies:
    UPDATE_FREQUENCIES = (
        ("unknown", "frequency of maintenance for the data is not known"),
        ("continual", "data is repeatedly and frequently updated"),
        ("notPlanned", "there are no plans to update the data"),
        ("daily", "data is updated each day"),
        ("annually", "data is updated every year"),
        ("asNeeded", "data is updated as deemed necessary"),
        ("monthly", "data is updated each month"),
        ("fortnightly", "data is updated every two weeks"),
        ("irregular", "data is updated in intervals that are uneven in duration"),
        ("weekly", "data is updated on a weekly basis"),
        ("biannually", "data is updated twice each year"),
        ("quarterly", "data is updated every three months"),
    )

    data: Dict[str, Any] = {}
    if title is not None:
        data["title"] = title
    if abstract is not None:
        data["abstract"] = abstract
    if edition is not None:
        data["edition"] = edition
    if license_id is not None:
        data["license"] = {"id": license_id}
    if attribution is not None:
        data["attribution"] = attribution
    if maintenance_frequency is not None:
        maintenance_frequency_clean = maintenance_frequency.strip().lower()
        # use UPDATE_FREQUENCIES to get the code value for the provided label, or validate if the provided value is already a valid code
        valid_codes = {code for code, label in UPDATE_FREQUENCIES}
        label_to_code = {label.lower(): code for code, label in UPDATE_FREQUENCIES}
        if maintenance_frequency_clean in valid_codes:
            maintenance_frequency_code = maintenance_frequency_clean
        elif maintenance_frequency_clean in label_to_code:
            maintenance_frequency_code = label_to_code[maintenance_frequency_clean]
        else:
            raise ValueError(
                f"Invalid maintenance frequency: '{maintenance_frequency}'"
            )
        data["maintenance_frequency"] = maintenance_frequency_code
    if supplemental_information is not None:
        data["supplemental_information"] = supplemental_information
    if purpose is not None:
        data["purpose"] = purpose

    contacts_payload: Dict[str, Any] = {}
    if owner is not None:
        owner_id = owner.get("id")
        owner_label = owner.get("label")
        if (
            owner_id is None
            or not isinstance(owner_label, str)
            or not owner_label.strip()
        ):
            raise ValueError("owner must include non-empty label and id")
        try:
            owner_id_int = int(owner_id)
        except (TypeError, ValueError):
            raise ValueError("owner id must be an integer")
        contacts_payload["owner"] = {"id": owner_id_int, "label": owner_label.strip()}

    if point_of_contact is not None:
        poc_id = point_of_contact.get("id")
        poc_label = point_of_contact.get("label")
        if poc_id is None or not isinstance(poc_label, str) or not poc_label.strip():
            raise ValueError("point_of_contact must include non-empty label and id")
        try:
            poc_id_int = int(poc_id)
        except (TypeError, ValueError):
            raise ValueError("point_of_contact id must be an integer")
        contacts_payload["pointOfContact"] = [
            {
                "id": poc_id_int,
                "label": poc_label.strip(),
            }
        ]

    if contacts_payload:
        data["contacts"] = contacts_payload

    if hkeywords is not None:
        if not isinstance(hkeywords, list):
            raise ValueError("hkeywords must be a list of strings")
        parsed_hkeywords: List[str] = []
        for keyword in hkeywords:
            if not isinstance(keyword, str):
                raise ValueError("hkeywords must be a list of strings")
            cleaned_keyword = keyword.strip()
            if cleaned_keyword and cleaned_keyword not in parsed_hkeywords:
                parsed_hkeywords.append(cleaned_keyword)
        data["hkeywords"] = parsed_hkeywords

    if category is not None:
        category_clean = category.strip()
        if not category_clean:
            raise ValueError("category must be a non-empty string")

        categories_result = await client.request(
            "GET",
            "categories",
            params={"filter{gn_description}": category_clean, "page_size": 100},
        )
        matched_category: Optional[Dict[str, Any]] = None
        if categories_result.get("total") == 0:
            raise ValueError(f"No category found matching name: '{category_clean}'")
        elif categories_result.get("total", 0) > 1:
            raise ValueError(
                f"Multiple categories found matching name: '{category_clean}'"
            )
        elif categories_result.get("total") == 1:
            matched_category = categories_result["categories"][0]

        if matched_category:
            category_id = matched_category.get("identifier")
            matched_category_label = matched_category.get("gn_description")
            if category_id is None:
                raise ValueError(
                    f"Resolved category '{matched_category_label}' does not have an id"
                )
            data["category"] = {"id": category_id, "label": matched_category_label}

    if regions is not None:
        cleaned_regions = []
        for region in regions:
            if not isinstance(region, str) or not region.strip():
                raise ValueError("Each regions value must be a non-empty string")
            cleaned_regions.append(region.strip())

        resolved_regions: List[Dict[str, Any]] = []
        for region_name in cleaned_regions:
            # Assume it's a code and use list_regions with code filter to resolve the name
            if len(region_name) == 3:
                regions_result = await client.request(
                    "GET",
                    "regions",
                    params={"filter{code}": region_name, "page_size": 100},
                )
            else:
                regions_result = await client.request(
                    "GET",
                    "regions",
                    params={"filter{name}": region_name, "page_size": 100},
                )
            if regions_result.get("total") == 0:
                raise ValueError(f"No region found matching name: '{region_name}'")
            elif regions_result.get("total", 0) > 1:
                raise ValueError(
                    f"Multiple regions found matching name: '{region_name}'"
                )
            elif regions_result.get("total") == 1:
                matched_region = regions_result["regions"][0]
                resolved_regions.append(
                    {"id": matched_region.get("id"), "name": matched_region.get("name")}
                )

        data["regions"] = resolved_regions

    if temporal_extent_start is not None or temporal_extent_end is not None:
        if temporal_extent_start is not None:
            data["temporal_extent_start"] = temporal_extent_start
        if temporal_extent_end is not None:
            data["temporal_extent_end"] = temporal_extent_end

    if tkeywords is not None:
        tkeywords_payload: Dict[str, List[Dict[str, str]]] = {}

        for entry in tkeywords:
            if not isinstance(entry, dict):
                raise ValueError(
                    'Each tkeywords entry must be an object like {"themes": ["id1", "id2"]}'
                )

            for thesaurus_name, keyword_ids in entry.items():
                if not isinstance(thesaurus_name, str) or not thesaurus_name.strip():
                    raise ValueError(
                        "Each tkeywords thesaurus name must be a non-empty string"
                    )
                if not isinstance(keyword_ids, list):
                    raise ValueError(
                        f"tkeywords for thesaurus '{thesaurus_name}' must be a list of IDs"
                    )

                existing_ids = {
                    item["id"] for item in tkeywords_payload.get(thesaurus_name, [])
                }
                for keyword_id in keyword_ids:
                    if not isinstance(keyword_id, str) or not keyword_id.strip():
                        raise ValueError(
                            f"Invalid keyword id in thesaurus '{thesaurus_name}': all IDs must be non-empty strings"
                        )
                    keyword_id_clean = keyword_id.strip()
                    if keyword_id_clean not in existing_ids:
                        tkeywords_payload.setdefault(thesaurus_name, []).append(
                            {"id": keyword_id_clean}
                        )
                        existing_ids.add(keyword_id_clean)

        data["tkeywords"] = tkeywords_payload

    if not data:
        raise ValueError("No metadata fields provided for update")
    logger.debug(
        "update_dataset_metadata metadata payload (dataset_id=%s): %s",
        dataset_id,
        _sanitize_for_logging(data),
    )
    return await client.request("PATCH", f"metadata/instance/{dataset_id}", data=data)


@mcp.tool()
async def update_dataset_settings(
    dataset_id: int,
    group_name: Optional[str] = None,
    is_published: Optional[bool] = None,
    is_approved: Optional[bool] = None,
    advertised: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Update dataset-level settings on the dataset endpoint.

    Args:
        dataset_id: ID of the dataset to update
        group_name: Group name to resolve and assign on the dataset endpoint
        is_published: Whether the dataset should be published (optional)
        is_approved: Whether the dataset should be approved (optional)
        advertised: Whether the dataset should be advertised (optional)

    Returns:
        Dictionary containing update status
    """
    client = get_client()
    dataset_patch_data: Dict[str, Any] = {}
    resolved_group: Optional[Dict[str, Any]] = None

    if group_name is not None:
        group_name_clean = group_name.strip()
        if not group_name_clean:
            return {"error": "group_name must be a non-empty string"}
        groups_result = await client.request(
            "GET",
            "groups",
            params={"filter{title}": group_name_clean, "page_size": 100},
        )
        if groups_result.get("total") == 0:
            return {"error": f"No groups found matching name: '{group_name_clean}'"}
        if groups_result.get("total", 0) > 1:
            return {
                "error": f"Multiple groups found matching name: '{group_name_clean}'"
            }
        matched_group = groups_result["group_profiles"][0]
        group_data = matched_group.get("group") or {}
        group_pk = group_data.get("pk")
        matched_group_name = matched_group.get("title")
        if group_pk is None:
            return {
                "error": f"Resolved group '{matched_group_name}' does not have a pk/id"
            }
        resolved_group = {"pk": group_pk, "name": group_data.get("name")}
        dataset_patch_data["group"] = resolved_group

    if is_published is not None:
        dataset_patch_data["is_published"] = is_published
    if advertised is not None:
        dataset_patch_data["advertised"] = advertised
    if is_approved is not None:
        dataset_patch_data["is_approved"] = is_approved
    if not dataset_patch_data:
        return {"error": "No dataset settings provided for update"}

    try:
        logger.debug(
            "update_dataset_settings dataset payload (dataset_id=%s): %s",
            dataset_id,
            _sanitize_for_logging(dataset_patch_data),
        )
        dataset_update_result = await client.request(
            "PATCH",
            f"datasets/{dataset_id}",
            data=dataset_patch_data,
        )
        if resolved_group is not None:
            return {
                "dataset_update": dataset_update_result,
                "resolved_group": resolved_group,
            }
        return dataset_update_result
    except Exception as e:
        return {"error": f"Failed to update dataset settings: {e}"}


@mcp.tool()
async def list_users(page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    """
    List users in GeoNode.

    Args:
        page: Page number for pagination
        page_size: Number of items per page

    Returns:
        Dictionary containing users list
    """
    client = get_client()

    params = {"page": page, "page_size": page_size}

    try:
        result = await client.request("GET", "users", params=params)
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list users: {e}") from e


@mcp.tool()
async def get_user_details(user_id: int) -> Dict[str, Any]:
    """
    Get detailed information about a specific user.

    Args:
        user_id: ID of the user to retrieve

    Returns:
        Dictionary containing user information
    """
    client = get_client()

    try:
        result = await client.request("GET", f"users/{user_id}")
        return result
    except Exception as e:
        return {"error": f"Failed to get user details: {e}"}


@mcp.tool()
async def create_user(
    username: str,
    password: str,
    email: str,
    first_name: str,
    last_name: str,
    avatar: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new user in GeoNode.

    Args:
        username: Username for the new user
        password: Password for the new user
        email: Email address
        first_name: First name
        last_name: Last name
        avatar: Avatar URL (optional)

    Returns:
        Dictionary containing creation status
    """
    client = get_client()

    data = {
        "username": username,
        "password": password,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
    }

    if avatar:
        data["avatar"] = avatar

    try:
        result = await client.request("POST", "users", data=data)
        return result
    except Exception as e:
        return {"error": f"Failed to create user: {e}"}


@mcp.tool()
async def get_resource_permissions(resource_id: int) -> Dict[str, Any]:
    """
    Get permissions set on a resource.

    Args:
        resource_id: ID of the resource

    Returns:
        Dictionary containing permission information
    """
    client = get_client()

    try:
        result = await client.request("GET", f"resources/{resource_id}/permissions")
        return result
    except Exception as e:
        return {"error": f"Failed to get resource permissions: {e}"}


@mcp.tool()
async def set_resource_permissions(
    resource_id: int,
    users: Optional[List[Dict[str, Any]]] = None,
    groups: Optional[List[Dict[str, Any]]] = None,
    organizations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Set permissions on a resource.

    Args:
        resource_id: ID of the resource
        users: List of user permissions (e.g., [{"id": 1, "permissions": "edit"}])
        groups: List of group permissions (e.g., [{"id": 2, "permissions": "view"}])
        organizations: List of organization permissions

    Returns:
        Dictionary containing permission update status
    """
    client = get_client()

    perm_spec = {}
    if users:
        perm_spec["users"] = users
    if groups:
        perm_spec["groups"] = groups
    if organizations:
        perm_spec["organizations"] = organizations

    if not perm_spec:
        return {"error": "No permissions provided"}

    try:
        result = await client.request(
            "PUT", f"resources/{resource_id}/permissions", data=perm_spec
        )
        return result
    except Exception as e:
        return {"error": f"Failed to set resource permissions: {e}"}


@mcp.tool()
async def check_upload_status(execution_id: str) -> Dict[str, Any]:
    """
    Check the status of an upload operation.

    Args:
        execution_id: ID of the execution request

    Returns:
        Dictionary containing execution status
    """
    client = get_client()

    try:
        result = await client.request("GET", f"executionrequest/{execution_id}")
        return result
    except Exception as e:
        return {"error": f"Failed to check upload status: {e}"}


@mcp.tool()
async def list_linked_resources(resource_id: int) -> Dict[str, Any]:
    """
    List resources linked to a specific resource.

    Args:
        resource_id: ID of the resource

    Returns:
        Dictionary containing linked resources
    """
    client = get_client()

    try:
        result = await client.request(
            "GET", f"resources/{resource_id}/linked_resources"
        )
        return result
    except Exception as e:
        raise RuntimeError(f"Failed to list linked resources: {e}") from e


def main():
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()

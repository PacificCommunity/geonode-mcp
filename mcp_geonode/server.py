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
from typing import Any, Dict, List, Optional

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


class GeoNodeConfig(BaseModel):
    """Configuration for GeoNode connection."""

    base_url: HttpUrl
    username: Optional[str] = None
    password: Optional[str] = None
    token: Optional[str] = None
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> Optional["GeoNodeConfig"]:
        """Create GeoNodeConfig from environment variables.

        Environment variables:
        - GEONODE_BASE_URL: Base URL of the GeoNode instance
        - GEONODE_USERNAME: Username for authentication (optional)
        - GEONODE_PASSWORD: Password for authentication (optional)
        - GEONODE_TOKEN: Bearer token for authentication (optional)
        - GEONODE_VERIFY_SSL: Whether to verify SSL certificates (default: true)
        - GEONODE_MAX_CONCURRENT_UPLOADS: Upload concurrency limit (default: 5)

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

        try:
            return cls(
                base_url=base_url,
                username=username,
                password=password,
                token=token,
                verify_ssl=verify_ssl,
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

        async with httpx.AsyncClient(verify=self.config.verify_ssl) as client:
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

                response.raise_for_status()

                # Handle different content types
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    return response.json()
                else:
                    return {"content": response.text, "content_type": content_type}

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Request failed: {e}")
                raise


# Create the MCP server
mcp = FastMCP("GeoNode MCP Server")

# Global client instance (will be set based on configuration)
geonode_client: Optional[GeoNodeClient] = None
MAX_CONCURRENT_UPLOADS = _load_max_concurrent_uploads()
upload_semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)


# Try to auto-configure from environment on startup
def _auto_configure_from_env():
    """Automatically configure GeoNode client from environment variables if available."""
    global geonode_client

    if geonode_client is None:
        env_config = GeoNodeConfig.from_env()
        if env_config:
            geonode_client = GeoNodeClient(env_config)
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
            "- GEONODE_MAX_CONCURRENT_UPLOADS (optional, default: 5)\n"
            "\nOr create a .env file with these variables."
        )
    return geonode_client


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
        "configuration_source": "environment",
        "base_url": None,
        "has_username": False,
        "has_token": False,
        "verify_ssl": True,
        "max_concurrent_uploads": MAX_CONCURRENT_UPLOADS,
        "env_vars_available": {},
    }

    # Check environment variables
    env_vars = {
        "GEONODE_BASE_URL": os.getenv("GEONODE_BASE_URL"),
        "GEONODE_USERNAME": os.getenv("GEONODE_USERNAME"),
        "GEONODE_PASSWORD": "***" if os.getenv("GEONODE_PASSWORD") else None,
        "GEONODE_TOKEN": "***" if os.getenv("GEONODE_TOKEN") else None,
        "GEONODE_VERIFY_SSL": os.getenv("GEONODE_VERIFY_SSL", "true"),
        "GEONODE_MAX_CONCURRENT_UPLOADS": os.getenv("GEONODE_MAX_CONCURRENT_UPLOADS"),
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
    page: int = 1,
    page_size: int = 20,
    featured: Optional[bool] = None,
    published: Optional[bool] = None,
    approved: Optional[bool] = None,
    category: Optional[str] = None,
    keywords: Optional[str] = None,
    thesaurus_keywords: Optional[str] = None,
    owner: Optional[str] = None,
    extent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List GeoNode resources with filtering options.

    Args:
        resource_type: Type of resource (dataset, map, document, service, geostory, dashboard)
        search: Free text search in title and abstract
        page: Page number for pagination (default: 1)
        page_size: Number of items per page (default: 20)
        featured: Filter by featured status
        published: Filter by published status
        approved: Filter by approved status
        category: Filter by category identifier
        keywords: Filter by keyword name
        thesaurus_keywords: Filter by thesaurus keyword term
        owner: Filter by owner username
        extent: Bounding box extent as "minx,miny,maxx,maxy"

    Returns:
        Dictionary containing resources list and metadata
    """
    client = get_client()

    params = {"page": page, "page_size": page_size}

    # Add search parameters
    if search:
        params["search"] = search
        params["search_fields"] = ["title", "abstract"]

    # Add filter parameters
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
        return {"error": f"Failed to list resources: {e}"}


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
        return {"error": f"Failed to list categories: {e}"}


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
        return {"error": f"Failed to list tkeywords: {e}"}


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
            # For datasets, first get the resource details to find the alternate name
            resource = await client.request("GET", f"resources/{resource_id}")
            alternate = resource.get("alternate")
            if alternate:
                download_url = (
                    f"{client.base_url}/datasets/{alternate}/dataset_download"
                )
            else:
                return {"error": "Could not find dataset alternate name for download"}
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
async def search_resources(
    query: str,
    search_fields: List[str] = ["title", "abstract"],
    resource_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Search resources by text query.

    Args:
        query: Search query text
        search_fields: Fields to search in (title, abstract)
        resource_type: Filter by resource type (optional)
        page: Page number for pagination
        page_size: Number of items per page

    Returns:
        Dictionary containing search results
    """
    client = get_client()

    params = {"search": query, "page": page, "page_size": page_size}

    for field in search_fields:
        params["search_fields"] = field

    if resource_type:
        params["filter{resource_type}"] = resource_type

    try:
        result = await client.request("GET", "resources", params=params)
        return result
    except Exception as e:
        return {"error": f"Failed to search resources: {e}"}


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
        await client.request("DELETE", f"resources/{resource_id}/delete")
        return {"message": f"Resource {resource_id} deleted successfully"}
    except Exception as e:
        return {"error": f"Failed to delete resource: {e}"}


@mcp.tool()
async def update_dataset_metadata(
    dataset_id: int,
    title: Optional[str] = None,
    abstract: Optional[str] = None,
    license_id: Optional[int] = None,
    keywords: Optional[List[str]] = None,
    regions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Update metadata for a dataset.

    Args:
        dataset_id: ID of the dataset to update
        title: New title (optional)
        abstract: New abstract/description (optional)
        license_id: New license ID (optional)
        keywords: List of keywords (optional)
        regions: List of regions (optional)

    Returns:
        Dictionary containing update status
    """
    client = get_client()

    data = {}
    if title:
        data["title"] = title
    if abstract:
        data["abstract"] = abstract
    if license_id:
        data["license"] = license_id
    if keywords:
        data["keywords"] = keywords
    if regions:
        data["regions"] = regions

    if not data:
        return {"error": "No metadata fields provided for update"}

    try:
        result = await client.request("PATCH", f"datasets/{dataset_id}", data=data)
        return result
    except Exception as e:
        return {"error": f"Failed to update dataset metadata: {e}"}


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
        return {"error": f"Failed to list users: {e}"}


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
        return {"error": f"Failed to list linked resources: {e}"}


def main():
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()

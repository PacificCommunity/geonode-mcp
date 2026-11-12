"""MCP Server for GeoNode API."""

from ._version import __version__
from .server import main

__all__ = ["main", "__version__"]

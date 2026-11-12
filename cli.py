#!/usr/bin/env python3
"""Compatibility shim for `python cli.py`.

The CLI lives in :mod:`mcp_geonode.cli` so that the ``mcp-geonode-cli``
console script works from an installed package.
"""

from mcp_geonode.cli import main_cli

if __name__ == "__main__":
    main_cli()

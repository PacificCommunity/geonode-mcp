#!/usr/bin/env python3
"""Command-line interface for MCP GeoNode Server and direct tool execution."""

import argparse
import asyncio
import inspect
import json
import logging
import sys
from typing import Any, Callable, Dict

import mcp_geonode.server as server


TOOL_NAMES = (
    "configure_geonode",
    "get_configuration_status",
    "list_resources",
    "list_groups",
    "list_categories",
    "list_tkeywords",
    "get_resource_details",
    "get_dataset_details",
    "download_resource",
    "download_asset",
    "upload_dataset",
    "upload_document",
    "delete_resource",
    "update_dataset_metadata",
    "update_dataset_settings",
    "list_users",
    "get_user_details",
    "create_user",
    "get_resource_permissions",
    "set_resource_permissions",
    "check_upload_status",
    "list_linked_resources",
)


def _tool_registry() -> Dict[str, Callable[..., Any]]:
    return {name: getattr(server, name) for name in TOOL_NAMES}


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="MCP Server for GeoNode API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version="MCP GeoNode Server 0.1.0"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run MCP server (default)")
    serve_parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol for MCP communication (default: stdio)",
    )

    subparsers.add_parser("list-tools", help="List directly callable tool names")

    call_parser = subparsers.add_parser("call", help="Call a tool directly")
    call_parser.add_argument("tool", choices=TOOL_NAMES, help="Tool name")
    call_parser.add_argument(
        "--args",
        default="{}",
        help="Tool arguments as JSON object, e.g. '{\"page_size\": 50}'",
    )
    call_parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )
    return parser


def _print_json(value: Any, pretty: bool = False) -> None:
    if pretty:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(value, ensure_ascii=False, default=str))


async def _call_tool(tool_name: str, args_json: str, pretty: bool) -> int:
    registry = _tool_registry()
    tool = registry[tool_name]
    try:
        kwargs = json.loads(args_json)
    except json.JSONDecodeError as exc:
        print(f"Invalid --args JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(kwargs, dict):
        print("--args must decode to a JSON object", file=sys.stderr)
        return 2

    try:
        if inspect.iscoroutinefunction(tool):
            result = await tool(**kwargs)
        else:
            result = tool(**kwargs)
        _print_json(result, pretty=pretty)
        return 0
    except Exception as exc:
        print(f"Tool {tool_name} failed: {exc}", file=sys.stderr)
        return 1


def _run_server(transport: str) -> int:
    if transport != "stdio":
        print(f"Warning: {transport} transport not yet implemented, using stdio")
    server.main()
    return 0


def main_cli() -> None:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("mcp_geonode").setLevel(logging.DEBUG)

    # Backward compatibility: default behavior remains starting the server.
    command = args.command or "serve"
    if command == "serve":
        exit_code = _run_server(getattr(args, "transport", "stdio"))
    elif command == "list-tools":
        for tool_name in TOOL_NAMES:
            print(tool_name)
        exit_code = 0
    elif command == "call":
        exit_code = asyncio.run(_call_tool(args.tool, args.args, args.pretty))
    else:
        parser.print_help()
        exit_code = 2

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main_cli()

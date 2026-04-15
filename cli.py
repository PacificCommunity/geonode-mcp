#!/usr/bin/env python3
"""
Command-line interface for MCP GeoNode Server
"""

import argparse
import asyncio
import sys
from mcp_geonode.server import main


def create_parser():
    """Create command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="MCP Server for GeoNode API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                     # Start server with default settings
  %(prog)s --help              # Show this help message

The server provides MCP tools for:
  • Resource management (list, search, details, upload, download)
  • User management (list, create, details)
  • Permission management (view, set permissions)
  • Data upload/download operations

Configure GeoNode connection using the configure_geonode tool.
        """
    )
    
    parser.add_argument(
        "--version",
        action="version",
        version="MCP GeoNode Server 0.1.0"
    )
    
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="Transport protocol for MCP communication (default: stdio)"
    )
    
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for HTTP transports (default: 127.0.0.1)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transports (default: 8000)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser


def main_cli():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if args.debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)
        print("Debug logging enabled")
    
    print("Starting MCP GeoNode Server...")
    print(f"Transport: {args.transport}")
    
    if args.transport in ["sse", "streamable-http"]:
        print(f"Address: http://{args.host}:{args.port}")
    
    # Check for environment configuration
    import os
    from pathlib import Path
    
    env_file = Path(".env")
    if env_file.exists():
        print(f"\n✓ Found .env file: {env_file}")
    
    base_url = os.getenv("GEONODE_BASE_URL")
    if base_url:
        print(f"✓ Environment configuration available for: {base_url}")
        print("  Server will auto-configure on startup")
    else:
        print("\nℹ No environment configuration found")
        print("  Configure using:")
        print("  1. Create .env file (copy from .env.example)")
        print("  2. Set GEONODE_BASE_URL environment variable")
        print("  3. Use configure_geonode MCP tool")
    
    print("\nAvailable tools:")
    print("  • configure_geonode - Configure GeoNode connection")
    print("  • get_configuration_status - Check configuration status")
    print("  • list_resources - List and filter resources")
    print("  • list_categories - List available categories")
    print("  • list_tkeywords - List thesaurus taxonomy keywords")
    print("  • search_resources - Search resources by text")
    print("  • get_resource_details - Get resource information")
    print("  • upload_dataset - Upload spatial datasets")
    print("  • upload_document - Upload documents")
    print("  • download_resource - Get download URLs")
    print("  • list_users - List users")
    print("  • create_user - Create new users")
    print("  • get_resource_permissions - View permissions")
    print("  • set_resource_permissions - Configure permissions")
    print("  • And more...")
    
    if not base_url:
        print("\n📝 Quick setup:")
        print("  1. cp .env.example .env")
        print("  2. Edit .env with your GeoNode URL and credentials")
        print("  3. Restart this server")
    
    print("\nServer starting...\n")
    
    try:
        # Import and run the server with the specified transport
        if args.transport == "stdio":
            main()
        else:
            # For HTTP transports, we would need to modify the server
            # to support different transports. For now, default to stdio.
            print(f"Warning: {args.transport} transport not yet implemented, using stdio")
            main()
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Error starting server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main_cli()

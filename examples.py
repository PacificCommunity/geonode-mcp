#!/usr/bin/env python3
"""
Example usage of MCP GeoNode Server

This script shows how to use the MCP server to interact with GeoNode.
Run this after starting the MCP server.
"""

import asyncio
import json
from typing import Dict, Any


# Example functions that would be called through MCP protocol
# In practice, these would be called by an MCP client

async def example_workflow():
    """Example workflow showing GeoNode operations."""
    
    print("GeoNode MCP Server - Example Workflow")
    print("=" * 50)
    
    # Step 1: Configuration
    print("\n1. Configuring GeoNode connection...")
    print("   Tool: configure_geonode")
    print("   Args: {")
    print('     "base_url": "https://master.demo.geonode.org",')
    print('     "verify_ssl": true')
    print("   }")
    print("   Result: Successfully configured GeoNode client")
    
    # Step 2: List resources
    print("\n2. Listing available resources...")
    print("   Tool: list_resources")
    print("   Args: {")
    print('     "page": 1,')
    print('     "page_size": 5,')
    print('     "resource_type": "dataset"')
    print("   }")
    print("   Result: Would return first 5 datasets")
    
    # Step 3: Search resources
    print("\n3. Searching for climate-related resources...")
    print("   Tool: search_resources")
    print("   Args: {")
    print('     "query": "climate",')
    print('     "search_fields": ["title", "abstract"],')
    print('     "page_size": 3')
    print("   }")
    print("   Result: Would return climate-related resources")
    
    # Step 4: Get resource details
    print("\n4. Getting details for a specific resource...")
    print("   Tool: get_resource_details")
    print("   Args: {")
    print('     "resource_id": 1234')
    print("   }")
    print("   Result: Would return detailed resource information")
    
    # Step 5: Download information
    print("\n5. Getting download information...")
    print("   Tool: download_resource")
    print("   Args: {")
    print('     "resource_id": 1234,')
    print('     "resource_type": "dataset"')
    print("   }")
    print("   Result: Would return download URL")
    
    # Step 6: List users
    print("\n6. Listing users...")
    print("   Tool: list_users")
    print("   Args: {")
    print('     "page": 1,')
    print('     "page_size": 10')
    print("   }")
    print("   Result: Would return user list")
    
    # Step 7: Check permissions
    print("\n7. Checking resource permissions...")
    print("   Tool: get_resource_permissions")
    print("   Args: {")
    print('     "resource_id": 1234')
    print("   }")
    print("   Result: Would return permission information")


def show_available_tools():
    """Show all available tools in the MCP server."""
    
    tools = [
        {
            "name": "configure_geonode",
            "description": "Configure connection to GeoNode instance (overrides environment)",
            "category": "Configuration"
        },
        {
            "name": "get_configuration_status",
            "description": "Check current configuration status and source",
            "category": "Configuration"
        },
        {
            "name": "list_resources",
            "description": "List GeoNode resources with filtering options",
            "category": "Resource Management"
        },
        {
            "name": "list_categories",
            "description": "List available GeoNode categories",
            "category": "Resource Management"
        },
        {
            "name": "list_tkeywords",
            "description": "List GeoNode thesaurus taxonomy keywords",
            "category": "Resource Management"
        },
        {
            "name": "get_resource_details",
            "description": "Get detailed information about a specific resource",
            "category": "Resource Management"
        },
        {
            "name": "get_dataset_details",
            "description": "Get detailed information about a specific dataset",
            "category": "Resource Management"
        },
        {
            "name": "search_resources",
            "description": "Search resources by text query",
            "category": "Resource Management"
        },
        {
            "name": "download_resource",
            "description": "Get download information for a resource",
            "category": "Resource Management"
        },
        {
            "name": "upload_dataset",
            "description": "Upload a dataset to GeoNode",
            "category": "Data Upload"
        },
        {
            "name": "upload_document",
            "description": "Upload a document to GeoNode or reference a remote document",
            "category": "Data Upload"
        },
        {
            "name": "delete_resource",
            "description": "Delete a resource from GeoNode",
            "category": "Resource Management"
        },
        {
            "name": "update_dataset_metadata",
            "description": "Update metadata for a dataset",
            "category": "Resource Management"
        },
        {
            "name": "list_users",
            "description": "List users in GeoNode",
            "category": "User Management"
        },
        {
            "name": "get_user_details",
            "description": "Get detailed information about a specific user",
            "category": "User Management"
        },
        {
            "name": "create_user",
            "description": "Create a new user in GeoNode",
            "category": "User Management"
        },
        {
            "name": "get_resource_permissions",
            "description": "Get permissions set on a resource",
            "category": "Permissions"
        },
        {
            "name": "set_resource_permissions",
            "description": "Set permissions on a resource",
            "category": "Permissions"
        },
        {
            "name": "check_upload_status",
            "description": "Check the status of an upload operation",
            "category": "Data Upload"
        },
        {
            "name": "list_linked_resources",
            "description": "List resources linked to a specific resource",
            "category": "Resource Management"
        }
    ]
    
    print("Available MCP Tools")
    print("=" * 50)
    
    categories = {}
    for tool in tools:
        category = tool["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(tool)
    
    for category, category_tools in categories.items():
        print(f"\n{category}:")
        for tool in category_tools:
            print(f"  • {tool['name']}")
            print(f"    {tool['description']}")


def show_usage_examples():
    """Show usage examples for different scenarios."""
    
    examples = [
        {
            "title": "Environment Configuration",
            "description": "Use .env file for automatic configuration",
            "steps": [
                "Create .env file with: GEONODE_BASE_URL=https://demo.geonode.org",
                "Add credentials: GEONODE_USERNAME=user, GEONODE_PASSWORD=pass",
                "Start server - configuration loaded automatically",
                "get_configuration_status() - Check configuration source",
                "list_resources() - Start using tools immediately"
            ]
        },
        {
            "title": "Data Management with Authentication",
            "description": "Upload and manage your own data",
            "steps": [
                "configure_geonode(base_url='https://your-geonode.org', username='user', password='pass')",
                "upload_dataset(base_file_path='/path/to/data.shp', title='My Dataset')",
                "check_upload_status(execution_id='abc-123')",
                "update_dataset_metadata(dataset_id=456, abstract='Updated description', regions=['global'])"
            ]
        },
        {
            "title": "Permission Management",
            "description": "Manage resource permissions",
            "steps": [
                "get_resource_permissions(resource_id=123)",
                "set_resource_permissions(resource_id=123, users=[{'id': 1, 'permissions': 'edit'}])"
            ]
        },
        {
            "title": "User Administration",
            "description": "Manage users and groups",
            "steps": [
                "list_users(page=1, page_size=20)",
                "create_user(username='newuser', email='user@example.com', ...)",
                "get_user_details(user_id=123)"
            ]
        }
    ]
    
    print("Usage Examples")
    print("=" * 50)
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['title']}")
        print(f"   {example['description']}")
        print("   Steps:")
        for step in example['steps']:
            print(f"     • {step}")


async def main():
    """Main function to show examples and run workflow."""
    
    print("MCP GeoNode Server - Examples and Usage")
    print("=" * 50)
    
    print("\nChoose an option:")
    print("1. Show available tools")
    print("2. Show usage examples") 
    print("3. Run example workflow")
    print("4. Show all")
    
    try:
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == "1":
            show_available_tools()
        elif choice == "2":
            show_usage_examples()
        elif choice == "3":
            await example_workflow()
        elif choice == "4":
            show_available_tools()
            print("\n")
            show_usage_examples()
            print("\n")
            await example_workflow()
        else:
            print("Invalid choice. Showing all options...")
            show_available_tools()
            print("\n")
            show_usage_examples()
            print("\n")
            await example_workflow()
    
    except KeyboardInterrupt:
        print("\n\nExample session interrupted.")
    except Exception as e:
        print(f"\nError: {e}")
    
    print("\n" + "=" * 50)
    print("To use this MCP server:")
    print("1. Install dependencies: pip install mcp httpx pydantic")
    print("2. Run the server: python main.py")
    print("3. Connect with an MCP client")
    print("4. Configure GeoNode connection")
    print("5. Start using the tools!")


if __name__ == "__main__":
    asyncio.run(main())

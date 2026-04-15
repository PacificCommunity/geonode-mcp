#!/usr/bin/env python3
"""
Test script for MCP GeoNode Server

This script demonstrates how to use the MCP server for common GeoNode operations.
"""

import asyncio
import json
from mcp_geonode.server import mcp, configure_geonode


async def test_configuration():
    """Test GeoNode configuration."""
    print("Testing GeoNode configuration...")
    
    # Configure with public demo instance
    result = configure_geonode("https://master.demo.geonode.org")
    print(f"Configuration result: {result}")
    
    return "Successfully configured" in result


async def test_list_resources():
    """Test listing resources."""
    print("\nTesting resource listing...")
    
    try:
        # Get list_resources tool function directly from the server
        tools = await mcp.list_tools()
        list_resources_tool = None
        
        for tool in tools:
            if tool.name == "list_resources":
                list_resources_tool = tool
                break
        
        if list_resources_tool:
            print("Found list_resources tool")
            # Note: In a real test, you would call the tool through the MCP protocol
            print("Tool description:", list_resources_tool.description)
            return True
        else:
            print("list_resources tool not found")
            return False
            
    except Exception as e:
        print(f"Error testing resource listing: {e}")
        return False


async def main():
    """Run all tests."""
    print("MCP GeoNode Server Test Suite")
    print("=" * 40)
    
    tests = [
        ("Configuration", test_configuration),
        ("List Resources", test_list_resources),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
            status = "PASS" if result else "FAIL"
            print(f"{test_name}: {status}")
        except Exception as e:
            results.append((test_name, False))
            print(f"{test_name}: FAIL - {e}")
    
    print("\n" + "=" * 40)
    print("Test Summary:")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓" if result else "✗"
        print(f"  {status} {test_name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("All tests passed! 🎉")
        return 0
    else:
        print("Some tests failed. 😞")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
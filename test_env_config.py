#!/usr/bin/env python3
"""
Test environment configuration for MCP GeoNode Server
"""

import os
import sys
from pathlib import Path

# Add the parent directory to Python path to import mcp_geonode
sys.path.insert(0, str(Path(__file__).parent))

from mcp_geonode.server import GeoNodeConfig, GeoNodeClient, _auto_configure_from_env, geonode_client


def test_env_configuration():
    """Test environment variable configuration."""
    print("Testing Environment Configuration")
    print("=" * 50)
    
    # Test 1: Check for .env file
    env_file = Path(".env")
    if env_file.exists():
        print("✓ Found .env file")
        with open(env_file) as f:
            lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            print(f"  Contains {len(lines)} configuration lines")
    else:
        print("ℹ No .env file found")
    
    # Test 2: Check environment variables
    print("\nEnvironment Variables:")
    env_vars = [
        "GEONODE_BASE_URL",
        "GEONODE_USERNAME", 
        "GEONODE_PASSWORD",
        "GEONODE_TOKEN",
        "GEONODE_VERIFY_SSL"
    ]
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            if "PASSWORD" in var or "TOKEN" in var:
                display_value = "*" * len(value) if len(value) > 0 else ""
            else:
                display_value = value
            print(f"  ✓ {var}={display_value}")
        else:
            print(f"  - {var}=<not set>")
    
    # Test 3: Try to create config from environment
    print("\nTesting GeoNodeConfig.from_env():")
    try:
        env_config = GeoNodeConfig.from_env()
        if env_config:
            print("✓ Successfully created config from environment")
            print(f"  Base URL: {env_config.base_url}")
            print(f"  Has username: {env_config.username is not None}")
            print(f"  Has token: {env_config.token is not None}")
            print(f"  Verify SSL: {env_config.verify_ssl}")
        else:
            print("- No configuration available from environment")
            print("  (GEONODE_BASE_URL not set)")
    except Exception as e:
        print(f"✗ Error creating config from environment: {e}")
    
    # Test 4: Test auto-configuration
    print("\nTesting auto-configuration:")
    global geonode_client
    original_client = geonode_client
    geonode_client = None  # Reset for testing
    
    try:
        success = _auto_configure_from_env()
        if success:
            print("✓ Auto-configuration successful")
            if geonode_client:
                print(f"  Configured for: {geonode_client.base_url}")
        else:
            print("- Auto-configuration not available")
    except Exception as e:
        print(f"✗ Auto-configuration failed: {e}")
    finally:
        # Restore original client
        if original_client:
            geonode_client = original_client
    
    # Test 5: Provide recommendations
    print("\nRecommendations:")
    base_url = os.getenv("GEONODE_BASE_URL")
    if not base_url:
        print("📝 To enable environment configuration:")
        print("   1. Copy .env.example to .env")
        print("   2. Edit .env with your GeoNode settings")
        print("   3. Restart the server")
        print("\n   Example .env content:")
        print("   GEONODE_BASE_URL=https://demo.geonode.org")
        print("   GEONODE_USERNAME=your_username")
        print("   GEONODE_PASSWORD=your_password")
    else:
        print("✓ Environment configuration is available")
        print("  The server can auto-configure on startup")


def create_sample_env_file():
    """Create a sample .env file for testing."""
    sample_content = """# Sample GeoNode MCP Server Configuration
GEONODE_BASE_URL=https://master.demo.geonode.org
# GEONODE_USERNAME=your_username
# GEONODE_PASSWORD=your_password
GEONODE_VERIFY_SSL=true
"""
    
    env_file = Path(".env.sample")
    with open(env_file, "w") as f:
        f.write(sample_content)
    
    print(f"Created sample configuration file: {env_file}")
    print("Copy this to .env and modify as needed:")
    print(f"  cp {env_file} .env")


def main():
    """Main function."""
    print("MCP GeoNode Server - Environment Configuration Test")
    print("=" * 60)
    
    try:
        # Import python-dotenv if available
        try:
            from dotenv import load_dotenv
            load_dotenv()
            print("✓ python-dotenv is available and loaded")
        except ImportError:
            print("ℹ python-dotenv not installed (optional)")
            print("  Install with: pip install python-dotenv")
        
        print()
        test_env_configuration()
        
        print("\n" + "=" * 60)
        
        choice = input("\nCreate sample .env file? (y/n): ").strip().lower()
        if choice in ['y', 'yes']:
            create_sample_env_file()
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted.")
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
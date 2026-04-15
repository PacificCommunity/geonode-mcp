# MCP GeoNode Server Usage Guide

This guide provides detailed instructions for using the MCP GeoNode Server to interact with GeoNode instances through the Model Context Protocol.

## Quick Start

1. **Install the server:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Start the server:**
   ```bash
   python main.py
   # or
   python cli.py
   ```

3. **Connect with an MCP client and configure GeoNode:**
## Configuration

The MCP GeoNode server supports multiple configuration methods for maximum flexibility:

### Method 1: Environment Variables / .env File (Recommended)

This is the most convenient method for persistent configuration.

#### Using .env File

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit the .env file:**
   ```env
   # Required
   GEONODE_BASE_URL=https://your-geonode.org
   
   # Optional - use either username/password OR token
   GEONODE_USERNAME=your_username
   GEONODE_PASSWORD=your_password
   # GEONODE_TOKEN=your_api_token
   
    # Optional
    GEONODE_VERIFY_SSL=true
    GEONODE_MAX_CONCURRENT_UPLOADS=5
    GEONODE_LOG_FILE=./geonode-mcp.log
   ```

3. **Start the server:**
   ```bash
   python main.py
   ```

The server will automatically load the configuration on startup.
Server logs are also written to `./geonode-mcp.log` by default so they remain accessible even when an MCP host does not display stderr. Set `GEONODE_LOG_FILE` to override the path.

#### Using Environment Variables

Set environment variables directly:

```bash
export GEONODE_BASE_URL=https://demo.geonode.org
export GEONODE_USERNAME=your_username
export GEONODE_PASSWORD=your_password
python main.py
```

### Method 2: MCP Tool Configuration

Configure dynamically using the MCP `configure_geonode` tool. This method overrides any environment configuration:

```python
configure_geonode(
    base_url="https://demo.geonode.org",
    username="your_username",
    password="your_password"
)
```

### Method 3: Mixed Configuration

You can use environment variables for basic settings and override specific values using the MCP tool:

1. Set base configuration in .env:
   ```env
   GEONODE_BASE_URL=https://demo.geonode.org
   GEONODE_VERIFY_SSL=true
   ```

2. Override with credentials via MCP tool:
   ```python
   configure_geonode(
       base_url="https://demo.geonode.org",  # Can be same as env
       username="temporary_user",           # Override for this session
       password="temporary_pass"
   )
   ```4. **Start using GeoNode tools:**
   ```python
   # List available resources
   list_resources(page=1, page_size=10)
   
   # Search for specific content
   search_resources(query="climate data")
   ```

## Authentication Methods

### Public Access (No Authentication)
For public GeoNode instances where you only need to read public data:

```python
configure_geonode(base_url="https://demo.geonode.org")
```

### Basic Authentication
For GeoNode instances requiring login:

```python
configure_geonode(
    base_url="https://your-geonode.org",
    username="your_username",
    password="your_password"
)
```

### Token Authentication
For GeoNode instances supporting API tokens:

```python
configure_geonode(
    base_url="https://your-geonode.org",
    token="your_api_token"
)
```

## Tool Reference

### Configuration Tools

#### `configure_geonode`
Configure connection to a GeoNode instance. This overrides any environment configuration.

**Parameters:**
- `base_url` (required): GeoNode instance URL
- `username` (optional): Username for basic auth
- `password` (optional): Password for basic auth
- `token` (optional): API token for bearer auth
- `verify_ssl` (optional): Verify SSL certificates (default: True)

**Example:**
```python
configure_geonode(
    base_url="https://demo.geonode.org",
    verify_ssl=True
)
```

#### `get_configuration_status`
Check current configuration status and source.

**Parameters:** None

**Returns:**
Dictionary with configuration information including:
- `configured`: Whether client is configured
- `configuration_source`: Source of configuration (environment, manual, etc.)
- `base_url`: Current base URL
- `has_username`: Whether username is configured
- `has_token`: Whether token is configured  
- `verify_ssl`: SSL verification setting
- `log_file`: Absolute path to the persistent server log file

**Example:**
```python
get_configuration_status()
```

### Resource Management Tools

#### `list_resources`
List and filter GeoNode resources.

**Parameters:**
- `resource_type` (optional): Filter by type (dataset, map, document, service, geostory, dashboard)
- `search` (optional): Free text search in title and abstract
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 20)
- `featured` (optional): Filter by featured status
- `published` (optional): Filter by published status
- `approved` (optional): Filter by approved status
- `category` (optional): Filter by category identifier
- `keywords` (optional): Filter by keyword name
- `thesaurus_keywords` (optional): Filter by thesaurus keyword term (`tkeywords`)
- `owner` (optional): Filter by owner username
- `extent` (optional): Bounding box as "minx,miny,maxx,maxy"

**Examples:**
```python
# List all resources
list_resources()

# List only datasets
list_resources(resource_type="dataset")

# List published datasets in environment category
list_resources(
    resource_type="dataset",
    published=True,
    category="environment",
    keywords="12NM"
)

# List resources within geographic extent
list_resources(extent="-180,-90,180,90")

# Filter by thesaurus keyword term
list_resources(thesaurus_keywords="Ocean and Maritime")
```

#### `list_categories`
List available GeoNode categories.

**Parameters:**
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 20)

**Example:**
```python
list_categories(page=1, page_size=20)
```

#### `list_tkeywords`
List GeoNode thesaurus taxonomy keywords (`tkeywords`).

**Parameters:**
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 20)

**Example:**
```python
list_tkeywords(page=1, page_size=20)
```

#### `get_resource_details`
Get detailed information about a specific resource.

**Parameters:**
- `resource_id` (required): ID of the resource

**Example:**
```python
get_resource_details(resource_id=123)
```

#### `get_dataset_details`
Get detailed dataset information including additional metadata.

**Parameters:**
- `dataset_id` (required): ID of the dataset

**Example:**
```python
get_dataset_details(dataset_id=123)
```

#### `search_resources`
Search resources using text queries.

**Parameters:**
- `query` (required): Search text
- `search_fields` (optional): Fields to search in (default: ["title", "abstract"])
- `resource_type` (optional): Filter by resource type
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 20)

**Examples:**
```python
# Basic text search
search_resources(query="climate")

# Search only in titles for datasets
search_resources(
    query="temperature",
    search_fields=["title"],
    resource_type="dataset"
)
```

#### `download_resource`
Get download URLs for resources.

**Parameters:**
- `resource_id` (required): ID of the resource
- `resource_type` (optional): Type of resource (default: "dataset")

**Example:**
```python
download_resource(resource_id=123, resource_type="dataset")
```

#### `delete_resource`
Delete a resource from GeoNode.

**Parameters:**
- `resource_id` (required): ID of the resource to delete

**Example:**
```python
delete_resource(resource_id=123)
```

#### `update_dataset_metadata`
Update metadata for a dataset.

**Parameters:**
- `dataset_id` (required): ID of the dataset
- `title` (optional): New title
- `abstract` (optional): New description
- `license_id` (optional): New license ID

**Example:**
```python
update_dataset_metadata(
    dataset_id=123,
    title="Updated Dataset Title",
    abstract="Updated description",
    license_id=7
)
```

#### `list_linked_resources`
List resources linked to a specific resource.

**Parameters:**
- `resource_id` (required): ID of the resource

**Example:**
```python
list_linked_resources(resource_id=123)
```

### Data Upload Tools

#### `upload_dataset`
Upload spatial datasets to GeoNode.

**Parameters:**
- `base_file_path` (required): Path to main dataset file (.shp, .tif, .csv)
- `title` (optional): Title for the dataset
- `abstract` (optional): Description
- `overwrite_existing` (optional): Overwrite existing datasets (default: False)
- `skip_existing` (optional): Skip if dataset exists (default: False)

**Examples:**
```python
# Upload a Shapefile
upload_dataset(
    base_file_path="/path/to/data.shp",
    title="My Shapefile Dataset",
    abstract="Description of the dataset"
)

# Upload a GeoTIFF
upload_dataset(
    base_file_path="/path/to/raster.tif",
    title="My Raster Dataset"
)
```

**Note:** For Shapefiles, include all supporting files (.dbf, .shx, .prj, .sld) in the same directory.

#### `upload_document`
Upload documents or reference remote documents.

**Parameters:**
- `file_path` (optional): Path to local file
- `doc_url` (optional): URL of remote document
- `title` (required): Title for the document
- `abstract` (optional): Description
- `extension` (optional): File extension for remote docs

**Examples:**
```python
# Upload local document
upload_document(
    file_path="/path/to/document.pdf",
    title="My Report",
    abstract="Technical report"
)

# Reference remote document
upload_document(
    doc_url="https://example.com/report.pdf",
    title="Remote Report"
)
```

#### `check_upload_status`
Monitor upload progress.

**Parameters:**
- `execution_id` (required): Execution ID from upload response

**Example:**
```python
# After uploading, check status
result = upload_dataset(base_file_path="/path/to/data.shp")
execution_id = result.get("execution_id")

if execution_id:
    check_upload_status(execution_id)
```

### User Management Tools

#### `list_users`
List users in the GeoNode instance.

**Parameters:**
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 20)

**Example:**
```python
list_users(page=1, page_size=10)
```

#### `get_user_details`
Get detailed information about a user.

**Parameters:**
- `user_id` (required): ID of the user

**Example:**
```python
get_user_details(user_id=1)
```

#### `create_user`
Create a new user account.

**Parameters:**
- `username` (required): Username
- `password` (required): Password
- `email` (required): Email address
- `first_name` (required): First name
- `last_name` (required): Last name
- `avatar` (optional): Avatar URL

**Example:**
```python
create_user(
    username="newuser",
    password="secure_password",
    email="user@example.com",
    first_name="John",
    last_name="Doe"
)
```

### Permission Management Tools

#### `get_resource_permissions`
View current permissions on a resource.

**Parameters:**
- `resource_id` (required): ID of the resource

**Example:**
```python
get_resource_permissions(resource_id=123)
```

#### `set_resource_permissions`
Configure permissions for a resource.

**Parameters:**
- `resource_id` (required): ID of the resource
- `users` (optional): List of user permissions
- `groups` (optional): List of group permissions
- `organizations` (optional): List of organization permissions

**Permission Levels:**
- `view`: Read-only access
- `download`: View and download
- `edit`: View, download, and edit
- `manage`: Full control including permissions

**Examples:**
```python
# Grant edit access to specific users
set_resource_permissions(
    resource_id=123,
    users=[
        {"id": 1, "permissions": "edit"},
        {"id": 2, "permissions": "view"}
    ]
)

# Set group permissions
set_resource_permissions(
    resource_id=123,
    groups=[
        {"id": 1, "permissions": "view"}
    ]
)

# Mixed permissions
set_resource_permissions(
    resource_id=123,
    users=[{"id": 1, "permissions": "manage"}],
    groups=[{"id": 2, "permissions": "view"}]
)
```

## Common Workflows

### Data Discovery Workflow
```python
# 1. Configure connection
configure_geonode(base_url="https://demo.geonode.org")

# 2. Search for relevant data
results = search_resources(query="climate temperature")

# 3. Get details for interesting resources
for resource in results.get("resources", []):
    details = get_resource_details(resource["pk"])
    print(f"Resource: {details['title']}")

# 4. Download data
download_info = download_resource(resource_id=123)
print(f"Download from: {download_info['download_url']}")
```

### Data Publishing Workflow
```python
# 1. Configure with authentication
configure_geonode(
    base_url="https://your-geonode.org",
    username="your_username",
    password="your_password"
)

# 2. Upload dataset
upload_result = upload_dataset(
    base_file_path="/path/to/data.shp",
    title="My Research Dataset",
    abstract="Data from field research"
)

# 3. Monitor upload progress
execution_id = upload_result.get("execution_id")
status = check_upload_status(execution_id)

# 4. Update metadata when ready
if status.get("status") == "finished":
    dataset_id = status.get("output_params", {}).get("detail_url", [None])[0]
    if dataset_id:
        update_dataset_metadata(
            dataset_id=int(dataset_id.split("/")[-1]),
            title="Ocean field data"
        )

# 5. Set permissions
set_resource_permissions(
    resource_id=dataset_id,
    groups=[{"id": 1, "permissions": "view"}]  # Public view access
)
```

### User Administration Workflow
```python
# 1. Configure with admin credentials
configure_geonode(
    base_url="https://your-geonode.org",
    username="admin",
    password="admin_password"
)

# 2. List existing users
users = list_users(page_size=50)

# 3. Create new user
new_user = create_user(
    username="researcher1",
    password="temp_password",
    email="researcher@university.edu",
    first_name="Jane",
    last_name="Smith"
)

# 4. Check user details
user_details = get_user_details(new_user["id"])
```

## Error Handling

The MCP server includes comprehensive error handling:

```python
# Errors are returned in the response
result = list_resources(resource_type="invalid_type")

if "error" in result:
    print(f"Error: {result['error']}")
else:
    # Process successful result
    print(f"Found {len(result.get('resources', []))} resources")
```

Common error scenarios:
- **Configuration errors**: Invalid URLs, authentication failures
- **Permission errors**: Insufficient privileges for operations
- **Network errors**: Connection timeouts, SSL certificate issues
- **Validation errors**: Invalid parameters, missing required fields
- **Resource errors**: Resource not found, invalid resource IDs

## Performance Tips

1. **Use pagination** for large result sets:
   ```python
   list_resources(page_size=50)  # Instead of default 20
   ```

2. **Filter results** to reduce data transfer:
   ```python
   list_resources(resource_type="dataset", published=True)
   ```

3. **Use specific searches** rather than broad queries:
   ```python
   search_resources(query="climate temperature", search_fields=["title"])
   ```

4. **Check upload status periodically** rather than continuously:
   ```python
   # Check every 5 seconds instead of continuously
   import time
   status = check_upload_status(execution_id)
   while status.get("status") == "running":
       time.sleep(5)
       status = check_upload_status(execution_id)
   ```

5. **Throttle batch uploads** to avoid server-side concurrency limits:
   - By default, this MCP server limits concurrent uploads to 5.
   - Set `GEONODE_MAX_CONCURRENT_UPLOADS` to adjust this limit for your environment.

## Troubleshooting

### Connection Issues
- Verify the GeoNode URL is correct and accessible
- Check authentication credentials
- Ensure SSL certificates are valid (or set `verify_ssl=False` for testing)

### Upload Issues
- Ensure file paths are correct and files exist
- For Shapefiles, include all required files (.shp, .dbf, .shx, .prj)
- Check file permissions and sizes
- Monitor upload status for detailed error messages

### Permission Issues
- Verify user has sufficient privileges for the operation
- Check resource ownership and permission settings
- Ensure authentication is properly configured

### API Compatibility
- The server supports GeoNode 3.x and 4.x with API v2
- Some features may not be available on older GeoNode versions
- Check GeoNode documentation for API endpoint availability

## Advanced Configuration

### SSL Certificate Handling
For GeoNode instances with self-signed certificates:

```python
configure_geonode(
    base_url="https://internal-geonode.org",
    username="user",
    password="pass",
    verify_ssl=False  # Disable SSL verification
)
```

### Custom Timeouts
The HTTP client uses default timeouts. For slow GeoNode instances, consider modifying the client code to increase timeout values.

### Batch Operations
For bulk operations, implement retry logic and rate limiting:

```python
import time

# Upload multiple files with delay
files = ["/path/to/file1.shp", "/path/to/file2.shp"]
for file_path in files:
    upload_dataset(base_file_path=file_path)
    time.sleep(2)  # 2-second delay between uploads
```

## Contributing

To extend the MCP server:

1. Add new tools by decorating functions with `@mcp.tool()`
2. Follow the existing pattern for error handling
3. Include comprehensive docstrings
4. Test with different GeoNode versions
5. Update this documentation

## Support

For issues and questions:
1. Check GeoNode API documentation
2. Review MCP protocol documentation
3. Check server logs for detailed error messages
4. Test with GeoNode demo instances first

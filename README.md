# MCP GeoNode Server

A Model Context Protocol (MCP) server for interacting with GeoNode APIs. This server provides comprehensive access to GeoNode functionality including resource management, user administration, data uploads/downloads, and permission management.

## Features

### Resource Management
- **List Resources**: Browse and filter resources by type, status, categories, keywords, and more
- **Resource Details**: Get detailed information about specific resources and datasets
- **Search**: Full-text search across resource titles and abstracts
- **Download**: Generate download URLs for datasets and documents
- **Upload**: Upload datasets (Shapefiles, GeoTIFFs, CSV) and documents
- **Delete**: Remove resources from GeoNode
- **Metadata Updates**: Update dataset titles, abstracts, and licenses

### User Management
- **List Users**: Browse users with pagination
- **User Details**: Get detailed user information
- **Create Users**: Add new users to the system

### Permissions & Security
- **View Permissions**: Check current resource permissions
- **Set Permissions**: Configure user, group, and organization permissions for resources
- **Authentication**: Support for Basic Auth and Bearer tokens

### Advanced Features
- **Upload Tracking**: Monitor upload progress with execution status
- **Linked Resources**: Discover relationships between resources
- **Filtering**: Advanced filtering by resource type, publication status, featured status, categories, and more

## Installation

1. Install dependencies:
```bash
pip install mcp httpx pydantic
```

2. Run the server:
```bash
python main.py
# or
python cli.py
```

## Configuration

The MCP GeoNode server is configured exclusively through environment variables or a `.env` file for security and simplicity.

### Environment Variables Configuration

Create a `.env` file in the project directory or set environment variables:

```bash
# Copy the example file
cp .env.example .env

# Edit with your GeoNode configuration
nano .env
```

**Required Environment Variables:**
- `GEONODE_BASE_URL` - Base URL of the GeoNode instance

**Optional Environment Variables:**
- `GEONODE_USERNAME` - Username for authentication
- `GEONODE_PASSWORD` - Password for authentication
- `GEONODE_TOKEN` - Bearer token for authentication (alternative to username/password)
- `GEONODE_VERIFY_SSL` - Verify SSL certificates (default: true)
- `GEONODE_MAX_CONCURRENT_UPLOADS` - Maximum concurrent upload requests handled by the server (default: 5)
- `GEONODE_LOG_FILE` - Persistent server log file path (default: `./geonode-mcp.log`)

**Example .env file:**
```env
GEONODE_BASE_URL=https://demo.geonode.org
GEONODE_USERNAME=your_username
GEONODE_PASSWORD=your_password
GEONODE_VERIFY_SSL=true
```

The server will automatically load configuration on startup. Use the `get_configuration_status` tool to check the current configuration.

Server logs are written to `./geonode-mcp.log` by default, which is useful when the MCP host hides stderr. Set `GEONODE_LOG_FILE` to change the path.

### Authentication Options

#### Public Access (No Authentication)
For public GeoNode instances where you only need to read public data:

```env
GEONODE_BASE_URL=https://demo.geonode.org
```

#### Basic Authentication
For GeoNode instances requiring login:

```env
GEONODE_BASE_URL=https://your-geonode.org
GEONODE_USERNAME=your_username
GEONODE_PASSWORD=your_password
```

#### Token Authentication
For GeoNode instances supporting API tokens:

```env
GEONODE_BASE_URL=https://your-geonode.org
GEONODE_TOKEN=your_api_token
```

## Usage Examples

### Listing Resources
```python
# List all resources
list_resources()

# Filter by resource type
list_resources(resource_type="dataset")

# Search with text query
list_resources(search="climate", page=1, page_size=10)

# Filter by multiple criteria
list_resources(
    resource_type="dataset",
    published=True,
    featured=True,
    category="environment"
)
```

### Resource Details
```python
# Get basic resource information
get_resource_details(resource_id=123)

# Get detailed dataset information (includes additional metadata)
get_dataset_details(dataset_id=123)
```

### Uploading Data
```python
# Upload a Shapefile dataset
upload_dataset(
    base_file_path="/path/to/data.shp",
    title="My Dataset",
    abstract="Description of the dataset"
)

# Upload a document
upload_document(
    file_path="/path/to/document.pdf",
    title="My Document",
    abstract="Document description"
)

# Reference a remote document
upload_document(
    doc_url="https://example.com/document.pdf",
    title="Remote Document"
)
```

### Permissions Management
```python
# View current permissions
get_resource_permissions(resource_id=123)

# Set permissions for users and groups
set_resource_permissions(
    resource_id=123,
    users=[
        {"id": 1, "permissions": "edit"},
        {"id": 2, "permissions": "view"}
    ],
    groups=[
        {"id": 1, "permissions": "view"}
    ]
)
```

### User Management
```python
# List users
list_users(page=1, page_size=20)

# Get user details
get_user_details(user_id=1)

# Create new user
create_user(
    username="newuser",
    password="secure_password",
    email="user@example.com",
    first_name="John",
    last_name="Doe"
)
```

### Updating Dataset Metadata
```python
# Update supported dataset fields
update_dataset_metadata(
    dataset_id=123,
    title="Updated Dataset Title",
    abstract="Updated description",
    license_id=7,
    group_name="Climate Data Team",
    category="Climate and Meteorology",
    hkeywords=["ocean", "reef", "marine habitat"],
    regions=["Pacific", "Melanesia"],
    temporal_extent_start="2020-01-01",
    temporal_extent_end="2024-12-31",
    attribution="Pacific Community (SPC)",
    maintenance_frequency="annually",  # code or label supported
    supplemental_information="Compiled from validated field observations.",
    tkeywords=[{"themes": ["PASTE_EXACT_ID_FROM_AUTOCOMPLETE"]}]
)
```

`maintenance_frequency` accepts either a canonical code or a full label (it is normalized to the code), and temporal extent is sent using top-level `temporal_extent_start` / `temporal_extent_end` fields.

## Available Tools

### Configuration
- `configure_geonode`: Set up connection to GeoNode instance (overrides environment)
- `get_configuration_status`: Check current configuration status and source

### Resource Management
- `list_resources`: List and filter resources
- `list_categories`: List available categories
- `list_tkeywords`: List thesaurus taxonomy keywords
- `get_resource_details`: Get basic resource information
- `get_dataset_details`: Get detailed dataset information
- `search_resources`: Search resources by text query
- `download_resource`: Get download URLs
- `delete_resource`: Remove resources
- `update_dataset_metadata`: Update dataset metadata fields via metadata instance endpoint
- `list_linked_resources`: Find linked resources

### Data Upload
- `upload_dataset`: Upload spatial datasets
- `upload_document`: Upload or reference documents
- `check_upload_status`: Monitor upload progress

### User Management
- `list_users`: Browse users
- `get_user_details`: Get user information
- `create_user`: Add new users

### Permissions
- `get_resource_permissions`: View permissions
- `set_resource_permissions`: Configure permissions

## Supported GeoNode Versions

This MCP server is designed to work with GeoNode 3.x and 4.x instances that provide the standard REST API v2. It supports:

- GeoNode 3.3+
- GeoNode 4.0+
- Custom GeoNode deployments with API v2

## API Coverage

The server implements the following GeoNode API endpoints:

- `/api/v2/resources` - Resource listing and filtering
- `/api/v2/resources/{id}` - Resource details and operations
- `/api/v2/metadata/instance/{id}` - Dataset metadata updates via PATCH
- `/api/v2/metadata/autocomplete/thesaurus/{name}/keywords` - Keyword ID lookup for metadata updates
- `/api/v2/uploads/upload` - Dataset uploads
- `/api/v2/documents` - Document operations
- `/api/v2/users` - User management
- `/api/v2/executionrequest/{id}` - Upload status tracking
- Permission management endpoints

## Error Handling

The server includes comprehensive error handling:

- HTTP status code validation
- Network error recovery
- Authentication failure detection
- Detailed error messages with context
- Graceful degradation for optional features

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## Docker Deployment

### Building the Docker Image

```bash
docker build -t mcp-geonode .
```

### Running with Docker

#### Using environment variables:
```bash
docker run --rm \
  -e GEONODE_BASE_URL=https://your-geonode.org \
  -e GEONODE_USERNAME=your_username \
  -e GEONODE_PASSWORD=your_password \
  -p 8000:8000 \
  mcp-geonode
```

#### Using an environment file (recommended):
```bash
# Create your .env file first
docker run --rm --env-file .env -p 8000:8000 mcp-geonode
```

#### For public GeoNode instances:
```bash
docker run --rm \
  -e GEONODE_BASE_URL=https://demo.geonode.org \
  -p 8000:8000 \
  mcp-geonode
```

### Environment Variables in Docker

All the same environment variables work in Docker:
- `GEONODE_BASE_URL` (required)
- `GEONODE_USERNAME` (optional)
- `GEONODE_PASSWORD` (optional) 
- `GEONODE_TOKEN` (optional)
- `GEONODE_VERIFY_SSL` (optional, default: true)

The container will automatically load your configuration and start the MCP server.

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
1. Check the GeoNode API documentation: https://docs.geonode.org/en/master/devel/api/usage/index.html
2. Review MCP documentation: https://github.com/modelcontextprotocol/python-sdk
3. Open an issue in this repository

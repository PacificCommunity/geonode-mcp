# Copilot instructions for `mcp-geonode`

## Build, test, and lint commands

Use the local project environment and lockfile-managed dependencies:

```bash
uv sync --extra dev --extra env
```

Run checks:

```bash
# tests (full suite)
uv run pytest -q

# single test
uv run pytest test_env_config.py::test_env_configuration -q

# lint
uv run ruff check .

# formatting check
uv run black --check .

# package build
uv build
```

Run the MCP server locally:

```bash
uv run python main.py
# or
uv run python cli.py
```

## High-level architecture

- The implementation is centralized in `mcp_geonode/server.py`.
- `main.py` is a thin entrypoint (`from mcp_geonode.server import main`), and `cli.py` wraps startup/transport flags but currently falls back to stdio by calling the same `main()`.
- `GeoNodeConfig` (Pydantic model) is responsible for reading and validating environment-based configuration (`GEONODE_*` vars).
- `GeoNodeClient` wraps all HTTP access to GeoNode API v2 through one async `request()` method, including auth header setup and upload-specific header handling.
- A module-global `geonode_client` is initialized via `_auto_configure_from_env()` at import time; all MCP tools call `get_client()` and fail early if config is missing.
- Each MCP capability is exposed as `@mcp.tool()` function in this same module (resources, uploads, users, permissions, upload-status, linked resources).

## Key codebase conventions

- Keep new MCP tools in `mcp_geonode/server.py` and register them with `@mcp.tool()`.
- Tool handlers generally return JSON-like dictionaries (`Dict[str, Any]`) and convert operational failures to `{"error": "...message..."}` instead of propagating exceptions to the MCP layer.
- Reuse `get_client()` + `GeoNodeClient.request()` for all API calls; endpoints are passed relative to `/api/v2`.
- Authentication precedence in `GeoNodeClient`: bearer token (`GEONODE_TOKEN`) first, then basic auth (`GEONODE_USERNAME`/`GEONODE_PASSWORD`).
- Environment-first configuration is the active runtime path (`.env` via optional `python-dotenv` + `GEONODE_*` vars). Keep any new config flow consistent with this startup behavior.
- For shapefile uploads, follow existing sidecar-file behavior (`.dbf`, `.shx`, `.prj`, `.sld`) when extending upload logic.

## Known current baseline (important for future sessions)

- `uv run pytest -q` currently errors during collection because `test_server.py` imports `configure_geonode` from `mcp_geonode.server`, but that symbol is not present in the current server module.

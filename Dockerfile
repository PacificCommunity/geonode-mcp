FROM python:3.13-slim

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install pip, build tools are not required for pure-Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel

# Install uv to manage dependencies and run the server
RUN pip install uvicorn


# Copy package metadata first for efficient caching
COPY pyproject.toml README.md /app/
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# Copy application source
COPY main.py /app/
COPY mcp_geonode /app/mcp_geonode

# Install the package and optional 'env' extras (for python-dotenv)
# Use quotes around extras to avoid shell globbing issues
RUN pip install --no-cache-dir ".[env]"

# Default environment variables (can be overridden at runtime)
ENV GEONODE_VERIFY_SSL=true

# Run the server
CMD ["python", "main.py"]

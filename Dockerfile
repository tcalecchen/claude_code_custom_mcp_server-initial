# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies for image processing
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1-mesa-dri \
    libgthread-2.0-0 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd --create-home --shell /bin/bash mcp-user

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create directories for images
RUN mkdir -p /app/images && \
    chown -R mcp-user:mcp-user /app

# Copy the server code
COPY server.py .

# Change ownership of the app directory to mcp-user
RUN chown -R mcp-user:mcp-user /app

# Switch to non-root user
USER mcp-user

# Set the entry point with signal handling
ENTRYPOINT ["python", "-u", "server.py"]

# Health check (optional, for monitoring)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Metadata
LABEL maintainer="MCP Image Tools Server" \
      description="MCP server providing image processing tools" \
      version="0.1.0"
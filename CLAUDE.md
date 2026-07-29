# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an MCP (Model Context Protocol) Image Tools Server that provides image processing capabilities to Claude Code. The server is implemented using the FastMCP framework and runs in a Docker container for consistent deployment.

## Architecture

**Core Components:**
- `server.py` - Main MCP server implementation using FastMCP framework
- `Dockerfile` - Container configuration with Python 3.11 and image processing dependencies
- `.mcp.json` - MCP server configuration for Claude Code integration
- Requirements managed via `requirements.txt` with dependencies for Pillow (PIL), requests, and duckduckgo-search

**MCP Tools Available:**
- `fetch_toy_image` - Downloads toy-related images via DuckDuckGo image search
- `resize_image` - Resizes images to specified dimensions, with optional aspect ratio preservation
- `remove_background_as_png` - Removes a solid-colour background and saves an RGBA PNG

**Directory Structure:**
- `./images/` - Working directory for downloaded and processed images
- `./input/` - Docker volume mount for input files
- `./output/` - Docker volume mount for output files

## Development Commands

### Docker Operations
```bash
# Build the Docker image (required after code changes)
docker build -t mcp-toy-image-tools-server .

# Check if Docker is running
docker --version

# Run the container interactively for testing
docker run --rm -i \
  -v $(pwd)/images:/app/images \
  -v $(pwd)/input:/app/input \
  -v $(pwd)/output:/app/output \
  mcp-toy-image-tools-server
```

### MCP Server Management
```bash
# Smoke-test the containerized server with a real MCP initialize handshake
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  | docker run --rm -i mcp-toy-image-tools-server
# Expect a JSON result with "serverInfo":{"name":"image-tools-server",...}

# Run server locally (requires dependencies installed)
python server.py
```

### Claude Code Integration
After making changes to the server code:
1. Rebuild Docker image: `docker build -t mcp-toy-image-tools-server .`
2. Use `/mcp` command in Claude Code
3. Reconnect to `image-tools-server-docker` server

## Implementation Details

**FastMCP Framework**: The server uses `@mcp.tool()` decorators to register async functions as MCP tools. Each tool function returns a string result that gets wrapped in TextContent by the framework.

**Image Processing Pipeline**: 
- Uses PIL (Pillow) for basic image operations (resizing)
- Background removal is done entirely with PIL channel LUTs + `ImageChops` so the
  work stays in the C layer. Never reintroduce a per-pixel `getpixel`/`putpixel`
  loop — the original one took ~35s on a 3815x3815 photo (now ~3s). The only
  Python-level loop is the border flood fill in `_border_connected`, which runs
  on a ≤400px copy of the mask so background-coloured regions enclosed by the
  subject stay opaque.
- DuckDuckGo search integration for image fetching (`duckduckgo-search`)
- `fetch_toy_image` outputs default to the `./images/` directory

**Container Architecture**: Runs as non-root user `mcp-user` with volume mounts for file I/O. The container includes OpenGL and imaging libraries for processing support.

**Error Handling**: Each tool validates input files exist and provides descriptive error messages. Network operations (image download in `fetch_toy_image`) use a request timeout and skip individual images that fail to download.

## Configuration Notes

The `.mcp.json` file configures the server for Claude Code with Docker execution via `docker run --rm -i`. The server is identified as `image-tools-server-docker` in Claude Code, and the Docker image it runs is named `mcp-toy-image-tools-server`.

Volume mounts use **absolute host paths** (not `${PWD}`, which does not expand on Windows and causes a `-32000` connection failure). The mounted host directories (`images/`, `input/`, `output/`) must exist before connecting:
- `/app/images` for general image storage
- `/app/input` and `/app/output` for organized file handling

If the project directory moves, update the absolute paths in `.mcp.json` accordingly.

## Adding New Tools

To add new image processing tools:
1. Define async function with `@mcp.tool()` decorator
2. Include proper parameter typing and docstring
3. Follow existing error handling patterns
4. Default output to `./images/` directory unless specified
5. Rebuild Docker image and reconnect MCP server

## Dependencies Management

Core dependencies in `requirements.txt`:
- `mcp>=1.0.0` - MCP SDK
- `Pillow>=10.0.0` - Image processing
- `requests>=2.31.0` - HTTP client
- `duckduckgo-search>=6.1.0` - Image search

Keep `requirements.txt` minimal — only add a dependency once code actually imports it. (Previously `numpy`, `torch`, and `torchvision` were listed but unused; they pulled in the full CUDA stack and bloated the image to multiple GB before being removed.)

System dependencies (imaging/OpenGL libraries) are handled in the Dockerfile for containerized deployment.
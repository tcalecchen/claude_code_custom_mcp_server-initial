# MCP Image Tools Server

A Model Context Protocol (MCP) server that provides powerful image processing tools for Claude Code. This server implements three main functionalities: downloading toy-related images from the web, resizing images, and removing backgrounds from images.

- Anthropic MCP Pythone SDK Github repo: https://github.com/modelcontextprotocol/python-sdk?tab=readme-ov-file

## Features

### 🧸 Toy Image Fetcher (`fetch_toy_image`)
- Downloads toy-related images from DuckDuckGo search
- Automatically prefixes search terms with "toy" for better results
- Supports downloading 1-10 images per request
- Saves images to a specified directory

### 🖼️ Image Resizer (`resize_image`)
- Resize images to specific dimensions
- Option to maintain aspect ratio
- High-quality resampling using Lanczos algorithm
- Support for all common image formats

### ✂️ Background Remover (`remove_background_as_png`)
- AI-powered background removal using state-of-the-art models
- Multiple model options (u2net, u2netp, silueta, isnet-general-use)
- Outputs PNG with transparent background
- Preserves main object details

## Prerequisites

- Python 3.11 or higher
- Docker (for containerized deployment)
- Claude Code (for MCP client integration)

## Installation

### Option 1: Local Python Installation

1. **Clone or create the project directory:**
   ```bash
   mkdir mcp-toy-image-tools && cd mcp-toy-image-tools
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server:**
   ```bash
   python server.py
   ```

### Option 2: Docker Installation (Recommended)

1. **Build the Docker image:**
   ```bash
   docker build -t mcp-toy-image-tools-server .
   ```

2. **Create necessary directories:**
   ```bash
   mkdir -p images input output
   ```

3. **Run the container:**
   ```bash
   docker run --rm -i \
     --name mcp-toy-image-tools \
     -v $(pwd)/images:/app/images \
     -v $(pwd)/input:/app/input \
     -v $(pwd)/output:/app/output \
     mcp-toy-image-tools-server
   ```

## Claude Code Integration

### Step 1: Configure Claude Code

1. **Copy the MCP configuration to your Claude Code settings:**
   
   For Docker execution:
   ```json
   {
     "mcpServers": {
       "image-tools-server-docker": {
         "command": "docker",
         "args": [
           "run",
           "--rm",
           "-i",
           "--name", "mcp-toy-image-tools",
           "-v", "${PWD}/images:/app/images",
           "-v", "${PWD}/input:/app/input",
           "-v", "${PWD}/output:/app/output",
           "mcp-toy-image-tools-server"
         ],
         "cwd": "/path/to/your/mcp-toy-image-tools"
       }
     }
   }
   ```

2. **Update the `cwd` path to match your actual project directory.**

### Step 2: Restart Claude Code

After updating your MCP configuration, restart Claude Code to load the new server.

## Usage Examples

Once integrated with Claude Code, you can use these commands:

### Download Toy Images
```
Please use the fetch_toy_image tool to download 5 robot toy images to the ./images directory.
```

### Resize Images
```
Can you resize the image at ./images/robot_toy_1.jpg to 800x600 pixels?
```

### Remove Background
```
Please remove the background from ./images/robot_toy_1.jpg and save it as a PNG.
```

## File Structure

```
mcp-toy-image-tools/
├── server.py              # Main MCP server implementation
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── .mcp.json            # Claude Code MCP configuration
├── README.md            # This documentation
├── images/              # Directory for downloaded/processed images
├── input/               # Directory for input images (Docker)
└── output/              # Directory for output images (Docker)
```

## Dependencies

### Python Libraries
- **mcp**: Anthropic's Model Context Protocol SDK
- **Pillow**: Python Imaging Library for image processing
- **requests**: HTTP client for downloading images
- **duckduckgo-search**: DuckDuckGo search API client
- **torch/torchvision**: PyTorch for AI model inference

### System Dependencies (Docker only)
- OpenGL libraries for image processing
- GLib and threading libraries
- Various image format support libraries

## Configuration Options

### Environment Variables
- `PYTHONPATH`: Set to project directory for proper module resolution

### Volume Mounts (Docker)
- `/app/images`: Directory for downloaded and processed images
- `/app/input`: Input directory for source images
- `/app/output`: Output directory for processed images

## Troubleshooting

### Common Issues

1. **"duckduckgo-search library not available" error:**
   ```bash
   pip install duckduckgo-search
   ```

2. **Image download failures:**
   - Check internet connection
   - Some images may be blocked by the source website
   - The tool automatically retries with additional results

3. **Background removal model download:**
   - First use may take longer as AI models are downloaded
   - Ensure sufficient disk space (~100MB+ for models)

4. **Permission errors (Docker):**
   - Ensure volume mount directories have proper permissions
   - The container runs as non-root user `mcp-user`

### Debug Mode

To run with debug logging:
```bash
# Direct Python
PYTHONPATH=. python server.py --log-level DEBUG

# Docker
docker run --rm -i -e LOG_LEVEL=DEBUG mcp-toy-image-tools-server
```

### Claude Code Connection Issues

1. **Server not appearing in Claude Code:**
   - Check that `.mcp.json` is in the correct location
   - Verify the `cwd` path is correct
   - Restart Claude Code after configuration changes

2. **Tool execution errors:**
   - Check server logs for detailed error messages
   - Ensure all dependencies are installed
   - Verify file paths are accessible

## Development

### Adding New Tools

To add new image processing tools:

1. **Define the tool in `handle_list_tools()`:**
   ```python
   Tool(
       name="your_new_tool",
       description="Description of what it does",
       inputSchema={...}
   )
   ```

2. **Implement the handler in `handle_call_tool()`:**
   ```python
   elif name == "your_new_tool":
       return await your_new_tool_function(arguments)
   ```

3. **Add the async function implementation:**
   ```python
   async def your_new_tool_function(arguments: dict[str, Any]) -> list[TextContent]:
       # Implementation here
       pass
   ```

### Testing

Test the server independently:
```bash
echo '{"method": "tools/list", "params": {}}' | python server.py
```

## License

This project is provided as-is for educational and development purposes. Please respect the terms of service of image sources and AI models used.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues and questions:
- Check the troubleshooting section above
- Review Claude Code MCP documentation
- Submit issues to the project repository

---

**Note**: This tool downloads images from the internet and uses AI models for processing. Please use responsibly and respect copyright and terms of service of source websites.
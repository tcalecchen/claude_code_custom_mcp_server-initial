### Check whether docker service is running 
use the command below to check whether docker is running.
```bash
docker --version
```

If not, reminder user to start the Docker service first and abort the command execution here.

### Rebuild Docker Image to reflect changes in python code 
```bash
   docker build -t mcp-toy-image-tools-server .
```

### Restart the MCP server 
Remind the users to use ```/mcp``` command, and look for ```image-tools-server-docker``` and reconnect
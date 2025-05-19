
This is NOT an official Modal product.

To use:
* Install uv: https://docs.astral.sh/uv/getting-started/installation/
* In Cursor, navigate to Settings > Cursor Settings > MCP, click "+Add new global MCP server", and add something like the following (be sure to provide the correct path):
```js
{
  "mcpServers": {
    "my-mcp-server": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/modal-mcp-server",
        "run",
        "mcp",
        "run",
        "main.py"
      ],
      "env": { }
    }
  }
}

```
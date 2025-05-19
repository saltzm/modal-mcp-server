# About

This is a demo of how one can create and use Modal sandboxes from an MCP server.

This is NOT an official Modal product.

# Installation

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

# Usage

You can ask things like "Make a sandbox for me with an hour timeout", "Install node in the sandbox", etc.

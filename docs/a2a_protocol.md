# A2A Protocol Integration

## Overview

a2a-mesh implements the A2A (Agent-to-Agent) protocol for inter-agent communication. A2A is Google's open protocol that standardizes how AI agents talk to each other, built on JSON-RPC 2.0 over HTTP and WebSocket transport.

## Protocol Basics

A2A uses JSON-RPC 2.0 as its transport layer. Every message is a JSON-RPC request or response:

```json
// Request
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tasks/send",
  "params": {
    "input": "Analyze this document"
  }
}

// Success response
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "status": "completed",
    "output": "Analysis results..."
  }
}

// Error response
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32603,
    "message": "Internal error"
  }
}
```

## Supported Methods

a2a-mesh exposes these JSON-RPC methods on its gateway over both `/rpc` and `/ws`:

| Method | Description |
|---|---|
| `tasks/send` | Submit a task for execution |
| `tasks/get` | Query the status of a submitted task |
| `tasks/cancel` | Cancel a running task |
| `agents/list` | List registered agents |
| `agents/register` | Register a new agent |

## Agent Cards

Agent Cards are the discovery mechanism in A2A. They describe an agent's capabilities, endpoints, and operational characteristics:

```json
{
  "name": "research-agent",
  "description": "Searches the web and synthesizes information",
  "url": "http://localhost:9001",
  "capabilities": ["web_search", "summarization"],
  "input_formats": ["text/plain", "application/json"],
  "output_formats": ["text/markdown", "application/json"],
  "version": "1.0.0",
  "max_concurrent": 5,
  "cost_per_task": 0.02,
  "health_endpoint": "/health",
  "auth_required": false
}
```

Agents register their cards with the mesh. The registry indexes capabilities for fast lookup.

## A2AClient

The `A2AClient` class handles outbound communication from the mesh to remote agents:

```python
from a2a_mesh.protocol.a2a import A2AClient

client = A2AClient(
    base_url="http://agent.example.com",
    timeout=30.0,
    headers={"Authorization": "Bearer <token>"},
)

# Send a task
result = await client.send_task("Analyze this data")

# Query task status
status = await client.get_task("task-id-123")

# Cancel a task
await client.cancel_task("task-id-123")

await client.close()
```

The client lazily initializes an `httpx.AsyncClient` for connection pooling. Request IDs auto-increment for JSON-RPC compliance.

## Error Codes

Standard JSON-RPC error codes used by a2a-mesh:

| Code | Constant | Meaning |
|---|---|---|
| -32700 | `PARSE_ERROR` | Invalid JSON |
| -32600 | `INVALID_REQUEST` | Invalid JSON-RPC structure |
| -32601 | `METHOD_NOT_FOUND` | Unknown method |
| -32603 | `INTERNAL_ERROR` | Server-side error |

## MCP Integration

While A2A handles agent-to-agent communication, MCP (Model Context Protocol) handles agent-to-tool communication. The `MCPBridge` connects agents to MCP tool servers:

```python
from a2a_mesh.protocol.mcp import MCPBridge

bridge = MCPBridge()
bridge.register_server("tools", "http://mcp-server.local")

# Discover available tools
tools = await bridge.discover_tools("tools")

# Call a tool
result = await bridge.call_tool("web_search", {"query": "quantum computing"})
```

This allows agents in the mesh to leverage external tools (databases, APIs, file systems) through the standardized MCP protocol.

## References

- [Google A2A Protocol Specification](https://github.com/google/A2A)
- [Anthropic MCP Specification](https://modelcontextprotocol.io)
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)

"""MCP (Model Context Protocol) bridge for a2a-mesh.

Provides a lightweight abstraction over MCP tool servers, allowing agents
in the mesh to invoke MCP tools and access MCP resources.
"""

from __future__ import annotations

from typing import Any

import httpx

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import ProtocolError

logger = get_logger(__name__)


class MCPToolDefinition:
    """Describes an MCP tool available on a tool server.

    Attributes:
        name: Unique tool name.
        description: Human-readable description.
        input_schema: JSON schema for tool input.
        server_url: URL of the MCP server hosting this tool.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        server_url: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema or {}
        self.server_url = server_url


class MCPBridge:
    """Bridge between the a2a-mesh and MCP tool servers.

    Manages connections to MCP servers, discovers available tools,
    and invokes tools on behalf of agents.

    Attributes:
        servers: Mapping of server name to URL.
        tools: Mapping of tool name to its definition.
    """

    def __init__(self) -> None:
        """Initialize the MCP bridge."""
        self.servers: dict[str, str] = {}
        self.tools: dict[str, MCPToolDefinition] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialize the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def register_server(self, name: str, url: str) -> None:
        """Register an MCP tool server.

        Args:
            name: Logical name for the server.
            url: Base URL of the MCP server.
        """
        self.servers[name] = url.rstrip("/")
        logger.info("mcp.server_registered", name=name, url=url)

    async def discover_tools(self, server_name: str) -> list[MCPToolDefinition]:
        """Discover tools available on an MCP server.

        Calls the server's ``tools/list`` endpoint and registers
        each discovered tool.

        Args:
            server_name: Name of a previously registered server.

        Returns:
            List of discovered tool definitions.

        Raises:
            ProtocolError: If the server is not registered or unreachable.
        """
        if server_name not in self.servers:
            raise ProtocolError(f"MCP server not registered: {server_name}")

        url = self.servers[server_name]
        client = await self._get_client()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ProtocolError(
                f"Failed to discover tools from {server_name}: {exc}"
            ) from exc

        result = data.get("result", {})
        raw_tools = result.get("tools", [])
        discovered: list[MCPToolDefinition] = []

        for tool_data in raw_tools:
            tool = MCPToolDefinition(
                name=tool_data.get("name", ""),
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server_url=url,
            )
            self.tools[tool.name] = tool
            discovered.append(tool)

        logger.info(
            "mcp.tools_discovered",
            server=server_name,
            count=len(discovered),
            tools=[t.name for t in discovered],
        )
        return discovered

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke an MCP tool.

        Args:
            tool_name: Name of the tool to invoke.
            arguments: Input arguments matching the tool's schema.

        Returns:
            The tool's output.

        Raises:
            ProtocolError: If the tool is not registered or the call fails.
        """
        if tool_name not in self.tools:
            raise ProtocolError(f"MCP tool not registered: {tool_name}")

        tool = self.tools[tool_name]
        client = await self._get_client()

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        try:
            resp = await client.post(tool.server_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise ProtocolError(f"MCP tool call failed for {tool_name}: {exc}") from exc

        if "error" in data:
            raise ProtocolError(
                f"MCP tool error: {data['error'].get('message', 'unknown')}"
            )

        return data.get("result", {})

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

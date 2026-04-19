"""Tests for protocol implementations (A2A + MCP bridge)."""

from __future__ import annotations

import httpx
import pytest
import respx

from a2a_mesh.exceptions import JsonRpcError, ProtocolError
from a2a_mesh.protocol.a2a import (
    A2AClient,
    ErrorCode,
    build_jsonrpc_error,
    build_jsonrpc_response,
)
from a2a_mesh.protocol.mcp import MCPBridge, MCPToolDefinition


class TestA2AClient:
    """Tests for the A2A protocol client."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_task_success(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"output": "analysis complete"},
                },
            )
        )
        client = A2AClient("http://agent.local")
        result = await client.send_task("analyze this")
        assert result["output"] == "analysis complete"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_task_jsonrpc_error(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32603, "message": "Internal error"},
                },
            )
        )
        client = A2AClient("http://agent.local")
        with pytest.raises(JsonRpcError):
            await client.send_task("fail")
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_task_http_error(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        client = A2AClient("http://agent.local")
        with pytest.raises(ProtocolError, match="HTTP 500"):
            await client.send_task("fail")
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_task_connection_error(self) -> None:
        respx.post("http://agent.local/").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        client = A2AClient("http://agent.local")
        with pytest.raises(ProtocolError, match="Connection error"):
            await client.send_task("fail")
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_send_task_missing_result(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1},
            )
        )
        client = A2AClient("http://agent.local")
        with pytest.raises(ProtocolError, match="missing result"):
            await client.send_task("bad response")
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_task(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"status": "completed"},
                },
            )
        )
        client = A2AClient("http://agent.local")
        result = await client.get_task("task-123")
        assert result["status"] == "completed"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_cancel_task(self) -> None:
        respx.post("http://agent.local/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"cancelled": True},
                },
            )
        )
        client = A2AClient("http://agent.local")
        result = await client.cancel_task("task-123")
        assert result["cancelled"] is True
        await client.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        client = A2AClient("http://agent.local")
        await client.close()
        await client.close()  # Should not raise

    def test_request_id_increments(self) -> None:
        client = A2AClient("http://agent.local")
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3


class TestJsonRpcHelpers:
    """Tests for JSON-RPC response builders."""

    def test_build_success_response(self) -> None:
        resp = build_jsonrpc_response(1, {"status": "ok"})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"]["status"] == "ok"

    def test_build_error_response(self) -> None:
        resp = build_jsonrpc_error(1, -32603, "Internal error")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["error"]["code"] == -32603
        assert resp["error"]["message"] == "Internal error"

    def test_build_error_response_null_id(self) -> None:
        resp = build_jsonrpc_error(None, -32700, "Parse error")
        assert resp["id"] is None


class TestErrorCode:
    """Tests for the structured ErrorCode enum."""

    def test_standard_jsonrpc_codes_present(self) -> None:
        assert ErrorCode.PARSE_ERROR == -32700
        assert ErrorCode.INVALID_REQUEST == -32600
        assert ErrorCode.METHOD_NOT_FOUND == -32601
        assert ErrorCode.INVALID_PARAMS == -32602
        assert ErrorCode.INTERNAL_ERROR == -32603

    def test_custom_mesh_codes_present(self) -> None:
        assert ErrorCode.RATE_LIMITED == -31000
        assert ErrorCode.AGENT_NOT_FOUND == -31001
        assert ErrorCode.AGENT_UNAVAILABLE == -31002
        assert ErrorCode.TASK_NOT_FOUND == -31003
        assert ErrorCode.TASK_TIMEOUT == -31004
        assert ErrorCode.CAPABILITY_MISMATCH == -31005
        assert ErrorCode.AUTH_REQUIRED == -31006
        assert ErrorCode.AUTH_INVALID == -31007
        assert ErrorCode.BUDGET_EXCEEDED == -31008
        assert ErrorCode.WORKFLOW_CYCLE == -31009

    def test_error_code_is_int(self) -> None:
        """ErrorCode values can be used directly as int in JSON-RPC responses."""
        resp = build_jsonrpc_error(1, ErrorCode.INTERNAL_ERROR, "boom")
        assert resp["error"]["code"] == -32603

    def test_all_codes_are_negative(self) -> None:
        for code in ErrorCode:
            assert code < 0, f"ErrorCode.{code.name} should be negative"

    def test_no_duplicate_values(self) -> None:
        values = [code.value for code in ErrorCode]
        assert len(values) == len(set(values))

    def test_backwards_compatible_aliases(self) -> None:
        """Module-level aliases still work for existing code."""
        from a2a_mesh.protocol.a2a import (
            INTERNAL_ERROR,
            INVALID_REQUEST,
            METHOD_NOT_FOUND,
            PARSE_ERROR,
        )

        assert PARSE_ERROR == ErrorCode.PARSE_ERROR
        assert INVALID_REQUEST == ErrorCode.INVALID_REQUEST
        assert METHOD_NOT_FOUND == ErrorCode.METHOD_NOT_FOUND
        assert INTERNAL_ERROR == ErrorCode.INTERNAL_ERROR


class TestMCPBridge:
    """Tests for the MCP bridge."""

    def test_register_server(self) -> None:
        bridge = MCPBridge()
        bridge.register_server("tools", "http://mcp.local")
        assert "tools" in bridge.servers
        assert bridge.servers["tools"] == "http://mcp.local"

    @pytest.mark.asyncio
    @respx.mock
    async def test_discover_tools(self) -> None:
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "tools": [
                            {
                                "name": "web_search",
                                "description": "Search the web",
                                "inputSchema": {"type": "object"},
                            },
                            {
                                "name": "fetch_url",
                                "description": "Fetch a URL",
                            },
                        ]
                    },
                },
            )
        )
        bridge = MCPBridge()
        bridge.register_server("tools", "http://mcp.local")
        discovered = await bridge.discover_tools("tools")
        assert len(discovered) == 2
        assert "web_search" in bridge.tools
        assert "fetch_url" in bridge.tools
        await bridge.close()

    @pytest.mark.asyncio
    async def test_discover_tools_unregistered_server(self) -> None:
        bridge = MCPBridge()
        with pytest.raises(ProtocolError, match="not registered"):
            await bridge.discover_tools("nonexistent")

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool(self) -> None:
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"content": "search results"},
                },
            )
        )
        bridge = MCPBridge()
        bridge.tools["web_search"] = MCPToolDefinition(
            name="web_search",
            server_url="http://mcp.local",
        )
        result = await bridge.call_tool("web_search", {"query": "test"})
        assert result["content"] == "search results"
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_unregistered_tool(self) -> None:
        bridge = MCPBridge()
        with pytest.raises(ProtocolError, match="not registered"):
            await bridge.call_tool("nonexistent")

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool_error_response(self) -> None:
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -1, "message": "Tool failed"},
                },
            )
        )
        bridge = MCPBridge()
        bridge.tools["broken"] = MCPToolDefinition(
            name="broken", server_url="http://mcp.local"
        )
        with pytest.raises(ProtocolError, match="Tool failed"):
            await bridge.call_tool("broken")
        await bridge.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_discover_tools_http_error(self) -> None:
        """discover_tools raises ProtocolError on HTTP failure."""
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(500, text="Server Error")
        )
        bridge = MCPBridge()
        bridge.register_server("tools", "http://mcp.local")
        with pytest.raises(ProtocolError, match="Failed to discover"):
            await bridge.discover_tools("tools")
        await bridge.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool_http_error(self) -> None:
        """call_tool raises ProtocolError on HTTP failure."""
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(503, text="Unavailable")
        )
        bridge = MCPBridge()
        bridge.tools["broken"] = MCPToolDefinition(
            name="broken", server_url="http://mcp.local"
        )
        with pytest.raises(ProtocolError, match="MCP tool call failed"):
            await bridge.call_tool("broken", {"arg": "val"})
        await bridge.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_discover_tools_connection_error(self) -> None:
        """discover_tools raises ProtocolError on connection error."""
        respx.post("http://mcp.local").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        bridge = MCPBridge()
        bridge.register_server("tools", "http://mcp.local")
        with pytest.raises(ProtocolError, match="Failed to discover"):
            await bridge.discover_tools("tools")
        await bridge.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool_connection_error(self) -> None:
        """call_tool raises ProtocolError on connection error."""
        respx.post("http://mcp.local").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        bridge = MCPBridge()
        bridge.tools["broken"] = MCPToolDefinition(
            name="broken", server_url="http://mcp.local"
        )
        with pytest.raises(ProtocolError, match="MCP tool call failed"):
            await bridge.call_tool("broken")
        await bridge.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_discover_tools_empty_list(self) -> None:
        """discover_tools handles a server returning empty tool list."""
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"tools": []},
                },
            )
        )
        bridge = MCPBridge()
        bridge.register_server("empty", "http://mcp.local")
        discovered = await bridge.discover_tools("empty")
        assert discovered == []
        await bridge.close()

    def test_register_server_strips_trailing_slash(self) -> None:
        """register_server normalizes URLs by stripping trailing slashes."""
        bridge = MCPBridge()
        bridge.register_server("s", "http://mcp.local/")
        assert bridge.servers["s"] == "http://mcp.local"

    @pytest.mark.asyncio
    @respx.mock
    async def test_call_tool_with_no_arguments(self) -> None:
        """call_tool with no arguments sends empty dict."""
        respx.post("http://mcp.local").mock(
            return_value=httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"output": "no-args"},
                },
            )
        )
        bridge = MCPBridge()
        bridge.tools["tool"] = MCPToolDefinition(
            name="tool", server_url="http://mcp.local"
        )
        result = await bridge.call_tool("tool")
        assert result["output"] == "no-args"
        await bridge.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        bridge = MCPBridge()
        await bridge.close()
        await bridge.close()

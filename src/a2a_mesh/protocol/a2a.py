"""A2A (Agent-to-Agent) protocol implementation.

Implements the JSON-RPC based A2A protocol for inter-agent communication.
Handles message serialization, task dispatch over HTTP, and streaming
updates via Server-Sent Events.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

import httpx

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import JsonRpcError, ProtocolError

logger = get_logger(__name__)


class ErrorCode(IntEnum):
    """Standard JSON-RPC and custom a2a-mesh error codes.

    Standard JSON-RPC 2.0 codes live in the -32xxx range. Custom a2a-mesh
    codes use the -31xxx range to avoid collisions.
    """

    # Standard JSON-RPC 2.0 codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # Custom a2a-mesh codes
    RATE_LIMITED = -31000
    AGENT_NOT_FOUND = -31001
    AGENT_UNAVAILABLE = -31002
    TASK_NOT_FOUND = -31003
    TASK_TIMEOUT = -31004
    CAPABILITY_MISMATCH = -31005
    AUTH_REQUIRED = -31006
    AUTH_INVALID = -31007
    BUDGET_EXCEEDED = -31008
    WORKFLOW_CYCLE = -31009


# Backwards-compatible aliases for the standard JSON-RPC codes
PARSE_ERROR = ErrorCode.PARSE_ERROR
INVALID_REQUEST = ErrorCode.INVALID_REQUEST
METHOD_NOT_FOUND = ErrorCode.METHOD_NOT_FOUND
INTERNAL_ERROR = ErrorCode.INTERNAL_ERROR


class A2AClient:
    """Client for the A2A protocol.

    Sends JSON-RPC requests to remote agents and handles response
    parsing, error mapping, and connection management.

    Attributes:
        base_url: The remote agent's base URL.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize the A2A client.

        Args:
            base_url: Base URL of the target agent.
            timeout: Request timeout in seconds.
            headers: Additional HTTP headers.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._headers = {
            "Content-Type": "application/json",
            **(headers or {}),
        }
        self._request_id = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialize the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._headers,
            )
        return self._client

    def _next_id(self) -> int:
        """Generate the next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    async def send_task(
        self,
        task_input: Any,
        method: str = "tasks/send",
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a task to the remote agent.

        Constructs a JSON-RPC 2.0 request and sends it to the agent's
        endpoint. Parses the response and raises on protocol errors.

        Args:
            task_input: The task payload (will be placed in params).
            method: JSON-RPC method name.

        Returns:
            The result field from the JSON-RPC response.

        Raises:
            JsonRpcError: If the response contains a JSON-RPC error.
            ProtocolError: If the response cannot be parsed.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": {
                "input": task_input,
            },
        }

        client = await self._get_client()
        try:
            response = await client.post(self.base_url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProtocolError(
                f"HTTP {exc.response.status_code} from {self.base_url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProtocolError(f"Connection error to {self.base_url}: {exc}") from exc

        return self._parse_response(response.json())

    async def get_task(
        self,
        task_id: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Query the status of a previously submitted task.

        Args:
            task_id: The task identifier to query.
            headers: Optional per-request HTTP headers.

        Returns:
            The task status and result.

        Raises:
            JsonRpcError: On protocol error.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tasks/get",
            "params": {"id": task_id},
        }

        client = await self._get_client()
        response = await client.post(self.base_url, json=payload, headers=headers)
        response.raise_for_status()
        return self._parse_response(response.json())

    async def cancel_task(
        self,
        task_id: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Cancel a running task.

        Args:
            task_id: The task identifier to cancel.

        Returns:
            The cancellation confirmation.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }

        client = await self._get_client()
        response = await client.post(self.base_url, json=payload, headers=headers)
        response.raise_for_status()
        return self._parse_response(response.json())

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse a JSON-RPC 2.0 response.

        Args:
            data: The raw JSON response dict.

        Returns:
            The result field.

        Raises:
            JsonRpcError: If the response contains an error.
            ProtocolError: If the response format is invalid.
        """
        if "error" in data:
            err = data["error"]
            code = err.get("code", INTERNAL_ERROR)
            message = err.get("message", "Unknown error")
            raise JsonRpcError(code, message)

        if "result" not in data:
            raise ProtocolError("Invalid JSON-RPC response: missing result")

        result: dict[str, Any] = data["result"]
        return result

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def build_jsonrpc_response(
    request_id: int | str | None,
    result: Any,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response.

    Args:
        request_id: The request ID to echo back.
        result: The result payload.

    Returns:
        A JSON-RPC 2.0 response dict.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def build_jsonrpc_error(
    request_id: int | str | None,
    code: int,
    message: str,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response.

    Args:
        request_id: The request ID to echo back (None if parse error).
        code: JSON-RPC error code.
        message: Error description.

    Returns:
        A JSON-RPC 2.0 error response dict.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }

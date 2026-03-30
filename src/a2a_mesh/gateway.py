"""HTTP and WebSocket gateway for a2a-mesh.

Provides the HTTP ingress layer for the mesh, handling JSON-RPC requests,
agent registration endpoints, health checks, rate limiting, and auth
middleware. Built on Starlette for async performance.
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from a2a_mesh._logging import get_logger
from a2a_mesh.exceptions import AuthError, MeshError, ProtocolError
from a2a_mesh.models import AgentCard, Task
from a2a_mesh.protocol.a2a import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    build_jsonrpc_error,
    build_jsonrpc_response,
)

if TYPE_CHECKING:
    from a2a_mesh.auth import AuthManager
    from a2a_mesh.mesh import Mesh

logger = get_logger(__name__)

# Paths that are exempt from authentication
_AUTH_EXEMPT_PATHS = frozenset({"/health"})


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates Bearer tokens via an AuthManager.

    When an ``auth_manager`` is provided, all requests (except those to
    exempt paths like ``/health``) must include a valid
    ``Authorization: Bearer <token>`` header.
    """

    def __init__(self, app: Any, auth_manager: AuthManager) -> None:  # noqa: ANN401
        super().__init__(app)
        self.auth_manager = auth_manager

    async def dispatch(
        self,
        request: Request,
        call_next: Any,  # noqa: ANN401
    ) -> JSONResponse:
        if request.url.path in _AUTH_EXEMPT_PATHS:
            response: JSONResponse = await call_next(request)
            return response

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
            )

        token = auth_header[len("Bearer ") :]
        try:
            self.auth_manager.validate_token(token)
        except AuthError:
            return JSONResponse(
                {"error": "Invalid or expired token"},
                status_code=401,
            )

        response = await call_next(request)
        return response


class RateLimiter:
    """Simple in-memory token bucket rate limiter.

    Attributes:
        max_requests: Maximum requests per window.
        window_seconds: Time window in seconds.
        max_buckets: Maximum number of tracked keys before evicting oldest.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: float = 60.0,
        max_buckets: int = 10_000,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()

    def allow(self, key: str) -> bool:
        """Check if a request from the given key is allowed.

        Args:
            key: Rate limit key (e.g., client IP or agent name).

        Returns:
            True if the request is within limits.
        """
        now = time.monotonic()

        if key in self._buckets:
            # Move to end (most-recently-used)
            self._buckets.move_to_end(key)
            bucket = self._buckets[key]
        else:
            # Evict oldest entries if we've exceeded max_buckets
            while len(self._buckets) >= self.max_buckets:
                self._buckets.popitem(last=False)
            bucket = []
            self._buckets[key] = bucket

        # Remove expired entries
        cutoff = now - self.window_seconds
        self._buckets[key] = [t for t in bucket if t > cutoff]

        if len(self._buckets[key]) >= self.max_requests:
            return False

        self._buckets[key].append(now)
        return True


def create_gateway(
    mesh: Mesh,
    auth_manager: AuthManager | None = None,
    on_startup: list[Callable[[], Coroutine[Any, Any, Any]]] | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for the mesh gateway.

    Args:
        mesh: The mesh instance to expose via HTTP.
        auth_manager: Optional auth manager. When provided, all endpoints
            except ``/health`` require a valid Bearer token.
        on_startup: Optional list of async startup callables invoked when
            the ASGI application starts.

    Returns:
        A configured Starlette application.
    """
    rate_limiter = RateLimiter()

    async def health(request: Request) -> JSONResponse:
        """Health check endpoint."""
        agent_count = len(mesh.registry.list_agents())
        return JSONResponse(
            {
                "status": "healthy",
                "agents": agent_count,
            }
        )

    async def list_agents(request: Request) -> JSONResponse:
        """List all registered agents."""
        agents = mesh.registry.list_agents()
        return JSONResponse(
            {
                "agents": [
                    {
                        "name": a.card.name,
                        "description": a.card.description,
                        "capabilities": a.card.capabilities,
                        "status": a.status.value,
                        "current_load": a.current_load,
                        "version": a.card.version,
                        "auth_required": a.card.auth_required,
                    }
                    for a in agents
                ]
            }
        )

    async def register_agent(request: Request) -> JSONResponse:
        """Register a new agent via HTTP."""
        try:
            body = await request.json()
            card = AgentCard(**body)
            agent = mesh.register(card)
            return JSONResponse(
                {
                    "agent_id": agent.agent_id,
                    "name": agent.card.name,
                    "auth_required": agent.card.auth_required,
                    "status": "registered",
                },
                status_code=201,
            )
        except MeshError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception as exc:
            return JSONResponse({"error": f"Invalid request: {exc}"}, status_code=400)

    async def jsonrpc_handler(request: Request) -> JSONResponse:
        """Handle JSON-RPC 2.0 requests."""
        client_ip = request.client.host if request.client else "unknown"

        if not rate_limiter.allow(client_ip):
            return JSONResponse(
                build_jsonrpc_error(None, -32000, "Rate limit exceeded"),
                status_code=429,
            )

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                build_jsonrpc_error(None, INVALID_REQUEST, "Invalid JSON"),
                status_code=400,
            )

        if not isinstance(body, dict):
            return JSONResponse(
                build_jsonrpc_error(None, INVALID_REQUEST, "Invalid request"),
                status_code=400,
            )

        request_id = body.get("id")
        response_id = request_id if isinstance(request_id, (int, str)) else None
        method = body.get("method", "")
        params = body.get("params", {})

        try:
            result = await _dispatch_method(mesh, method, params)
            return JSONResponse(build_jsonrpc_response(response_id, result))
        except MeshError as exc:
            return JSONResponse(
                build_jsonrpc_error(response_id, INTERNAL_ERROR, str(exc))
            )
        except Exception as exc:
            logger.exception("jsonrpc.unhandled_error", method=method)
            return JSONResponse(
                build_jsonrpc_error(
                    response_id, INTERNAL_ERROR, f"Internal error: {exc}"
                )
            )

    async def traces_endpoint(request: Request) -> JSONResponse:
        """Return recent trace spans."""
        limit = int(request.query_params.get("limit", "50"))
        spans = mesh.tracer.get_traces(limit=limit)
        return JSONResponse(
            {
                "spans": [s.model_dump(mode="json") for s in spans],
                "total_cost": mesh.tracer.total_cost(),
            }
        )

    async def websocket_rpc(websocket: WebSocket) -> None:
        """Handle JSON-RPC 2.0 requests over WebSocket."""
        client_ip = websocket.client.host if websocket.client else "unknown"
        if auth_manager is not None:
            auth_header = websocket.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                await websocket.accept()
                await websocket.close(code=4401)
                return
            token = auth_header[len("Bearer ") :]
            try:
                auth_manager.validate_token(token)
            except AuthError:
                await websocket.accept()
                await websocket.close(code=4401)
                return

        await websocket.accept()
        while True:
            try:
                payload = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            if not rate_limiter.allow(client_ip):
                await websocket.send_json(
                    build_jsonrpc_error(None, -32000, "Rate limit exceeded")
                )
                continue

            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                await websocket.send_json(
                    build_jsonrpc_error(None, INVALID_REQUEST, "Invalid JSON")
                )
                continue

            if not isinstance(body, dict):
                await websocket.send_json(
                    build_jsonrpc_error(None, INVALID_REQUEST, "Invalid request")
                )
                continue

            request_id = body.get("id")
            response_id = request_id if isinstance(request_id, (int, str)) else None
            method = body.get("method", "")
            params = body.get("params", {})

            try:
                result = await _dispatch_method(mesh, method, params)
                await websocket.send_json(build_jsonrpc_response(response_id, result))
            except MeshError as exc:
                await websocket.send_json(
                    build_jsonrpc_error(response_id, INTERNAL_ERROR, str(exc))
                )
            except Exception as exc:
                logger.exception("websocket.unhandled_error", method=method)
                await websocket.send_json(
                    build_jsonrpc_error(
                        response_id,
                        INTERNAL_ERROR,
                        f"Internal error: {exc}",
                    )
                )

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/agents", list_agents, methods=["GET"]),
        Route("/agents/register", register_agent, methods=["POST"]),
        Route("/rpc", jsonrpc_handler, methods=["POST"]),
        Route("/traces", traces_endpoint, methods=["GET"]),
        WebSocketRoute("/ws", websocket_rpc),
        WebSocketRoute("/rpc/ws", websocket_rpc),
    ]

    middleware: list[Middleware] = []
    if auth_manager is not None:
        middleware.append(Middleware(AuthMiddleware, auth_manager=auth_manager))

    startup_hooks = on_startup or []

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        for hook in startup_hooks:
            await hook()
        yield

    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan if startup_hooks else None,
    )
    return app


async def _dispatch_method(
    mesh: Any,
    method: str,
    params: dict[str, Any],
) -> Any:
    """Dispatch a JSON-RPC method to the appropriate mesh operation.

    Args:
        mesh: The mesh instance.
        method: JSON-RPC method name.
        params: Method parameters.

    Returns:
        The method result.

    Raises:
        MeshError: On dispatch failure.
    """
    if method == "tasks/send":
        task = Task(
            name=params.get("name", "dispatch"),
            agent=params.get("agent", ""),
            input=params.get("input", ""),
            required_capabilities=params.get("capabilities", []),
        )
        await mesh.dispatch(task)
        return task.model_dump(mode="json")

    if method == "tasks/get":
        task_id = params.get("id") or params.get("task_id")
        if not task_id:
            raise ProtocolError("Missing task id")
        task = mesh.get_task(str(task_id))
        return task.model_dump(mode="json")

    if method == "tasks/cancel":
        task_id = params.get("id") or params.get("task_id")
        if not task_id:
            raise ProtocolError("Missing task id")
        task = mesh.cancel_task(str(task_id))
        return task.model_dump(mode="json")

    if method == "agents/list":
        agents = mesh.registry.list_agents()
        return {
            "agents": [
                {
                    "name": a.card.name,
                    "capabilities": a.card.capabilities,
                    "status": a.status.value,
                    "auth_required": a.card.auth_required,
                }
                for a in agents
            ]
        }

    if method == "agents/register":
        card = AgentCard(**params)
        agent = mesh.register(card)
        return {
            "agent_id": agent.agent_id,
            "name": agent.card.name,
            "auth_required": agent.card.auth_required,
        }

    raise ProtocolError(f"Unknown method: {method}")

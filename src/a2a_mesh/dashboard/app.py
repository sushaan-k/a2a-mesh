"""Dashboard web UI for a2a-mesh.

Provides a simple web dashboard for monitoring the mesh: agent status,
active workflows, trace viewer, and cost tracking.
"""

from __future__ import annotations

import html
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from a2a_mesh.mesh import Mesh

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>a2a-mesh Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif;
               background: #0f172a; color: #e2e8f0; padding: 2rem; }
        h1 { color: #38bdf8; margin-bottom: 1.5rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 1rem; margin-bottom: 2rem; }
        .card { background: #1e293b; border-radius: 12px; padding: 1.5rem;
                border: 1px solid #334155; }
        .card h2 { color: #94a3b8; font-size: 0.875rem; text-transform: uppercase;
                   letter-spacing: 0.05em; margin-bottom: 0.5rem; }
        .metric { font-size: 2rem; font-weight: 700; color: #f1f5f9; }
        .status-healthy { color: #4ade80; }
        .status-degraded { color: #fbbf24; }
        .status-unhealthy { color: #f87171; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #334155; }
        th { color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; }
        .refresh { background: #2563eb; color: white; border: none; padding: 0.5rem 1rem;
                   border-radius: 6px; cursor: pointer; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <h1>a2a-mesh Dashboard</h1>
    <button class="refresh" onclick="location.reload()">Refresh</button>
    <div class="grid" id="metrics"></div>
    <div class="card">
        <h2>Registered Agents</h2>
        <table><thead><tr>
            <th>Name</th><th>Status</th><th>Load</th>
            <th>Capabilities</th><th>Version</th>
        </tr></thead><tbody id="agents"></tbody></table>
    </div>
    <script>
        async function load() {
            const resp = await fetch('/api/dashboard');
            const data = await resp.json();
            document.getElementById('metrics').innerHTML = `
                <div class="card"><h2>Agents</h2>
                    <div class="metric">${data.agent_count}</div></div>
                <div class="card"><h2>Total Cost</h2>
                    <div class="metric">$${data.total_cost.toFixed(4)}</div></div>
                <div class="card"><h2>Traces</h2>
                    <div class="metric">${data.trace_count}</div></div>
            `;
            const tbody = document.getElementById('agents');
            tbody.innerHTML = data.agents.map(a => `<tr>
                <td>${a.name}</td>
                <td class="status-${a.status}">${a.status}</td>
                <td>${a.current_load}</td>
                <td>${a.capabilities.join(', ')}</td>
                <td>${a.version}</td>
            </tr>`).join('');
        }
        load();
    </script>
</body>
</html>"""


def create_dashboard(
    mesh: Mesh,
    on_startup: list[Callable[[], Coroutine[Any, Any, Any]]] | None = None,
) -> Starlette:
    """Create the dashboard Starlette application.

    Args:
        mesh: The mesh instance to visualize.
        on_startup: Optional list of async startup callables invoked when
            the ASGI application starts.

    Returns:
        A configured Starlette application for the dashboard.
    """

    async def index(request: Request) -> HTMLResponse:
        """Serve the dashboard HTML page."""
        return HTMLResponse(_DASHBOARD_HTML)

    async def api_dashboard(request: Request) -> JSONResponse:
        """API endpoint returning dashboard data."""
        agents = mesh.registry.list_agents()
        return JSONResponse(
            {
                "agent_count": len(agents),
                "total_cost": mesh.tracer.total_cost(),
                "trace_count": len(mesh.tracer.spans),
                "agents": [
                    {
                        "name": html.escape(a.card.name),
                        "description": html.escape(a.card.description),
                        "status": html.escape(a.status.value),
                        "current_load": a.current_load,
                        "capabilities": [html.escape(c) for c in a.card.capabilities],
                        "version": html.escape(a.card.version),
                        "avg_latency_ms": round(a.avg_latency_ms, 2),
                    }
                    for a in agents
                ],
            }
        )

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/api/dashboard", api_dashboard, methods=["GET"]),
    ]

    startup_hooks = on_startup or []

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        for hook in startup_hooks:
            await hook()
        yield

    return Starlette(
        routes=routes,
        lifespan=lifespan if startup_hooks else None,
    )

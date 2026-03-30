"""Command-line interface for a2a-mesh.

Provides commands to start the mesh, register agents, dispatch tasks,
view traces, and launch the dashboard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from a2a_mesh._logging import configure_logging


@click.group()
@click.option(
    "--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)"
)
@click.pass_context
def cli(ctx: click.Context, log_level: str) -> None:
    """a2a-mesh - Lightweight multi-agent coordination runtime."""
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
    configure_logging(level=log_level)


@cli.command()
@click.option("--port", default=8080, help="HTTP gateway port")
@click.option("--host", default="127.0.0.1", help="HTTP gateway bind address")
@click.pass_context
def start(ctx: click.Context, port: int, host: str) -> None:
    """Start the mesh runtime with HTTP gateway."""
    from a2a_mesh.mesh import Mesh

    mesh = Mesh(port=port, log_level=ctx.obj["log_level"])
    click.echo(f"Starting a2a-mesh on {host}:{port}...")
    mesh.serve(host=host)


@cli.command()
@click.option(
    "--card",
    required=True,
    type=click.Path(exists=True),
    help="Path to agent card JSON",
)
@click.option("--endpoint", default="", help="Agent HTTP endpoint URL")
@click.option("--mesh-url", default="http://localhost:8080", help="Mesh gateway URL")
def register(card: str, endpoint: str, mesh_url: str) -> None:
    """Register an agent with the mesh."""
    import asyncio

    import httpx

    card_path = Path(card)
    try:
        card_data = json.loads(card_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        click.echo(f"Error reading agent card: {exc}", err=True)
        sys.exit(1)

    if endpoint:
        card_data["url"] = endpoint

    async def _register() -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{mesh_url}/agents/register",
                json=card_data,
            )
            if resp.status_code == 201:
                data = resp.json()
                click.echo(f"Registered agent: {data.get('name', 'unknown')}")
            else:
                click.echo(f"Registration failed: {resp.text}", err=True)
                sys.exit(1)

    asyncio.run(_register())


@cli.command()
@click.option("--mesh-url", default="http://localhost:8080", help="Mesh gateway URL")
def agents(mesh_url: str) -> None:
    """List registered agents."""
    import asyncio

    import httpx

    async def _list() -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{mesh_url}/agents")
            if resp.status_code == 200:
                data = resp.json()
                for agent in data.get("agents", []):
                    status = agent.get("status", "unknown")
                    caps = ", ".join(agent.get("capabilities", []))
                    load = agent.get("current_load", 0)
                    click.echo(
                        f"  {agent['name']}  [{status}]  load={load}  caps=[{caps}]"
                    )
                if not data.get("agents"):
                    click.echo("  No agents registered.")
            else:
                click.echo(f"Error: {resp.text}", err=True)

    asyncio.run(_list())


@cli.command()
@click.argument("task_input")
@click.option("--capabilities", "-c", multiple=True, help="Required capabilities")
@click.option("--mesh-url", default="http://localhost:8080", help="Mesh gateway URL")
def dispatch(task_input: str, capabilities: tuple[str, ...], mesh_url: str) -> None:
    """Dispatch a task to the mesh."""
    import asyncio

    import httpx

    async def _dispatch() -> None:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tasks/send",
            "params": {
                "input": task_input,
                "capabilities": list(capabilities),
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{mesh_url}/rpc", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", {})
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"Error: {resp.text}", err=True)
                sys.exit(1)

    asyncio.run(_dispatch())


@cli.command()
@click.option("--last", default=10, help="Number of recent traces")
@click.option("--mesh-url", default="http://localhost:8080", help="Mesh gateway URL")
def traces(last: int, mesh_url: str) -> None:
    """View recent traces."""
    import asyncio

    import httpx

    async def _traces() -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{mesh_url}/traces",
                params={"limit": last},
            )
            if resp.status_code == 200:
                data = resp.json()
                click.echo(f"Total cost: ${data.get('total_cost', 0):.4f}")
                click.echo(f"Spans ({len(data.get('spans', []))}):")
                for span in data.get("spans", []):
                    dur = span.get("duration_ms", 0)
                    click.echo(
                        f"  [{span.get('operation', '?')}] "
                        f"agent={span.get('agent_name', '?')} "
                        f"duration={dur:.1f}ms "
                        f"cost=${span.get('cost', 0):.4f}"
                    )
            else:
                click.echo(f"Error: {resp.text}", err=True)

    asyncio.run(_traces())


@cli.command(name="dashboard")
@click.option("--port", default=8081, help="Dashboard port")
@click.option("--host", default="127.0.0.1", help="Dashboard bind address")
@click.pass_context
def dashboard_cmd(ctx: click.Context, port: int, host: str) -> None:
    """Launch the monitoring dashboard."""
    from a2a_mesh.mesh import Mesh

    mesh = Mesh(port=port - 1, log_level=ctx.obj["log_level"])
    click.echo(f"Starting dashboard on http://{host}:{port}")
    mesh.dashboard(host=host)


if __name__ == "__main__":
    cli()

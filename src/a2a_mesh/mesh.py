"""Main mesh runtime for a2a-mesh.

The Mesh class is the top-level orchestrator that ties together the
registry, router, coordinator, auth manager, tracer, and gateway into
a single coherent runtime.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import uvicorn

from a2a_mesh._logging import configure_logging, get_logger
from a2a_mesh.auth import AuthManager
from a2a_mesh.coordinator import WorkflowCoordinator
from a2a_mesh.exceptions import ProtocolError
from a2a_mesh.models import (
    AgentCard,
    RegisteredAgent,
    RoutingPolicy,
    Task,
    TaskStatus,
    Workflow,
    WorkflowResult,
)
from a2a_mesh.protocol.a2a import A2AClient
from a2a_mesh.registry import AgentRegistry, RedisAgentRegistry
from a2a_mesh.router import Router
from a2a_mesh.tracer import MeshTracer

logger = get_logger(__name__)


class Mesh:
    """The a2a-mesh runtime.

    Central entry point for the multi-agent coordination system. Manages
    agent registration, task dispatch, workflow execution, authentication,
    and observability.

    Attributes:
        port: HTTP port for the gateway.
        registry: The agent registry.
        router: The task router.
        coordinator: The workflow coordinator.
        auth: The authentication manager.
        tracer: The distributed tracer.
    """

    def __init__(
        self,
        port: int = 8080,
        policy: RoutingPolicy | None = None,
        auth_secret: str | None = None,
        log_level: str = "INFO",
        health_interval: float = 30.0,
        *,
        registry: AgentRegistry | None = None,
        redis_url: str | None = None,
    ) -> None:
        """Initialize the mesh runtime.

        Args:
            port: Port for the HTTP gateway.
            policy: Routing policy configuration.
            auth_secret: JWT signing secret for auth.
            log_level: Logging level.
            health_interval: Seconds between health check sweeps.
            registry: Optional pre-built registry implementation.
            redis_url: Optional Redis URL for the built-in shared registry.
        """
        configure_logging(level=log_level)

        self.port = port
        if registry is not None:
            self.registry = registry
        elif redis_url is not None:
            self.registry = RedisAgentRegistry(
                redis_url=redis_url,
                health_interval=health_interval,
            )
        else:
            self.registry = AgentRegistry(health_interval=health_interval)
        self.router = Router(self.registry, policy=policy)
        self.auth = AuthManager(secret=auth_secret)
        self.tracer = MeshTracer()
        self.coordinator = WorkflowCoordinator(executor=self._execute_single_task)

        self._a2a_clients: dict[str, A2AClient] = {}
        self._tasks: dict[str, Task] = {}
        self._started: bool = False

        logger.info("mesh.initialized", port=port)

    def register(
        self,
        card: AgentCard,
        *,
        force: bool = False,
    ) -> RegisteredAgent:
        """Register an agent with the mesh.

        Args:
            card: The agent's capability card.
            force: Overwrite existing registration if True.

        Returns:
            The registered agent record.
        """
        agent = self.registry.register(card, force=force)

        if card.url:
            self._a2a_clients[card.name] = A2AClient(card.url)

        return agent

    def deregister(self, agent_name: str) -> None:
        """Remove an agent from the mesh.

        Args:
            agent_name: Name of the agent to remove.
        """
        self.registry.deregister(agent_name)
        client = self._a2a_clients.pop(agent_name, None)
        if client is not None:
            # Schedule cleanup without blocking
            asyncio.ensure_future(client.close())

    async def dispatch(
        self,
        task: str | Task,
        required_capabilities: list[str] | None = None,
    ) -> Any:
        """Dispatch a task to the best available agent.

        Args:
            task: Either a string prompt or a Task object.
            required_capabilities: Required agent capabilities.

        Returns:
            The task result from the selected agent.

        Raises:
            NoCapableAgentError: If no agent can handle the task.
        """
        if isinstance(task, str):
            task_obj = Task(
                name="dispatch",
                input=task,
                required_capabilities=required_capabilities or [],
            )
        else:
            task_obj = task

        self._tasks[task_obj.task_id] = task_obj
        async with self.tracer.trace_task(
            "dispatch",
            agent_name="mesh",
            attributes={"task_id": task_obj.task_id},
        ) as span:
            result = await self._execute_single_task(task_obj)
            span.cost = task_obj.cost
            return result

    def get_task(self, task_id: str) -> Task:
        """Return a tracked task by identifier."""
        if task_id not in self._tasks:
            raise ProtocolError(f"Unknown task: {task_id}")
        return self._tasks[task_id]

    def cancel_task(self, task_id: str) -> Task:
        """Cancel a tracked task when it has not yet completed."""
        task = self.get_task(task_id)
        if task.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            return task

        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now(UTC)
        task.error = "Task cancelled"
        return task

    async def execute_workflow(
        self,
        workflow: Workflow,
        timeout: float | None = None,
    ) -> WorkflowResult:
        """Execute a multi-agent workflow.

        Args:
            workflow: The workflow DAG to execute.
            timeout: Optional timeout in seconds. When reached, the workflow
                returns partial results for completed tasks.

        Returns:
            The workflow result containing all task outputs.
        """
        await self.start()
        async with self.tracer.trace_task(
            "workflow",
            attributes={"workflow_id": workflow.workflow_id},
        ) as span:
            result = await self.coordinator.execute(workflow, timeout=timeout)
            span.cost = result.total_cost
            return result

    async def _execute_single_task(self, task: Task) -> Any:
        """Execute a single task via the router and A2A protocol.

        Routes the task to the best agent, dispatches it via the A2A
        client, updates load counters, and records latency.

        Args:
            task: The task to execute.

        Returns:
            The agent's response.
        """
        self._tasks[task.task_id] = task
        agent = self.router.route(task)
        agent.current_load += 1
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)

        async with self.tracer.trace_task(
            "task.execute",
            agent_name=agent.card.name,
            attributes={"task_id": task.task_id},
        ) as span:
            try:
                client = self._a2a_clients.get(agent.card.name)
                headers = self._auth_headers_for_agent(agent)
                if client is not None:
                    result = await client.send_task(task.input, headers=headers)
                else:
                    # Local agent without URL — return input echo
                    result = {
                        "agent": agent.card.name,
                        "input": task.input,
                        "status": "completed",
                    }

                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.now(UTC)
                task.cost = agent.card.cost_per_task

                span.cost = task.cost

                # Update agent latency EMA
                if span.duration_ms > 0:
                    alpha = 0.3
                    agent.avg_latency_ms = (
                        alpha * span.duration_ms + (1 - alpha) * agent.avg_latency_ms
                    )

                return result

            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                task.completed_at = datetime.now(UTC)
                raise

            finally:
                agent.current_load = max(0, agent.current_load - 1)

    def _auth_headers_for_agent(self, agent: RegisteredAgent) -> dict[str, str] | None:
        """Build per-request auth headers for agents that require auth."""
        if not agent.card.auth_required:
            return None

        token = self.auth.issue_token(
            issuer="mesh",
            subject=agent.card.name,
            scopes=["tasks/send", "tasks/get", "tasks/cancel"],
        )
        return {"Authorization": f"Bearer {token.token}"}

    def traces(self, limit: int = 50) -> list[Any]:
        """Return recent trace spans.

        Args:
            limit: Maximum number of spans.

        Returns:
            List of SpanRecord objects.
        """
        return self.tracer.get_traces(limit=limit)

    async def start(self) -> None:
        """Start the mesh runtime (registry health checks + HTTP gateway).

        This method is idempotent: subsequent calls are no-ops if the
        mesh is already running.
        """
        if self._started:
            return
        await self.registry.start()
        self._started = True
        logger.info("mesh.started", port=self.port)

    async def stop(self) -> None:
        """Stop the mesh runtime and clean up resources."""
        await self.registry.stop()
        for client in self._a2a_clients.values():
            await client.close()
        self._a2a_clients.clear()
        self.tracer.shutdown()
        self._started = False
        logger.info("mesh.stopped")

    def serve(self, host: str = "127.0.0.1") -> None:
        """Start the HTTP gateway server (blocking).

        This starts a uvicorn server with the gateway ASGI app.
        Typically used from the CLI.

        Args:
            host: Bind address. Defaults to ``127.0.0.1`` (loopback only).
                  Pass ``"0.0.0.0"`` for network access.
        """
        from a2a_mesh.gateway import create_gateway

        app = create_gateway(self, auth_manager=self.auth, on_startup=[self.start])
        uvicorn.run(app, host=host, port=self.port)

    def dashboard(self, host: str = "127.0.0.1") -> None:
        """Start the dashboard web UI (blocking).

        Serves the monitoring dashboard on port + 1.

        Args:
            host: Bind address. Defaults to ``127.0.0.1`` (loopback only).
        """
        from a2a_mesh.dashboard.app import create_dashboard

        app = create_dashboard(self, on_startup=[self.start])
        dash_port = self.port + 1
        logger.info("dashboard.started", port=dash_port)
        uvicorn.run(app, host=host, port=dash_port)
